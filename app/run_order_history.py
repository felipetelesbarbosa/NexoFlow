"""Histórico sob demanda; lê APIs, grava estado privado, não aplica Weni."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from order_history import HistoryError, HistoryQuery
from pedido_utils import BUSINESS_TIMEZONE


def parser():
    result = argparse.ArgumentParser(
        description="Histórico de pedidos e LTV observado — segmento selecionado no Terminal."
    )
    result.add_argument(
        "--inicio", help="Dia/data-hora inicial enviada sem alteração à API"
    )
    result.add_argument(
        "--fim", help="Dia/data-hora final; inclusividade da API ainda não homologada"
    )
    result.add_argument(
        "--limite",
        type=int,
        default=500,
        help="Pedidos por página (padrão 500; 1.000 também permitido)",
    )
    result.add_argument(
        "--max-paginas",
        type=int,
        help="1: uma página; omitido: todas, até 10.000 por execução",
    )
    result.add_argument(
        "--modo",
        choices=("historica", "incremental", "reconciliacao"),
        default="historica",
    )
    result.add_argument(
        "--reiniciar-janela",
        action="store_true",
        help="Página 1, preservando pedidos já recebidos",
    )
    result.add_argument(
        "--somente-resumo", action="store_true", help="Estado local sem conexões"
    )
    result.add_argument(
        "--planilhas",
        choices=("preparar", "aplicar"),
        help="Revisão separada, sem nova coleta",
    )
    result.add_argument(
        "--revisao", type=Path, help="Arquivo privado de revisão de planilhas"
    )
    return result


def interactive():
    print("\nHistórico — sem mensagens ou alterações na Weni.")
    start = input("Data inicial (AAAA-MM-DD): ").strip()
    end = input("Data final (ENTER = mesmo dia): ").strip() or start
    limit = input("Pedidos por página (ENTER = 500): ").strip() or "500"
    maximum = input("Máximo de páginas (ENTER = todas; 1 = uma): ").strip()
    args = ["--inicio", start, "--fim", end, "--limite", limit]
    if maximum:
        args += ["--max-paginas", maximum]
    return run(args)


def run(argv=None):
    args = parser().parse_args(argv)
    from config import LOG_DIR
    from customer_observations import connect
    from order_history_store import HistoryStore, collect_windows
    from recompra_lock import state_lock
    from runtime_profile import segment

    now = datetime.now(BUSINESS_TIMEZONE)
    if args.modo == "incremental":
        if args.inicio or args.fim:
            raise HistoryError("INCREMENTAL_USA_HOJE_MENOS_20_DIAS")
        args.inicio = (now.date() - timedelta(days=20)).isoformat()
        args.fim = now.date().isoformat()
    query = (
        None
        if args.somente_resumo or args.planilhas
        else HistoryQuery(segment(), args.inicio, args.fim, args.limite)
    )
    with state_lock(LOG_DIR / "historico_pedidos_state.json"), connect() as db:
        history = HistoryStore(db, segment())
        if args.somente_resumo:
            summary = history.totals()
        elif args.planilhas:
            if args.revisao is None:
                raise HistoryError("REVISAO_OBRIGATORIA")
            from order_history_sheets import HistorySheets, google_store_type, tables
            from project_paths import load_private_settings
            from proxy_config import configure_proxy

            configure_proxy()
            settings = load_private_settings()
            google = google_store_type().open_native_readonly(
                settings.GOOGLE_SPREADSHEET_ID
            )
            try:
                adapter = HistorySheets(
                    google, segment(), LOG_DIR / "privado" / "historico_backups"
                )
                data = tables(history)
                if args.planilhas == "preparar":
                    plan = adapter.plan(data)
                    args.revisao.parent.mkdir(parents=True, exist_ok=True)
                    args.revisao.write_text(
                        json.dumps(plan, ensure_ascii=False), encoding="utf-8"
                    )
                    args.revisao.chmod(0o600)
                    summary = {
                        "linhas_preparadas": sum(
                            len(v) for v in plan["changes"].values()
                        ),
                        "aplicadas": 0,
                    }
                else:
                    summary = {
                        "linhas_aplicadas": adapter.apply(
                            data, json.loads(args.revisao.read_text(encoding="utf-8"))
                        )
                    }
            finally:
                google.close()
        else:
            from farmalider_customers import CustomerDirectory
            from nexo_cli import _make_farmalider_client, _make_weni_client

            history.seed_observations(now.isoformat())
            farm = _make_farmalider_client()
            try:
                assert query is not None
                summary = collect_windows(
                    farm,
                    history,
                    query,
                    now=now.isoformat(),
                    max_pages=args.max_paginas,
                    restart=args.reiniciar_janela,
                    mode=args.modo,
                    progress=lambda s: print(
                        f"[Histórico] Recebidos={s['received']}/{s['total']} | próxima página={s['next_page']} | extração={s['status']}"
                    ),
                )
                directory = CustomerDirectory(
                    farm.get_clientes_segmento(segment()), segment=segment()
                )
                weni = _make_weni_client()
                try:
                    summary.update(history.link(directory, weni.list_contacts()))
                finally:
                    weni.close()
            finally:
                farm.close()
        print("\nResumo do histórico — " + segment())
        for key, value in summary.items():
            print(f"  {key}: {value}")
        print(
            "LTV observado; calendário da API ainda requer homologação. Nenhum disparo de Recompra."
        )
        return (
            3
            if summary.get("status") == "incompleta" or summary.get("pendencias")
            else 0
        )


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(
            "[PENDENTE] Histórico preservado. Diagnóstico: "
            + (str(exc) if isinstance(exc, HistoryError) else type(exc).__name__)
        )
        raise SystemExit(1) from None
