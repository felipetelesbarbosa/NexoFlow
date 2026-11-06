"""Contrato histórico puro: não acessa rede, Weni ou configurações privadas."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from business_identity import cpf_checksum_valid
from pedido_utils import (
    business_order_datetime,
    is_order_cancelled,
    is_order_sale,
    normalize_farmalider_order_status_code,
    normalize_farmalider_payment_code,
)

SOURCE = "FARMALIDER_PEDIDOS_PAGINADOS"
POLICY = "itens_liquidos_mais_frete_v1"


class HistoryError(ValueError):
    """Somente códigos estáticos, sem payload, URL ou credenciais."""


def identity(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    text = str(value).strip()
    return text if re.fullmatch(r"[0-9]{1,30}", text) and int(text) > 0 else ""


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


@dataclass(frozen=True)
class HistoryQuery:
    segment: str
    start: str
    end: str
    limit: int = 500

    def __post_init__(self):
        if self.segment not in {"FARMA", "PET"}:
            raise HistoryError("SEGMENTO_INVALIDO")
        if type(self.limit) is not int or not 1 <= self.limit <= 2147483647:
            raise HistoryError("LIMITE_INVALIDO")
        for value in (self.start, self.end):
            if (
                not isinstance(value, str)
                or not re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?)?",
                    value,
                )
                or business_order_datetime(value) is None
            ):
                raise HistoryError("PERIODO_INVALIDO")
        if self.start_at > self.end_at:
            raise HistoryError("PERIODO_INVERTIDO")

    @property
    def start_at(self):
        result = business_order_datetime(self.start)
        assert result is not None
        return result

    @property
    def end_at(self):
        result = business_order_datetime(self.end)
        assert result is not None
        return result

    @property
    def key(self):
        # Limite faz parte do cursor: tamanho diferente inicia pela página 1.
        return digest([SOURCE, self.segment, self.start, self.end, self.limit])

    def contains(self, value):
        dt = business_order_datetime(value)
        if dt is None:
            return False
        # Aceitar data civil retornada não afirma inclusividade do filtro remoto.
        lower = (
            dt.date() >= self.start_at.date()
            if len(self.start) == 10
            else dt >= self.start_at
        )
        upper = (
            dt.date() <= self.end_at.date()
            if len(self.end) == 10
            else dt <= self.end_at
        )
        return lower and upper


def page_envelope(payload, query, page):
    if not isinstance(payload, dict) or not isinstance(payload.get("pedidos"), list):
        raise HistoryError("ENVELOPE_INVALIDO")
    for key in ("pagina", "limite", "totalRegistros", "totalPaginas"):
        if type(payload.get(key)) is not int or payload[key] < 0:
            raise HistoryError("TOTALIZADOR_INVALIDO")
    total, pages, rows = (
        payload["totalRegistros"],
        payload["totalPaginas"],
        payload["pedidos"],
    )
    if payload["pagina"] != page or payload["limite"] != query.limit:
        raise HistoryError("PAGINA_OU_LIMITE_DIVERGENTE")
    expected = (total + query.limit - 1) // query.limit
    if (total and pages != expected) or (not total and pages not in (0, 1)):
        raise HistoryError("TOTALIZADORES_INCONSISTENTES")
    if page > max(1, pages) or len(rows) > query.limit or (not rows and total):
        raise HistoryError("PAGINA_VAZIA_OU_FORA_DO_INTERVALO")
    ids = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("capa"), dict):
            raise HistoryError("PEDIDO_MALFORMADO")
        oid = identity(row["capa"].get("id"))
        if not oid:
            raise HistoryError("PEDIDO_ID_INVALIDO")
        ids.append(oid)
    if len(set(ids)) != len(ids):
        raise HistoryError("PAGINA_COM_IDS_REPETIDOS")
    return rows, total, pages


def money(value):
    try:
        if value is None or isinstance(value, bool):
            raise ValueError
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise HistoryError("VALOR_INVALIDO") from None


def cents(value):
    if value != value.quantize(Decimal("0.01")):
        raise HistoryError("PRECISAO_MONETARIA_NAO_CONFIRMADA")
    return int(value * 100)


def normalize_order(payload, segment, now):
    """Prova oficial independe de CPF/Weni; nenhum dado de endereço é persistido."""
    header = payload["capa"]
    oid, owner = identity(header.get("id")), identity(header.get("codCliente"))
    result = {
        "id": oid,
        "owner": owner,
        "segment": segment,
        "source": SOURCE,
        "state": "pendente",
        "reason": "",
        "date": "",
        "items": [],
        "products_cents": 0,
        "freight_cents": 0,
        "revenue_cents": 0,
        "policy": POLICY,
        "contact_uuid": "",
        "link_state": "NAO_CONFERIDO",
    }
    try:
        if not owner:
            raise HistoryError("CLIENTE_OFICIAL_AUSENTE")
        if str(header.get("segmento", "")).upper() != segment:
            result.update(state="ignorado", reason="SEGMENTO_NAO_COMPROVADO")
            return result
        dt, captured = (
            business_order_datetime(header.get("emissao")),
            business_order_datetime(now),
        )
        if dt is None or captured is None or dt > captured:
            raise HistoryError("EMISSAO_INVALIDA")
        result["date"] = dt.isoformat()
        result["timezone_evidence"] = (
            "OFFSET_API"
            if datetime.fromisoformat(header["emissao"].replace("Z", "+00:00")).tzinfo
            else "AMERICA_BELEM_CONVENCAO"
        )
        status = normalize_farmalider_order_status_code(header.get("status"))
        payment = normalize_farmalider_payment_code(header.get("formaPagamento"))
        if not status or not payment:
            raise HistoryError("STATUS_OU_PAGAMENTO_INVALIDO")
        result.update(status=status, payment=payment)
        signals = {
            "farmalider_status_pedido": status,
            "farmalider_forma_pagamento": payment,
            "farmalider_cancelamento": header.get("cancelamento"),
        }
        if is_order_cancelled(signals):
            result.update(state="cancelado", reason="CANCELAMENTO_OFICIAL")
            return result
        if "itens" not in payload or not isinstance(payload["itens"], list):
            raise HistoryError("ITENS_AUSENTES_OU_MALFORMADOS")
        if not payload["itens"]:
            result.update(state="cancelado", reason="SEM_ITENS_CONFIRMADO")
            return result
        freight = money(header.get("frete"))
        freight_items, products, freight_count = Decimal(0), Decimal(0), 0
        seen = set()
        for position, item in enumerate(payload["itens"], 1):
            if not isinstance(item, dict) or identity(item.get("codPedido")) != oid:
                raise HistoryError("ITEM_VINCULO_INVALIDO")
            iid = str(item.get("id") or "")
            if not iid or iid in seen:
                raise HistoryError("ITEM_ID_AUSENTE_OU_DUPLICADO")
            seen.add(iid)
            qty, unit, total = (
                money(item.get("quantidade")),
                money(item.get("valor")),
                money(item.get("total")),
            )
            discount = money(item.get("desconto", 0))
            if qty <= 0:
                raise HistoryError("QUANTIDADE_INVALIDA")
            # Sem contrato de desconto/estorno: não deduzir outra vez nem supor base.
            if discount != 0 or total != qty * unit:
                raise HistoryError("DESCONTO_OU_TOTAL_NAO_CONCILIADO")
            is_freight = (
                str(item.get("codProduto")) == "0"
                and not str(item.get("descricao") or "").strip()
            )
            if is_freight:
                freight_items += total
                freight_count += 1
            else:
                products += total
            result["items"].append(
                {
                    "id": iid,
                    "position": position,
                    "sku": str(item.get("codProduto") or ""),
                    "name": str(item.get("descricao") or ""),
                    "quantity": str(qty),
                    "unit": str(unit),
                    "total_cents": cents(total),
                    "freight": is_freight,
                }
            )
        if freight_count and freight_items != freight:
            raise HistoryError("FRETE_DIVERGENTE")
        if all(i["freight"] for i in result["items"]):
            result.update(state="cancelado", reason="SEM_PRODUTOS_CONFIRMADO")
            return result
        for key in (
            "valorTotal",
            "valorTotalPedido",
            "valorTotalCompra",
            "totalPedido",
            "totalGeral",
            "total",
        ):
            if (
                key in header
                and header[key] is not None
                and money(header[key]) != products + freight
            ):
                raise HistoryError("TOTAL_CAPA_DIVERGENTE")
        if not is_order_sale(signals):
            raise HistoryError("VENDA_NAO_CONFIRMADA")
        result.update(
            state="valido",
            products_cents=cents(products),
            freight_cents=cents(freight),
            revenue_cents=cents(products + freight),
        )
    except (HistoryError, ValueError) as exc:
        result.update(
            state="pendente",
            reason=str(exc) if isinstance(exc, HistoryError) else "FORMATO_INVALIDO",
            items=[],
        )
    return result


def canonical(row):
    """Contrato Analytics, com ID único já utilizado pelas outras fontes."""
    return {
        "pedido_id": row["id"],
        "pedido_chave": "FARMALIDER:" + row["id"],
        "farmalider_cliente_id": row["owner"],
        "farmalider_cod_cliente": row["owner"],
        "data_hora": row["date"],
        "data": row["date"][:10],
        "contact_uuid": row.get("contact_uuid", ""),
        "origem_pedido": SOURCE,
        "status_confirmacao": "CONFIRMADO_API"
        if row["state"] == "valido"
        else "CANCELADO_API"
        if row["state"] == "cancelado"
        else "PENDENTE_HISTORICO",
        "status_validacao": "OK" if row["state"] == "valido" else row["reason"],
        "farmalider_status_pedido": row.get("status", ""),
        "farmalider_forma_pagamento": row.get("payment", ""),
        "valor_total_compra": f"{Decimal(row['products_cents']) / 100:.2f}",
        "farmalider_frete": f"{Decimal(row['freight_cents']) / 100:.2f}",
        "valor_total_faturamento": f"{Decimal(row['revenue_cents']) / 100:.2f}",
    }


def ltv(rows):
    customers = {}
    for row in rows:
        if row["state"] != "valido":
            continue
        key = (row["segment"], row["owner"])
        result = customers.setdefault(
            key,
            {
                "segment": key[0],
                "owner": key[1],
                "revenue_cents": 0,
                "orders": 0,
                "first": row["date"],
                "last": row["date"],
                "coverage": "LTV_OBSERVADO",
            },
        )
        result["orders"] += 1
        result["revenue_cents"] += row["revenue_cents"]
        result["first"] = min(result["first"], row["date"])
        result["last"] = max(result["last"], row["date"])
    for result in customers.values():
        result["average"] = str(
            (Decimal(result["revenue_cents"]) / 100 / result["orders"]).quantize(
                Decimal("0.01")
            )
        )
    return list(customers.values())


def _name(value):
    return " ".join(
        re.sub(
            r"[^a-z0-9 ]",
            " ",
            unicodedata.normalize("NFKD", str(value or ""))
            .encode("ascii", "ignore")
            .decode()
            .lower(),
        ).split()
    )


def _cpf(value):
    text = re.sub(r"[.\-\s]", "", str(value or ""))
    if not re.fullmatch(r"[0-9]{1,11}", text) or not text.strip("0"):
        return ""
    padded = text.zfill(11)
    return padded if cpf_checksum_valid(padded) else text


def _phone(value):
    text = str(value or "").split(":")[-1]
    if not re.fullmatch(r"[+0-9 ()-]+", text):
        return ""
    digits = re.sub(r"\D", "", text)
    if len(digits) in (12, 13) and digits.startswith("55"):
        digits = digits[2:]
    return digits if len(digits) in (10, 11) else ""


class IdentityIndex:
    """O(n) para construir; cruzamento sem consultas individuais e sem fusões."""

    def __init__(self, contacts):
        self.by_cpf, self.by_phone, self.by_email = {}, {}, {}
        for contact in contacts:
            fields = contact.get("fields") or {}
            fields = {
                k: v.get("value") if isinstance(v, dict) else v
                for k, v in fields.items()
            }
            uid = str(contact.get("uuid") or "")
            if not uid:
                continue
            name = _name(fields.get("nome") or contact.get("name"))
            phones = {
                _phone(v)
                for v in [
                    fields.get("telefone"),
                    fields.get("celular"),
                    *(contact.get("urns") or []),
                ]
            } - {""}
            email = str(fields.get("email") or "").strip().casefold()
            entry = (uid, name, phones, email, _cpf(fields.get("cpf")))
            if entry[4]:
                self.by_cpf.setdefault(entry[4], {})[uid] = entry
            for phone in phones:
                self.by_phone.setdefault(phone, {})[uid] = entry
            if "@" in email:
                self.by_email.setdefault(email, {})[uid] = entry

    def match(self, customer):
        cpf = _cpf(customer.get("cpf"))
        if not cpf:
            return "", "CPF_AUSENTE_OU_MALFORMADO"
        name, phone = _name(customer.get("nome")), _phone(customer.get("celular"))
        email = str(customer.get("email") or "").strip().casefold()
        candidates = dict(self.by_cpf.get(cpf, {}))
        if cpf_checksum_valid(cpf):
            if len(candidates) == 1:
                return next(iter(candidates)), "CPF_VALIDO_UNICO"
            return "", "AMBIGUO" if candidates else "SEM_CONTATO"
        # CPF inválido: nome completo + telefone ou e-mail; divergência de CPF bloqueia.
        candidates.update(self.by_phone.get(phone, {}))
        candidates.update(self.by_email.get(email, {}))
        matches = [
            uid
            for uid, n, phones, e, c in candidates.values()
            if name
            and n == name
            and c == cpf
            and ((phone and phone in phones) or ("@" in email and email == e))
        ]
        if len(matches) == 1:
            return matches[0], "NOME_E_CANAL_CONFIRMADOS"
        return "", "AMBIGUO" if matches else "IDENTIDADE_NAO_COMPROVADA"


def attribute_history(order, events, *, window_days):
    """Último evento comprovado dentro da janela explicitamente homologada.

    Recebe evidências normalizadas do conector, nunca texto livre de contato.
    Sem janela explícita, apenas conserva a compra sem atribuição.
    """
    if (
        type(window_days) is not int
        or window_days <= 0
        or order["state"] != "valido"
        or not order.get("contact_uuid")
    ):
        return None
    from datetime import timedelta

    dt = business_order_datetime(order["date"])
    if dt is None:
        return None
    candidates = []
    for event in events:
        at = business_order_datetime(event.get("date"))
        if (
            event.get("official") is True
            and event.get("segment") == order["segment"]
            and event.get("contact_uuid") == order["contact_uuid"]
            and event.get("event_id")
            and event.get("ad_id")
            and at is not None
            and dt - timedelta(days=window_days) <= at <= dt
        ):
            candidates.append((at, event))
    if not candidates:
        return None
    latest = max(at for at, _ in candidates)
    final = [e for at, e in candidates if at == latest]
    if len({e["ad_id"] for e in final}) != 1:
        return None
    chosen = sorted(final, key=lambda e: e["event_id"])[0]
    return {
        "order_id": order["id"],
        "event_id": chosen["event_id"],
        "ad_id": chosen["ad_id"],
        "policy": "ULTIMO_TOQUE_JANELA_EXPLICITA_V1",
        "window_days": window_days,
        "revenue_cents": order["revenue_cents"],
    }
