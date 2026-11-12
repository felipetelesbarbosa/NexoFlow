"""Conferência privada do corte, com as regras financeiras já distribuídas."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import closing
from decimal import Decimal

from ds_backend.contract import StorageError, digest
from ds_backend.migration import Export


def audit(path):
    from history_conference import from_published, summarize

    with closing(Export(path)) as source:
        manifest = source.manifest()
        with tempfile.TemporaryDirectory(prefix="nexoflow-auditoria-pg-") as directory:
            with closing(sqlite3.connect(directory + "/conferencia.sqlite")) as db:
                # A cópia recebe os índices auxiliares; a evidência permanece query_only.
                source.db.backup(db)
                db.execute("ALTER TABLE linhas RENAME TO observed")
                report = summarize(from_published(db), manifest["segment"])
                revenue = next(
                    r["faturamento_centavos"]
                    for r in report["recortes"]
                    if r["recorte"] == "TOTAL"
                )
                ltv = Decimal(0)
                for (raw,) in db.execute(
                    "SELECT v FROM observed WHERE t='BI_LTV_Clientes'"
                ):
                    row = json.loads(raw)
                    if row["vigente"] == "Sim":
                        ltv += Decimal(row["ltv_observado"]) * 100
                if ltv != revenue:
                    raise StorageError("DS_CORTE_LTV_DIVERGENTE")
                return dict(
                    manifest_hash=digest(manifest),
                    tables=manifest["tables"],
                    history=report,
                    ltv_centavos=int(ltv),
                    financial_equal=True,
                )
