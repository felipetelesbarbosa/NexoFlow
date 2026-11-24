"""Atribuição comercial FARMA com pedido oficial e evidência Weni Flows."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import BadZipFile
from zoneinfo import ZoneInfo

from analytics import _sales_order_is_valid
from delivery_spreadsheets import (
    CONVERSATIONS_FILENAME,
    ROOM_COLUMNS,
    _date,
    _rows,
    _tags,
    _uuid,
)
from meta_ads_evidence import PROJECT_NAMES, ReadOnlyEvidenceClient
from order_history import HistoryQuery, IdentityIndex
from pedido_utils import business_order_datetime
from weni_client import WeniError

PAYLOAD_KEY = "nf_atribuicao_comercial_v1"
FLOWS_SOURCE = "WENI_FLOWS_V2"
XLSX_SOURCE = "WENI_XLSX_SALAS"
WINDOW = timedelta(days=7)
START_TOLERANCE = timedelta(seconds=5)
BELEM = ZoneInfo("America/Belem")
HISTORY_START = date(2020, 1, 1)
CONVERSATION_STATES = (
    "com_pedido",
    "sem_pedido_apos_7d",
    "em_acompanhamento",
    "pendente_de_conferencia",
)
ROOM_EXPORT_NAME = re.compile(
    rf"{re.escape(Path(CONVERSATIONS_FILENAME).stem)}(?: ?\(\d+\))?\.xlsx",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Conversation:
    identity: str
    opened: datetime
    closed: datetime
    human: bool


@dataclass(frozen=True)
class Room:
    opened: datetime
    closed: datetime


@dataclass(frozen=True)
class Touch:
    event_id: str
    at: datetime
    urn: str
    chat_id: str
    grain: tuple[str, str, str]


@dataclass(frozen=True)
class Purchase:
    order_id: str
    owner: str
    at: datetime
    revenue: Decimal
    contact: str = ""


def read_finalized_rooms(path, start, end, clock):
    """Retorna as salas elegíveis e as datas observadas em Belém."""
    required = ROOM_COLUMNS | {"queue__sector__name"}
    rooms = defaultdict(set)
    observed = set()
    for _, header, values in _rows(Path(path), "rooms", required):
        row = dict(zip(header, values, strict=False))
        if row.get("queue__sector__name") != PROJECT_NAMES["FARMA"]:
            continue
        tags = {" ".join(tag.casefold().split()) for tag in _tags(row.get("tags_list"))}
        if "pedido finalizado" not in tags:
            continue
        opened, closed = _date(row["created_on"]), _date(row["ended_at"])
        urn = str(row["urn"] or "").strip()
        if ":" in urn and not urn.startswith("whatsapp:"):
            # O mesmo setor também atende Instagram. CTWA aqui é WhatsApp.
            continue
        if (
            not opened
            or not closed
            or opened > closed
            or closed > clock
            or not _uuid(row["contact__uuid"])
            or not urn.startswith("whatsapp:")
            or not urn.removeprefix("whatsapp:").isdigit()
            or row["is_active"] not in (False, 0, "false", "False")
            or not row["user__email"]
        ):
            raise ValueError("Sala marcada como finalizada com evidência inválida.")
        closed_day = closed.astimezone(BELEM).date()
        observed.add(closed_day)
        if start <= closed_day <= end:
            rooms[urn].add(Room(opened, closed))
    return (min(observed), max(observed), rooms) if rooms else None


def optional_room_export(root, config, start, end, clock):
    """Procura o XLSX mais recente com salas válidas no período da análise."""
    candidates = set()
    if isinstance(config, dict) and isinstance(config.get("arquivo"), str):
        if config["arquivo"]:
            candidates.add(root / config["arquivo"])
    folders = [root / "importacoes"]
    try:
        folders.append(Path.home() / "Downloads")
    except RuntimeError:
        pass
    for folder in folders:
        try:
            candidates.update(
                path for path in folder.iterdir() if ROOM_EXPORT_NAME.fullmatch(path.name)
            )
        except OSError:
            continue
    modified = {}
    for path in candidates:
        try:
            if path.is_file():
                modified[path] = path.stat().st_mtime_ns
        except OSError:
            continue
    status = "ausente"
    for path in sorted(modified, key=lambda p: (modified[p], str(p)), reverse=True):
        try:
            export = read_finalized_rooms(path, start, end, clock)
        except (BadZipFile, KeyError, OSError, SyntaxError, ValueError):
            status = "invalido"
            continue
        if export is not None:
            return export, "utilizado"
        if status == "ausente":
            status = "sem_salas_no_periodo"
    return None, status


def retain_commercial_audits(tables, previous):
    """O rebuild de fatos Meta preserva atribuição fora do corte recalculado."""
    saved = {
        row["chave"]: json.loads(row.get("payload_api_json") or "{}").get(PAYLOAD_KEY)
        for row in previous.get("Meta_Ads_Diario", [])
        if row["segmento"] == row["classificacao"] == "FARMA"
    }
    for row in tables["Meta_Ads_Diario"]:
        audit = saved.get(row["chave"])
        if isinstance(audit, dict) and row["segmento"] == row["classificacao"] == "FARMA":
            payload = json.loads(row["payload_api_json"])
            payload[PAYLOAD_KEY] = audit
            row["payload_api_json"] = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )


def load_conversations(token, urns, begin, end, *, org_uuid=""):
    if not urns:
        return {}, set()
    client = ReadOnlyEvidenceClient(token, segment="FARMA")
    try:
        org = client.get_org()
        if (
            not isinstance(org, dict)
            or org.get("name") != PROJECT_NAMES["FARMA"]
            or org.get("timezone") != BELEM.key
            or not _uuid(org.get("uuid"))
            or (org_uuid and org.get("uuid") != org_uuid)
        ):
            raise ValueError("Organização Weni FARMA divergente.")
        conversations, failed = {}, set()
        for urn in sorted(urns):
            try:
                conversations[urn] = parse_conversations(
                    client.list_conversation_classifications(
                        urn, after=begin, before=end
                    ),
                    urn,
                )
            except (WeniError, ValueError, KeyError, TypeError) as exc:
                if getattr(exc, "status_code", None) in {401, 403}:
                    raise
                failed.add(urn)
        return conversations, failed
    finally:
        client.close()


def parse_conversations(rows, urn):
    conversations = {}
    for row in rows:
        meta = row["metadata"]
        identity = _uuid(meta["conversation_uuid"])
        opened = datetime.fromisoformat(meta["conversation_start_date"])
        closed = datetime.fromisoformat(meta["conversation_end_date"])
        human = meta["human_support"]
        if (
            row["contact_urn"] != urn
            or row["event_name"] != "weni_nexus_data"
            or row["key"] != "conversation_classification"
            or not identity
            or not opened.tzinfo
            or not closed.tzinfo
            or opened > closed
            or type(human) is not bool
        ):
            raise ValueError("Classificação da conversa da Weni inválida.")
        item = Conversation(identity, opened, closed, human)
        if conversations.setdefault(identity, item) != item:
            raise ValueError("Classificações conflitantes para a mesma conversa.")
    return tuple(conversations.values())


def _conversation_at_click(touch, conversations):
    if touch.chat_id:
        candidates = [
            c
            for c in conversations
            if c.identity == touch.chat_id
            and c.opened - START_TOLERANCE <= touch.at <= c.closed
        ]
    else:
        candidates = [
            c
            for c in conversations
            if timedelta(0) <= c.opened - touch.at <= START_TOLERANCE
        ]
    return candidates[0] if len(candidates) == 1 else None


def _conversation_of_room(room, conversations):
    candidates = [c for c in conversations if c.opened <= room.opened <= c.closed]
    if not candidates:
        return None
    newest = max(c.opened for c in candidates)
    candidates = [c for c in candidates if c.opened == newest]
    if len(candidates) != 1:
        return None
    chosen = candidates[0]
    if (
        not chosen.human
        or room.closed > chosen.closed
        or any(room.opened < c.opened < room.closed for c in conversations)
    ):
        return None
    return chosen


def classify_purchase(purchase, touches, room, conversations_by_urn):
    candidates = []
    for touch in touches:
        if touch.at > purchase.at:
            continue
        conversations = conversations_by_urn.get(touch.urn, ())
        click = _conversation_at_click(touch, conversations)
        sale = _conversation_of_room(room, conversations)
        opening = click.opened if click else touch.at
        if click and sale and click.identity == sale.identity:
            candidates.append(("direto", touch, opening))
        elif opening <= purchase.at <= opening + WINDOW:
            candidates.append(
                ("posterior" if click and sale else "pendente", touch, opening)
            )
    direct = [row for row in candidates if row[0] == "direto"]
    if direct:
        # A primeira entrada identificada abre a conversa. Toques com a mesma
        # abertura e anúncios diferentes exigem revisão.
        opening = min(row[2] for row in direct)
        finalists = [row for row in direct if row[2] == opening]
        first = min(row[1].at for row in finalists)
        finalists = [row for row in finalists if row[1].at == first]
    elif candidates:
        newest = max(row[1].at for row in candidates)
        finalists = [row for row in candidates if row[1].at == newest]
    else:
        return None
    if len({(row[0], row[1].grain) for row in finalists}) != 1:
        return None
    return finalists[0]


def _coverage(rows):
    return sorted(
        (date.fromisoformat(r["inicio"]), date.fromisoformat(r["fim"]))
        for r in rows
        if r.get("segmento") == "FARMA"
        and r.get("vigente") == "Sim"
        and r.get("extracao") == "extraida"
        and str(r.get("pendencias")) == "0"
    )


def _covered(windows, first, last):
    cursor = first
    for start, end in windows:
        if start > cursor:
            break
        if end >= cursor:
            cursor = end + timedelta(days=1)
        if cursor > last:
            return True
    return False


def _order_timestamp(record):
    for field in ("farmalider_emissao", "data_hora"):
        value = str(record.get(field) or "").strip()
        at = business_order_datetime(value) if len(value) > 10 else None
        if at is not None:
            return at.astimezone(UTC)
    return None


def _owner(record):
    return str(
        record.get("farmalider_cliente_id")
        or record.get("farmalider_cod_cliente")
        or ""
    ).strip()


def _unique_rows(rows, field):
    unique = {}
    for row in rows:
        key = row.get(field)
        if key and unique.setdefault(key, row) != row:
            unique[key] = None
    return unique


def _first_purchase(owner, first_day, first_day_orders, operational):
    if len(first_day_orders) == 1:
        return first_day_orders[0]
    dated = []
    for oid in first_day_orders:
        row = operational.get(oid) or {}
        at = _order_timestamp(row)
        if (
            at is None
            or _owner(row) != owner
            or at.astimezone(BELEM).date() != first_day
        ):
            return None
        dated.append((at, oid))
    dated.sort()
    return dated[0][1] if dated[0][0] != dated[1][0] else None


def _official_customers(contacts, weni_contacts, directory):
    owners = defaultdict(set)
    if directory is not None and weni_contacts is not None:
        if directory.segment != "FARMA":
            raise ValueError("Cadastro oficial de outro segmento.")
        index = IdentityIndex(weni_contacts)
        for owner, customer in directory.by_id.items():
            if owner not in directory.conflicted_ids:
                uid, reason = index.match(customer)
                if uid and reason == "CPF_VALIDO_UNICO":
                    owners[uid].add(owner)
    else:
        for row in contacts:
            if (
                row.get("farmalider_cliente_id")
                and row.get("contact_uuid")
                and row.get("farmalider_cliente_status") == "CPF_CONFIRMADO"
            ):
                owners[row["contact_uuid"]].add(row["farmalider_cliente_id"])
    return {uid: next(iter(ids)) for uid, ids in owners.items() if len(ids) == 1}


def _observed_intervals(coverage, clock):
    intervals = []
    for row in coverage:
        if (
            row["segmento"] != "FARMA"
            or row["vigente"] != "Sim"
            or row["extracao"] != "extraida"
            or str(row["pendencias"]) != "0"
        ):
            continue
        observed = business_order_datetime(row.get("atualizado"))
        if observed is None or observed > clock:
            continue
        query = HistoryQuery("FARMA", row["inicio"], row["fim"])
        intervals.append((query.start_at, min(query.end_at, observed)))
    merged = []
    for start, end in sorted(intervals):
        if start > end:
            continue
        if merged and start - merged[-1][1] <= timedelta(microseconds=1):
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _official_purchases(history, raw_history, orders, owners):
    """Recupera a hora oficial quando a publicação conserva apenas a data civil."""
    published = _unique_rows(history, "pedido_id")
    if any(row is None for row in published.values()):
        raise ValueError("Histórico com duplicidade conflitante de pedido.")
    raw = {
        row["id"]: row["record"]
        for row in raw_history
        if row["segment"] == "FARMA" and row["owner"] in owners
    }
    operational = _unique_rows(orders, "pedido_id")
    purchases, unresolved = defaultdict(list), defaultdict(set)
    for oid, row in published.items():
        owner = row["cliente_id"]
        if (
            owner not in owners
            or row["segmento"] != "FARMA"
            or row["vigente"] != "Sim"
            or row["estado"] != "valido"
        ):
            continue
        day = date.fromisoformat(row["data"]) if row["data"] else None
        revenue = Decimal(str(row["faturamento"]))
        at = None
        if oid in raw:
            record = json.loads(raw[oid])
            if (
                record["segment"] == "FARMA"
                and record["id"] == oid
                and record["owner"] == owner
                and record["state"] == "valido"
                and record["revenue_cents"] == revenue * 100
            ):
                at = _order_timestamp({"data_hora": record["date"]})
        else:
            candidate = operational.get(oid)
            if (
                candidate
                and _owner(candidate) == owner
                and _sales_order_is_valid(candidate)
            ):
                at = _order_timestamp(candidate)
        if (
            at is None
            or at.astimezone(BELEM).date() != day
            or not revenue.is_finite()
            or revenue < 0
        ):
            unresolved[owner].add(day)
            continue
        purchases[owner].append(
            Purchase(oid, owner, at, revenue, row.get("contato_weni") or "")
        )
    return purchases, unresolved


def audit_conversations(
    tables,
    evidence,
    contacts,
    orders,
    history,
    raw_history,
    coverage,
    conversations,
    rooms,
    start,
    end,
    clock,
    *,
    weni_contacts=None,
    directory=None,
    failed_urns=(),
    period_evidence=None,
):
    """Confere cada conversa CTWA e devolve somente totais do recorte solicitado."""
    owners = _official_customers(contacts, weni_contacts, directory)
    contacts_without_cpf = set()
    for row in weni_contacts or []:
        cpf = (row.get("fields") or {}).get("cpf")
        if isinstance(cpf, dict):
            cpf = cpf.get("value")
        if row.get("uuid") and not str(cpf or "").strip():
            contacts_without_cpf.add(row["uuid"])
    by_conversation = defaultdict(set)
    unresolved_events = set()
    lookup_failures = set()
    for event in evidence:
        if event["segment"] != "FARMA":
            continue
        at = datetime.fromisoformat(event["date"])
        if at > clock:
            continue
        urn = event.get("contact_urn")
        if not isinstance(urn, str) or not urn.strip():
            if start <= at.astimezone(BELEM).date() <= end:
                unresolved_events.add(event["event_id"])
            continue
        touch = Touch(
            event["event_id"],
            at,
            urn,
            _uuid(event.get("conversation_id")),
            ("", event["ad_id"], ""),
        )
        conversation = _conversation_at_click(touch, conversations.get(touch.urn, ()))
        if conversation is None:
            if start <= at.astimezone(BELEM).date() <= end:
                unresolved_events.add(touch.event_id)
                if touch.urn in failed_urns:
                    lookup_failures.add(touch.event_id)
            continue
        if conversation.opened <= clock:
            uid = (event.get("contact_uuid") or "") if event.get("link_status") == "unique" else ""
            by_conversation[conversation.identity].add(
                (touch.at, event["ad_id"], uid, touch.urn, conversation)
            )

    purchases, unresolved = _official_purchases(
        history,
        raw_history,
        orders,
        set(owners.values()),
    )
    intervals = _observed_intervals(coverage, clock)
    states = Counter(dict.fromkeys(CONVERSATION_STATES, 0))
    reasons = Counter()
    matched = defaultdict(list)
    customers = set()
    complete = 0
    if rooms is None:
        rooms = {
            urn: tuple(
                Room(conv.opened, conv.closed)
                for conv in entries
                if conv.human
                and conv.closed <= clock
                and conv.closed.astimezone(BELEM).time() != time.max
            )
            for urn, entries in conversations.items()
        }
    for events in by_conversation.values():
        first = min(event[0] for event in events)
        finalists = {
            (ad, uid, urn, conv) for at, ad, uid, urn, conv in events if at == first
        }
        if not any(
            start <= entry[3].opened.astimezone(BELEM).date() <= end
            for entry in finalists
        ):
            continue
        if (
            len(finalists) != 1
            or len({(uid, conv) for _, _, uid, _, conv in events}) != 1
        ):
            states["pendente_de_conferencia"] += 1
            reasons["ANUNCIO_OU_CONVERSA_AMBIGUOS"] += 1
            continue
        ad, uid, urn, conversation = finalists.pop()
        owner = owners.get(uid)
        if owner is None:
            states["pendente_de_conferencia"] += 1
            reason = (
                "SEM_CPF_NA_WENI" if uid in contacts_without_cpf
                else "CLIENTE_OFICIAL_NAO_CONFIRMADO"
            )
            reasons[reason] += 1
            continue
        customers.add(owner)
        opening = conversation.opened.astimezone(UTC)
        deadline = opening + WINDOW
        first_day, last_day = (
            opening.astimezone(BELEM).date(),
            deadline.astimezone(BELEM).date(),
        )
        missing_time = any(
            day is None or first_day <= day <= last_day for day in unresolved[owner]
        )
        full = (
            not missing_time
            and clock >= deadline
            and any(a <= opening and deadline <= b for a, b in intervals)
        )
        complete += int(full)
        eligible = [
            purchase
            for purchase in purchases[owner]
            if opening < purchase.at <= min(clock, deadline)
        ]
        if eligible:
            states["com_pedido"] += 1
            for purchase in eligible:
                candidates = [
                    room
                    for room in rooms.get(urn, ())
                    if room.opened <= purchase.at <= room.closed
                ]
                direct = (
                    purchase.contact == uid
                    and len(candidates) == 1
                    and _conversation_of_room(candidates[0], conversations[urn])
                    == conversation
                    and sum(
                        candidates[0].opened <= p.at <= candidates[0].closed
                        for p in purchases[owner]
                    )
                    == 1
                )
                kind = "sem_vinculo_conversa"
                if direct:
                    kind = "direto"
                elif (
                    conversation.closed < purchase.at
                    and conversation.closed.astimezone(BELEM).time() != time.max
                ):
                    kind = "posterior"
                matched[purchase].append((direct, opening, ad, kind))
        elif missing_time:
            states["pendente_de_conferencia"] += 1
            reasons["PEDIDO_SEM_EMISSAO_CONCILIADA"] += 1
        elif clock < deadline:
            states["em_acompanhamento"] += 1
        elif full:
            states["sem_pedido_apos_7d"] += 1
        else:
            states["pendente_de_conferencia"] += 1
            reasons["COBERTURA_DE_PEDIDOS_INCOMPLETA"] += 1

    attributed = {}
    for purchase, candidates in matched.items():
        priority = max((direct, opening) for direct, opening, _, _ in candidates)
        winners = {
            (ad, kind)
            for direct, opening, ad, kind in candidates
            if (direct, opening) == priority
        }
        if len(winners) == 1:
            ad, kind = winners.pop()
            attributed[purchase] = (ad, kind)
            if period_evidence is not None:
                purchase_day = purchase.at.astimezone(BELEM).date()
                previous = max(
                    (
                        p.at
                        for p in purchases[purchase.owner]
                        if p.at < purchase.at
                    ),
                    default=None,
                )
                covered_from = min(
                    (
                        a.astimezone(BELEM).date()
                        + timedelta(days=int(a.astimezone(BELEM).time() != time.min))
                        for a, b in intervals
                        if a <= purchase.at <= b
                    ),
                    default=None,
                )
                unknown_days = unresolved[purchase.owner]
                if None in unknown_days or any(
                    p != purchase and p.at == purchase.at
                    for p in purchases[purchase.owner]
                ):
                    covered_from = None
                elif covered_from is not None:
                    covered_from = max(
                        [
                            covered_from,
                            *(
                                day + timedelta(days=1)
                                for day in unknown_days
                                if day <= purchase_day
                            ),
                        ]
                    )
                period_evidence[ad].append(
                    dict(
                        abertura=priority[1].astimezone(BELEM).date().isoformat(),
                        emissao=purchase_day.isoformat(),
                        compra_anterior=previous.astimezone(BELEM).date().isoformat()
                        if previous
                        else None,
                        primeira_compra_desde=covered_from.isoformat()
                        if covered_from and covered_from <= purchase_day
                        else None,
                        receita=str(purchase.revenue),
                        vinculo=kind,
                    )
                )
    ambiguous = len(matched) - len(attributed)
    media = [
        row
        for row in tables["BI_Meta_Resultados"]
        if row["segmento"] == row["classificacao"] == "FARMA"
        and start.isoformat() <= row["data"] <= end.isoformat()
    ]
    meta = [
        Decimal(row["conversas_iniciadas_meta"])
        for row in media
        if row["conversas_iniciadas_meta"] != ""
    ]
    spend = (
        sum((Decimal(row["investimento_atribuivel"]) for row in media), Decimal(0))
        if media
        and all(
            row["moeda"] == "BRL" and row["investimento_atribuivel"] != ""
            for row in media
        )
        else None
    )
    revenue = sum((p.revenue for p in attributed), Decimal(0))
    media_ads = {row["anuncio_id"] for row in media}
    period_begin = datetime.combine(start, time.min, BELEM)
    period_end = datetime.combine(end, time.max, BELEM)
    metric_purchases = {
        p: kind for p, (ad, kind) in attributed.items()
        if ad in media_ads and period_begin <= p.at <= period_end
    }
    metric_revenue = sum((p.revenue for p in metric_purchases), Decimal(0))
    direct_revenue = sum(
        (p.revenue for p, kind in metric_purchases.items() if kind == "direto"),
        Decimal(0),
    )
    kinds = Counter(kind for _, kind in attributed.values())
    first_buyers = set()
    for owner in {p.owner for p in metric_purchases}:
        if None in unresolved[owner] or any(
            start <= day <= end for day in unresolved[owner] if day
        ):
            continue
        in_period = [p for p in purchases[owner] if period_begin <= p.at <= period_end]
        first = min(p.at for p in in_period)
        candidates = [p for p in in_period if p.at == first]
        if len(candidates) == 1 and candidates[0] in metric_purchases:
            first_buyers.add(owner)
    complete_cac = any(
        a <= period_begin and min(clock, period_end) <= b for a, b in intervals
    )
    audited_completely = (
        not unresolved_events
        and not ambiguous
        and complete == sum(states.values())
        and len(meta) == len(media)
        and sum(meta) == sum(states.values())
    )
    metric_order_count = len(metric_purchases)
    return dict(
        status="conferida" if audited_completely else "dados_parciais",
        inicio=start.isoformat(),
        fim=end.isoformat(),
        conversas_weni_identificadas=sum(states.values()),
        conversas_meta_informadas=str(sum(meta)) if meta else None,
        fatos_sem_metrica_meta=len(media) - len(meta),
        diferenca_meta_weni=str(sum(meta) - sum(states.values()))
        if media and len(media) == len(meta)
        else None,
        eventos_sem_conversa_comprovada=len(unresolved_events),
        eventos_com_falha_na_leitura_weni=len(lookup_failures),
        clientes_confirmados=len(customers),
        consultas_completas=complete,
        situacoes=dict(states),
        pendencias_por_motivo=dict(sorted(reasons.items())),
        pedidos_comprovados_distintos=len(matched),
        pedidos_com_atribuicao_ambigua=ambiguous,
        pedidos_na_conversa_original=kinds["direto"],
        pedidos_apos_conversa_original_7d=kinds["posterior"],
        pedidos_sem_vinculo_com_a_conversa_original=kinds["sem_vinculo_conversa"],
        pedidos_atribuidos_fora_do_periodo=sum(
            not period_begin <= p.at <= period_end for p in attributed
        ),
        receita_atribuida_comprovada=str(revenue),
        receita_atribuida_anuncios_com_investimento=str(metric_revenue),
        investimento_brl=str(spend) if spend is not None else None,
        pedidos_atribuidos_no_periodo=metric_order_count
        if metric_order_count or audited_completely
        else None,
        cpa_sobre_pedidos_comprovados=str(spend / metric_order_count)
        if spend is not None and metric_order_count
        else None,
        roas_sobre_receita_comprovada=str(metric_revenue / spend)
        if spend and (metric_purchases or audited_completely)
        else None,
        roas_na_conversa_original=str(direct_revenue / spend)
        if spend and ("direto" in metric_purchases.values() or audited_completely)
        else None,
        clientes_com_primeira_compra_atribuida_comprovada=len(first_buyers)
        if complete_cac
        else None,
        cac_sobre_clientes_comprovados=str(spend / len(first_buyers))
        if spend and first_buyers and complete_cac
        else None,
    )


def prepare_attribution(tables, evidence, orders, history, rooms, *, through):
    """Indexa revisões por pedido, contato e grão diário; a chave do cliente é oficial."""
    raw = [
        r
        for r in tables["Meta_Ads_Diario"]
        if r["segmento"] == r["classificacao"] == "FARMA"
    ]
    days = {}
    accounts = defaultdict(set)
    for row in raw:
        grain = (row["conta_id"], row["anuncio_id"], row["data"])
        if grain in days:
            raise ValueError("Mais de um fato Meta para anúncio e dia.")
        days[grain] = row
        accounts[row["anuncio_id"]].add((row["conta_id"], row["fuso"]))
    touches = defaultdict(set)
    pending = set()
    for event in evidence:
        if event["segment"] != "FARMA":
            continue
        targets = accounts[event["ad_id"]]
        if len(targets) != 1:
            continue
        account, zone = next(iter(targets))
        at = datetime.fromisoformat(event["date"])
        grain = (
            account,
            event["ad_id"],
            at.astimezone(ZoneInfo(zone)).date().isoformat(),
        )
        if grain in days and (
            event.get("link_status") != "unique"
            or not event.get("contact_urn")
            or not event.get("contact_uuid")
        ):
            pending.add(grain)
        elif grain in days:
            touches[event["contact_uuid"]].add(
                Touch(
                    event["event_id"],
                    at,
                    event["contact_urn"],
                    _uuid(event.get("conversation_id")),
                    grain,
                )
            )
    operational = _unique_rows(orders, "pedido_id")
    canonical = _unique_rows(history, "pedido_id")
    first = {}
    unknown_emission = set()
    purchases = defaultdict(list)
    unresolved = Counter()
    for oid, record in canonical.items():
        if record is None:
            raise ValueError("Histórico com duplicidade conflitante de pedido.")
        if (
            record["segmento"] != "FARMA"
            or record["vigente"] != "Sim"
            or record["estado"] != "valido"
        ):
            continue
        owner = record["cliente_id"]
        row = operational.get(oid) or {}
        uid = record.get("contato_weni") or row.get("contact_uuid")
        own_touches = touches.get(uid, ())
        if not record["data"]:
            if owner:
                unknown_emission.add(owner)
            pending.update(t.grain for t in own_touches)
            if own_touches:
                unresolved["EMISSAO_AUSENTE"] += 1
            continue
        day = date.fromisoformat(record["data"])
        if owner and (owner not in first or day < first[owner][0]):
            first[owner] = (day, [oid])
        elif owner and day == first[owner][0]:
            first[owner][1].append(oid)
        if day > through:
            continue
        possible = [
            t
            for t in own_touches
            if t.at.astimezone(BELEM).date() <= day
            and (
                rooms is None
                or day <= (t.at + WINDOW + START_TOLERANCE).astimezone(BELEM).date()
                or any(
                    r.opened.astimezone(BELEM).date() <= day <= r.closed.astimezone(BELEM).date()
                    for r in rooms.get(t.urn, ())
                )
            )
        ]
        if not possible:
            continue
        at = _order_timestamp(row)
        if (
            not at
            or at.astimezone(BELEM).date() != day
            or not owner
            or _owner(row) != owner
            or row.get("contact_uuid") != uid
            or not _sales_order_is_valid(row)
        ):
            pending.update(t.grain for t in possible)
            unresolved["PEDIDO_OPERACIONAL_NAO_CONCILIADO"] += 1
            continue
        try:
            revenue = Decimal(str(record["faturamento"]))
            if not revenue.is_finite() or revenue < 0:
                raise ValueError
        except (ValueError, InvalidOperation):
            pending.update(t.grain for t in possible)
            unresolved["RECEITA_INVALIDA"] += 1
            continue
        purchases[uid].append(Purchase(oid, owner, at, revenue))
    return (
        days,
        touches,
        purchases,
        pending,
        unresolved,
        {
            owner: None
            if owner in unknown_emission
            else _first_purchase(owner, day, ids, operational)
            for owner, (day, ids) in first.items()
        },
    )


def apply_attribution(
    tables,
    evidence,
    orders,
    history,
    coverage,
    rooms,
    start,
    end,
    clock,
    conversations_loader,
):
    flows_only = rooms is None
    days, touches, purchases, pending, unresolved, first = prepare_attribution(
        tables, evidence, orders, history, rooms, through=end
    )
    # O identificador de atendimento da exportação pode ser interno ao Chats.
    # O vínculo usa somente a URN oficial de um evento CTWA de contato único.
    urns = {
        t.urn
        for uid in purchases
        for t in touches[uid]
        if rooms is None or t.urn in rooms
    }
    conversations = conversations_loader(urns)
    if flows_only:
        # Flows pode fechar a classificação no último microssegundo do dia,
        # mesmo quando a sala do Live Desk encerrou antes.
        rooms = {
            urn: tuple(
                Room(conversation.opened, conversation.closed)
                for conversation in entries
                if start <= conversation.closed.astimezone(BELEM).date() <= end
                and conversation.closed <= clock
                and conversation.closed.astimezone(BELEM).time() != time.max
            )
            for urn, entries in conversations.items()
        }
    assert rooms is not None
    windows = _coverage(coverage)
    values = defaultdict(Counter)
    revenues = defaultdict(Counter)
    unknown_first = set()
    for uid, own_purchases in purchases.items():
        own_touches = touches[uid]
        linked_rooms = defaultdict(list)
        count_by_room = Counter()
        for purchase in own_purchases:
            for urn in {t.urn for t in own_touches}:
                matching = [
                    r for r in rooms.get(urn, ()) if r.opened <= purchase.at <= r.closed
                ]
                linked_rooms[purchase].extend((urn, r) for r in matching)
                count_by_room.update((urn, r) for r in matching)
        for purchase, matches in linked_rooms.items():
            if not matches:
                eligible = {
                    t.grain
                    for t in own_touches
                    if t.at <= purchase.at <= t.at + WINDOW + START_TOLERANCE
                }
                if eligible:
                    pending.update(eligible)
                    unresolved["SEM_ATENDIMENTO_COMPROVADO"] += 1
                continue
            if len(matches) != 1 or count_by_room[matches[0]] != 1:
                pending.update(
                    t.grain for t in own_touches if t.at <= purchase.at <= t.at + WINDOW
                )
                unresolved["ATENDIMENTO_OU_PEDIDO_AMBIGUO"] += 1
                continue
            urn, room = matches[0]
            paid = [t for t in own_touches if t.urn == urn and t.at <= purchase.at]
            result = classify_purchase(purchase, paid, room, conversations)
            if result is None or result[0] == "pendente":
                pending.update(t.grain for t in paid if purchase.at <= t.at + WINDOW)
                if paid:
                    unresolved["VINCULO_ANUNCIO_CONVERSA_INCONCLUSIVO"] += 1
                continue
            kind, touch, opening = result
            day = (
                opening.astimezone(ZoneInfo(days[touch.grain]["fuso"]))
                .date()
                .isoformat()
            )
            grain = (*touch.grain[:2], day)
            if grain not in days:
                pending.add(touch.grain)
                unresolved["SEM_FATO_DIARIO_DO_ANUNCIO"] += 1
                continue
            values[grain][kind] += 1
            revenues[grain][kind] += purchase.revenue
            if kind == "direto":
                if first.get(purchase.owner) == purchase.order_id:
                    values[grain]["novos"] += 1
                elif first.get(purchase.owner) is None:
                    unknown_first.add(grain)
    report = Counter()
    for grain, row in days.items():
        day = date.fromisoformat(row["data"])
        zone = ZoneInfo(row["fuso"])
        first_day = datetime.combine(day, time.min, zone).astimezone(BELEM).date()
        last_instant = (
            datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC)
            + WINDOW
        )
        last_day = (last_instant - timedelta(microseconds=1)).astimezone(BELEM).date()
        counts = values[grain]
        if not start <= first_day <= end and not counts:
            continue
        complete = (
            first_day >= start
            and last_day <= end
            and clock >= last_instant
            and _covered(windows, first_day, last_day)
            and grain not in pending
        )
        history_complete = _covered(windows, HISTORY_START, last_day)
        audit = dict(
            pedidos_conversa_anuncio=counts["direto"]
            if complete or counts["direto"]
            else None,
            receita_conversa_anuncio=str(revenues[grain]["direto"])
            if complete or counts["direto"]
            else None,
            pedidos_apos_conversa_7d=counts["posterior"]
            if complete or counts["posterior"]
            else None,
            receita_apos_conversa_7d=str(revenues[grain]["posterior"])
            if complete or counts["posterior"]
            else None,
            novos_clientes_anuncio=counts["novos"]
            if complete and history_complete and grain not in unknown_first
            else None,
            cobertura_comercial=complete,
            origem_evidencia=FLOWS_SOURCE if flows_only else XLSX_SOURCE,
        )
        payload = json.loads(row["payload_api_json"])
        payload[PAYLOAD_KEY] = audit
        row["payload_api_json"] = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        report.update(
            direto=counts["direto"],
            posterior=counts["posterior"],
            dias_parciais=int(not complete),
        )
    return dict(report, pedidos_pendentes_por_motivo=dict(sorted(unresolved.items())))
