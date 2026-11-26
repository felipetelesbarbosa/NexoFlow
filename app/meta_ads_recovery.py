"""Regra compartilhada de recuperação de conversas Meta; sem rede ou armazenamento próprios."""

from decimal import Decimal, InvalidOperation


class MetaReadError(RuntimeError):
    """Erro público sanitizado de consulta à Meta."""

    def __init__(self, message, *, status_code=None, critical=False, retryable=False):
        super().__init__(message)
        self.status_code = status_code
        self.critical = critical
        self.retryable = retryable


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


def started_conversations(actions):
    return _action_value(
        actions,
        (
            "onsite_conversion.messaging_conversation_started_7d",
            "messaging_conversation_started_7d",
        ),
    )


def read_complete_rows(result):
    if not isinstance(result, dict) or result.get("parcial") is not False:
        raise MetaReadError(
            "Consulta Meta parcial; checkpoint preservado.", retryable=True
        )
    rows = result.get("dados")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise MetaReadError("Dados Meta inválidos.")
    return rows


def _fact_key(row):
    return (
        str(row.get("account_id", "")),
        str(row.get("ad_id", "")),
        str(row.get("date_start", "")),
        str(row.get("currency", "")),
        str(row.get("timezone_name", "")),
        str(row.get("attribution_policy", "")),
    )


def observed_media_metrics(fact):
    """Métrica ausente continua vazia; não inventar denominadores."""
    spend, impressions, clicks = (
        _number(fact.get(k)) for k in ("spend", "impressions", "clicks")
    )
    return {
        "investimento_original": _money(spend),
        "impressoes": _money(impressions),
        "cliques": _money(clicks),
        "ctr_pct": _ratio(clicks, impressions, Decimal(100)),
        "cpm": _ratio(spend, impressions, Decimal(1000)),
        "conversas_iniciadas_meta": started_conversations(fact.get("actions")),
    }


def merge_observations(previous, refreshed):
    """Sobrepor apenas grãos observados; omissão não equivale a zero."""
    facts = {_fact_key(row): row for row in previous}
    for row in refreshed:
        facts[_fact_key(row)] = row
    return list(facts.values())


def recover_direct_conversations(
    client, account, published, local_facts, *, ads, since, end,
    meta, attribution, api_version, policy,
):
    """Mesma recuperação FARMA da 1.5.64. Conserva o limite de 20 consultas.

    O cliente deve fornecer somente a leitura diária por anúncio. Não escreve
    e não depende de configuração/credenciais Windows.
    """
    from meta_ads_destinations import reconcile_conversation_days

    missing = reconcile_conversation_days(
        published, [], local_facts, {account: (since, end)},
    )
    catalog_ids = {row.get("id") for row in ads}
    candidates = [
        row for row in missing
        if row["acao"] == "PENDENTE_HISTORICO"
        and row["consulta"]["estado"] == "SEM_LINHA"
        and row["anuncio_id"] in catalog_ids
    ]
    recovered = []
    for gap in candidates[:20]:
        day, ad = gap["data"], gap["anuncio_id"]
        try:
            direct = client.daily_insights(account, day, day, pages=1, ad_id=ad)
            direct_rows = read_complete_rows(direct)
        except MetaReadError as exc:
            if exc.critical:
                raise
            continue
        if (
            len(direct_rows) != 1
            or direct.get("time_increment") != 1
            or direct.get("attribution") != attribution
            or direct.get("api_version") != api_version
        ):
            continue
        row = direct_rows[0]
        if (
            row.get("account_id") != account
            or row.get("ad_id") != ad
            or row.get("date_start") != day
            or row.get("date_stop") != day
            or row.get("spend") in (None, "")
            or started_conversations(row.get("actions")) in (None, "")
        ):
            continue
        # Impressões opcionais, CTR e CPM permanecem indisponíveis.
        recovered.append(dict(
            row, currency=meta.get("currency", ""),
            timezone_name=meta.get("timezone_name", ""),
            attribution_policy=policy,
        ))
    return recovered, {
        "linhas_omitidas": len(candidates),
        "consultas": min(20, len(candidates)),
        "recuperadas": len(recovered),
    }
