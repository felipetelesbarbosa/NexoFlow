"""Recompra D+25: planos revisados, sem envio nem edição da campanha."""
from __future__ import annotations

from collections import Counter, OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from itertools import groupby, islice
import json
import logging
import os
from pathlib import Path
import tempfile
from threading import Lock
from time import monotonic
import unicodedata
from zoneinfo import ZoneInfo

from analytics import get_fields, normalize_value, cpf_query_priority, _sales_order_is_valid
from config import FARMALIDER_MAX_WORKERS
from farmalider_integration import resolve_contact_order, select_cliente_response, weni_customer_identity
from pedido_utils import business_order_datetime, serialize_pedido_products, serialize_weni_order_list

GROUP = "Recompra FarmaLíder"
OPT_OUT = "Opt-Out Marketing"
FLOW = "Recompra FarmaLíder D+25"
TZ = ZoneInfo("America/Belem")
DAY_EXPRESSION = '@(if(default(datetime_diff(format_date(fields.pedido_data, "YYYY-MM-DD"), today(), "D"), -1) = 25, "D25_OK", "D25_FORA"))'
REFUSAL_EXPRESSION = '@(if(or(lower(trim(fields.marketing_opt_in)) = "recusado", lower(trim(fields.marketing_opt_in)) = "não", lower(trim(fields.marketing_opt_in)) = "nao", lower(trim(fields.marketing_opt_in)) = "negado"), "MKT_RECUSADO", "MKT_SEM_RECUSA"))'
FIELDS = {"pedido_data", "pedido_produtos", "ultimo_pedido"}
FIELDS |= {"pedido_id", "pedido_quantidade_itens", "pedido_valor_produtos", "pedido_valor", "pedido_status", "pedido_forma_pagamento"}
GUARD_FIELDS = FIELDS | {"pedido_id", "cpf", "nome", "email", "marketing_opt_in", "pedido_status", "pedido_forma_pagamento"}
STATE = Path("logs/recompra_state.json")
REVIEW = Path("logs/recompra_review.json")
AUDIT = Path("logs/recompra_audit.jsonl")


class RecompraReadCache:
    """Payloads brutos por execução; uma consulta por chave em andamento.

    A seleção de identidade continua ocorrendo separadamente para cada contato.
    Nada deste cache serve como confirmação para uma execução posterior.
    """

    def __init__(self, farm, max_entries=4096):
        if max_entries < 1:
            raise ValueError("O cache precisa ter ao menos uma entrada.")
        self.farm = farm
        self.max_entries = max_entries
        self._lock = Lock()
        self._responses = OrderedDict()
        self._hits = 0
        self._misses = 0

    def _read(self, kind, key, fetch):
        cache_key = (kind, str(key))
        with self._lock:
            future = self._responses.get(cache_key)
            owner = future is None
            if owner:
                future = Future()
                self._responses[cache_key] = future
                self._misses += 1
            else:
                self._responses.move_to_end(cache_key)
                self._hits += 1
        if owner:
            try:
                future.set_result(fetch())
            except BaseException as exc:
                future.set_exception(exc)
                from farmalider_client import FarmaliderBadRequestError
                # HTTP 400 é definitivo para esta consulta; falhas transitórias
                # não impedem outra tentativa nesta mesma execução.
                if not isinstance(exc, FarmaliderBadRequestError):
                    with self._lock:
                        if self._responses.get(cache_key) is future:
                            del self._responses[cache_key]
            finally:
                with self._lock:
                    # Não expulsar consultas em andamento: seus consumidores
                    # precisam continuar compartilhando a mesma requisição.
                    while len(self._responses) > self.max_entries:
                        candidate = next((key for key, response in self._responses.items() if response.done()), None)
                        if candidate is None:
                            break
                        del self._responses[candidate]
        return deepcopy(future.result())

    def get_cliente_by_cpf(self, cpf):
        return self._read("cpf", cpf, lambda: self.farm.get_cliente_by_cpf(cpf))

    def get_pedido(self, order_id):
        return self._read("pedido", order_id, lambda: self.farm.get_pedido(order_id))

    def metrics(self):
        with self._lock:
            return {"consultas": self._misses, "reusos": self._hits, "entradas": len(self._responses)}


def iter_prioritized_contacts(contacts):
    """Processa válidos durante a paginação; adia os demais em disco.

    Mantém a prioridade global de CPF sem guardar toda a base em memória.
    O diretório temporário é privado e removido também em caso de falha.
    """
    with tempfile.TemporaryDirectory(prefix="nexoflow-recompra-") as directory:
        paths = {priority: Path(directory) / f"cpf-{priority}.jsonl" for priority in (1, 2)}
        with paths[1].open("w", encoding="utf-8") as invalid, paths[2].open("w", encoding="utf-8") as empty:
            outputs = {1: invalid, 2: empty}
            for contact in contacts:
                priority = cpf_query_priority(get_fields(contact).get("cpf"))
                if priority == 0:
                    yield contact
                else:
                    outputs[priority].write(json.dumps(contact, ensure_ascii=False) + "\n")
        for priority in (1, 2):
            with paths[priority].open(encoding="utf-8") as handle:
                for line in handle:
                    yield json.loads(line)


def build_plans(contacts, farm, structure, state, *, now=None, workers=FARMALIDER_MAX_WORKERS):
    """GETs concorrentes e limitados; Weni e estado permanecem na thread principal."""
    if not 1 <= workers <= FARMALIDER_MAX_WORKERS:
        raise ValueError(f"Use de 1 a {FARMALIDER_MAX_WORKERS} consultas simultâneas.")
    now = now or now_local()
    reads = RecompraReadCache(farm)
    plans = []
    results = Counter()
    started = monotonic()

    def plan_contact(contact):
        saved = state["contacts"].get(contact["uuid"])
        order, items = resolve_latest(contact, reads, now.isoformat(), saved=saved)
        return propose(contact, order, items, structure, saved, now=now)

    prioritized = iter_prioritized_contacts(contacts)
    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="recompra") as pool:
            # Cada fase termina antes da seguinte, inclusive as requisições que
            # estiverem em andamento. A fila tem no máximo workers * 2 contatos.
            for _, phase in groupby(prioritized, key=lambda c: cpf_query_priority(get_fields(c).get("cpf"))):
                while batch := list(islice(phase, workers * 2)):
                    for plan in pool.map(plan_contact, batch):
                        plans.append(plan)
                        results[plan["reason"]] += 1
                        if len(plans) % 100 == 0:
                            elapsed = max(monotonic() - started, 0.001)
                            logging.info("Recompra: contatos=%s; velocidade=%.1f/s; resultados=%s; cache=%s.",
                                         len(plans), len(plans) / elapsed, dict(results), reads.metrics())
    finally:
        prioritized.close()
    elapsed = max(monotonic() - started, 0.001)
    logging.info("Recompra: contatos=%s; duração=%.1fs; resultados=%s; cache=%s.",
                 len(plans), elapsed, dict(results), reads.metrics())
    return plans


def plan_needs_apply(plan, saved=None):
    """Inclui persistência local necessária mesmo quando não há POST."""
    saved = saved or {}
    if plan["action"] or plan["fields"] or (plan["purchase"] and plan["purchase"] != saved.get("purchase")):
        return True
    if plan["in_group"] and plan["order_id"]:
        entry = (saved.get("orders") or {}).get(plan["order_id"], {})
        return not entry.get("admitted") or bool(entry.get("pending"))
    return False


def now_local():
    return datetime.now(TZ)


def text(value):
    return normalize_value(value).strip()


def norm(value):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", text(value)) if not unicodedata.combining(c)).casefold().split())


def refused(contact):
    return norm(get_fields(contact).get("marketing_opt_in")) in {
        "recusado", "nao", "negado", "inativo", "recusa", "opt-out", "opt out",
        "false", "0", "cancelado", "nao autorizado", "nao quero receber",
    }


def member(contact, group_uuid, group_name):
    return any((isinstance(g, dict) and (g.get("uuid") == group_uuid or g.get("name") == group_name))
               or (isinstance(g, str) and g in {group_uuid, group_name}) for g in contact.get("groups", []) or [])


def field_guard(key, value):
    if key in {"pedido_valor", "pedido_forma_pagamento"} and text(value):
        from weni_update import _weni_number_text
        number = _weni_number_text(value)
        if number: return number
    if key == "pedido_data":
        dt = business_order_datetime(value)
        if dt is not None: return dt.isoformat()
    return text(value)


def guard(contact):
    fields = get_fields(contact)
    return {"fields": {key: field_guard(key, fields.get(key)) for key in sorted(GUARD_FIELDS)},
            "name": text(contact.get("name")), "urns": sorted(contact.get("urns") or []),
            "groups": sorted(text(g.get("uuid") or g.get("name")) if isinstance(g, dict) else text(g)
                             for g in contact.get("groups", []) or [])}


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix="recompra-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2); handle.flush(); os.fsync(handle.fileno())
        os.replace(filename, path)
    finally:
        if os.path.exists(filename): os.unlink(filename)


def load_state(path=STATE):
    path = Path(path)
    if not path.exists(): return {"schema": 1, "contacts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != 1 or not isinstance(data.get("contacts"), dict): raise ValueError()
        return data
    except (ValueError, OSError, AttributeError) as exc:
        raise RuntimeError("Estado de recompra inválido. Aplicação bloqueada para evitar duplicidade; preserve o arquivo e investigue.") from exc


@contextmanager
def state_lock(path=STATE):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    try: fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("Outra carga de recompra está em execução ou foi interrompida. Verifique antes de remover o lock.") from exc
    try:
        with os.fdopen(fd, "w") as handle: handle.write(str(os.getpid()))
        yield
    finally: lock.unlink(missing_ok=True)


def validate_flow_guards(flow, opt_out_uuid):
    nodes = {node["uuid"]: node for node in flow.get("nodes", [])}
    if not nodes: return False
    current = next(iter(nodes.values()))
    def branch(node, category):
        router = node.get("router") or {}
        exit_id = next((c.get("exit_uuid") for c in router.get("categories", []) if c.get("uuid") == category), None)
        target = next((e.get("destination_uuid") for e in node.get("exits", []) if e.get("uuid") == exit_id), None)
        return nodes.get(target)
    def reject_ends(node):
        seen = set()
        while node:
            if node["uuid"] in seen or node.get("router"): return False
            seen.add(node["uuid"])
            if any(a.get("type") != "remove_contact_groups" for a in node.get("actions", [])): return False
            exits = node.get("exits", [])
            if len(exits) != 1: return False
            node = nodes.get(exits[0].get("destination_uuid"))
        return True
    expected = [("@contact.groups", "has_group", opt_out_uuid, False),
                ("marketing_opt_in", "has_phrase", "MKT_RECUSADO", False),
                ("datetime_diff", "has_phrase", "D25_OK", True),
                ("@fields.pedido_produtos", "has_text", None, True)]
    for operand, case_type, argument, accepted in expected:
        if not current or current.get("actions"): return False
        router = current.get("router") or {}
        expression = str(router.get("operand") or "")
        if operand not in expression: return False
        expected_expression = DAY_EXPRESSION if operand == "datetime_diff" else REFUSAL_EXPRESSION if operand == "marketing_opt_in" else operand
        if "".join(expression.split()) != "".join(expected_expression.split()): return False
        cases = router.get("cases", [])
        if len(cases) != 1: return False
        case = cases[0]
        if case.get("type") != case_type or (argument is not None and case.get("arguments") != [argument]): return False
        matched = branch(current, case.get("category_uuid"))
        default = branch(current, router.get("default_category_uuid"))
        rejected, current = (default, matched) if accepted else (matched, default)
        if not rejected or not reject_ends(rejected): return False
    return bool(current and len(current.get("actions", [])) == 1 and any(a.get("type") == "send_msg" and (a.get("templating", {}).get("template") or {}).get("name") == "recompra" for a in current.get("actions", [])))


def inspect_structure(weni):
    fields = {f.get("key"): f.get("value_type") for f in weni.list_fields()}
    groups = weni.list_groups()
    errors = []
    def find_group(name):
        matches = [g for g in groups if g.get("name") == name]
        if len(matches) != 1 or not matches[0].get("uuid"):
            errors.append(f"Grupo ausente ou ambíguo: {name}"); return ""
        return matches[0]["uuid"]
    group_uuid, opt_out_uuid = find_group(GROUP), find_group(OPT_OUT)
    for key in sorted(FIELDS):
        if key not in fields: errors.append(f"Campo obrigatório ausente: {key}")
    if fields.get("pedido_data") != "datetime": errors.append("pedido_data precisa ser DateTime.")
    if fields.get("pedido_produtos") != "text" or fields.get("ultimo_pedido") != "text": errors.append("Produtos e JSON precisam ser campos Texto.")
    org = weni.get_org()
    if org.get("timezone") != "America/Belem": errors.append("Organização Weni precisa usar America/Belem; nenhuma configuração será alterada.")
    campaigns = [c for c in weni.list_campaigns() if c.get("name") == GROUP]
    event = {}
    if len(campaigns) != 1: errors.append("Campanha ausente ou ambígua.")
    else:
        campaign = campaigns[0]
        if (campaign.get("group") or {}).get("uuid") != group_uuid: errors.append("Campanha usa outro grupo.")
        events = weni.list_campaign_events(campaign["uuid"])
        if len(events) != 1: errors.append("A campanha deve ter exatamente um evento; múltiplos eventos podem duplicar envio.")
        else:
            event = events[0]
            if ((event.get("relative_to") or {}).get("key") != "pedido_data" or event.get("offset") != 25
                or event.get("unit") != "days" or (event.get("flow") or {}).get("name") != FLOW):
                errors.append("Evento não corresponde a pedido_data +25 dias e ao fluxo esperado.")
            definition = weni.get_flow_definition((event.get("flow") or {}).get("uuid", ""))
            matching = [f for f in definition.get("flows", []) if f.get("uuid") == (event.get("flow") or {}).get("uuid")]
            if len(matching) != 1: errors.append("Não foi possível ler o fluxo de recompra.")
            else:
                if not validate_flow_guards(matching[0], opt_out_uuid):
                    errors.append("Rotas do fluxo não correspondem às proteções auditadas de D+25, recusa, produtos e template; revisar manualmente.")
    return {"group_uuid": group_uuid, "opt_out_uuid": opt_out_uuid,
            "event_uuid": event.get("uuid", ""), "delivery_hour": event.get("delivery_hour", -1),
            "event_signature": digest(event), "errors": errors}


def resolve_latest(contact, farm, captured_at, lookup_cache=None, saved=None):
    """Reutiliza seleção de identidade e resolução oficiais, sem novos endpoints."""
    fields = get_fields(contact)
    from analytics import normalize_cpf
    cpf = normalize_cpf(fields.get("cpf"))
    if not cpf: return None, []
    cache = lookup_cache if lookup_cache is not None else {}
    if cpf not in cache:
        from farmalider_client import FarmaliderBadRequestError
        try: cache[cpf] = farm.get_cliente_by_cpf(cpf)
        except FarmaliderBadRequestError:
            cache[cpf] = {"_nexoflow_lookup": "CPF_REJEITADO_API"}
    if isinstance(cache[cpf], dict) and cache[cpf].get("_nexoflow_lookup") == "CPF_REJEITADO_API":
        return {"status_confirmacao": "CPF_REJEITADO_API"}, []
    payload = cache[cpf]
    result, selected = select_cliente_response(cpf, payload, weni_identity=weni_customer_identity(contact))
    if result[0] not in {"CPF_CONFIRMADO", "CPF_INVALIDO_ENCONTRADO"}: return {"status_confirmacao": result[0]}, []
    # Sem ultimoPedido, não reconstruir a compra a partir de campos soltos.
    if not selected or not isinstance(selected.get("ultimoPedido"), dict): return None, []
    latest = resolve_contact_order(contact, farm_client=farm, captured_at=captured_at,
                                   linked_cliente_id=result[1], cliente_response=payload)
    if latest[0] and _sales_order_is_valid(latest[0]) and latest[0].get("status_validacao") == "OK":
        return latest
    # A API retorna apenas ultimoPedido. Uma compra confirmada anterior só
    # pode ser recuperada de um ID conhecido, revalidado pelo GET e mesmo ID
    # de cliente. Não inventamos histórico nem interpretamos JSON Weni como prova.
    candidates = {text(((saved or {}).get("purchase") or {}).get("pedido_id"))}
    try:
        old_snapshot = json.loads(text(fields.get("ultimo_pedido")) or "{}")
        if isinstance(old_snapshot, dict): candidates.add(text(old_snapshot.get("pedido_id")))
    except ValueError:
        pass
    recovered = []
    for candidate in candidates - {"", text((latest[0] or {}).get("pedido_id"))}:
        if not candidate.isascii() or not candidate.isdigit(): continue
        reference_payload = {"cliente": selected["cliente"], "ultimoPedido": {"id": candidate, "codCliente": result[1]}, "itens": []}
        previous = resolve_contact_order(contact, farm_client=farm, captured_at=captured_at,
                                        linked_cliente_id=result[1], cliente_response=reference_payload)
        if previous[0] and _sales_order_is_valid(previous[0]) and previous[0].get("status_validacao") == "OK" and previous[1]:
            recovered.append(previous)
    return max(recovered, key=lambda pair: business_order_datetime(pair[0].get("data_hora"))) if recovered else latest


def propose(contact, order, items, structure, saved=None, *, now=None):
    now = (now or now_local()).astimezone(TZ)
    saved = saved or {}
    fields = get_fields(contact)
    in_group = member(contact, structure["group_uuid"], GROUP)
    uid = text(contact.get("uuid"))
    plan = {"contact_uuid": uid, "guard": guard(contact), "fields": {}, "action": "",
            "reason": "SEM_PEDIDO_CONFIRMADO", "order_id": "", "purchase": None,
            "in_group": in_group, "event_at": "", "due_today": False, "within_window": False, "scheduled_future": False}
    diagnostic = text((order or {}).get("status_confirmacao"))
    if diagnostic.startswith("CPF_") or diagnostic.startswith("ERRO_"): plan["reason"] = diagnostic
    dt = business_order_datetime((order or {}).get("data_hora"))
    names = [text(item.get("produto_nome")) for item in items]
    valid = bool(order and _sales_order_is_valid(order) and order.get("status_validacao") == "OK"
                 and dt and dt <= now and items and all(names))
    if valid:
        order_id = text(order.get("pedido_id"))
        from pedido_utils import normalize_farmalider_order_status_code, normalize_farmalider_payment_code
        current_order = business_order_datetime(fields.get("pedido_data")) if (
            normalize_farmalider_order_status_code(text(fields.get("pedido_status"))) in {"4", "1", "2"}
            and normalize_farmalider_payment_code(text(fields.get("pedido_forma_pagamento"))) != "0"
            and norm(fields.get("pedido_forma_pagamento")) != "cancelado"
        ) else None
        saved_dt = business_order_datetime((saved.get("purchase") or {}).get("data_hora"))
        if any(other and other > dt for other in (current_order, saved_dt)):
            valid = False; plan["reason"] = "PEDIDO_ANTIGO_BLOQUEADO"
        else:
            # Reutilizar o plano de pedido evita combinar a compra nova com
            # ID, valores ou quantidades da compra anterior no Analytics.
            from weni_update import ContactUpdatePlan, _apply_purchase_candidate
            candidate = {**contact, "fields": dict(fields)}
            if current_order is None: candidate["fields"]["pedido_data"] = ""
            purchase_plan = ContactUpdatePlan(uid)
            _apply_purchase_candidate(purchase_plan, candidate, farm_client=None,
                                      captured_at=now.isoformat(), resolved_order=(order, items))
            if not purchase_plan.order_validated:
                plan["reason"] = "PEDIDO_INCOMPLETO"
                if in_group: plan["action"] = "remove"
                return plan
            plan["order_id"] = order_id
            plan["purchase"] = {"pedido_id": order_id, "data_hora": dt.isoformat(),
                                "snapshot": serialize_pedido_products(order, items)}
            proposal = {**{k: v for k, v in purchase_plan.fields.items() if k in FIELDS}, "pedido_data": dt.isoformat(),
                        "pedido_produtos": serialize_weni_order_list(names), "ultimo_pedido": serialize_pedido_products(order, items)}
            for key, value in proposal.items():
                same = business_order_datetime(fields.get(key)) == dt if key == "pedido_data" else field_guard(key, fields.get(key)) == field_guard(key, value)
                if not same: plan["fields"][key] = value
            event_at = dt + timedelta(days=25)
            hour = structure.get("delivery_hour", -1)
            if isinstance(hour, int) and 0 <= hour <= 23: event_at = event_at.replace(hour=hour, minute=0, second=0, microsecond=0)
            plan["event_at"] = event_at.isoformat()
            age_days = (now.date() - dt.date()).days
            plan["due_today"] = age_days == 25
            plan["within_window"] = 0 <= age_days <= 25
            plan["scheduled_future"] = event_at > now
            plan["reason"] = "JANELA_0_A_25" if plan["within_window"] else "MAIS_DE_25_DIAS"
    opted_out = refused(contact) or member(contact, structure["opt_out_uuid"], OPT_OUT)
    if opted_out: plan["reason"] = "RECUSA_MARKETING"
    eligible = valid and plan["within_window"] and not opted_out
    entry = (saved.get("orders") or {}).get(plan["order_id"], {})
    same_reference = not plan["fields"].get("pedido_data")
    if in_group:
        if not eligible or not same_reference: plan["action"] = "remove"
        # Troca de referência requer remoção antes de campos e nova admissão
        # com seu próprio ID, somente após validação do resultado remoto.
        if eligible and not same_reference: plan["action"] = "replace"
    elif eligible:
        if entry.get("admitted") or entry.get("pending"):
            plan["reason"] = "PEDIDO_JA_ADMITIDO_OU_INDETERMINADO"
        else: plan["action"] = "add"
    if plan["action"] == "replace" and (entry.get("admitted") or entry.get("pending")):
        plan["action"] = "remove"
        plan["reason"] = "PEDIDO_JA_ADMITIDO_OU_INDETERMINADO"
    return plan


def audit_plan(plan):
    if not plan.get("contact_uuid"): raise RuntimeError("Plano sem UUID.")
    if not set(plan["fields"]).issubset(FIELDS): raise RuntimeError("Plano tenta alterar campo fora da recompra.")
    if plan["action"] not in {"", "add", "remove", "replace"}: raise RuntimeError("Ação de grupo inválida.")
    if plan["action"] in {"add", "replace"} and (not plan["within_window"] or plan["reason"] != "JANELA_0_A_25" or not plan["purchase"]):
        raise RuntimeError("Inclusão sem pedido validado na janela de 0 a 25 dias.")


def make_review(plans, structure, *, now=None, state=None):
    now = now or now_local()
    for plan in plans: audit_plan(plan)
    return {"schema": 1, "day": now.astimezone(TZ).date().isoformat(), "created_at": now.isoformat(),
            "policy": "JANELA_0_A_25_SEM_RECUSA", "structure": structure,
            "state_sha256": digest(state or {"schema": 1, "contacts": {}}), "plans": plans}


def write_review(review, path=REVIEW):
    path = Path(path)
    atomic_json(path, {"review": review, "sha256": digest(review)})
    counts = Counter(plan["reason"] for plan in review["plans"])
    lines = ["NexoFlow 1.0 — Revisão de recompra D+25", f"Dia local: {review['day']}",
             "Política: grupo entre 0 e 25 dias; envio somente D+25, bloqueando recusas; marketing_opt_in não será alterado.",
             "Sem disparos, sem alterações de campanha. Horário já passado não cria envio retroativo.",
             "Pendências: " + "; ".join(review["structure"]["errors"]), f"Resultados: {dict(counts)}"]
    for plan in review["plans"]:
        lines.append(f"Contato {plan['contact_uuid']} | pedido {plan['order_id']} | {plan['reason']} | grupo={plan['action'] or 'sem mudança'} | evento={plan['event_at']} | horário futuro={plan['scheduled_future']}")
        lines.extend(f"  {key}: {text(plan['guard']['fields'].get(key))} -> {value}" for key, value in plan["fields"].items())
    path.with_suffix(".txt").write_text("\n".join(lines)+"\n", encoding="utf-8-sig")


def read_review(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    review = data.get("review")
    if not isinstance(review, dict) or data.get("sha256") != digest(review) or review.get("schema") != 1 or review.get("policy") != "JANELA_0_A_25_SEM_RECUSA":
        raise RuntimeError("Revisão inválida ou alterada. Nenhuma aplicação iniciada.")
    for plan in review["plans"]: audit_plan(plan)
    return review


def append_audit(event, path=AUDIT):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True)+"\n"); handle.flush(); os.fsync(handle.fileno())


def apply_review(review, weni, farm, *, state_path=STATE, now_fn=now_local, audit_path=AUDIT):
    """Somente snapshots revisados; conflito ou confirmação incerta bloqueia inclusão."""
    now = now_fn()
    if review["day"] != now.astimezone(TZ).date().isoformat(): raise RuntimeError("Revisão de outro dia. Gere um novo dry-run, sem recuperação retroativa.")
    structure = inspect_structure(weni)
    if structure["errors"]: raise RuntimeError("Aplicação bloqueada: " + "; ".join(structure["errors"]))
    if structure != review["structure"]: raise RuntimeError("Campanha ou campos mudaram depois da revisão.")
    summary = Counter()
    started = monotonic()
    with state_lock(state_path):
        state = load_state(state_path)
        if digest(state) != review["state_sha256"]: raise RuntimeError("Estado mudou após a revisão. Gere um novo dry-run.")
        reads = RecompraReadCache(farm)
        for index, reviewed in enumerate(review["plans"], 1):
            if index > 1 and (index - 1) % 100 == 0:
                logging.info("Recompra aplicação: contatos=%s/%s; resultados=%s; cache=%s.",
                             index - 1, len(review["plans"]), dict(summary), reads.metrics())
            audit_plan(reviewed)
            uid = reviewed["contact_uuid"]
            saved = state["contacts"].get(uid, {})
            # Um plano sem trabalho não autoriza novas alterações descobertas
            # depois da revisão; elas serão propostas no próximo dry-run.
            if not plan_needs_apply(reviewed, saved):
                summary["sem_mudanca"] += 1
                continue
            current = weni.get_contact(uuid=uid)
            if not current or guard(current) != reviewed["guard"]:
                summary["conflitos"] += 1; append_audit({"contact_uuid": uid, "status": "CONFLITO_CONTATO"}, audit_path); continue
            order, items = resolve_latest(current, reads, now_fn().isoformat(), saved=saved)
            fresh = propose(current, order, items, structure, saved, now=now_fn())
            if any(fresh[key] != reviewed[key] for key in ("fields", "action", "order_id", "reason", "purchase", "event_at", "due_today", "within_window")):
                summary["conflitos"] += 1; append_audit({"contact_uuid": uid, "status": "CONFLITO_PEDIDO_OU_DIA"}, audit_path); continue
            action = fresh["action"]
            if not plan_needs_apply(fresh, saved):
                summary["sem_mudanca"] += 1
                continue
            # Persistir intenção antes de qualquer inclusão: uma resposta perdida
            # não autoriza reentrar no grupo na próxima execução.
            previous_state = deepcopy(saved)
            contact_state = state["contacts"].setdefault(uid, {"orders": {}})
            contact_state.setdefault("orders", {})
            if fresh["purchase"]: contact_state["purchase"] = fresh["purchase"]
            entry = contact_state["orders"].setdefault(fresh["order_id"], {}) if fresh["order_id"] else {}
            if action in {"add", "replace"}:
                entry.update({"pending": True, "day": review["day"], "event_uuid": structure["event_uuid"]})
            if contact_state != previous_state:
                atomic_json(state_path, state)
            persisted_state = deepcopy(contact_state)
            try:
                if action in {"remove", "replace"}:
                    weni.contact_group_action(uid, action="remove", group=structure["group_uuid"])
                    removed_contact = weni.get_contact(uuid=uid)
                    if not removed_contact or member(removed_contact, structure["group_uuid"], GROUP):
                        raise RuntimeError("Remoção do agendamento anterior não foi confirmada.")
                if fresh["fields"]: weni.update_contact_fields(uid, fresh["fields"])
                if action in {"add", "replace"}:
                    # Releitura imediatamente antes de admitir: recusa concorrente
                    # e mudanças externas não podem ser ignoradas.
                    latest = weni.get_contact(uuid=uid)
                    if not latest: raise RuntimeError("Contato ausente antes da inclusão.")
                    expected = dict(fresh["guard"]); expected["fields"] = {**expected["fields"], **{k: field_guard(k, v) for k,v in fresh["fields"].items()}}
                    actual = guard(latest)
                    actual["groups"] = [g for g in actual["groups"] if g not in {structure["group_uuid"], GROUP}]
                    expected["groups"] = [g for g in expected["groups"] if g not in {structure["group_uuid"], GROUP}]
                    if actual != expected or refused(latest) or member(latest, structure["opt_out_uuid"], OPT_OUT):
                        raise RuntimeError("Identidade, campos ou recusa mudaram antes da inclusão.")
                    if not 0 <= (now_fn().astimezone(TZ).date() - business_order_datetime(fresh["purchase"]["data_hora"]).date()).days <= 25:
                        raise RuntimeError("Janela de 0 a 25 dias terminou durante a aplicação.")
                    weni.contact_group_action(uid, action="add", group=structure["group_uuid"])
                    entry.update({"pending": False, "admitted": True, "admitted_at": now_fn().isoformat()})
                if fresh["in_group"] and fresh["order_id"] and action == "":
                    entry.update({"admitted": True, "pending": False})
                if contact_state != persisted_state:
                    atomic_json(state_path, state)
                summary["aplicados"] += 1
                append_audit({"contact_uuid": uid, "pedido_id": fresh["order_id"], "status": "APLICADO", "action": action, "at": now_fn().isoformat()}, audit_path)
            except Exception:
                if contact_state != persisted_state:
                    atomic_json(state_path, state)
                append_audit({"contact_uuid": uid, "pedido_id": fresh["order_id"], "status": "FALHA_OU_RESULTADO_INDETERMINADO", "at": now_fn().isoformat()}, audit_path)
                raise RuntimeError("Recompra interrompida. Estado preservado; inclusão incerta não será repetida automaticamente.") from None
    logging.info("Recompra aplicação: contatos=%s; duração=%.1fs; resultados=%s; cache=%s.",
                 len(review["plans"]), monotonic() - started, dict(summary), reads.metrics())
    return dict(summary)
