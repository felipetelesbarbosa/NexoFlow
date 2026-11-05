"""Sincronização Meta nativa opcional; planejamento e checkpoints por conta/perfil."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from time import monotonic
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from connectors.meta_ads_mcp.client import MetaAdsClient, MetaReadError  # noqa: E402
from connectors.meta_ads_mcp.settings import SettingsError, load_settings  # noqa: E402
from meta_ads_evidence import collect_weni_evidence  # noqa: E402
from meta_ads_model import build_native_tables  # noqa: E402
from meta_ads_sheets import NativeMetaSheets  # noqa: E402

TZ = ZoneInfo("America/Belem")
POLICY = "META_AD_DAY_LAST_OBSERVED_V1"


class MetaMigrationRequired(ValueError):
    """Grão já armazenado com política/moeda/fuso diferentes exige revisão."""


def _bounded(settings, segment, name, default, maximum):
    value = _setting(settings, segment, name, default)
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("Parâmetro de lote/overlap Meta inválido.")
    return value


def _setting(settings, segment, name, default=None):
    if isinstance(settings, dict):
        profiles = settings.get("PERFIS", {})
        return profiles.get(segment, {}).get(name, settings.get(name, default))
    profiles = getattr(settings, "PERFIS", {})
    if isinstance(profiles, dict) and isinstance(profiles.get(segment), dict):
        return profiles[segment].get(name, getattr(settings, name, default))
    return getattr(settings, name, default)


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix="meta-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _state(path, segment, account):
    if not path.exists():
        return {}
    state = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(state, dict)
        or state.get("schema") != 1
        or state.get("segment") != segment
        or state.get("account_id") != account
    ):
        raise ValueError("Estado Meta pertence a outro perfil/conta ou é inválido.")
    date.fromisoformat(state["through"])
    return state


def _rows(result):
    if not isinstance(result, dict) or result.get("parcial") is not False:
        raise MetaReadError(
            "Consulta Meta parcial; checkpoint preservado.", retryable=True
        )
    rows = result.get("dados")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise MetaReadError("Dados Meta inválidos.")
    return rows


def _restore_facts(tables):
    result = []
    for row in tables.get("Meta_Ads_Diario", []):
        payload = row.get("payload_api_json")
        if isinstance(payload, str) and payload:
            fact = json.loads(payload)
            if not isinstance(fact, dict):
                raise ValueError("Payload diário Meta inválido.")
            fact.update(
                account_id=row.get("conta_id", ""),
                ad_id=row.get("anuncio_id", ""),
                date_start=row.get("data", ""),
                date_stop=row.get("data_fim") or row.get("data", ""),
                currency=row.get("moeda", ""),
                timezone_name=row.get("fuso", ""),
                attribution_policy=row.get("politica_atribuicao", ""),
            )
            result.append(fact)
            continue
        fact = {
            "account_id": row.get("conta_id", ""),
            "ad_id": row.get("anuncio_id", ""),
            "date_start": row.get("data", ""),
            "date_stop": row.get("data_fim") or row.get("data", ""),
            "campaign_id": row.get("campanha_id", ""),
            "adset_id": row.get("conjunto_id", ""),
            "currency": row.get("moeda", ""),
            "timezone_name": row.get("fuso", ""),
            "attribution_policy": row.get("politica_atribuicao", ""),
        }
        for api, column in [
            ("spend", "investimento_original"),
            ("impressions", "impressoes"),
            ("clicks", "cliques"),
            ("reach", "alcance"),
            ("frequency", "frequencia"),
            ("inline_link_clicks", "cliques_link"),
        ]:
            fact[api] = row.get(column, "")
        for api, column in [
            ("actions", "acoes_meta_json"),
            ("action_values", "valores_acoes_meta_json"),
            ("purchase_roas", "roas_meta_json"),
            ("cost_per_action_type", "custos_acoes_meta_json"),
            ("results", "resultados_meta_json"),
        ]:
            raw = row.get(column, "")
            fact[api] = json.loads(raw) if isinstance(raw, str) and raw else raw or []
        for api, column in [
            ("account_name", "conta_nome"),
            ("campaign_name", "campanha_nome"),
            ("adset_name", "conjunto_nome"),
            ("ad_name", "anuncio_nome"),
            ("result_type", "resultado_tipo_meta"),
        ]:
            fact[api] = row.get(column, "")
        result.append(fact)
    return result


def _fact_key(row):
    return (
        str(row.get("account_id", "")),
        str(row.get("ad_id", "")),
        str(row.get("date_start", "")),
        str(row.get("currency", "")),
        str(row.get("timezone_name", "")),
        str(row.get("attribution_policy", "")),
    )


def _failure(account, stage, exc):
    status = getattr(exc, "status_code", None)
    if type(status) is not int or not 100 <= status <= 599:
        status = None
    code, message = (
        "META_STAGE_FAILED",
        "Etapa Meta não concluída; confira a configuração e tente novamente.",
    )
    if isinstance(exc, SettingsError):
        code, message = (
            "META_CREDENTIALS_INVALID",
            "Credenciais Meta ausentes ou inválidas. Configure o token ads_read em credentials/mcp/meta_ads_credentials.json.",
        )
    elif isinstance(exc, MetaReadError):
        if status in (401, 403) or getattr(exc, "critical", False):
            code, message = (
                "META_READ_AUTHORIZATION_REQUIRED",
                "Verifique token, permissão ads_read e acesso de leitura à conta; ads_management não é permitido.",
            )
        elif status == 429:
            code, message = (
                "META_RATE_LIMIT",
                "Limite de consultas Meta atingido; aguarde a próxima execução.",
            )
        else:
            code, message = (
                "META_QUERY_INCOMPLETE",
                "Consulta Meta incompleta ou recusada; dados e checkpoint anteriores foram preservados.",
            )
    elif isinstance(exc, MetaMigrationRequired):
        code, message = (
            "META_MIGRATION_REQUIRED",
            "Política de atribuição, moeda ou fuso mudou; revise a migração antes de aplicar.",
        )
    return {
        "account_id": account,
        "stage": stage,
        "error_type": type(exc).__name__,
        "code": code,
        "message": message,
        "status_code": status,
        "critical": bool(
            isinstance(exc, SettingsError) or getattr(exc, "critical", False)
        ),
        "retryable": bool(getattr(exc, "retryable", False)),
    }


def sync_native_meta(
    store,
    settings,
    segment,
    contacts,
    orders,
    items,
    now=None,
    apply=True,
    state_dir=None,
    client_factory=None,
    evidence_collector=None,
    *,
    expected_manifest=None,
    schema_approved=False,
    weni_contacts=None,
):
    """Serviços injetáveis; apply=False não cria estado, abas ou recibos."""
    started = monotonic()
    report = {
        "status": "desativado",
        "enabled": False,
        "partial": False,
        "critical": False,
        "accounts": {},
        "errors": [],
        "counts": {},
        "schema_manifest": None,
        "applied": False,
    }
    if _setting(settings, segment, "META_ADS_ENABLED", False) is not True:
        return report
    report.update(enabled=True, status="planejando")
    stage, client = "configuracao", None
    runtime_root = (
        Path(getattr(settings, "__file__", "") or ROOT / "secrets_config.py")
        .resolve()
        .parent
    )
    try:
        if segment not in {"FARMA", "PET"}:
            raise ValueError("Segmento Meta inválido.")
        clock = now or datetime.now(TZ)
        if clock.tzinfo is None:
            raise ValueError("Relógio Meta exige fuso explícito.")
        today = clock.astimezone(TZ).date()
        start = date.fromisoformat(
            str(
                _setting(
                    settings,
                    segment,
                    "META_ADS_START_DATE",
                    today.replace(day=1).isoformat(),
                )
            )
        )
        end = date.fromisoformat(
            str(_setting(settings, segment, "META_ADS_END_DATE", today.isoformat()))
        )
        if end < start or end > today:
            raise ValueError("Período Meta inválido.")
        factory = client_factory or (
            lambda: MetaAdsClient(
                load_settings(
                    runtime_root / "credentials/mcp/meta_ads_credentials.json"
                )
            )
        )
        client = factory()
        accounts = tuple(client.settings.allowed_account_ids)
        adapter = (
            store
            if callable(getattr(store, "load_tables", None))
            else NativeMetaSheets(store, segment, account_ids=accounts)
        )
        overlap = _bounded(settings, segment, "META_ADS_OVERLAP_DAYS", 7, 31)
        batch = _bounded(settings, segment, "META_ADS_BATCH_DAYS", 7, 7)
        stage = "ler_planilhas"
        manifest = adapter.schema_manifest()
        previous = adapter.load_tables()
        read_errors = getattr(adapter, "read_errors", {})
        if read_errors:
            raise ValueError("Leitura Meta incompleta; histórico preservado.")
        if adapter.schema_manifest() != manifest:
            raise ValueError("Fontes Meta mudaram durante a leitura.")
        report["schema_manifest"] = manifest
        if expected_manifest is not None and expected_manifest != manifest:
            raise ValueError("Fontes Meta mudaram após a revisão.")
        facts, catalogs, account_meta, ready = (
            _restore_facts(previous),
            {"campaigns": [], "adsets": [], "ads": []},
            {},
            {},
        )
        root = (
            Path(state_dir)
            if state_dir is not None
            else runtime_root / "logs" / segment / "privado/meta_ads_native"
        )
        for account in accounts:
            stage = "coleta_meta"
            try:
                path = root / f"{segment}-{account}.json"
                state = _state(path, segment, account)
                since = start
                if state and state.get("policy") == POLICY:
                    through = date.fromisoformat(state["through"])
                    if through > today:
                        raise ValueError("Cursor Meta está no futuro.")
                    previous_start = date.fromisoformat(
                        state.get("from", start.isoformat())
                    )
                    if start >= previous_start and end >= through:
                        since = max(start, through - timedelta(days=overlap))
                meta = client.account_details(account)
                ZoneInfo(meta.get("timezone_name", ""))
                local_catalogs = {}
                for name, method in [
                    ("campaigns", client.campaigns),
                    ("adsets", client.adsets),
                    ("ads", client.ads),
                ]:
                    stage = "coleta_meta_" + name
                    local_catalogs[name] = [
                        dict(row, account_id=account)
                        for row in _rows(method(account, limit=100, pages=None))
                    ]
                stage = "coleta_meta_insights"
                local_facts = []
                cursor = since
                while cursor <= end:
                    stop = min(end, cursor + timedelta(days=batch - 1))
                    response = client.daily_insights(
                        account,
                        cursor.isoformat(),
                        stop.isoformat(),
                        limit=100,
                        pages=None,
                    )
                    rows = _rows(response)
                    attribution = response.get("attribution")
                    if (
                        not isinstance(attribution, dict)
                        or response.get("time_increment") != 1
                    ):
                        raise ValueError(
                            "Consulta Meta sem política diária/atribuição comprovada."
                        )
                    policy = json.dumps(
                        {
                            "api_version": response.get(
                                "api_version", client.settings.api_version
                            ),
                            "attribution": attribution,
                            "time_increment": 1,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    for row in rows:
                        if row.get("account_id") not in (None, "", account):
                            raise ValueError("Fato Meta retornou outra conta.")
                        day = date.fromisoformat(str(row.get("date_start", "")))
                        if (
                            not cursor <= day <= stop
                            or row.get("date_stop") != day.isoformat()
                        ):
                            raise ValueError(
                                "Fato Meta fora da janela diária consultada."
                            )
                        local_facts.append(
                            dict(
                                row,
                                account_id=account,
                                currency=meta.get("currency", ""),
                                timezone_name=meta.get("timezone_name", ""),
                                attribution_policy=policy,
                            )
                        )
                    cursor = stop + timedelta(days=1)
                existing_grains = {
                    (row.get("account_id"), row.get("ad_id"), row.get("date_start")): (
                        row.get("currency"),
                        row.get("timezone_name"),
                        row.get("attribution_policy"),
                    )
                    for row in facts
                }
                for row in local_facts:
                    grain = (
                        row.get("account_id"),
                        row.get("ad_id"),
                        row.get("date_start"),
                    )
                    observation = (
                        row.get("currency"),
                        row.get("timezone_name"),
                        row.get("attribution_policy"),
                    )
                    if (
                        grain in existing_grains
                        and existing_grains[grain] != observation
                    ):
                        raise MetaMigrationRequired(
                            "Política/moeda/fuso Meta mudou para um grão já armazenado."
                        )
                facts_by_key = {_fact_key(row): row for row in facts}
                for row in local_facts:
                    facts_by_key[_fact_key(row)] = row
                facts = list(facts_by_key.values())
                for name, rows in local_catalogs.items():
                    catalogs[name].extend(rows)
                account_meta[account] = meta
                ready[account] = (
                    path,
                    {
                        "schema": 1,
                        "segment": segment,
                        "account_id": account,
                        "through": max(
                            end,
                            date.fromisoformat(state.get("through", end.isoformat())),
                        ).isoformat(),
                        "from": min(
                            start,
                            date.fromisoformat(state.get("from", start.isoformat())),
                        ).isoformat(),
                        "policy": POLICY,
                        "confirmed_at": clock.isoformat(),
                    },
                )
                report["accounts"][account] = {
                    "status": "coletado",
                    "facts": len(local_facts),
                }
            except Exception as exc:
                report["errors"].append(_failure(account, stage, exc))
                report["accounts"][account] = {"status": "pendente"}
                if getattr(exc, "critical", False):
                    report.update(status="erro", critical=True, partial=True)
                    return report
        if not ready:
            report.update(status="parcial", partial=True)
            return report
        stage = "evidencias_weni"
        earliest = min(
            [start] + [date.fromisoformat(str(row["date_start"])) for row in facts]
        )
        supplied = {"PET" if segment == "FARMA" else "FARMA": []}
        if weni_contacts is not None:
            supplied[segment] = weni_contacts
        zones = {
            TZ,
            *[ZoneInfo(meta["timezone_name"]) for meta in account_meta.values()],
        }
        zones.update(
            ZoneInfo(row["timezone_name"]) for row in facts if row.get("timezone_name")
        )
        evidence_start = min(
            datetime.combine(earliest, time.min, zone).astimezone(UTC) for zone in zones
        )
        latest_evidence_day = max(
            [end] + [date.fromisoformat(str(row["date_start"])) for row in facts]
        )
        evidence_end = max(
            datetime.combine(
                latest_evidence_day + timedelta(days=1), time.min, zone
            ).astimezone(UTC)
            for zone in zones
        )
        evidence, coverage = (evidence_collector or collect_weni_evidence)(
            settings,
            start=evidence_start,
            end=evidence_end,
            contacts_by_segment=supplied,
        )
        if coverage.get("auth_failed"):
            report["errors"].append(
                {
                    "stage": "evidencias_weni",
                    "error_type": "WeniAuthenticationError",
                    "critical": True,
                }
            )
            report.update(status="erro", partial=True, critical=True)
            return report
        if not all(
            coverage.get("segments", {}).get(s) is True for s in ("FARMA", "PET")
        ):
            report["errors"].append(
                {
                    "stage": "evidencias_weni",
                    "error_type": "IncompleteCoverage",
                    "critical": False,
                }
            )
            report.update(status="parcial", partial=True)
            return report
        stage = "transformacao"
        tables = build_native_tables(
            segment=segment,
            facts=facts,
            catalogs=catalogs,
            evidence=evidence,
            contacts=contacts,
            orders=orders,
            items=items,
            account_meta=account_meta,
            updated_at=clock.isoformat(),
            coverage=coverage,
        )
        # Conversões deixam rastro em vez de manter receita de compra cancelada.
        fresh = {row["chave"] for row in tables["BI_Meta_Conversoes"]}
        for row in previous.get("BI_Meta_Conversoes", []):
            if row.get("conta_id") in ready and row["chave"] not in fresh:
                tables["BI_Meta_Conversoes"].append(
                    dict(
                        row,
                        venda_valida="Não",
                        status_vinculo="INVALIDADO",
                        receita_confirmada="0",
                        atualizado_em=clock.isoformat(),
                    )
                )
        for title in ("Meta_Ads_Diario", "BI_Meta_Resultados"):
            current_keys = {row["chave"] for row in tables.get(title, [])}
            for old in previous.get(title, []):
                if old.get("conta_id") not in ready or old.get("chave") in current_keys:
                    continue
                inactive = dict(
                    old,
                    segmento="NAO_CLASSIFICADO",
                    classificacao="NAO_CLASSIFICADO",
                    investimento_atribuivel="",
                    atualizado_em=clock.isoformat(),
                )
                if title == "BI_Meta_Resultados":
                    inactive["motivo_indisponibilidade"] = "SEM_VINCULO_NO_PERFIL_ATUAL"
                    for field in (
                        "pedidos_confirmados",
                        "compradores_confirmados",
                        "receita_confirmada",
                        "eventos_ctwa",
                        "contatos",
                    ):
                        inactive[field] = "0"
                    for field in (
                        "conversas",
                        "cpa_confirmado",
                        "roas_confirmado",
                        "cac",
                        "taxa_conversao_contatos_pct",
                        "taxa_conversao_cliques_meta_pct",
                    ):
                        inactive[field] = ""
                tables[title].append(inactive)
        for title, rows in tables.items():
            tables[title] = [row for row in rows if row.get("conta_id") in ready] + [
                row
                for row in previous.get(title, [])
                if row.get("conta_id") not in ready
            ]
        stage = "plano_planilhas"
        plan = adapter.plan_tables(tables)
        if plan.get("schema_manifest") != manifest:
            raise ValueError("Fontes Meta mudaram durante a coleta; plano bloqueado.")
        report["plan"] = plan
        report["counts"] = {title: len(rows) for title, rows in tables.items()}
        report["coverage"] = coverage
        if plan.get("pending_tabs"):
            report.update(status="parcial", partial=True)
            return report
        if not apply:
            report.update(status="simulacao", partial=bool(report["errors"]))
            return report
        approved = (
            schema_approved
            or _setting(settings, segment, "META_ADS_SCHEMA_APPROVED", False) is True
        )
        if (
            any(
                not table.get("exists") for table in manifest.get("tables", {}).values()
            )
            and not approved
        ):
            report.update(status="schema_pendente", partial=True)
            return report
        stage = "aplicar_planilhas"
        applied = adapter.apply_tables(
            tables, expected_manifest=expected_manifest or manifest
        )
        report["summary"] = applied
        if not applied.get("applied") or applied.get("pending_tabs"):
            report.update(status="parcial", partial=True)
            return report
        report["applied"] = True
        stage = "checkpoint"
        for account, (path, state) in ready.items():
            _atomic(path, state)
            report["accounts"][account]["status"] = "confirmado"
        report.update(
            status="parcial" if report["errors"] else "concluido",
            partial=bool(report["errors"]),
        )
        return report
    except Exception as exc:
        report["errors"].append(_failure("", stage, exc))
        report.update(
            status="erro", partial=True, critical=_failure("", stage, exc)["critical"]
        )
        return report
    finally:
        report["elapsed_seconds"] = round(monotonic() - started, 3)
        report["last_stage"] = stage
        if client is not None:
            try:
                metrics = getattr(client, "metrics_snapshot", None)
                if callable(metrics):
                    counts = metrics()
                    if isinstance(counts, dict):
                        report["http_meta"] = {
                            key: value
                            for key, value in counts.items()
                            if isinstance(value, (int, float))
                            and str(key)
                            in {
                                "GET",
                                "retries",
                                "seconds",
                                "network_errors",
                                "HTTP_200",
                                "HTTP_400",
                                "HTTP_401",
                                "HTTP_403",
                                "HTTP_429",
                                "HTTP_500",
                                "HTTP_502",
                                "HTTP_503",
                                "HTTP_504",
                            }
                        }
            except Exception:
                report["http_meta"] = {"available": False}
            try:
                client.close()
            except Exception:
                pass
