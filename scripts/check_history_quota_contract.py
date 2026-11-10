"""Impede distribuir o ajuste de quota com contrato de revisão incompatível."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

# Assinatura dos bytes do ZIP público Windows 1.5.29, commit c3da63d.
# Código-fonte LF equivalente não basta para um recibo ligado aos bytes CRLF.
PACKAGED_SIGNATURE = "0c7132fa1f066f9f24556258667894f67c38a68edc993e841c4e5df57236448f"
MODULES = (
    "history_publication.py",
    "history_reconciliation.py",
    "history_sheets_transport.py",
    "history_capacity.py",
    "history_conference.py",
    "history_exclusions.py",
    "order_history_sheets.py",
    "sheets_partitions.py",
    "sheets_provisioning.py",
    "google_sheets.py",
)


def verify(path, prefix):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        expected = [prefix + "app/" + name for name in MODULES]
        expected += [
            prefix + "app/history_sheets_quota.py",
            prefix + "app/history_publish_cli.py",
            prefix + "app/history_sheets_bulk.py",
            prefix + "app/history_batch_progress.py",
            prefix + "app/analytics_history_sync.py",
            prefix + "app/duration_display.py",
        ]
        if any(names.count(name) != 1 for name in expected):
            raise ValueError("Pacote sem módulos únicos do contrato de histórico.")
        hashes = {
            name: hashlib.sha256(archive.read(prefix + "app/" + name)).hexdigest()
            for name in MODULES
        }
        signature = hashlib.sha256(
            json.dumps(hashes, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        if signature != PACKAGED_SIGNATURE:
            raise ValueError(
                "Contrato da revisão mudou; não publicar ajuste de quota sobre carga em andamento."
            )
        if b"from history_sheets_quota import google_store_type" not in archive.read(
            prefix + "app/history_publish_cli.py"
        ):
            raise ValueError("Entrada do histórico não ativa o controle de quota.")
        if (
            b"from history_sheets_bulk import BulkHistorySheets as HistorySheets"
            not in archive.read(prefix + "app/history_publish_cli.py")
        ):
            raise ValueError("Entrada do histórico não ativa o transporte agrupado.")
        return signature


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets-dir", required=True, type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    if not args.version or any(c not in "0123456789." for c in args.version):
        parser.error("Versão inválida.")
    try:
        a = verify(args.assets_dir / f"NexoFlow-{args.version}.zip", "NexoFlow/")
        b = verify(
            args.assets_dir / f"NexoFlow-Setup-{args.version}.zip",
            "NexoFlow Setup/payload/",
        )
        if a != b:
            raise ValueError("Contratos dos dois pacotes divergem.")
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        print(f"[ERRO] Contrato de histórico não aprovado: {type(error).__name__}.")
        return 1
    print("[OK] Dois pacotes preservam o contrato 1.5.29 e ativam o ritmo HTTP.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
