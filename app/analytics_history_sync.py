"""Orquestra histórico e publicação nativa; mesmos planos, guardas e journals."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from dedup_io import save_private
from history_conference import receipts, summarize
from history_exclusions import AUDIT_TABLE, exclusion_audit
from history_publication import get
from history_sheets_bulk import BulkHistorySheets, batch_budget
from history_snapshot import readonly, sha256, snapshot
from order_history import HistoryError, HistoryQuery
from order_history_sheets import iter_tables


def requested_period(settings, now, segment):
    """Um backfill exige dois limites explícitos; FORCE_FULL_SYNC não os inventa."""
    from datetime import timedelta

    from pedido_utils import business_order_datetime

    fraction = os.getenv("NEXOFLOW_HISTORY_PERCENTUAL", "100").strip()
    if fraction not in {"25", "50", "75", "100"}:
        raise HistoryError("PERCENTUAL_INVALIDO")
    start = os.getenv("NEXOFLOW_HISTORY_INICIO", "").strip()
    end = os.getenv("NEXOFLOW_HISTORY_FIM", "").strip()
    if bool(start) != bool(end):
        raise HistoryError("HISTORICO_EXIGE_INICIO_E_FIM")
    dt = business_order_datetime(now)
    if dt is None:
        raise HistoryError("DATA_EXECUCAO_INVALIDA")
    return HistoryQuery(
        segment,
        start or (dt.date() - timedelta(days=20)).isoformat(),
        end or dt.date().isoformat(),
        int(getattr(settings, "FARMALIDER_HISTORY_PAGE_LIMIT", 500)),
    ), bool(start)


def prepare(adapter, source, directory, segment, previous=None):
    """Cópia consistente; exclusões anteriores só migram se o fato for idêntico."""
    logging.info(
        "Histórico Sheets: preparando snapshot consistente e capacidade das cinco tabelas."
    )
    evidence = snapshot(source, directory / "fontes", segment)
    if previous and previous.get("evidence", {}).get("publication_exclusions"):
        old = previous["evidence"]
        if sha256(old["path"]) != old["sha256"]:
            raise HistoryError("FONTE_EXCLUSOES_ALTERADA")
        # Nunca apagar fatos na origem. Reaplica somente à NOVA cópia privada.
        with readonly(old["path"], segment) as original:
            ddl = original.db.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (AUDIT_TABLE,)
            ).fetchone()
            if not ddl:
                raise HistoryError("AUDITORIA_EXCLUSOES_AUSENTE")
            entries = original.db.execute(f"SELECT * FROM {AUDIT_TABLE}").fetchall()
        with closing(sqlite3.connect(evidence["path"])) as db:
            with db:
                if not db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name=?", (AUDIT_TABLE,)
                ).fetchone():
                    db.execute(ddl[0])
                for entry in entries:
                    stored = db.execute(
                        "SELECT record FROM history_orders WHERE segment=? AND id=?",
                        entry[:2],
                    ).fetchone()
                    expected = json.loads(json.loads(entry[7])[3])
                    if stored:
                        actual = json.loads(stored[0])
                        # Mudanças de vínculo não mudam a autorização financeira.
                        fields = (
                            "segment",
                            "id",
                            "owner",
                            "date",
                            "state",
                            "products_cents",
                            "freight_cents",
                            "revenue_cents",
                            "items",
                        )
                        if any(actual.get(k) != expected.get(k) for k in fields):
                            raise HistoryError("EXCLUSAO_ALTERADA_REQUER_REVISAO")
                        db.execute(
                            "DELETE FROM history_orders WHERE segment=? AND id=?",
                            entry[:2],
                        )
                    existing = db.execute(
                        f"SELECT * FROM {AUDIT_TABLE} WHERE segment=? AND id=?",
                        entry[:2],
                    ).fetchone()
                    if existing and existing != entry:
                        raise HistoryError("AUDITORIA_EXCLUSAO_DIVERGENTE")
                    db.execute(
                        f"INSERT OR IGNORE INTO {AUDIT_TABLE} VALUES(?,?,?,?,?,?,?,?)",
                        entry,
                    )
        evidence.update(
            sha256=sha256(evidence["path"]), bytes=Path(evidence["path"]).stat().st_size
        )
    with readonly(evidence["path"], segment) as history:
        evidence["publication_exclusions"] = exclusion_audit(history.db, segment)
        evidence["conference"] = summarize(
            history.records(), segment, context={"snapshot_sha256": evidence["sha256"]}
        )
        evidence["receipts"] = receipts(history)
        return adapter.plan(iter_tables(history), evidence=evidence)


def previous_review(adapter, directory, publication):
    """Recupera apenas o journal local da revisão que o manifesto identifica."""
    revision = publication.get("revision")
    if not revision:
        return None
    if (
        not isinstance(revision, str)
        or len(revision) != 32
        or any(c not in "0123456789abcdef" for c in revision)
    ):
        raise HistoryError("REVISAO_MANIFESTO_INVALIDA")
    path = directory / revision / "plano.sqlite"
    if not path.is_file():
        raise HistoryError("JOURNAL_PUBLICADO_AUSENTE_AUTOMACAO_BLOQUEADA")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        review = get(db, "review")
    with closing(adapter.engine._open(review)):
        pass
    return review


def synchronize(adapter, source, directory, segment, publication, *, percent=100):
    """Retoma o mesmo snapshot antes de preparar outro. Checkpoint só após releitura."""
    directory = Path(directory)
    state_path = directory / "analytics_estado.json"
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {}
    )
    if state and state.get("segment") != segment:
        raise HistoryError("ESTADO_ANALYTICS_DE_OUTRO_SEGMENTO")
    previous = previous_review(adapter, directory, publication)
    active = state.get("review") if state.get("status") != "conferida" else None
    if publication.get("state") == "WRITING" and not active:
        raise HistoryError("PUBLICACAO_MANUAL_PENDENTE_RETOME_A_REVISAO_ORIGINAL")
    if active:
        # A evidência da revisão é imutável mesmo com novos pedidos coletados.
        review = active
        resumed = True
    else:
        review = prepare(adapter, source, directory, segment, previous)
        resumed = False
        save_private(directory / review["revision"] / "revisao.json", review)
        save_private(
            state_path, dict(segment=segment, status="preparada", review=review)
        )
    logging.info(
        "Histórico Sheets: %s revisão; total original=%s lotes; fração=%s%%.",
        "retomando" if resumed else "aplicando",
        review["batches"],
        percent,
    )
    adapter.apply(None, review, max_batches=batch_budget(review, percent, None))
    result = dict(adapter.last_result)
    if not result["remaining_batches"]:
        logging.info(
            "Histórico Sheets: conferindo todos os intervalos e fechamento financeiro."
        )
        report = adapter.check(review)
        save_private(
            directory / review["revision"] / "fechamento_analytics.json", report
        )
        if report["status"] != "conferida":
            raise HistoryError("CONFERENCIA_ANALYTICS_DIVERGENTE")
        save_private(
            state_path, dict(segment=segment, status="conferida", review=review)
        )
    result["resumed"] = resumed
    result["partial"] = bool(result["remaining_batches"] or resumed)
    return result


def run(settings):
    """Falha histórica é explícita e isolada; não declara sucesso das cinco fontes."""
    from config import LOG_DIR
    from customer_observations import DB_ROOT
    from history_sheets_quota import google_store_type
    from recompra_lock import state_lock
    from runtime_profile import segment

    enabled = getattr(
        settings,
        "FARMALIDER_HISTORY_SHEETS_ENABLED",
        getattr(settings, "FARMALIDER_HISTORY_ENABLED", False),
    )
    if not enabled and not os.getenv("NEXOFLOW_HISTORY_INICIO"):
        return {"status": "desativado", "partial": False}
    percent = int(os.getenv("NEXOFLOW_HISTORY_PERCENTUAL", "100"))
    if percent not in (25, 50, 75, 100):
        raise HistoryError("PERCENTUAL_INVALIDO")
    directory = LOG_DIR / "privado" / "historico_publicacoes"
    source = (
        DB_ROOT / segment() if DB_ROOT is not None else LOG_DIR / "privado"
    ) / "clientes_observados.sqlite"
    try:
        with state_lock(LOG_DIR / "historico_pedidos_state.json"):
            google = google_store_type().open_native_readonly(
                settings.GOOGLE_SPREADSHEET_ID
            )
            try:
                adapter = BulkHistorySheets(google, segment(), directory)
                remote = adapter.engine.remote
                remote.manifest()  # Releitura do índice; nunca criar fontes implicitamente.
                publication = dict(
                    remote.manager.index.config.get("history_publication", {})
                )
                result = synchronize(
                    adapter, source, directory, segment(), publication, percent=percent
                )
            finally:
                google.close()
        logging.info(
            "Histórico Sheets: estado=%s; linhas confirmadas=%s; lotes restantes=%s.",
            result["status"],
            result["applied_rows"],
            result["remaining_batches"],
        )
        if result["resumed"]:
            logging.warning(
                "Revisão anterior retomada. Pedidos coletados depois de seu snapshot serão publicados na próxima carga Analytics."
            )
        return result
    except Exception as exc:
        # Não registrar a mensagem/URL do provedor nem valores de células.
        code = (
            str(exc)
            if isinstance(exc, HistoryError) and str(exc).replace("_", "").isalnum()
            else type(exc).__name__
        )
        logging.error(
            "Histórico Sheets pendente: %s. Revisão e lotes preservados; próxima carga retoma a etapa.",
            code,
        )
        save_private(
            directory / "analytics_ultima_falha.json",
            dict(segment=segment(), error=code),
        )
        return {"status": "pendente", "partial": True, "error": code}
