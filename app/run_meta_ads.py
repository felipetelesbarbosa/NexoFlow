"""Entrada nativa Meta Ads: simulação por padrão, sem Codex CLI ou servidor MCP."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path


def _date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Informe a data no formato AAAA-MM-DD."
        ) from exc


def _fixture(path: Path, segment: str) -> dict:
    """Transformação offline; não abre credenciais, clientes HTTP ou planilhas."""
    from meta_ads_model import build_native_tables

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("A simulação exige um objeto JSON.")
    if payload.get("segment", segment) != segment:
        raise ValueError("O segmento da simulação diverge do perfil escolhido.")
    arrays = ("facts", "evidence", "contacts", "orders", "items")
    objects = ("catalogs", "account_meta", "coverage")
    for key in arrays:
        if not isinstance(payload.get(key, []), list) or not all(
            isinstance(row, dict) for row in payload.get(key, [])
        ):
            raise ValueError("Tabela de simulação inválida: " + key)
    for key in objects:
        if not isinstance(payload.get(key, {}), dict):
            raise ValueError("Objeto de simulação inválido: " + key)
    tables = build_native_tables(
        segment=segment,
        updated_at=datetime.now(UTC).isoformat(),
        **{key: payload.get(key, []) for key in arrays},
        **{key: payload.get(key, {}) for key in objects},
    )
    return {
        "mode": "offline_dry_run",
        "segment": segment,
        "tables": {title: len(rows) for title, rows in tables.items()},
    }


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Coleta nativa Meta Ads; padrão: simular sem gravar."
    )
    parser.add_argument(
        "--perfil",
        choices=("FARMA", "PET"),
        default=os.environ.get("NEXOFLOW_PERFIL", "FARMA"),
    )
    parser.add_argument(
        "--start", type=_date, help="Primeiro dia inclusivo, AAAA-MM-DD"
    )
    parser.add_argument("--end", type=_date, help="Último dia inclusivo, AAAA-MM-DD")
    parser.add_argument(
        "--input", type=Path, help="JSON sintético para simulação inteiramente offline"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Consultar e preparar sem gravar (padrão)",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Aplicar somente após validar fontes e schemas",
    )
    parser.add_argument(
        "--confirm-schema",
        action="store_true",
        help="Confirmar o modelo aditivo das abas Meta",
    )
    parser.add_argument(
        "--review",
        type=Path,
        help="Arquivo local de revisão: salvar na simulação e conferir na aplicação",
    )
    args = parser.parse_args(argv)
    if bool(args.start) != bool(args.end):
        parser.error("Informe --start e --end juntos.")
    if args.start and args.end < args.start:
        parser.error("--end não pode ser anterior a --start.")
    if args.apply and not args.confirm_schema:
        parser.error(
            "A aplicação exige --confirm-schema após a validação da simulação."
        )
    if args.apply and (args.review is None or not args.review.is_file()):
        parser.error(
            "A aplicação exige --review apontando para uma revisão já gerada na simulação."
        )
    if args.input and args.apply:
        parser.error("Arquivos de simulação nunca autorizam escrita em produção.")
    # Nenhum módulo operacional é importado antes da escolha de perfil.
    os.environ["NEXOFLOW_PERFIL"] = args.perfil
    try:
        if args.input:
            summary = _fixture(args.input, args.perfil)
        else:
            summary = _real(args)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 3 if summary.get("partial") else 0
    except Exception as exc:
        # Exceções de bibliotecas externas podem carregar URL/token ou dados
        # pessoais: mostrar só a classe, deixando a auditoria sanitizada no core.
        print(
            "[ERRO] Coleta Meta não concluída (" + type(exc).__name__ + "). "
            "Confira a configuração local, permissões e os diagnósticos da integração."
        )
        return 1


def _real(args):
    from types import SimpleNamespace

    from dedup_io import save_private
    from google_sheets import GoogleSheetsStore
    from meta_ads_native import sync_native_meta
    from project_paths import load_private_settings
    from proxy_config import configure_proxy

    configure_proxy()
    settings = load_private_settings()
    values = dict(vars(settings))
    if args.start:
        values["META_ADS_START_DATE"] = args.start
        values["META_ADS_END_DATE"] = args.end
        profiles = values.get("PERFIS")
        if isinstance(profiles, dict) and isinstance(profiles.get(args.perfil), dict):
            values["PERFIS"] = {
                **profiles,
                args.perfil: {
                    **profiles[args.perfil],
                    "META_ADS_START_DATE": args.start,
                    "META_ADS_END_DATE": args.end,
                },
            }
    settings = SimpleNamespace(**values)
    expected = None
    if args.apply:
        review = json.loads(args.review.read_text(encoding="utf-8-sig"))
        if (
            not isinstance(review, dict)
            or review.get("segment") != args.perfil
            or review.get("start") != args.start
            or review.get("end") != args.end
            or not isinstance(review.get("schema_manifest"), dict)
        ):
            raise ValueError(
                "Revisão incompatível com o perfil ou intervalo solicitado."
            )
        expected = review["schema_manifest"]
    dashboard = str(getattr(settings, "GOOGLE_SPREADSHEET_ID", "") or "").strip()
    from ds_backend.client import enabled as postgres_enabled

    if not postgres_enabled(settings) and not dashboard:
        raise ValueError("Dashboard do perfil não configurado.")
    # Ao contrário do construtor operacional, esta abertura não cria ou migra
    # nenhuma aba, mesmo durante simulações com fontes reais.
    from ds_backend.runtime import complete, open_store

    store = open_store(
        settings, GoogleSheetsStore, purpose="meta", readonly=not args.apply
    )
    try:
        inputs = store.native_meta_inputs()
        result = sync_native_meta(
            store,
            settings,
            args.perfil,
            contacts=inputs["contacts"],
            orders=inputs["orders"],
            items=inputs["items"],
            apply=args.apply,
            expected_manifest=expected,
            schema_approved=args.confirm_schema,
        )
        if (
            not args.apply
            and args.review
            and isinstance(result.get("schema_manifest"), dict)
        ):
            save_private(
                args.review,
                {
                    "segment": args.perfil,
                    "start": args.start,
                    "end": args.end,
                    "schema_manifest": result["schema_manifest"],
                },
            )
        if args.apply:
            complete(store, success=not result.get("partial", False))
        return result
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(run())
