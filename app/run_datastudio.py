"""CLI do contrato definitivo. Nunca coleta Weni/FarmaLíder ou aplica Sheets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ds_backend.client import Client
from ds_backend.contract import StorageError
from ds_backend.migration import apply, prepare
from project_paths import load_private_settings


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operacao",
        choices=(
            "manifesto",
            "conferir",
            "recortar-piloto",
            "capacidade",
            "configurar",
            "extrair-exclusoes",
            "exportar-sheets",
            "auditar-exportacao",
            "diagnosticar",
            "preparar",
            "simular",
            "aplicar",
            "retomar",
            "finalizar-selada",
            "status",
            "reverter",
            "abortar",
            "importar-estado",
        ),
    )
    parser.add_argument("--ambiente", choices=("homologacao", "producao"))
    parser.add_argument("--credencial", type=Path)
    parser.add_argument("--backend", choices=("sheets", "postgres"), default="sheets")
    parser.add_argument("--ativar", action="store_true")
    parser.add_argument("--exportacao", type=Path)
    parser.add_argument("--origem-revisao")
    parser.add_argument("--revisao-publicada", type=Path)
    parser.add_argument("--banco", type=Path)
    parser.add_argument("--pedido")
    parser.add_argument("--exclusoes", type=Path)
    parser.add_argument("--saida", type=Path)
    parser.add_argument("--revisao", type=Path)
    parser.add_argument("--max-lotes", type=int)
    parser.add_argument("--id-revisao")
    parser.add_argument("--versao", type=int)
    parser.add_argument(
        "--estado",
        choices=("weni_update", "recompra", "historico_cursor", "carga_fracionada"),
    )
    parser.add_argument("--arquivo", type=Path)
    args = parser.parse_args(argv)
    from proxy_config import configure_proxy

    configure_proxy()
    client = None
    try:
        if args.operacao == "configurar":
            if args.ambiente is None or args.credencial is None:
                parser.error(
                    "Informe --ambiente e --credencial privada; --backend postgres requer --ativar."
                )
            from ds_backend.configuration import configure
            from project_paths import ROOT
            from runtime_profile import segment

            result = configure(
                ROOT / "secrets_config.py",
                segment(),
                args.ambiente,
                args.credencial,
                backend=args.backend,
                activate=args.ativar,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        settings = load_private_settings()
        if args.operacao == "recortar-piloto":
            if args.exportacao is None or args.saida is None or not args.pedido:
                parser.error(
                    "Informe --exportacao, --saida privada inédita e --pedido oficial."
                )
            from ds_backend.migration import pilot

            result = pilot(args.exportacao, args.saida, args.pedido)
            print(
                json.dumps(
                    dict(
                        state="RECORTADA",
                        rows=sum(s["count"] for s in result["tables"].values()),
                        scope="PILOTO_PEDIDO",
                    )
                )
            )
            return 0
        if args.operacao == "extrair-exclusoes":
            if any(
                x is None
                for x in (
                    args.revisao_publicada,
                    args.banco,
                    args.origem_revisao,
                    args.saida,
                )
            ):
                parser.error(
                    "Informe --revisao-publicada, --banco, --origem-revisao e --saida privados."
                )
            from ds_backend.exclusions import extract
            from runtime_profile import segment

            result = extract(
                args.revisao_publicada,
                args.banco,
                segment(),
                args.origem_revisao,
                args.saida,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.operacao in ("exportar-sheets", "auditar-exportacao", "manifesto"):
            if args.saida is None:
                parser.error("Informe --saida privada para os totais.")
            if args.exportacao is None:
                parser.error("Informe --exportacao privada.")
            if args.operacao == "exportar-sheets":
                if not args.origem_revisao:
                    parser.error("Informe --origem-revisao READY conferida.")
                from ds_backend.sheets_export import export_sheets
                from google_sheets import GoogleSheetsStore
                from runtime_profile import segment

                if args.exclusoes is None:
                    parser.error("Informe --exclusoes geradas da revisão publicada.")
                exclusions = json.loads(args.exclusoes.read_text(encoding="utf-8-sig"))
                google = GoogleSheetsStore.open_native_readonly(
                    settings.GOOGLE_SPREADSHEET_ID
                )
                try:
                    result = export_sheets(
                        google,
                        args.exportacao,
                        segment(),
                        args.origem_revisao,
                        exclusions,
                    )
                finally:
                    google.close()
            elif args.operacao == "manifesto":
                from contextlib import closing

                from ds_backend.migration import Export

                with closing(Export(args.exportacao)) as export:
                    result = export.manifest()
            else:
                from ds_backend.audit import audit

                result = audit(args.exportacao)
            if args.saida is None:
                parser.error("Informe --saida privada para os totais.")
            from ds_backend.migration import private_json

            private_json(args.saida, result)
            print(
                "[OK] Evidência privada gravada; nenhum destino comercial foi atualizado."
            )
            return 0
        client = Client.from_settings(settings)
        if args.operacao == "diagnosticar":
            result = client.info
        elif args.operacao == "conferir":
            if args.saida is None:
                parser.error("Informe --saida privada.")
            result = client.call("/v1/conferencia")
            from ds_backend.migration import private_json

            private_json(args.saida, result)
            print("[OK] Conferência PostgreSQL privada gravada; nenhum fato publicado.")
            return 0
        elif args.operacao == "capacidade":
            result = client.call("/v1/capacidade")
            if args.exportacao:
                from contextlib import closing

                from ds_backend.migration import Export

                with closing(Export(args.exportacao)) as source:
                    manifest = source.manifest()
                    result["planned_rows"] = sum(
                        t["count"] for t in manifest["tables"].values()
                    )
                    result["export_bytes"] = args.exportacao.stat().st_size
                    result["json_bytes"] = source.db.execute(
                        "SELECT coalesce(sum(length(CAST(v AS BLOB))),0) FROM linhas"
                    ).fetchone()[0]
        elif args.operacao == "preparar":
            if args.exportacao is None or args.revisao is None:
                parser.error("Informe --exportacao e --revisao novas.")
            plan = prepare(args.exportacao, args.revisao, client)
            result = dict(state=plan["state"], revision=plan["revision"])
        elif args.operacao in ("simular", "aplicar", "retomar"):
            if args.revisao is None:
                parser.error("Informe --revisao.")
            result = apply(
                args.revisao,
                client,
                max_batches=args.max_lotes,
                simulate=args.operacao == "simular",
            )
        elif args.operacao == "finalizar-selada":
            if not args.id_revisao:
                parser.error("Informe --id-revisao.")
            status = client.call("/v1/revisoes/" + args.id_revisao)
            manifest = status.get("sealed_manifest")
            if manifest is None:
                raise StorageError(
                    "DS_REVISAO_NAO_SELADA; não é seguro concluir uma coleta sem comprovante"
                )
            result = client.call(
                "/v1/confirmar",
                dict(revision=args.id_revisao, manifest=manifest, complete=True),
            )
        elif args.operacao == "status":
            if not args.id_revisao:
                parser.error("Informe --id-revisao.")
            result = client.call("/v1/revisoes/" + args.id_revisao)
        elif args.operacao == "importar-estado":
            if not args.estado or args.arquivo is None:
                parser.error("Informe --estado e --arquivo privado.")
            from uuid import uuid4

            result = client.call(
                "/v1/estados/gravar",
                dict(
                    name=args.estado,
                    expected_version=0,
                    document=json.loads(args.arquivo.read_text(encoding="utf-8-sig")),
                    receipt_id=str(uuid4()),
                ),
            )
        else:
            if not args.id_revisao:
                parser.error("Informe --id-revisao.")
            if args.operacao == "reverter":
                if args.versao is None:
                    parser.error("Informe --versao ativa conferida.")
                result = client.call(
                    "/v1/reverter",
                    dict(revision=args.id_revisao, expected_version=args.versao),
                )
            else:
                result = client.call("/v1/abortar", dict(revision=args.id_revisao))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except StorageError as error:
        print("[PENDÊNCIA] " + str(error))
        return 3
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(run())
