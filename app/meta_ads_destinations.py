"""Evidência privada de destinos Meta/Weni. Intervalos documentados são [início, fim)."""

import hashlib
from collections import Counter
from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo


def instant(value):
    stamp = datetime.fromisoformat(value)
    if stamp.utcoffset() is None:
        raise ValueError("Instante de evidência sem fuso.")
    return stamp


def reference(doc):
    """A lista é um extrato oficial revisado pelo operador, independente do criativo."""
    if doc["segment"] != "FARMA" or doc["source"] != "WENI_CX_PROJECT_WABAS":
        raise ValueError("Origem do cadastro de destino inválida.")
    for field in ("cx_project", "flows_org"):
        UUID(doc[field])
    instant(doc["observed"])
    if (
        not isinstance(doc["waba"], str)
        or not doc["waba"].isascii()
        or not doc["waba"].isdigit()
    ):
        raise ValueError("ID do WABA inválido.")
    phones = doc["phones"]
    if (
        not isinstance(phones, dict)
        or len(phones) != 2
        or any(
            not isinstance(p, str)
            or not p.startswith("+")
            or not p[1:].isascii()
            or not p[1:].isdigit()
            or len(p) > 16
            for p in phones
        )
        or set(phones.values()) != {"WA_1", "WA_2"}
    ):
        raise ValueError("Cadastro de números empresariais inválido.")
    if not isinstance(doc["bindings"], list):
        raise ValueError("Vínculos históricos inválidos.")
    for binding in doc["bindings"]:
        if instant(binding["from"]) >= instant(binding["until"]) or not binding["ref"]:
            raise ValueError("Vigência da evidência inválida.")
        instant(binding["observed"])
        if binding["kind"] == "channel":
            UUID(binding["channel"])
            if (
                binding["waba"] != doc["waba"]
                or binding["phone"] not in phones
                or not isinstance(binding["phone_id"], str)
                or not binding["phone_id"].isdigit()
                or binding["source"] != "WENI_META_CHANNEL_HISTORY"
            ):
                raise ValueError("Vínculo oficial do canal inválido.")
        elif binding["kind"] == "ad":
            # Uma linha descreve TODOS os receptores do anúncio nessa vigência.
            if (
                binding["source"] != "META_AD_DESTINATION_HISTORY"
                or any(
                    not isinstance(binding[k], str) or not binding[k].isdigit()
                    for k in ("account", "ad", "adset")
                )
                or not isinstance(binding["receivers"], list)
                or not binding["receivers"]
                or any(
                    r not in {*phones, "DIRECT_FARMA", "OUTRO", "DESCONHECIDO"}
                    for r in binding["receivers"]
                )
                or (
                    "DIRECT_FARMA" in binding["receivers"]
                    and (
                        not isinstance(binding.get("exclusive_ig_id"), str)
                        or not binding["exclusive_ig_id"].isdigit()
                    )
                )
            ):
                raise ValueError("Destino oficial do anúncio inválido.")
        else:
            raise ValueError("Tipo de vínculo inválido.")
    return doc


def matches(rows, start, end):
    return [
        r for r in rows if instant(r["from"]) <= start and end <= instant(r["until"])
    ]


def day_evidence(
    doc,
    channels,
    events,
    *,
    account,
    ad,
    adset,
    day,
    zone,
    observed,
    delivered_segments,
    complete,
    current_destination,
):
    start = datetime.combine(day, time.min, ZoneInfo(zone))
    end = start + timedelta(days=1)
    full = complete and end <= instant(observed)
    counts = Counter()
    refs = set()
    history = [b for b in doc["bindings"] if b["kind"] == "channel"]
    for event in events:
        # O modelo nativo já deduplicou e delimitou o dia no fuso da conta.
        event_at = event["dt"]
        candidates = [
            b
            for b in history
            if b["channel"] == event["channel_uuid"]
            and instant(b["from"]) <= event_at < instant(b["until"])
        ]
        choices = {(b["phone"], b["phone_id"]) for b in candidates}
        refs.update(b["ref"] for b in candidates)
        current = channels.get(event["channel_uuid"], [])
        if len(choices) > 1:
            status = "CONFLITO"
        elif not choices:
            status = "VIGENCIA_DESCONHECIDA" if current else "CANAL_AUSENTE"
        else:
            phone, phone_id = next(iter(choices))
            # Cadastro atual pode ter mudado. Coincidência isolada nunca comprova vigência.
            status = (
                doc["phones"][phone]
                if current in ([phone_id], [phone], [phone[1:]])
                else "CONFLITO"
                if current
                else "CANAL_AUSENTE"
            )
        counts[status] += 1
    scope = [
        b
        for b in doc["bindings"]
        if b["kind"] == "ad"
        and (b["account"], b["ad"], b["adset"]) == (account, ad, adset)
    ]
    overlapping = [
        b for b in scope if instant(b["from"]) < end and start < instant(b["until"])
    ]
    configurations = {tuple(sorted(set(b["receivers"]))) for b in overlapping}
    refs.update(b["ref"] for b in overlapping)
    configured = "VIGENCIA_DESCONHECIDA"
    if len(configurations) > 1:
        configured = "CONFLITO"
    elif matches(scope, start, end):
        receivers = next(iter(configurations))
        configured = (
            "AMBIGUO"
            if any(r in {"OUTRO", "DESCONHECIDO"} for r in receivers)
            else "FARMA"
        )
    if "PET" in delivered_segments:
        configured = "COMPARTILHADO"
    if not full:
        configured = "COBERTURA_INCOMPLETA"
    used = [b for b in doc["bindings"] if b["ref"] in refs]
    identities = None
    if full and all(e.get("conversation_id") for e in events):
        identities = sorted(
            {
                hashlib.sha256(
                    (doc["cx_project"] + ":" + e["conversation_id"]).encode()
                ).hexdigest()
                for e in events
            }
        )
    return dict(
        conversas_distintas_privadas=identities,
        projeto_cx=doc["cx_project"],
        organizacao_flows=doc["flows_org"],
        waba=doc["waba"],
        vigencias=[
            {
                k: b[k]
                for k in (
                    "from",
                    "until",
                    "observed",
                    "source",
                    "ref",
                    "channel",
                    "phone",
                    "phone_id",
                    "waba",
                    "account",
                    "ad",
                    "adset",
                    "receivers",
                    "exclusive_ig_id",
                )
                if k in b
            }
            for b in used
        ],
        numeros_autorizados=doc["phones"],
        configurado=configured,
        canal_configurado_observado=current_destination or None,
        observado=observed,
        cadastro_observado=doc["observed"],
        cobertura="COMPLETA" if full else "PARCIAL",
        origem="WENI_FLOWS_CHANNELS_META_ADSET",
        referencias=sorted(refs),
        eventos=dict(sorted(counts.items())),
    )


def _farma_delivery(rows):
    return {
        (r["conta_id"], r["anuncio_id"])
        for r in rows
        if r["segmento"] == r["classificacao"] == "FARMA"
        and any(
            Decimal(str(r[k] or 0)) > 0 for k in ("impressoes", "investimento_original")
        )
    }


def _conversation_observation(value):
    if value in ("", None):
        return {"estado": "SEM_METRICA", "valor": None}
    number = Decimal(value)
    return {
        "estado": "ZERO_EXPLICITO" if number == 0 else "VALOR_INFORMADO",
        "valor": int(number) if number == number.to_integral_value() else float(number),
    }


def reconcile_conversation_days(published, candidate, refreshed, windows):
    """Compara a resposta bruta com a revisão anterior antes de aceitar a mescla."""
    from meta_ads_model import started_conversations

    eligible = _farma_delivery(published) | _farma_delivery(candidate)

    def index(rows):
        result = {}
        for account, ad, day, value in rows:
            interval = windows.get(account)
            if (account, ad) not in eligible or not interval:
                continue
            if interval[0] <= day <= interval[1]:
                key = account, ad, day
                observation = _conversation_observation(value)
                if key in result and result[key] != observation:
                    raise ValueError(
                        "Observações de conversas Meta divergentes no mesmo dia."
                    )
                result[key] = observation
        return result

    before = index(
        (r["conta_id"], r["anuncio_id"], r["data"], r.get("conversas_iniciadas_meta"))
        for r in published
        if r["segmento"] == r["classificacao"] == "FARMA"
    )
    current = index(
        (
            r["account_id"],
            r["ad_id"],
            r["date_start"],
            started_conversations(r.get("actions")),
        )
        for r in refreshed
    )
    absent = {"estado": "SEM_LINHA", "valor": None}
    differences = []
    for account, ad, day in sorted(before.keys() | current.keys()):
        key = account, ad, day
        old, new = before.get(key, absent), current.get(key, absent)
        if old == new and new["valor"] is not None:
            continue
        if new["valor"] is None:
            action = (
                "PENDENTE_HISTORICO" if old["valor"] is not None else "INDISPONIVEL"
            )
        else:
            action = "VALOR_CONFIRMADO_NA_CONSULTA"
        differences.append(
            dict(
                conta_id=account,
                anuncio_id=ad,
                data=day,
                historico=old,
                consulta=new,
                acao=action,
            )
        )
    return differences


def period_control(tables, start, end):
    """Mesmo universo da função SQL. Exibe IDs de anúncio e contagens sem identidades Weni."""
    rows = [
        r
        for r in tables["BI_Meta_Resultados"]
        if r["segmento"] == r["classificacao"] == "FARMA" and start <= r["data"] <= end
    ]
    eligible = _farma_delivery(rows)
    sums = {}
    grains = set()
    for r in rows:
        account, ad = r["conta_id"], r["anuncio_id"]
        if (account, ad) not in eligible:
            continue
        grain = account, ad, r["data"]
        if grain in grains:
            raise ValueError("Sobreposição na conta, anúncio e dia Meta.")
        grains.add(grain)
        scope = account, ad, r["moeda"], r["fuso"], r["politica_atribuicao"]
        item = sums.setdefault(
            scope,
            dict(
                conta_id=account,
                anuncio_id=ad,
                moeda=scope[2],
                fuso=scope[3],
                politica=scope[4],
                eventos_ctwa=0,
                conversas_meta=0,
            ),
        )
        item["eventos_ctwa"] += int(r["eventos_ctwa"])
        value = r["conversas_iniciadas_meta"]
        if value in ("", None):
            item["conversas_meta"] = None
        elif item["conversas_meta"] is not None:
            item["conversas_meta"] += int(Decimal(str(value)))
    return [sums[k] for k in sorted(sums)]
