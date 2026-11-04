"""Fatos Meta e conversões observadas: transformação pura, sem clientes ou escritas."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from analytics import (
    _order_revenue_parts,
    _sales_order_is_valid,
    ad_is_after_order,
    bi_customer_key,
)
from pedido_utils import business_order_datetime

COMMON = [
    "chave",
    "segmento",
    "conta_id",
    "anuncio_id",
    "data",
    "moeda",
    "fuso",
    "politica_atribuicao",
]
SCHEMAS = {
    "Meta_Ads_Diario": COMMON
    + [
        "data_fim",
        "campanha_id",
        "conjunto_id",
        "classificacao",
        "investimento_original",
        "investimento_atribuivel",
        "impressoes",
        "cliques",
        "alcance",
        "frequencia",
        "acoes_meta_json",
        "valores_acoes_meta_json",
        "roas_meta_json",
        "origem",
        "atualizado_em",
    ],
    "Meta_Ads_Campanhas": [
        "chave",
        "segmento",
        "conta_id",
        "campanha_id",
        "campanha_nome",
        "status",
        "objetivo",
        "classificacao",
        "atualizado_em",
    ],
    "Meta_Ads_Anuncios": [
        "chave",
        "segmento",
        "conta_id",
        "anuncio_id",
        "anuncio_nome",
        "campanha_id",
        "conjunto_id",
        "status",
        "classificacao",
        "atualizado_em",
    ],
    "BI_Meta_Resultados": COMMON
    + [
        "classificacao",
        "investimento_original",
        "investimento_atribuivel",
        "impressoes",
        "cliques",
        "ctr_pct",
        "cpc",
        "cpm",
        "eventos_ctwa",
        "contatos",
        "conversas",
        "compradores_confirmados",
        "pedidos_confirmados",
        "receita_confirmada",
        "moeda_receita",
        "compras_atribuidas_meta",
        "cpa_confirmado",
        "roas_confirmado",
        "cac",
        "metodo_atribuicao",
        "motivo_indisponibilidade",
        "atualizado_em",
    ],
    "BI_Meta_Conversoes": [
        "chave",
        "segmento",
        "conta_id",
        "anuncio_id",
        "pedido_chave",
        "cliente_chave",
        "data_pedido",
        "data_exposicao",
        "evento_id",
        "receita_confirmada",
        "moeda_receita",
        "metodo_atribuicao",
        "origem_confirmacao",
        "atualizado_em",
    ],
}

SCHEMAS["Meta_Ads_Diario"] += [
    "conta_nome",
    "campanha_nome",
    "conjunto_nome",
    "anuncio_nome",
    "campanha_status",
    "conjunto_status",
    "anuncio_status",
    "objetivo",
    "cliques_link",
    "custos_acoes_meta_json",
    "resultados_meta_json",
    "resultado_tipo_meta",
    "conversas_iniciadas_meta",
    "valor_compras_atribuido_meta",
    "payload_api_json",
]
SCHEMAS["Meta_Ads_Campanhas"] += ["conta_nome"]
SCHEMAS["Meta_Ads_Anuncios"] += [
    "conta_nome",
    "campanha_nome",
    "conjunto_nome",
    "campanha_status",
    "conjunto_status",
    "objetivo",
]
SCHEMAS["BI_Meta_Resultados"] += [
    "cliques_link",
    "conversas_iniciadas_meta",
    "valor_compras_atribuido_meta",
    "custo_conversa_weni_confirmada",
    "custo_conversa_meta",
    "taxa_conversao_contatos_pct",
    "taxa_conversao_cliques_meta_pct",
]
SCHEMAS["BI_Meta_Conversoes"] += [
    "pedido_id",
    "contact_uuid",
    "produtos_json",
    "quantidade_itens",
    "politica_atribuicao",
    "venda_valida",
    "status_vinculo",
]


_FACT_SCALARS = frozenset(
    {
        "account_id",
        "account_name",
        "ad_id",
        "ad_name",
        "adset_id",
        "adset_name",
        "campaign_id",
        "campaign_name",
        "date_start",
        "date_stop",
        "spend",
        "impressions",
        "clicks",
        "inline_link_clicks",
        "reach",
        "frequency",
        "ctr",
        "cpc",
        "cpm",
        "currency",
        "account_currency",
        "timezone_name",
        "timezone",
        "attribution_policy",
        "politica_atribuicao",
        "api_version",
        "result_type",
        "objective",
        "campaign_status",
        "adset_status",
        "ad_status",
    }
)
_ACTION_FIELDS = frozenset(
    {
        "action_type",
        "value",
        "1d_click",
        "7d_click",
        "28d_click",
        "1d_view",
        "7d_view",
        "28d_view",
        "inline",
        "indicator",
    }
)
_FACT_ARRAYS = frozenset(
    {"actions", "action_values", "purchase_roas", "cost_per_action_type", "results"}
)


def _safe_fact_payload(fact):
    scalar_types = (str, int, float, bool, Decimal)
    result: dict[str, Any] = {
        key: value
        for key, value in fact.items()
        if key in _FACT_SCALARS and (value is None or isinstance(value, scalar_types))
    }
    for key in _FACT_ARRAYS:
        value = fact.get(key)
        if isinstance(value, list):
            result[key] = [
                {
                    field: item_value
                    for field, item_value in row.items()
                    if field in _ACTION_FIELDS
                    and (item_value is None or isinstance(item_value, scalar_types))
                }
                for row in value
                if isinstance(row, dict)
            ]
    return result


def _json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def _action_value(actions, names):
    if not isinstance(actions, list):
        return ""
    for name in names:
        found = [
            _number(a.get("value"))
            for a in actions
            if isinstance(a, dict) and a.get("action_type") == name
        ]
        if found:
            return (
                _money(found[0]) if None not in found and len(set(found)) == 1 else ""
            )
    return ""


def _catalog_index(rows):
    return {
        (
            _text(r.get("account_id") or r.get("conta_id")).removeprefix("act_"),
            _text(r.get("id")),
        ): r
        for r in rows
    }


def _text(value):
    return str(value or "").strip()


def _key(*parts):
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _number(value):
    try:
        result = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return None
    return result if result.is_finite() and result >= 0 else None


def _money(value):
    return "" if value is None else format(value.quantize(Decimal("0.01")), "f")


def _ratio(numerator, denominator, factor=Decimal(1)):
    return (
        _money(numerator * factor / denominator)
        if numerator is not None and denominator and denominator > 0
        else ""
    )


def _rows(catalogs, name, alias):
    value = catalogs.get(name, catalogs.get(alias, []))
    return value if isinstance(value, list) else []


def _account_meta(account_meta, account):
    value = account_meta.get(account)
    return value if isinstance(value, dict) else account_meta


def _classification(ad, events, complete):
    segments = {e["segment"] for e in events if e["ad_id"] == ad}
    if segments == {"FARMA", "PET"}:
        return "COMPARTILHADO"
    if len(segments) == 1 and complete:
        return next(iter(segments))
    return "NAO_CLASSIFICADO"


def _canonical_purchase(actions):
    if not isinstance(actions, list):
        return ""
    # Aliases podem representar a mesma compra. Não somar purchase + omni_purchase.
    for name in ("purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase"):
        values = [
            a.get("value")
            for a in actions
            if isinstance(a, dict) and a.get("action_type") == name
        ]
        if values:
            numbers = {_number(v) for v in values}
            return (
                _money(next(iter(numbers)))
                if len(numbers) == 1 and None not in numbers
                else ""
            )
    return ""


def build_native_tables(
    *,
    segment: str,
    facts: list[dict],
    catalogs: dict,
    evidence: list[dict],
    contacts: list[dict],
    orders: list[dict],
    items: list[dict],
    account_meta: dict,
    updated_at: str,
    coverage: dict,
) -> dict[str, list[dict]]:
    """Não atribui custos compartilhados; último toque observado não é causalidade.

    Fatos usam campos originais da API. coverage.segments deve comprovar a coleta
    de ambos os projetos Weni para autorizar classificação exclusiva. Receita é
    sempre a da API de pedidos, separada das ações atribuídas pela Meta.
    """
    if segment not in {"FARMA", "PET"}:
        raise ValueError("Segmento Meta inválido.")
    tables: dict[str, list[dict]] = {name: [] for name in SCHEMAS}
    campaigns = _rows(catalogs, "campaigns", "campanhas")
    ads = _rows(catalogs, "ads", "anuncios")
    adsets = _rows(catalogs, "adsets", "conjuntos")
    campaign_index, adset_index, ad_index = (
        _catalog_index(rows) for rows in (campaigns, adsets, ads)
    )
    items_by_key, items_by_id = defaultdict(list), defaultdict(list)
    for item in items:
        if item.get("pedido_chave"):
            items_by_key[_text(item["pedido_chave"])].append(item)
        elif item.get("pedido_id"):
            items_by_id[_text(item["pedido_id"])].append(item)
    ad_accounts = defaultdict(set)
    for r in [*facts, *ads]:
        aid, account = (
            _text(r.get("ad_id") or r.get("id")),
            _text(r.get("account_id") or r.get("conta_id")).removeprefix("act_"),
        )
        if aid and account:
            ad_accounts[aid].add(account)
    events, event_keys = [], {}
    for raw in evidence:
        aid = _text(raw.get("ad_id") or raw.get("anuncio_id"))
        account = _text(raw.get("account_id") or raw.get("conta_id")).removeprefix(
            "act_"
        )
        if not account and len(ad_accounts[aid]) == 1:
            account = next(iter(ad_accounts[aid]))
        dt = business_order_datetime(raw.get("date"))
        uid, event_id = _text(raw.get("contact_uuid")), _text(raw.get("event_id"))
        esegment = raw.get("segment")
        if (
            esegment not in {"FARMA", "PET"}
            or not aid
            or not account
            or dt is None
            or not event_id
        ):
            continue
        key = (esegment, account, event_id)
        signature = (
            esegment,
            account,
            aid,
            uid,
            dt.isoformat(),
            _text(raw.get("conversation_id")),
        )
        if key in event_keys:
            if event_keys[key] != signature:
                raise ValueError("Evento Weni divergente para a mesma identidade.")
            continue
        event_keys[key] = signature
        events.append(
            {
                **raw,
                "ad_id": aid,
                "account_id": account,
                "contact_uuid": uid,
                "event_id": event_id,
                "dt": dt,
                "segment": esegment,
            }
        )
    supplied = coverage.get("segments", coverage)
    complete = isinstance(supplied, dict) and all(
        supplied.get(s) is True for s in ("FARMA", "PET")
    )
    by_account_events = defaultdict(list)
    for e in events:
        by_account_events[e["account_id"]].append(e)
    class_map = {}
    for aid, accounts in ad_accounts.items():
        for account in accounts:
            class_map[(account, aid)] = _classification(
                aid, by_account_events[account], complete
            )
    by_contact = defaultdict(list)
    for e in events:
        if e["segment"] == segment and e["contact_uuid"]:
            by_contact[e["contact_uuid"]].append(e)
    bases = {r.get("contact_uuid") or r.get("uuid"): r for r in contacts}
    converted, seen_orders = [], set()
    order_signatures, conflicting_orders = {}, set()
    for record in orders:
        identity = _text(record.get("pedido_id") or record.get("pedido_chave"))
        signature = tuple(
            _text(record.get(k))
            for k in (
                "contact_uuid",
                "data_hora",
                "status_confirmacao",
                "status_validacao",
                "farmalider_status_pedido",
                "farmalider_forma_pagamento",
                "farmalider_cliente_id",
                "valor_total_compra",
                "farmalider_frete",
                "valor_total_faturamento",
            )
        )
        if identity in order_signatures and order_signatures[identity] != signature:
            conflicting_orders.add(identity)
        order_signatures[identity] = signature
    for order in orders:
        oid = _text(order.get("pedido_id"))
        okey = _text(order.get("pedido_chave"))
        unique = oid or okey
        if (
            not unique
            or unique in conflicting_orders
            or unique in seen_orders
            or not _sales_order_is_valid(order)
        ):
            continue
        seen_orders.add(unique)
        dt = business_order_datetime(
            order.get("data_hora") or order.get("farmalider_emissao")
        )
        if dt is None:
            continue
        candidates = [
            e for e in by_contact.get(order.get("contact_uuid"), []) if e["dt"] <= dt
        ]
        if not candidates:
            continue
        latest = max(e["dt"] for e in candidates)
        finalists = [e for e in candidates if e["dt"] == latest]
        if len({(e["account_id"], e["ad_id"]) for e in finalists}) != 1:
            continue
        event = sorted(finalists, key=lambda e: e["event_id"])[0]
        # Reutilizar a guarda temporal existente com a prova escolhida.
        if ad_is_after_order(
            {**order, "ultimo_anuncio_data": event["dt"].isoformat()}, "ultimo_anuncio_"
        ):
            continue
        products = []
        item_seen = set()
        for position, item in enumerate(
            items_by_key.get(okey, []) or items_by_id.get(oid, [])
        ):
            if item.get("contact_uuid") and item.get("contact_uuid") != order.get(
                "contact_uuid"
            ):
                continue
            product = {
                k: item.get(k, "")
                for k in (
                    "produto_codigo",
                    "produto_nome",
                    "quantidade",
                    "valor_unitario",
                    "valor_total",
                )
            }
            identity = _text(item.get("item_chave")) or "line:" + str(position)
            if identity not in item_seen:
                item_seen.add(identity)
                products.append(product)
        quantities = [_number(p["quantidade"]) for p in products]
        quantity = (
            sum((q for q in quantities if q is not None), Decimal(0))
            if products and None not in quantities
            else None
        )
        converted.append(
            {
                "chave": _key(segment, event["account_id"], oid or okey),
                "segmento": segment,
                "conta_id": event["account_id"],
                "anuncio_id": event["ad_id"],
                "pedido_chave": okey,
                "cliente_chave": bi_customer_key(
                    order, bases.get(order.get("contact_uuid"))
                ),
                "data_pedido": dt.date().isoformat(),
                "data_exposicao": event["dt"].isoformat(),
                "evento_id": event["event_id"],
                "receita_confirmada": _money(_order_revenue_parts(order)[2]),
                "metodo_atribuicao": "ULTIMO_TOQUE_OBSERVADO",
                "origem_confirmacao": "API_FARMALIDER",
                "venda_valida": "Sim",
                "status_vinculo": "ATIVO",
                "pedido_id": oid,
                "contact_uuid": _text(order.get("contact_uuid")),
                "produtos_json": _json(products),
                "quantidade_itens": _money(quantity) if products else "",
                "politica_atribuicao": "ULTIMO_TOQUE_OBSERVADO_SEM_JANELA_CAUSAL",
                "moeda_receita": "BRL",
                "atualizado_em": updated_at,
            }
        )
    tables["BI_Meta_Conversoes"] = sorted(converted, key=lambda r: r["chave"])
    events_by_ad, conversions_by_ad = defaultdict(list), defaultdict(list)
    for event in events:
        events_by_ad[(event["account_id"], event["ad_id"])].append(event)
    for conversion in converted:
        conversions_by_ad[(conversion["conta_id"], conversion["anuncio_id"])].append(
            conversion
        )
    seen_facts = {}
    for original_fact in facts:
        fact = _safe_fact_payload(original_fact)
        account, aid = (
            _text(fact.get("account_id")).removeprefix("act_"),
            _text(fact.get("ad_id")),
        )
        start, end = (
            _text(fact.get("date_start")),
            _text(fact.get("date_stop") or fact.get("date_start")),
        )
        try:
            if date.fromisoformat(start) != date.fromisoformat(end):
                raise ValueError("Fato Meta deve ser diário, não agregado por período.")
        except ValueError as exc:
            raise ValueError("Data diária Meta inválida.") from exc
        meta = _account_meta(account_meta, account)
        currency = _text(
            fact.get("currency") or fact.get("account_currency") or meta.get("currency")
        )
        tz = _text(
            fact.get("timezone_name")
            or fact.get("timezone")
            or meta.get("timezone_name")
        )
        policy = (
            _text(fact.get("attribution_policy") or fact.get("politica_atribuicao"))
            or "DESCONHECIDA"
        )
        if not account or not aid or not currency or not tz:
            raise ValueError(
                "Fato diário sem conta, anúncio, moeda ou fuso comprovado."
            )
        try:
            zone = ZoneInfo(tz)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Fuso Meta inválido.") from exc
        key = _key(account, aid, start, currency, tz, policy)
        normalized = json.dumps(fact, sort_keys=True, ensure_ascii=False, default=str)
        if key in seen_facts:
            if seen_facts[key] != normalized:
                raise ValueError("Fatos Meta divergentes para a mesma chave diária.")
            continue
        seen_facts[key] = normalized
        classification = class_map.get((account, aid), "NAO_CLASSIFICADO")
        if classification in {"FARMA", "PET"} and classification != segment:
            continue
        exclusive = classification == segment
        spend, impressions, clicks = (
            _number(fact.get(k)) for k in ("spend", "impressions", "clicks")
        )
        dims = {
            "chave": key,
            "segmento": segment if exclusive else classification,
            "conta_id": account,
            "anuncio_id": aid,
            "data": start,
            "moeda": currency,
            "fuso": tz,
            "politica_atribuicao": policy,
        }
        raw = {
            **dims,
            "data_fim": end,
            "campanha_id": _text(fact.get("campaign_id")),
            "conjunto_id": _text(fact.get("adset_id")),
            "classificacao": classification,
            "investimento_original": _money(spend),
            "investimento_atribuivel": _money(spend) if exclusive else "",
            "impressoes": _money(impressions),
            "cliques": _money(clicks),
            "alcance": _money(_number(fact.get("reach"))),
            "frequencia": _money(_number(fact.get("frequency"))),
            "acoes_meta_json": json.dumps(
                fact.get("actions", []), ensure_ascii=False, sort_keys=True
            ),
            "valores_acoes_meta_json": json.dumps(
                fact.get("action_values", []), ensure_ascii=False, sort_keys=True
            ),
            "roas_meta_json": json.dumps(
                fact.get("purchase_roas", []), ensure_ascii=False, sort_keys=True
            ),
            "origem": "META_MARKETING_API",
            "payload_api_json": _json(_safe_fact_payload(fact)),
            "atualizado_em": updated_at,
        }
        campaign = campaign_index.get((account, _text(fact.get("campaign_id"))), {})
        adset = adset_index.get((account, _text(fact.get("adset_id"))), {})
        ad = ad_index.get((account, aid), {})
        link_clicks = _number(fact.get("inline_link_clicks"))
        if link_clicks is None:
            link_clicks = _number(_action_value(fact.get("actions"), ("link_click",)))
        started = _action_value(
            fact.get("actions"),
            (
                "onsite_conversion.messaging_conversation_started_7d",
                "messaging_conversation_started_7d",
            ),
        )
        purchase_value = _canonical_purchase(fact.get("action_values"))
        raw.update(
            {
                "conta_nome": _text(fact.get("account_name") or meta.get("name")),
                "campanha_nome": _text(
                    fact.get("campaign_name") or campaign.get("name")
                ),
                "conjunto_nome": _text(fact.get("adset_name") or adset.get("name")),
                "anuncio_nome": _text(fact.get("ad_name") or ad.get("name")),
                "campanha_status": _text(
                    campaign.get("effective_status") or campaign.get("status")
                ),
                "conjunto_status": _text(
                    adset.get("effective_status") or adset.get("status")
                ),
                "anuncio_status": _text(ad.get("effective_status") or ad.get("status")),
                "objetivo": _text(campaign.get("objective")),
                "cliques_link": _money(link_clicks),
                "custos_acoes_meta_json": _json(fact.get("cost_per_action_type", [])),
                "resultados_meta_json": _json(fact.get("results", [])),
                "resultado_tipo_meta": _text(fact.get("result_type")),
                "conversas_iniciadas_meta": started,
                "valor_compras_atribuido_meta": purchase_value,
            }
        )
        tables["Meta_Ads_Diario"].append(raw)
        local_events = [
            e
            for e in events_by_ad[(account, aid)]
            if e["segment"] == segment
            and e["ad_id"] == aid
            and e["dt"].astimezone(zone).date().isoformat() == start
        ]
        local_conversions = [
            r
            for r in conversions_by_ad[(account, aid)]
            if r["conta_id"] == account
            and r["anuncio_id"] == aid
            and (exposed := business_order_datetime(r["data_exposicao"])) is not None
            and exposed.astimezone(zone).date().isoformat() == start
        ]
        revenues = sum(
            (Decimal(r["receita_confirmada"]) for r in local_conversions), Decimal(0)
        )
        conversation_ids = {
            e.get("conversation_id") for e in local_events if e.get("conversation_id")
        }
        conversations = (
            len(conversation_ids)
            if local_events and all(e.get("conversation_id") for e in local_events)
            else ""
        )
        availability = exclusive and policy != "DESCONHECIDA" and currency == "BRL"
        tables["BI_Meta_Resultados"].append(
            {
                **dims,
                "segmento": segment,
                "classificacao": classification,
                "investimento_original": _money(spend),
                "investimento_atribuivel": _money(spend) if exclusive else "",
                "impressoes": _money(impressions),
                "cliques": _money(clicks),
                "ctr_pct": _ratio(clicks, impressions, Decimal(100)),
                "cpc": _ratio(spend, clicks),
                "cpm": _ratio(spend, impressions, Decimal(1000)),
                "eventos_ctwa": len(local_events),
                "contatos": len(
                    {e["contact_uuid"] for e in local_events if e["contact_uuid"]}
                ),
                "conversas": conversations,
                "compradores_confirmados": len(
                    {
                        r["cliente_chave"]
                        for r in local_conversions
                        if r["cliente_chave"]
                    }
                ),
                "pedidos_confirmados": len(local_conversions),
                "receita_confirmada": _money(revenues),
                "moeda_receita": "BRL",
                "compras_atribuidas_meta": _canonical_purchase(fact.get("actions")),
                "cpa_confirmado": _ratio(spend, Decimal(len(local_conversions)))
                if availability
                else "",
                "roas_confirmado": _ratio(revenues, spend) if availability else "",
                "cac": "",
                "cliques_link": _money(link_clicks),
                "conversas_iniciadas_meta": started,
                "valor_compras_atribuido_meta": purchase_value,
                "custo_conversa_weni_confirmada": _ratio(spend, _number(conversations))
                if availability
                else "",
                "custo_conversa_meta": _ratio(spend, _number(started))
                if availability
                else "",
                "taxa_conversao_contatos_pct": _ratio(
                    Decimal(
                        len(
                            {
                                r["cliente_chave"]
                                for r in local_conversions
                                if r["cliente_chave"]
                            }
                        )
                    ),
                    Decimal(
                        len(
                            {
                                e["contact_uuid"]
                                for e in local_events
                                if e["contact_uuid"]
                            }
                        )
                    ),
                    Decimal(100),
                ),
                "taxa_conversao_cliques_meta_pct": _ratio(
                    _number(_canonical_purchase(fact.get("actions"))),
                    clicks,
                    Decimal(100),
                )
                if policy != "DESCONHECIDA"
                else "",
                "metodo_atribuicao": "ULTIMO_TOQUE_OBSERVADO",
                "motivo_indisponibilidade": ""
                if availability
                else "CUSTO_NAO_EXCLUSIVO_JANELA_DESCONHECIDA_OU_MOEDA_INCOMPATIVEL",
                "atualizado_em": updated_at,
            }
        )
    for name, rows in [("Meta_Ads_Campanhas", campaigns), ("Meta_Ads_Anuncios", ads)]:
        collected = {}
        for r in rows:
            account = _text(r.get("account_id") or r.get("conta_id")).removeprefix(
                "act_"
            )
            rid = _text(
                r.get("id")
                or r.get("anuncio_id" if name == "Meta_Ads_Anuncios" else "campanha_id")
            )
            if not account or not rid:
                continue
            key = _key(account, rid)
            if name == "Meta_Ads_Anuncios":
                classification = class_map.get((account, rid), "NAO_CLASSIFICADO")
                row = {
                    "chave": key,
                    "segmento": segment
                    if classification == segment
                    else classification,
                    "conta_id": account,
                    "anuncio_id": rid,
                    "anuncio_nome": _text(r.get("name")),
                    "campanha_id": _text(r.get("campaign_id")),
                    "conjunto_id": _text(r.get("adset_id")),
                    "status": _text(r.get("effective_status") or r.get("status")),
                    "classificacao": classification,
                    "atualizado_em": updated_at,
                }
            else:
                classes = {
                    class_map.get(
                        (account, _text(a.get("id") or a.get("ad_id"))),
                        "NAO_CLASSIFICADO",
                    )
                    for a in ads
                    if _text(a.get("campaign_id")) == rid
                    and _text(a.get("account_id") or a.get("conta_id")).removeprefix(
                        "act_"
                    )
                    == account
                }
                classification = (
                    next(iter(classes))
                    if len(classes) == 1
                    else "COMPARTILHADO"
                    if "COMPARTILHADO" in classes or classes == {"FARMA", "PET"}
                    else "NAO_CLASSIFICADO"
                )
                row = {
                    "chave": key,
                    "segmento": segment
                    if classification == segment
                    else classification,
                    "conta_id": account,
                    "campanha_id": rid,
                    "campanha_nome": _text(r.get("name")),
                    "status": _text(r.get("effective_status") or r.get("status")),
                    "objetivo": _text(r.get("objective")),
                    "classificacao": classification,
                    "atualizado_em": updated_at,
                }
            row["conta_nome"] = _text(_account_meta(account_meta, account).get("name"))
            if name == "Meta_Ads_Anuncios":
                campaign = campaign_index.get((account, row["campanha_id"]), {})
                adset = adset_index.get((account, row["conjunto_id"]), {})
                row.update(
                    {
                        "campanha_nome": _text(campaign.get("name")),
                        "conjunto_nome": _text(adset.get("name")),
                        "campanha_status": _text(
                            campaign.get("effective_status") or campaign.get("status")
                        ),
                        "conjunto_status": _text(
                            adset.get("effective_status") or adset.get("status")
                        ),
                        "objetivo": _text(campaign.get("objective")),
                    }
                )
            if classification in {"FARMA", "PET"} and classification != segment:
                continue
            if key in collected and collected[key] != row:
                raise ValueError("Catálogo Meta divergente para a mesma identidade.")
            collected[key] = row
        tables[name] = sorted(collected.values(), key=lambda r: r["chave"])
    return tables
