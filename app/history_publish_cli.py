"""Operações locais/Sheets do histórico: nunca instancia Weni ou FarmaLíder."""

from __future__ import annotations

import json
from pathlib import Path

from dedup_io import save_private
from history_conference import receipts, summarize
from history_snapshot import readonly, snapshot
from order_history import HistoryError
from order_history_sheets import HistorySheets, google_store_type, iter_tables


def _publish(args):
    from config import LOG_DIR
    from customer_observations import DB_ROOT
    from project_paths import load_private_settings
    from proxy_config import configure_proxy
    from recompra_lock import state_lock
    from runtime_profile import segment

    if args.revisao is None:
        raise HistoryError("REVISAO_OBRIGATORIA")
    if args.planilhas == "rollback" and (args.lote is None or args.lote < 1):
        raise HistoryError("LOTE_POSITIVO_OBRIGATORIO")
    if args.planilhas != "rollback" and args.lote is not None:
        raise HistoryError("LOTE_REQUER_ROLLBACK")
    directory = LOG_DIR / "privado" / "historico_publicacoes"
    configure_proxy()
    settings = load_private_settings()
    with state_lock(LOG_DIR / "historico_pedidos_state.json"):
        google = google_store_type().open_native_readonly(
            settings.GOOGLE_SPREADSHEET_ID
        )
        try:
            adapter = HistorySheets(google, segment(), directory)
            if args.planilhas in ("preparar", "capacidade"):
                root = (
                    DB_ROOT / segment() if DB_ROOT is not None else LOG_DIR / "privado"
                )
                source = args.banco or root / "clientes_observados.sqlite"
                evidence = snapshot(source, directory / "fontes", segment())
                with readonly(evidence["path"], segment()) as history:
                    conference = summarize(
                        history.records(),
                        segment(),
                        context={"snapshot_sha256": evidence["sha256"]},
                    )
                    evidence["receipts"] = receipts(history)
                    evidence["conference"] = conference
                    evidence["local_counts"] = {
                        table: history.db.execute(
                            f"SELECT count(*) FROM {table} WHERE segment=?",
                            (segment(),),
                        ).fetchone()[0]
                        for table in (
                            "history_orders",
                            "history_windows",
                            "history_issues",
                            "history_revisions",
                        )
                    }
                    evidence["local_counts"]["product_item_lines"] = conference[
                        "recortes"
                    ][-1]["itens_linhas_observadas"]
                    evidence["local_counts"]["valid_buyers"] = conference["recortes"][
                        -1
                    ]["clientes_com_compra_valida"]
                    evidence["schema_user_version"] = history.db.execute(
                        "PRAGMA user_version"
                    ).fetchone()[0]
                    review = adapter.plan(iter_tables(history), evidence=evidence)
                save_private(args.revisao, review)
                if args.resumo_mensal:
                    save_private(args.resumo_mensal, conference)
                print(
                    f"[OK] Preparo sem escrita comercial: {review['changed_rows']} linhas; {review['batches']} lotes; {len(review['capacity']['creations'])} partes novas planejadas."
                )
                for item in review["capacity"]["books"]:
                    print(
                        f"[CAPACIDADE] Arquivo {review['capacity']['books'].index(item) + 1}: grade projetada={item['after']}; células livres no limite físico={item['remaining_hard']}."
                    )
                print(
                    "[INFO] Revisão privada salva. Até 200 linhas por lote; use --max-lotes 1 para piloto."
                )
                return 0
            review = json.loads(Path(args.revisao).read_text(encoding="utf-8"))
            if args.planilhas == "aplicar":
                adapter.apply(None, review, max_batches=args.max_lotes)
                result = adapter.last_result
                print(
                    f"[RESULTADO] {result['status']}: linhas confirmadas nesta execução={result['applied_rows']}; lotes restantes={result['remaining_batches']}."
                )
                if "seconds" in result:
                    print(
                        f"[MÉTRICAS] Escritas de linhas={result['written_rows']}; reconciliadas sem novo POST={result['reconciled_rows']}; tentativas de leitura/escrita={result['read_attempts']}/{result['write_attempts']}; tempo={result['seconds']:.3f}s; backup acumulado={result['backup_bytes']} bytes."
                    )
                if result["remaining_batches"]:
                    print(
                        "[INFO] Piloto pausado; retome com a mesma revisão. O leitor não apresenta esta carga parcial como completa."
                    )
                return (
                    3
                    if result["remaining_batches"] or result["status"] == "divergente"
                    else 0
                )
            if args.planilhas == "rollback":
                result = adapter.rollback(review, args.lote)
                print(
                    f"[OK] Lote {result['batch']} restaurado: {result['rows']} linhas. Partes e legado preservados; retome a revisão para fechar a publicação."
                )
                return 0
            result = adapter.check(review)
            if args.resumo_mensal:
                save_private(args.resumo_mensal, result)
            print(
                f"[CONFERÊNCIA] {result['status']}; lotes confirmados={result['confirmed_batches']}; lotes restantes={result['remaining_batches']}."
            )
            return (
                3
                if result["remaining_batches"] or result["status"] == "divergente"
                else 0
            )
        finally:
            google.close()


def publish(args):
    from gspread.exceptions import APIError
    from requests import RequestException

    from sheets_continuation import ContinuationError

    try:
        return _publish(args)
    except (HistoryError, ContinuationError):
        raise
    except APIError as error:
        code = error.response.status_code
        if code == 429:
            raise HistoryError(
                "SHEETS_QUOTA: aguarde o prazo do serviço e retome a mesma revisão; lotes confirmados preservados."
            ) from None
        if code in (401, 403):
            raise HistoryError(
                "SHEETS_AUTENTICACAO_OU_PERMISSAO: confira o acesso privado aos destinos; preserve a revisão."
            ) from None
        raise HistoryError(
            f"SHEETS_HTTP_{code}: gravação não confirmada; conferir e retomar a mesma revisão."
        ) from None
    except RequestException:
        raise HistoryError(
            "SHEETS_TRANSPORTE: resposta não confirmada; preserve o plano e reconcilie antes de retomar."
        ) from None
