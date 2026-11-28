"""FARMA HML: reprodução offline de captura lacrada, sem clientes comerciais.

Os checkpoints contêm SOMENTE contagens/agregados. A linha original fica no
ZIP privado, verificado de novo a cada tentativa. Nenhuma mutação de API,
estado operacional, recibo ou publicação é executada por este caminho.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import zipfile
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from typing import cast
from unittest.mock import patch
from uuid import UUID

from .contracts import LostLease
from .real_read_transport import ProbePending

SCENARIO = "referencia_congelada"
INTERRUPTION = "referencia_congelada_retomada"
PERIODS = (("2026-11-01", "2026-11-26"), ("2026-11-10", "2026-11-26"), ("2026-11-08", "2026-11-08"))
BATCH_SIZE = 1000
PROTOCOL = 1
# Limites exclusivos de leitura OFFLINE. Não alteram ReadOnlySession/real_plan.
MAX_ARCHIVE = 512 * 1024**2
MAX_EXPANDED = 3 * 1024**3
MAX_STATE = 128 * 1024**2
MAX_LINE = 8 * 1024**2
MAX_CONTACTS = 100_000
REQUIRED = frozenset({
    "ready_recibo.json", "farma-reservas.json", "weni_update_state.json",
    "recompra_state.json", "weni_update_review.json", "weni_update_review_duplicados.json",
    "recompra_review.json", "weni_insumos_privados.jsonl", "recompra_insumos_privados.jsonl",
    "BI_Vendas.jsonl", "Historico_Pedidos.jsonl", "Pedidos_FarmaLider.jsonl",
    "Historico_Itens.jsonl", "Itens_Pedidos_FarmaLider.jsonl",
    "Meta_Ads_Diario.jsonl", "meta_diagnostico.json", "meta_cobertura.json",
    "meta_tabelas_farma.json",
})


def require(condition, code="REFERENCIA_DIVERGENTE"):
    if not condition:
        raise ProbePending(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def scope(task):
    require(task["segmento"] == "FARMA" and task["cenario"] in {SCENARIO, INTERRUPTION}
            and os.environ.get("HUB_AMBIENTE") == "homologacao"
            and os.environ.get("HUB_ESCRITA_REAL") == "false"
            and os.environ.get("NEXOFLOW_PERFIL") == "FARMA"
            and os.environ.get("HUB_FROZEN_REPLAY_ENABLED") == "true", "ESCOPO_FARMA_HML_OBRIGATORIO")
    require(task["cenario"] != INTERRUPTION or os.environ.get("HUB_FROZEN_REPLAY_INTERRUPT_TEST") == "true",
            "ESCOPO_FARMA_HML_OBRIGATORIO")


def stream_sha256(stream):
    value = hashlib.sha256()
    while block := stream.read(1024 * 1024):
        value.update(block)
    return value.hexdigest()


def expected_revision():
    revision = os.environ.get("HUB_FROZEN_REPLAY_REVISION", "")
    try:
        return str(UUID(revision))
    except ValueError:
        raise ProbePending("ESTADO_PRIVADO_AUSENTE") from None


class Capture:
    def __init__(self, archive, expected_sha):
        self.archive = archive
        self.sha = expected_sha
        require(archive.stat().st_size <= MAX_ARCHIVE, "LIMITE_REFERENCIA_EXCEDIDO")
        self.file = archive.open("rb")
        try:
            require(stream_sha256(self.file) == expected_sha)
            revision = expected_revision()
            self.file.seek(0)
            self.zip = zipfile.ZipFile(self.file)
            names = self.zip.namelist()
            require(len(names) == len(set(names)) <= 100)
            require("manifesto.json" in names and self.zip.getinfo("manifesto.json").file_size < 1024**2)
            self.manifest = self.read("manifesto.json")
            m = self.manifest
            require(m["versao"] == "1.5.64" and m["segmento"] == "FARMA" and m["modo"] == "somente_leitura"
                    and m["publicacao_remota"] is False and m["escrita_comercial"] is False
                    and m["ready_preservada"] is True and m["ready"]["version"] == 15
                    and m["ready"]["revisao"] == revision and m["ready"]["segment"] == "FARMA"
                    and m["ready"]["target"] == "nexoflow_datastudio.farma"
                    and m["ready"]["environment"] == "producao"
                    and m["periodo"] == {"inicio": PERIODS[0][0], "fim": PERIODS[0][1]}
                    and m["status"] in {"captura_concluida", "captura_concluida_com_revisao"})
            entries = {e["caminho"]: e for e in m["arquivos"]}
            require(len(entries) == len(m["arquivos"]) and set(names) == set(entries) | {"manifesto.json"}
                    and REQUIRED <= set(entries))
            require(sum(self.zip.getinfo(n).file_size for n in names) <= MAX_EXPANDED,
                    "LIMITE_REFERENCIA_EXCEDIDO")
            for name, entry in entries.items():
                require(self.zip.getinfo(name).file_size == entry["bytes"])
                with self.zip.open(name) as f:
                    require(stream_sha256(f) == entry["sha256"])
            receipt = self.read("ready_recibo.json")
            require(receipt["state"] == "READY" and receipt["revision"] == revision
                    and receipt["version"] == 15 and receipt["source_sha"] == m["ready"]["source_sha"])
        except BaseException:
            if hasattr(self, "zip"):
                self.zip.close()
            self.file.close()
            raise

    def close(self):
        self.zip.close()
        self.file.close()

    def read(self, name):
        require(self.zip.getinfo(name).file_size <= MAX_STATE, "LIMITE_REFERENCIA_EXCEDIDO")
        return json.loads(self.zip.read(name))

    def rows(self, name):
        # Não extrair o ZIP, nem usar nomes de arquivos vindos de payload externo.
        with self.zip.open(name) as f:
            while True:
                line = f.readline(MAX_LINE + 1)
                if not line:
                    return
                require(len(line) <= MAX_LINE, "LIMITE_REFERENCIA_EXCEDIDO")
                yield json.loads(line)


@contextmanager
def offline_rules():
    import requests

    def forbidden(*_a, **_kw):
        raise ProbePending("ESCRITA_O_REDE_BLOQUEADA")

    # Não bloquear a conexão PostgreSQL da fila/lease. Nenhum cliente HTTP
    # pode ser usado durante o replay. Suprimir logging das regras legadas.
    level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with patch.object(requests.Session, "request", forbidden):
            yield
    finally:
        logging.disable(level)


class FrozenRules:
    def __init__(self, cap):
        import recompra as rc
        import reservas_farma as rf
        import weni_update as wu
        from purchase_checks import merge_purchase_checks

        self.rc, self.wu = rc, wu
        self.weni_review = cap.read("weni_update_review.json")
        w = self.weni_review
        require(w["segment"] == "FARMA" and w["mode"] == "incremental")
        require(w["schema_version"] == wu.REVIEW_SCHEMA_VERSION)
        self.weni = {p["contact_uuid"]: p for p in w["plans"]}
        require(len(self.weni) == len(w["plans"]) <= MAX_CONTACTS)
        canonical_plans = [{k: v for k, v in p.items() if k != "display"} for p in sorted(w["plans"], key=lambda p: p["contact_uuid"])]
        require(digest(canonical_plans) == w["plan_sha256"])
        d = cap.read("weni_update_review_duplicados.json")
        dh = d.pop("sha256")
        require(digest(d) == dh == w["dedup_sha256"] and d["segment"] == "FARMA")
        self.dedup = {k: len(d[k]) for k in ("pairs", "pending", "renames")}
        # O arquivo de reservas é lacrado, e as duas revisões devem referir
        # exatamente seu hash. Usar o validador original do formato UUID.
        raw = cap.zip.read("farma-reservas.json")
        import tempfile
        with tempfile.TemporaryDirectory(prefix="nf-reservas-") as tmp:
            path = Path(tmp) / "reservas.json"
            path.write_bytes(raw)
            with patch.object(rf, "MANIFESTO", path):
                self.reservas = rf.carregar("FARMA")
                # A revisão inteira também é validada pela auditoria nativa,
                # inclusive as criações que não podem ser recalculadas.
                wpath = Path(tmp) / "weni_update_review.json"
                wpath.write_bytes(cap.zip.read("weni_update_review.json"))
                old_plans, _, _ = wu.load_review_snapshot(full=False, json_path=wpath)
                wu.audit_plans(old_plans, opt_out_group_available=True, opt_in_group_available=True)
                del old_plans
        require(bool(self.reservas.sha256) and self.reservas.sha256 == cap.manifest["reservas"]["sha256"])
        self.reservas.conferir_revisao(w)
        self.reservas.conferir_revisao(d)
        losers = [p["duplicate_uuid"] for p in d["pairs"]]
        require(d["schema"] == 2 and d["full"] is False and d["quarter"] is None
                and len(losers) == len(set(losers)) and not set(losers)&{p["canonical_uuid"] for p in d["pairs"]})
        state = cap.read("recompra_state.json")
        require(state["schema"] == 1 and isinstance(state["contacts"], dict)
                and state.get("segment", "FARMA") == "FARMA")
        weni_state = cap.read("weni_update_state.json")
        pending = merge_purchase_checks(state.get("pending_purchase_checks"), weni_state.get("pending_purchase_checks"))
        if pending or "pending_purchase_checks" in state:
            state["pending_purchase_checks"] = pending
        r = cap.read("recompra_review.json")
        self.recompra_review = r["review"]
        review = self.recompra_review
        require(rc.digest(review) == r["sha256"] and rc.digest(state) == review["state_sha256"]
                and review["structure"]["segment"] == "FARMA" and not review["structure"]["errors"]
                and review["schema"] == 1 and review["policy"] == rc.profile_for("FARMA").policy)
        self.reservas.conferir_revisao(review)
        self.recompra = {p["contact_uuid"]: p for p in review["plans"]}
        require(len(self.recompra) == len(review["plans"]) <= MAX_CONTACTS)
        for plan in review["plans"]:
            require(plan.get("segment", "FARMA") == "FARMA")
            rc.audit_plan(plan)
        existing = [p for p in w["plans"] if not p["contact_uuid"].startswith("novo-api:")]
        self.expected = {
            "weni": {"contatos": w["summary"]["contacts_considered"] - (len(w["plans"]) - len(existing)),
                     "planos": len(existing), "campos": sum(len(p["changes"]) for p in existing),
                     "grupos": sum(len(p["group_actions"]) for p in existing)},
            "recompra": {"planos":len(review["plans"]),
                         "inclusoes":sum(p.get("action")=="add" for p in review["plans"]),
                         "remocoes":sum(p.get("action")=="remove" for p in review["plans"]),
                         "trocas":sum(p.get("action")=="replace" for p in review["plans"])}
        }
        self.state = state
        self.start = datetime.fromisoformat(review["created_at"])
        self.end = datetime.fromisoformat(review["generated_at"])
        require(self.start <= self.end)
        require(len(self.reservas.contatos) == cap.manifest["reservas"]["quantidade"])

    def weni_row(self, a, counts):
        from farmalider_client import FarmaliderClient

        wu = self.wu
        uid = a["contato"]["uuid"]
        kw = dict(a["parametros"])
        require(kw["captured_at"] == self.weni_review["captured_at_utc"])
        old = self.weni.get(uid)
        new_customer = uid.startswith("novo-api:")
        if new_customer:
            # A decisão de descoberta deve permanecer pendente sem o diretório
            # completo; mas os campos/pedido da proposta podem ser recalculados
            # com o cadastro selecionado e a resposta normalizada já capturados.
            require(old is not None)
            counts["novos_pendentes"] += 1
        def recorded(key):
            # Alguns caminhos (identidade com pedidos distintos) não consultam
            # pedido; ausência é permitida somente se a regra não pedir o dado.
            require(key in a)
            return deepcopy(a[key])

        kw["candidate_message_ids"] = set(kw["candidate_message_ids"])
        if kw.get("available_weni_fields") is not None:
            kw["available_weni_fields"] = set(kw["available_weni_fields"])
        with patch.object(wu, "selected_customer", lambda *_a, **_kw: recorded("cadastro_selecionado")), patch.object(wu, "resolve_contact_order", lambda *_a, **_kw: recorded("pedido_normalizado")):
            # Objeto marcador, não é cliente e não sabe fazer requisições.
            fresh = wu._build_contact_plan(a["contato"], farm_client=cast(FarmaliderClient, object()), **kw)
        if new_customer:
            self.creation_content(a, fresh, old, counts)
            return
        emitted = fresh.has_changes or any(k.startswith("__pending_purchase_check") for k in fresh.guards)
        counts["contatos"] += 1
        if emitted:
            wu.audit_plans([fresh], opt_out_group_available=True, opt_in_group_available=True)
            counts["planos"] += 1
            counts["campos"] += len(fresh.fields)
            counts["grupos"] += len(fresh.group_actions)
            counts["reservados"] += int(self.reservas.protege(uid))
        old_value = None if old is None else {k: v for k, v in old.items() if k != "display"}
        new_value = wu._canonical_plan(fresh) if emitted else None
        counts["identicos" if canonical(old_value) == canonical(new_value) else "divergentes"] += 1

    def creation_content(self, a, fresh, old, counts):
        from analytics import normalize_cpf
        from customer_discovery import GUARD, phone
        from farmalider_customers import matching_order_address

        customer = a["cadastro_selecionado"]
        require(isinstance(customer, dict) and fresh.order_validated)
        fields = set(a["parametros"]["available_weni_fields"])
        cpf = normalize_cpf(customer["cpf"])
        number = phone(customer.get("celular"))
        urns = ["whatsapp:" + number] if number else []
        name = str(customer.get("nome") or "").strip()
        require(a["contato"]["urns"] == urns and a["contato"]["name"] == name
                and a["contato"]["fields"]["cpf"] == cpf)
        extra = {}
        if "email" in fields and customer.get("email"):
            extra["email"] = str(customer["email"]).strip()
        if "origem_contato" in fields:
            extra["origem_contato"] = "API FarmaLíder — FARMA"
        status, address = matching_order_address(customer, segment="FARMA")
        if "endereco" in fields and status == "ENDERECO_CONFIRMADO" and address:
            extra["endereco"] = ", ".join(str(address.get(k) or "").strip()
                for k in ("logradouro","numero","complemento") if str(address.get(k) or "").strip())
        fresh.fields["cpf"] = cpf
        fresh.previous["cpf"] = None
        fresh.guards[GUARD] = {
            "segment": "FARMA", "customer_id": str(customer["id"]), "name": name,
            "urns": urns, "extra_fields": extra,
        }
        self.wu.audit_plans([fresh], opt_out_group_available=True, opt_in_group_available=True)
        expected = deepcopy({k:v for k,v in old.items() if k!="display"})
        # O hash do snapshot bruto não pode ser reconstruído de um cadastro
        # selecionado; excluí-lo explicitamente da comparação de conteúdo.
        expected["guards"][GUARD].pop("source_sha256")
        actual = self.wu._canonical_plan(fresh)
        counts["novos_conteudo_identico" if canonical(expected) == canonical(actual)
               else "novos_conteudo_divergente"] += 1

    def recompra_row(self, a, counts):
        rc = self.rc
        uid = a["contato"]["uuid"]
        require(uid in self.recompra and a["estrutura"] == self.recompra_review["structure"]
                and datetime.fromisoformat(a["corte"]) == self.start
                and canonical(a["estado_contato"]) == canonical(rc._saved_with_purchase_check(self.state, uid)))
        new = rc.propose(a["contato"], a["pedido"], a["itens"], a["estrutura"], a["estado_contato"], now=self.start)
        rc._refresh_plan_deadline(new, self.end)
        rc.audit_plan(new)
        old = {k: v for k, v in self.recompra[uid].items() if k != "_incremental"}
        counts["planos"] += 1
        counts["identicos" if canonical(old) == canonical(new) else "divergentes"] += 1
        action = {"add": "inclusoes", "remove": "remocoes", "replace": "trocas", "": "sem_acao"}[new["action"] or ""]
        counts[action] += 1
        if self.reservas.protege(uid):
            counts["reservados"] += 1
            counts["reservados_" + action] += 1


def reference_ids(cap, rules, stage, filename):
    """Verificação de identidade completa antes de confirmar lotes.
    Guarda só UUIDs em memória, nunca os persiste. Detecta duplicatas mesmo
    entre lotes; a SHA lacrada garante a mesma ordem na retomada.
    """
    seen = set()
    for a in cap.rows(filename):
        uid = a["contato"]["uuid"]
        require(isinstance(uid, str) and uid and uid not in seen and len(seen) < MAX_CONTACTS)
        seen.add(uid)
    expected = rules.weni if stage == "weni" else rules.recompra
    require(set(expected) <= seen)
    if stage == "recompra":
        require(set(expected) == seen)
    return len(seen)


def progress(stage, last, total, counts, **extra):
    try:
        revision = expected_revision()
    except ProbePending:
        revision = None
    return {
        "modo": SCENARIO, "externas_gravacoes": 0, "publicacoes": 0,
        "referencia": {"revisao": revision, "versao": 15, "periodo": list(PERIODS[0])},
        "replay": {"etapa": stage, "ultimo_lote": last, "lotes_total": total,
                   "contagens": dict(counts), **extra},
    }


def persist_batch(store, task, cap, stage, base, number, total, counts, *, offset, resumed):
    value = {
        "protocolo": PROTOCOL, "sha256_referencia": cap.sha, "fase": stage,
        "lote": number, "linhas": offset, "contagens": dict(counts),
    }
    store.checkpoint(task, base + number, value,
                     progress=progress(stage, number, total, counts, retomada=resumed))


def replay_rows(store, task, cap, rules, stage, base, filename, saved, lost, interrupt_after):
    total_rows = reference_ids(cap, rules, stage, filename)
    total = (total_rows + BATCH_SIZE - 1) // BATCH_SIZE
    checkpoint_keys = sorted(k for k in saved if base < k <= base + 999)
    require(checkpoint_keys == list(range(base + 1, base + 1 + len(checkpoint_keys))))
    require(len(checkpoint_keys) <= total)
    offset, counts, last = 0, Counter(), 0
    for key in checkpoint_keys:
        item = saved[key]
        require(item["protocolo"] == PROTOCOL and item["sha256_referencia"] == cap.sha
                and item["fase"] == stage and item["lote"] == key - base
                and item["linhas"] == min((key - base)*BATCH_SIZE, total_rows))
        last, offset, counts = item["lote"], item["linhas"], Counter(item["contagens"])
    resumed = last > 0
    handler = rules.weni_row if stage == "weni" else rules.recompra_row
    for index, a in enumerate(cap.rows(filename), 1):
        if index <= offset:
            continue
        if lost.is_set():
            raise LostLease("LEASE_PERDIDO")
        handler(a, counts)
        if index % BATCH_SIZE == 0 or index == total_rows:
            number = (index + BATCH_SIZE - 1) // BATCH_SIZE
            persist_batch(store, task, cap, stage, base, number, total, counts, offset=index, resumed=resumed)
            # Ensaio exclusivamente de homologação: simula parada depois do
            # commit. Liberar lease para nova tentativa, sem reiniciar processo
            # nem interromper outros segmentos. Checkpoint já durável.
            if (interrupt_after == base + number or
                    (task["cenario"] == INTERRUPTION and stage == "weni" and number == 1 and task["tentativa"] == 1)):
                store.finish(task, "aguardando", error="REDE_SIMULADA",
                             result=progress(stage, number, total, counts, retomada=False, interrupcao_ensaio=True))
                return None
    return dict(counts), total, resumed


def finance(cap):
    """Somas de fatos normalizados lacrados; não reconsulta API nem republica."""
    from decimal import Decimal

    from analytics import _order_revenue_parts, _sales_order_is_valid, _to_decimal
    from order_history import cents

    def within(row):
        return PERIODS[0][0] <= row["data"][:10] <= PERIODS[0][1]
    def values(row):
        return tuple(cents(Decimal(str(row[k]))) for k in ("produtos", "frete", "faturamento"))
    hist, op = {}, {}
    for row in cap.rows("Historico_Pedidos.jsonl"):
        require(row["segmento"] == "FARMA")
        if within(row) and row["vigente"] == "Sim" and row["estado"] == "valido":
            require(row["pedido_id"] not in hist)
            v = values(row)
            require(v[0]+v[1] == v[2])
            hist[row["pedido_id"]] = (row["data"], v)
    for row in cap.rows("Pedidos_FarmaLider.jsonl"):
        if within(row) and _sales_order_is_valid(row):
            require(row["pedido_id"] not in op)
            op[row["pedido_id"]] = (row["data"], tuple(cents(v) for v in _order_revenue_parts(row)))
    require(set(hist) == set(op))
    bi = [r for r in cap.rows("BI_Vendas.jsonl") if within(r)]
    totals = []
    for start, end in PERIODS:
        h = [v for d, v in hist.values() if start <= d <= end]
        b = [r for r in bi if start <= r["data"] <= end]
        historical = [len(h), *(sum(v[i] for v in h) for i in range(3))]
        stored = [sum(int(r["pedidos"]) for r in b), *(sum(cents(Decimal(str(r[k]))) for r in b) for k in ("faturamento_produtos", "faturamento_frete", "faturamento_total"))]
        keys = ("pedidos", "produtos_centavos", "frete_centavos", "faturamento_centavos")
        totals.append({"periodo": [start, end], "historico": dict(zip(keys, historical, strict=True)),
                       "bi_armazenada": dict(zip(keys, stored, strict=True)), "diferenca": dict(zip(keys, (a-b for a,b in zip(historical,stored, strict=True)), strict=True))})
    ids = {k for k,h in hist.items() if h != op[k]}
    differences = [hist[k][1][2]-op[k][1][2] for k in ids]
    diff_days = sorted({hist[k][0] for k in ids})
    hi, oi, hn, on = Counter(), Counter(), Counter(), Counter()
    if ids:
        for row in cap.rows("Historico_Itens.jsonl"):
            k=row["pedido_id"]
            if k in ids and row["vigente"]=="Sim" and row["estado"]=="valido" and row["frete"]=="Não":
                hi[k]+=cents(Decimal(str(row["valor"])))
                hn[k]+=1
        for row in cap.rows("Itens_Pedidos_FarmaLider.jsonl"):
            key=row["pedido_chave"]
            if key.startswith("FARMALIDER:") and (k:=key.removeprefix("FARMALIDER:")) in ids:
                oi[k]+=cents(_to_decimal(row["valor_total"], "valor_total"))
                on[k]+=1
        require(all(hi[k]==hist[k][1][0] and oi[k]==op[k][1][0] for k in ids))
    # Somente números, sem identificador do pedido.
    item_evidence=sorted(({"historico_centavos":hi[k],"operacional_centavos":oi[k],
                           "itens_historico":hn[k],"itens_operacional":on[k]} for k in ids),
                         key=lambda row:row["historico_centavos"])
    return {"periodos": totals, "pedidos_divergentes": len(differences),
            "dias_divergentes": diff_days, "diferencas_centavos": sorted(differences),
            "itens_divergentes":item_evidence,
            "atribuicao_comercial": "parcial", "fonte_financeira": "historico_vigente_ready"}


def meta_summary(cap):
    from decimal import Decimal

    from .real_read_probe import ACCOUNT, AD, DAYS

    diagnostic=cap.read("meta_diagnostico.json")
    coverage=cap.read("meta_cobertura.json")
    observed={}
    table=cap.read("meta_tabelas_farma.json")["Meta_Ads_Diario"]
    for row in table:
        if row.get("conta_id")==ACCOUNT and row.get("anuncio_id")==AD and row.get("data") in DAYS:
            day=row["data"]
            require(day not in observed)
            observed[day]={"conversas":int(Decimal(str(row["conversas_iniciadas_meta"]))),
                           "impressoes_disponiveis":bool(str(row.get("impressoes") or "").strip()),
                           "classificacao_confirmada":row.get("segmento")=="FARMA"}
    require(set(observed)==set(DAYS))
    return {"atribuicao":"parcial","dias":observed,"cobertura_weni":"parcial",
            "eventos_ctwa":coverage["details"]["FARMA"]["events"],
            "lotes_ctwa":coverage["details"]["FARMA"]["batches"],
            "consultas_meta":diagnostic["http_meta"]["GET"]}


def run_frozen(store, task, *, interrupt_after=None):
    stopped, lost = Event(), Event()
    current_stage = "validacao"
    cap = None
    def heartbeat():
        while not stopped.wait(min(5.0, store.settings.lease_seconds/3)):
            try:
                store.renew_lease(task)
                Path("/tmp/hub-worker-heartbeat").touch()
            except Exception:
                lost.set()
                return
    store.renew_lease(task)
    thread = Thread(target=heartbeat, name="nf-replay-lease", daemon=True)
    thread.start()
    try:
        scope(task)
        zip_path = os.environ.get("HUB_FROZEN_REPLAY_ZIP_FILE")
        expected = os.environ.get("HUB_FROZEN_REPLAY_SHA256")
        require(bool(zip_path and expected), "ESTADO_PRIVADO_AUSENTE")
        require(Path(str(zip_path)).is_file(), "ESTADO_PRIVADO_AUSENTE")
        cap = Capture(Path(str(zip_path)), str(expected))
        saved = store.checkpoints(task)
        with offline_rules():
            rules = FrozenRules(cap)
            current_stage = "weni"
            w = replay_rows(store, task, cap, rules, "weni", 1000, "weni_insumos_privados.jsonl", saved, lost, interrupt_after)
            if w is None:
                return
            current_stage = "recompra"
            r = replay_rows(store, task, cap, rules, "recompra", 2000, "recompra_insumos_privados.jsonl", saved, lost, interrupt_after)
            if r is None:
                return
            current_stage = "analytics"
            if 3001 in saved:
                cached = saved[3001]
                require(cached["protocolo"] == PROTOCOL and cached["sha256_referencia"] == cap.sha)
                financial = cached["financial"]
            else:
                start_marker = {"protocolo": PROTOCOL, "sha256_referencia": cap.sha}
                store.checkpoint(task, 3000, start_marker, progress=progress("analytics",0,1,{},retomada=w[2] or r[2]))
                financial = finance(cap)
                financial["meta"] = meta_summary(cap)
                store.checkpoint(task,3001,{**start_marker,"financial":financial},
                                 progress=progress("analytics",1,1,{},retomada=w[2] or r[2]))
        wc, wl, wr = w
        rc, rl, rr = r
        differences = {stage: {key: counts.get(key, 0)-value for key,value in rules.expected[stage].items()}
                       for stage, counts in (("weni", wc), ("recompra", rc))}
        valid = (not wc.get("divergentes") and not wc.get("novos_conteudo_divergente") and not rc.get("divergentes")
                 and not any(v for d in differences.values() for v in d.values()))
        outcome = progress("conferido", wl+rl+1, wl+rl+1,
                           {"identicos":wc.get("identicos",0)+rc.get("identicos",0),
                            "divergentes":wc.get("divergentes",0)+rc.get("divergentes",0),
                            "novos_pendentes":wc.get("novos_pendentes",0),
                            "novos_conteudo_identico":wc.get("novos_conteudo_identico",0),
                            "novos_conteudo_divergente":wc.get("novos_conteudo_divergente",0)},
                           retomada=wr or rr, paridade=valid, etapa_pendente="weni")
        outcome.update(
            update_weni=wc, recompra=rc, analytics=financial, diferencas=differences,
            referencia_contagens=rules.expected,
            cortes={"weni":rules.weni_review["captured_at_utc"],"recompra":rules.recompra_review["created_at"]},
            reservas=len(rules.reservas.contatos),
            lotes_confirmados=wl+rl+1, criacao_pendente=wc.get("novos_pendentes",0),
            deduplicacao_pendente=rules.dedup, historico_checkpoint="indisponivel",
            meta_atribuicao="parcial", primeira_etapa_pendente="atualizacao_weni",
            pendencias=[{"fonte":"weni","motivo":"FONTE_ESSENCIAL_INCOMPLETA","tratamento":"validar_criacao_e_deduplicacao"},
                        {"fonte":"anuncios","motivo":"COBERTURA_PARCIAL","tratamento":"verificar_meta"}])
        if lost.is_set():
            raise LostLease("LEASE_PERDIDO")
        store.finish(task, "parcial" if valid else "revisao_necessaria", result=outcome)
    except LostLease:
        raise
    except Exception as exc:
        # Não expor exceção bruta, payload ou caminhos. Preserve o último lote
        # confirmado no resultado e apresente a etapa que ficou pendente.
        if lost.is_set():
            raise LostLease("LEASE_PERDIDO") from None
        latest = store.get(task["segmento"], task["id"]) or {}
        result = dict(latest.get("resultado") or progress(current_stage,0,0,{}))
        result["replay"]["etapa_pendente"] = current_stage
        safe_codes = {"ESTADO_PRIVADO_AUSENTE", "ESCOPO_FARMA_HML_OBRIGATORIO", "REFERENCIA_DIVERGENTE",
                      "LIMITE_REFERENCIA_EXCEDIDO", "ESCRITA_O_REDE_BLOQUEADA"}
        result["replay"]["motivo"] = str(exc) if isinstance(exc,ProbePending) and str(exc) in safe_codes else "REFERENCIA_DIVERGENTE"
        store.finish(task,"revisao_necessaria",result=result,error="FONTE_ESSENCIAL_INCOMPLETA")
    finally:
        if cap is not None:
            cap.close()
        stopped.set()
        thread.join()
