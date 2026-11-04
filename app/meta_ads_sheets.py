"""Persistência nativa Meta isolada: fontes autorizadas, revisão e upsert sem clear."""

from __future__ import annotations

import logging
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from dedup_io import digest, save_private
from runtime_profile import scoped_path
from runtime_profile import segment as active_segment

PRIVATE_ROOT: Path | None = None
NUMERIC_COLUMNS = {
    "investimento_original",
    "investimento_atribuivel",
    "impressoes",
    "cliques",
    "alcance",
    "frequencia",
    "ctr_pct",
    "cpc",
    "cpm",
    "eventos_ctwa",
    "contatos",
    "conversas",
    "compradores_confirmados",
    "pedidos_confirmados",
    "receita_confirmada",
    "compras_atribuidas_meta",
    "cpa_confirmado",
    "roas_confirmado",
    "cac",
    "cliques_link",
    "conversas_iniciadas_meta",
    "valor_compras_atribuido_meta",
    "custo_conversa_weni_confirmada",
    "custo_conversa_meta",
    "taxa_conversao_contatos_pct",
    "taxa_conversao_cliques_meta_pct",
    "quantidade_itens",
}
TEXT_ID_COLUMNS = {
    "conta_id",
    "anuncio_id",
    "campanha_id",
    "conjunto_id",
    "evento_id",
    "pedido_id",
    "contact_uuid",
}
REFERENCE_LABELS = {"COMPARTILHADO", "NAO_CLASSIFICADO"}


class NativeMetaSchemaError(ValueError):
    """Aba, destino ou revisão incompatível; não autoriza migração ou exclusão."""


def _schemas():
    from meta_ads_model import SCHEMAS

    return SCHEMAS


def _number(value):
    if value in ("", None):
        return ""
    if isinstance(value, bool):
        raise NativeMetaSchemaError("Métrica Meta não pode ser um booleano.")
    try:
        number = Decimal(str(value))
    except (ValueError, InvalidOperation) as exc:
        raise NativeMetaSchemaError("Métrica Meta não numérica.") from exc
    if not number.is_finite() or number < 0:
        raise NativeMetaSchemaError("Métrica Meta negativa ou não finita.")
    return int(number) if number == number.to_integral_value() else float(number)


def _same_record(before, after, headers):
    for field in headers:
        if field == "atualizado_em":
            continue
        left, right = before.get(field, ""), after.get(field, "")
        if field in NUMERIC_COLUMNS:
            if _number(left) != _number(right):
                return False
        elif str(left or "") != str(right or ""):
            return False
    return True


class NativeMetaSheets:
    """Store protocol: native_meta_context/read/upsert_chunk; construtor sem I/O."""

    def __init__(self, store, segment, *, account_ids=()):
        if segment not in {"FARMA", "PET"} or active_segment() != segment:
            raise NativeMetaSchemaError("Perfil Meta incompatível com o processo.")
        self.store = store
        self.segment = segment
        self.account_ids = tuple(
            sorted({str(x).removeprefix("act_") for x in account_ids})
        )
        if any(not x.isascii() or not x.isdigit() for x in self.account_ids):
            raise NativeMetaSchemaError("Conta Meta autorizada inválida.")
        self.read_errors = {}

    def _context(self):
        context = self.store.native_meta_context()
        if active_segment() != self.segment or context.get("segment") != self.segment:
            raise NativeMetaSchemaError("A fonte Meta pertence a outro perfil.")
        ids = [context.get(key) for key in ("dashboard", "operations", "history")]
        if not all(isinstance(x, str) and x for x in ids) or len(set(ids)) != 3:
            raise NativeMetaSchemaError("Meta exige os três destinos Google distintos.")
        return context

    def _record(self, title, value):
        headers = _schemas()[title]
        if not isinstance(value, dict) or set(value) - set(headers):
            raise NativeMetaSchemaError("Registro Meta fora do schema autorizado.")
        row = {name: value.get(name, "") for name in headers}
        if not isinstance(row["chave"], str) or not row["chave"].strip():
            raise NativeMetaSchemaError(
                "Registro Meta sem chave textual determinística."
            )
        if row["segmento"] not in {self.segment, *REFERENCE_LABELS}:
            raise NativeMetaSchemaError("Registro Meta pertence a outro segmento.")
        if (
            row["segmento"] in REFERENCE_LABELS
            and row.get("classificacao") != row["segmento"]
        ):
            raise NativeMetaSchemaError(
                "Classificação Meta inconsistente com o segmento de referência."
            )
        if row.get("classificacao") in REFERENCE_LABELS and row.get(
            "investimento_atribuivel"
        ) not in ("", None):
            raise NativeMetaSchemaError(
                "Custo compartilhado não pode ser atribuído a um segmento."
            )
        for name in headers:
            value = row[name]
            if name in NUMERIC_COLUMNS:
                row[name] = _number(value)
            else:
                if isinstance(value, (dict, list, tuple)):
                    raise NativeMetaSchemaError("Célula Meta deve ser escalar.")
                if (
                    name in TEXT_ID_COLUMNS
                    and value not in ("", None)
                    and not isinstance(value, str)
                ):
                    raise NativeMetaSchemaError(
                        "IDs Meta precisam permanecer texto, sem conversão numérica."
                    )
                row[name] = "" if value is None else str(value)
        account = row["conta_id"]
        if not account or not account.isascii() or not account.isdigit():
            raise NativeMetaSchemaError("Registro Meta sem conta válida.")
        if self.account_ids and account not in self.account_ids:
            raise NativeMetaSchemaError("Registro Meta de conta não autorizada.")
        return row

    def _read(self, title, context):
        headers = _schemas()[title]
        snapshot = self.store.native_meta_read(title, headers)
        expected = context["dashboard" if title.startswith("BI_") else "operations"]
        if snapshot.get("book_id") != expected:
            raise NativeMetaSchemaError("Aba Meta no arquivo Google errado.")
        values = snapshot.get("values", [])
        records = {}
        if snapshot.get("exists"):
            if not values or values[0] != headers:
                raise NativeMetaSchemaError(
                    "Cabeçalho Meta divergente; migração automática proibida."
                )
            for cells in values[1:]:
                if not any(v not in ("", None) for v in cells):
                    continue
                if any(v not in ("", None) for v in cells[len(headers) :]):
                    raise NativeMetaSchemaError(
                        "Dados Meta além do cabeçalho autorizado."
                    )
                padded = [*cells, *[""] * (len(headers) - len(cells))]
                row = self._record(title, dict(zip(headers, padded, strict=False)))
                if row["chave"] in records:
                    raise NativeMetaSchemaError(
                        "Chave Meta duplicada na fonte; nenhuma consolidação destrutiva."
                    )
                records[row["chave"]] = row
        return snapshot, records

    def load_tables(self):
        context = self._context()
        result, self.read_errors = {}, {}
        for title in _schemas():
            try:
                _, records = self._read(title, context)
                result[title] = list(records.values())
            except Exception as exc:
                self.read_errors[title] = type(exc).__name__
                result[title] = []
                logging.warning(
                    "Meta nativa: leitura de %s pendente (%s); dados existentes preservados.",
                    title,
                    type(exc).__name__,
                )
        return result

    def schema_manifest(self):
        context = self._context()
        tables = {}
        for title, headers in _schemas().items():
            snapshot = self.store.native_meta_read(title, headers)
            expected = context["dashboard" if title.startswith("BI_") else "operations"]
            if snapshot.get("book_id") != expected:
                raise NativeMetaSchemaError("Manifesto Meta com destino divergente.")
            values = snapshot.get("values", [])
            tables[title] = {
                "book_id": snapshot["book_id"],
                "worksheet_id": snapshot.get("worksheet_id"),
                "exists": bool(snapshot.get("exists")),
                "headers": values[0] if values else [],
                "data_sha256": digest(values),
                "row_count": max(0, len(values) - 1),
            }
        manifest = {
            "schema": 1,
            "segment": self.segment,
            "sources": context,
            "account_ids": list(self.account_ids),
            "schema_sha256": digest(_schemas()),
            "tables": tables,
        }
        manifest["sha256"] = digest(manifest)
        return manifest

    def _prepared(self, tables, context):
        if not isinstance(tables, dict) or set(tables) - set(_schemas()):
            raise NativeMetaSchemaError(
                "A integração Meta não pode alterar abas legadas."
            )
        prepared, failures = {}, {}
        for title, rows in tables.items():
            try:
                _, existing = self._read(title, context)
                incoming = {}
                for value in rows:
                    row = self._record(title, value)
                    if row["chave"] in incoming and incoming[row["chave"]] != row:
                        raise NativeMetaSchemaError(
                            "Valores Meta divergentes para a mesma chave."
                        )
                    incoming[row["chave"]] = row
                inserted = [r for k, r in incoming.items() if k not in existing]
                updated = [
                    r
                    for k, r in incoming.items()
                    if k in existing
                    and not _same_record(existing[k], r, _schemas()[title])
                ]
                prepared[title] = {
                    "rows": inserted + updated,
                    "inserted": len(inserted),
                    "updated": len(updated),
                    "unchanged": len(incoming) - len(inserted) - len(updated),
                    "preserved": len(set(existing) - set(incoming)),
                    "keys": sorted(incoming),
                    "before": {key: existing.get(key) for key in incoming},
                }
            except Exception as exc:
                failures[title] = type(exc).__name__
        return prepared, failures

    def plan_tables(self, tables):
        manifest = self.schema_manifest()
        prepared, failures = self._prepared(tables, manifest["sources"])
        return {
            "schema_manifest": manifest,
            "tables": {
                title: {
                    key: value
                    for key, value in plan.items()
                    if key not in {"rows", "before"}
                }
                for title, plan in prepared.items()
            },
            "pending_tabs": failures,
            "applied": False,
        }

    def _backup(self, title, snapshot, rows, manifest):
        from config import BASE_DIR

        root = (
            PRIVATE_ROOT
            if PRIVATE_ROOT is not None
            else BASE_DIR / scoped_path("logs") / "privado" / "meta_ads_sheets"
        )
        path = root / (title + "-" + uuid4().hex + ".json")
        values = snapshot.get("values", [])
        keys = {row["chave"] for row in rows}
        before_rows = [
            {"row_number": number, "values": cells}
            for number, cells in enumerate(values[1:], 2)
            if cells and str(cells[0]) in keys
        ]
        # Só as linhas que este lote pode alterar precisam de cópia. Repetir
        # o histórico completo em cada lote tornaria o custo quadrático.
        before = {
            "exists": snapshot["exists"],
            "book_id": snapshot["book_id"],
            "worksheet_id": snapshot.get("worksheet_id"),
            "headers": values[0] if values else [],
            "row_count": max(0, len(values) - 1),
            "data_sha256": digest(values),
            "affected_rows": before_rows,
        }
        save_private(
            path,
            {
                "schema": 1,
                "segment": self.segment,
                "schema_manifest": manifest,
                "title": title,
                "before": before,
                "changes": rows,
            },
        )
        return path

    def apply_tables(self, tables, *, expected_manifest):
        if not self.account_ids:
            raise NativeMetaSchemaError(
                "Confirme as contas Meta autorizadas antes de aplicar."
            )
        current_manifest = self.schema_manifest()
        if current_manifest != expected_manifest:
            raise NativeMetaSchemaError(
                "Fontes ou dados Meta mudaram após a revisão; nenhuma gravação iniciada."
            )
        prepared, failures = self._prepared(tables, current_manifest["sources"])
        summary = {
            "tables": {},
            "pending_tabs": dict(failures),
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "applied": False,
        }
        for title, plan in prepared.items():
            confirmed = 0
            try:
                initial, _ = self._read(title, current_manifest["sources"])
                baseline = current_manifest["tables"][title]
                if (
                    initial.get("worksheet_id") != baseline["worksheet_id"]
                    or bool(initial.get("exists")) != baseline["exists"]
                    or digest(initial.get("values", [])) != baseline["data_sha256"]
                ):
                    raise NativeMetaSchemaError(
                        "A fonte Meta mudou antes de iniciar a tabela."
                    )
                if not initial["exists"] and not plan["rows"]:
                    self._backup(title, initial, [], current_manifest)
                    self.store.native_meta_upsert_chunk(
                        title, _schemas()[title], [], expected_snapshot=initial
                    )
                    self._read(title, current_manifest["sources"])
                for start in range(0, len(plan["rows"]), 200):
                    batch = plan["rows"][start : start + 200]
                    self._context()
                    snapshot, current_rows = self._read(
                        title, current_manifest["sources"]
                    )
                    for row in batch:
                        before = plan["before"][row["chave"]]
                        current = current_rows.get(row["chave"])
                        if (before is None) != (current is None) or (
                            before is not None
                            and current is not None
                            and not _same_record(before, current, _schemas()[title])
                        ):
                            raise NativeMetaSchemaError(
                                "Registro Meta mudou após a revisão do lote."
                            )
                    self._backup(title, snapshot, batch, current_manifest)
                    self.store.native_meta_upsert_chunk(
                        title,
                        _schemas()[title],
                        deepcopy(batch),
                        expected_snapshot=snapshot,
                    )
                    confirm = getattr(self.store, "native_meta_confirm", None)
                    if callable(confirm):
                        checked = confirm(
                            title, _schemas()[title], batch, expected_snapshot=snapshot
                        )
                        if not isinstance(checked, list):
                            raise NativeMetaSchemaError(
                                "Formato inválido de confirmação Meta."
                            )
                        observed = {
                            record["chave"]: self._record(title, record)
                            for record in checked
                        }
                    else:
                        _, observed = self._read(title, current_manifest["sources"])
                    if any(
                        row["chave"] not in observed
                        or not _same_record(
                            observed[row["chave"]], row, _schemas()[title]
                        )
                        for row in batch
                    ):
                        raise NativeMetaSchemaError(
                            "Gravação Meta sem confirmação dos registros enviados."
                        )
                    confirmed += len(batch)
                summary["tables"][title] = {
                    k: plan[k]
                    for k in ("inserted", "updated", "unchanged", "preserved")
                }
                for key in ("inserted", "updated", "unchanged"):
                    summary[key] += plan[key]
            except Exception as exc:
                summary["pending_tabs"][title] = type(exc).__name__
                summary["tables"][title] = {
                    "confirmed_rows": confirmed,
                    "pending": True,
                }
                logging.warning(
                    "Meta nativa: %s pendente (%s); lotes confirmados e legado preservados.",
                    title,
                    type(exc).__name__,
                )
        summary["applied"] = not bool(summary["pending_tabs"])
        return summary
