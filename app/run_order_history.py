"""Histórico sob demanda; lê APIs, grava estado privado, não aplica Weni."""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from order_history import HistoryError, HistoryQuery
from pedido_utils import BUSINESS_TIMEZONE


def parser():
    result = argparse.ArgumentParser(
        description="Histórico de pedidos e LTV observado — segmento selecionado no Terminal."
    )
    result.add_argument(
        "--auditar-banco",
        type=Path,
        help="Cópia SQLite consistente, somente leitura; sem rede",
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
        help="Pedidos por página (de 1 a 500; padrão 500)",
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
        choices=("preparar", "capacidade", "aplicar", "conferir", "rollback"),
        help="Revisão separada, sem nova coleta",
    )
    result.add_argument(
        "--banco",
        type=Path,
        help="SQLite local do perfil; preparo cria cópia consistente sem nova coleta",
    )
    result.add_argument(
        "--max-lotes",
        type=int,
        help="Pausar após N lotes (até 200 linhas por lote), preservando a revisão",
    )
    result.add_argument(
        "--lote", type=int, help="Lote específico para rollback protegido"
    )
    result.add_argument(
        "--resumo-mensal",
        type=Path,
        help="Saída privada de conferência agregada por mês e período",
    )
    result.add_argument(
        "--revisao", type=Path, help="Arquivo privado de revisão de planilhas"
    )
    result.add_argument(
        "--excluir-pedidos",
        nargs="+",
        help="IDs autorizados: cria cópia privada para publicação, sem alterar a fonte",
    )
    result.add_argument(
        "--motivo-exclusao", help="Motivo registrado na auditoria privada"
    )
    result.add_argument(
        "--responsavel-exclusao", help="Responsável que autorizou a exclusão"
    )
    result.add_argument(
        "--sha256-banco", help="SHA-256 do backup consistente usado nas exclusões"
    )
    return result


def interactive():
    print("\nHistórico — digite 0, sair ou exit em qualquer campo para voltar ao menu.")

    def read(prompt, default=None, numeric=False, maximum=2147483647):
        while True:
            value = input(prompt).strip()
            if value.lower() in {"0", "sair", "exit"}:
                raise InterruptedError
            if not value and default is not None:
                return default
            if numeric:
                if value.isdecimal() and 1 <= int(value) <= maximum:
                    return value
                print(f"Informe um inteiro entre 1 e {maximum}, ou 0 para cancelar.")
            else:
                return value

    try:
        while True:
            start = read("Data inicial (AAAA-MM-DD): ")
            end = read("Data final (ENTER = mesmo dia): ", start)
            try:
                HistoryQuery("FARMA", start, end)
            except HistoryError:
                print(
                    "Datas/período inválidos. Informe AAAA-MM-DD, com início até o fim."
                )
                continue
            break
        limit = read("Pedidos por página (1 a 500; ENTER = 500): ", "500", True, 500)
        maximum = read("Máximo de páginas (ENTER = todas): ", "", True)
        args = ["--inicio", start, "--fim", end, "--limite", limit]
        if maximum:
            args += ["--max-paginas", maximum]
        code = run(args)
        print(
            f"Código da operação: {code}."
            + (
                " Histórico preservado; há pendências para conferir."
                if code == 3
                else ""
            )
        )
        return code
    except (InterruptedError, EOFError, KeyboardInterrupt):
        print("\nImportação cancelada. Retornando ao menu.")
        return 130


def print_progress(state):
    pending = state.get(
        "pending_page", None if state["status"] == "extraida" else state["next_page"]
    )
    page_label = (
        "sem pedidos nesta janela"
        if state["status"] == "extraida" and state["total"] == 0
        else f"página {state.get('current_page', state['next_page'] - 1)}/{state['pages']}"
    )
    print(
        f"[Histórico] Janela {state.get('window', 1)}/{state.get('windows', 1)} | "
        f"{page_label} | "
        f"recebidos={state['received']}/{state['total']} | "
        + (
            (
                "janela concluída"
                + (
                    f"; próxima janela a conferir={state['window'] + 1}"
                    if state.get("window", 1) < state.get("windows", 1)
                    else "; coleta das janelas concluída"
                )
            )
            if pending is None
            else f"próxima página pendente={pending}"
        )
    )


def print_summary(summary):
    def money(cents):
        from decimal import Decimal

        return "R$ " + f"{Decimal(cents) / 100:,.2f}".replace(",", "_").replace(
            ".", ","
        ).replace("_", ".")

    labels = {
        "pedidos_validos": "Compras válidas",
        "avisos_frete": "Avisos de frete (não excluem a compra)",
        "clientes_oficiais": "Clientes com compras válidas",
        "vinculados": "Pedidos com vínculo Weni (acumulado)",
        "sem_vinculo": "Pedidos sem vínculo Weni (acumulado)",
        "faturamento_centavos": "Faturamento observado",
    }
    for name, data in (
        ("EXECUÇÃO ATUAL", summary.get("execution")),
        ("PERÍODO SOLICITADO", summary.get("audit", {}).get("periodo")),
        ("HISTÓRICO ACUMULADO", summary.get("audit", {}).get("acumulado")),
    ):
        if data is None:
            continue
        print("\n" + name)
        for key, value in data.items():
            print(
                f"  {labels.get(key, key.replace('_', ' ').capitalize())}: {money(value) if key == 'faturamento_centavos' else value}"
            )
    if not summary.get("audit"):
        for key, value in summary.items():
            print(
                f"  {labels.get(key, key)}: {money(value) if key == 'faturamento_centavos' else value}"
            )
    print(
        f"\nJanelas: {summary.get('windows', '—')}; incompletas: {summary.get('incomplete_windows', '—')}"
    )
    audit = summary.get("audit", {})
    if summary.get("rejected_legacy_windows"):
        print(
            f"Tentativas antigas com limite inválido: {summary['rejected_legacy_windows']}; "
            "preservadas no diagnóstico, sem retomada automática."
        )
    if audit.get("origens"):
        print("ORIGENS DOS FATOS ARMAZENADOS (não comprovam a execução de entrada)")
        for source, count in sorted(audit["origens"].items()):
            print(f"  {source}: {count} pedido(s)")
    if audit.get("janelas_persistidas"):
        print("Janelas persistidas (podem incluir execuções anteriores):")
        for window in audit["janelas_persistidas"]:
            print("  " + str(window))
        print(
            f"  IDs únicos: {audit['ids_unicos_janelas_persistidas']}; repetições: {audit['repeticoes_janelas_persistidas']}"
        )
    print("PENDÊNCIAS LOCAIS (não são ausência de compra)")
    issues = summary.get("audit", {}).get("pendencias", [])
    print(f"  Quantidade: {sum(i['quantidade'] for i in issues)}")
    for issue in issues:
        print(
            f"  {issue['motivo']}: {issue['quantidade']} | origem do fato={issue['origem']} | {issue['efeito']} | {issue['acao']}"
        )
    print(
        "Cobertura temporal: LIMITES_DA_API_NAO_HOMOLOGADOS; páginas completas não comprovam todo o período civil."
    )


def run(argv=None):
    summary: dict[str, Any] = {}
    args = parser().parse_args(argv)
    if args.excluir_pedidos is not None:
        if any(
            (
                args.planilhas,
                args.auditar_banco,
                args.somente_resumo,
                args.inicio,
                args.fim,
                args.max_paginas is not None,
                args.reiniciar_janela,
                args.revisao,
                args.lote is not None,
                args.max_lotes is not None,
                args.modo != "historica",
            )
        ):
            raise HistoryError("EXCLUSAO_NAO_COMBINA_COLETA_OU_PUBLICACAO")
        from history_exclusions import exclude

        return exclude(args)
    if any((args.motivo_exclusao, args.responsavel_exclusao, args.sha256_banco)):
        raise HistoryError("OPCOES_EXCLUSAO_EXIGEM_EXCLUIR_PEDIDOS")
    if args.max_paginas is not None and args.max_paginas < 1:
        raise HistoryError("MAXIMO_PAGINAS_INVALIDO")
    if args.max_lotes is not None and (
        args.planilhas != "aplicar" or args.max_lotes < 1
    ):
        raise HistoryError("MAX_LOTES_REQUER_APLICACAO_E_VALOR_POSITIVO")
    if args.planilhas:
        from history_publish_cli import publish

        return publish(args)
    if args.auditar_banco:
        import sqlite3

        from order_history_store import HistoryStore, history_audit
        from runtime_profile import segment

        query = (
            HistoryQuery(segment(), args.inicio, args.fim, args.limite)
            if args.inicio or args.fim
            else None
        )
        with closing(
            sqlite3.connect(
                args.auditar_banco.resolve().as_uri() + "?mode=ro", uri=True
            )
        ) as db:
            db.execute("PRAGMA query_only=ON")
            history = object.__new__(HistoryStore)
            history.db, history.segment = db, segment()
            if args.resumo_mensal:
                from dedup_io import save_private
                from history_conference import receipts, summarize

                report = summarize(history.records(), segment())
                from history_exclusions import aggregate_exclusions, exclusion_audit

                report["exclusoes_publicacao"] = aggregate_exclusions(
                    exclusion_audit(db, segment())
                )
                report["recebimentos"] = receipts(history)
                save_private(args.resumo_mensal, report)
            audit = history_audit(history, query)
            print_summary(dict(audit=audit))
            return 3 if audit["pendencias"] else 0
    from config import LOG_DIR
    from customer_observations import connect
    from order_history_store import HistoryStore, collect_windows, history_audit
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
            summary = dict(history.totals(), audit=history_audit(history))
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
                    progress=print_progress,
                )
                linking_started = perf_counter()
                directory = CustomerDirectory(
                    farm.get_clientes_segmento(segment()), segment=segment()
                )
                weni = _make_weni_client()
                try:
                    summary.update(history.link(directory, weni.list_contacts()))
                    summary["execution"]["clientes_cadastrais_carregados"] = len(
                        directory.by_id
                    )
                    summary["execution"]["cadastro_e_vinculo_segundos"] = round(
                        perf_counter() - linking_started, 3
                    )
                    summary["execution"]["requisicoes_farma"] = farm.endpoint_metrics()
                    summary["audit"] = history_audit(history, query)
                finally:
                    weni.close()
            finally:
                farm.close()
        print("\nResumo do histórico — " + segment())
        print_summary(summary)
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
    except (KeyboardInterrupt, EOFError):
        print("\nOperação interrompida; páginas confirmadas preservadas.")
        raise SystemExit(130) from None
    except Exception as exc:
        print(
            "[PENDENTE] Histórico preservado. Diagnóstico: "
            + (str(exc) if isinstance(exc, HistoryError) else type(exc).__name__)
        )
        raise SystemExit(1) from None
