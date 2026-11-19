"""Atribuição comercial FARMA com pedido oficial, CTWA, Flows e export de Salas."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from analytics import _sales_order_is_valid
from delivery_spreadsheets import ROOM_COLUMNS, _date, _rows, _tags, _uuid
from meta_ads_evidence import PROJECT_NAMES, ReadOnlyEvidenceClient
from pedido_utils import business_order_datetime

PAYLOAD_KEY = "nf_atribuicao_comercial_v1"
WINDOW = timedelta(days=7)
START_TOLERANCE = timedelta(seconds=5)
BELEM = ZoneInfo("America/Belem")
HISTORY_START = date(2020, 1, 1)


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


def read_finalized_rooms(path, start, end, clock):
    """Lê a aba original; a faixa declarada é por encerramento em Belém."""
    required = ROOM_COLUMNS | {"queue__sector__name"}
    rooms = defaultdict(set)
    for _, header, values in _rows(Path(path), "rooms", required):
        row = dict(zip(header, values, strict=False))
        # Exportações do Excel podem trazer linhas finais completamente vazias.
        if not any(value not in (None, "") for value in values):
            continue
        if row["queue__sector__name"] != PROJECT_NAMES["FARMA"]:
            raise ValueError("Export de salas de outro projeto/setor.")
        tags = {" ".join(tag.casefold().split()) for tag in _tags(row["tags_list"])}
        if "pedido finalizado" not in tags:
            raise ValueError("Selecione Pedido Finalizado na geração do XLSX.")
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
            or not start <= closed.astimezone(BELEM).date() <= end
            or not _uuid(row["contact__uuid"])
            or not urn.startswith("whatsapp:")
            or not urn.removeprefix("whatsapp:").isdigit()
            or row["is_active"] not in (False, 0, "false", "False")
            or not row["user__email"]
        ):
            raise ValueError("Sala marcada como finalizada com evidência inválida.")
        rooms[urn].add(Room(opened, closed))
    return rooms


def load_conversations(token, urns, begin, end, *, org_uuid=""):
    if not urns:
        return {}
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
        return {
            urn: parse_conversations(
                client.list_conversation_classifications(urn, after=begin, before=end),
                urn,
            )
            for urn in sorted(urns)
        }
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


def prepare_attribution(tables, evidence, orders, history, rooms):
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
        if grain in days and event.get("link_status") != "unique":
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
            pending.update(t.grain for t in own_touches if t.urn in rooms)
            continue
        day = date.fromisoformat(record["data"])
        if owner and (owner not in first or day < first[owner][0]):
            first[owner] = (day, [oid])
        elif owner and day == first[owner][0]:
            first[owner][1].append(oid)
        possible = [
            t
            for t in own_touches
            if t.urn in rooms
            and t.at.astimezone(BELEM).date() <= day
            and (
                day <= (t.at + WINDOW).astimezone(BELEM).date()
                or any(
                    r.opened.astimezone(BELEM).date()
                    <= day
                    <= r.closed.astimezone(BELEM).date()
                    for r in rooms[t.urn]
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
            continue
        try:
            revenue = Decimal(str(record["faturamento"]))
            if not revenue.is_finite() or revenue < 0:
                raise ValueError
        except (ValueError, InvalidOperation):
            pending.update(t.grain for t in possible)
            continue
        purchases[uid].append(Purchase(oid, owner, at, revenue))
    return (
        days,
        touches,
        purchases,
        pending,
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
    days, touches, purchases, pending, first = prepare_attribution(
        tables, evidence, orders, history, rooms
    )
    # O identificador de atendimento da exportação pode ser interno ao Chats.
    # O vínculo usa somente a URN oficial de um evento CTWA de contato único.
    urns = {t.urn for uid in purchases for t in touches[uid] if t.urn in rooms}
    conversations = conversations_loader(urns)
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
                continue
            if len(matches) != 1 or count_by_room[matches[0]] != 1:
                pending.update(
                    t.grain for t in own_touches if t.at <= purchase.at <= t.at + WINDOW
                )
                continue
            urn, room = matches[0]
            paid = [t for t in own_touches if t.urn == urn and t.at <= purchase.at]
            result = classify_purchase(purchase, paid, room, conversations)
            if result is None or result[0] == "pendente":
                pending.update(t.grain for t in paid if purchase.at <= t.at + WINDOW)
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
        if not start <= first_day <= end and not counts and grain not in pending:
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
    return dict(report)
