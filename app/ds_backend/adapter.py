"""Transporte PostgreSQL que reutiliza as regras do store Windows existente.

Nenhum método pode abrir Google ou confirmar uma revisão implicitamente em close.
"""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

from ds_backend.contract import (
    REGISTRY,
    SCHEMA_HASH,
    StorageError,
    digest,
    normalize,
    record_key,
    table_contract,
)
from google_sheets import GoogleSheetsStore, UpsertResult


class Table:
    def __init__(self, store, title):
        self.store, self.title = store, title
        self.id = title

    def get_all_values(self, **_kwargs):
        return self.store.values(self.title)

    def col_values(self, index):
        return [
            row[index - 1] if len(row) >= index else "" for row in self.get_all_values()
        ]


class PostgresStore(GoogleSheetsStore):
    """Cada instância é uma revisão no servidor; staging não fica visível ao BI."""

    def __init__(
        self,
        client,
        *,
        purpose="analytics",
        revision=None,
        evidence=None,
        readonly=False,
    ):
        # Não chamar GoogleSheetsStore.__init__: credenciais Google são dispensáveis.
        self.client = client
        self.readonly = readonly
        self.revision = (
            None
            if readonly
            else (revision or client.begin(purpose, evidence)["revision"])
        )
        self._continuity = None
        self._headers_cache = {n: s["columns"] for n, s in REGISTRY.items()}
        self._known_sheets = {n: Table(self, n) for n in REGISTRY}
        self._assign_sheet_handles(self._known_sheets)
        self._cache = {}
        self._receipts = {}
        self._hub_id = client.expected_target
        self.book = SimpleNamespace(id=self._hub_id)
        self._stats = dict(reads=0, writes=0)
        self._finished = False

    def records(self, name):
        table_contract(name)
        if name not in self._cache:
            self._cache[name] = list(self.client.rows(name, self.revision))
        return self._cache[name]

    def values(self, name):
        spec = table_contract(name)
        return [
            spec["columns"],
            *[[row[c] for c in spec["columns"]] for row in self.records(name)],
        ]

    def _get_or_create_sheet(self, title, headers, rows=1000, **_kwargs):
        if table_contract(title)["columns"] != headers:
            raise StorageError("DS_SCHEMA_DIVERGENTE")
        return self._known_sheets[title]

    def _table_values(self, ws):
        return self.values(ws.title)

    def _read_with_retry(self, _description, func, **_kwargs):
        return func()

    def _write_with_retry(self, _description, _func, **_kwargs):
        raise StorageError("DS_OPERACAO_SHEETS_NAO_PERMITIDA")

    def _format_bi_columns(self, *_args, **_kwargs):
        return None

    def migrate_bi_summary_numbers(self):
        return None

    @staticmethod
    def _typed_bi_rows(_headers, rows):
        return rows

    def request_stats(self):
        return dict(reads=self.client.reads, writes=self.client.writes)

    def close(self):
        from ds_backend import runtime

        if runtime.CURRENT_STORE is self:
            runtime.CURRENT_STORE = None
        self.client.close()

    def _send(self, name, rows, remove=None):
        if self.readonly:
            raise StorageError("DS_OPERACAO_SOMENTE_LEITURA")
        normalized = []
        for offset in range(0, len(rows), 1000):
            chunk = normalize(
                name, rows[offset : offset + 1000], self.client.config["segment"]
            )
            receipt = self.client.send(self.revision, name, chunk)
            if receipt.get("state") != "CONFIRMADO":
                raise StorageError("DS_LOTE_NAO_CONFIRMADO")
            self._receipts[receipt["id"]] = receipt["hash"]
            normalized.extend(chunk)
        if remove:
            for offset in range(0, len(remove), 1000):
                receipt = self.client.send(
                    self.revision, name, [], remove=remove[offset : offset + 1000]
                )
                if receipt.get("state") != "CONFIRMADO":
                    raise StorageError("DS_LOTE_NAO_CONFIRMADO")
                self._receipts[receipt["id"]] = receipt["hash"]
        return normalized

    def _upsert_records_detailed(
        self,
        ws,
        records,
        key_name,
        *,
        existing_values=None,
        ignore_compare_fields=None,
        **_kwargs,
    ):
        name = ws.title
        headers = table_contract(name)["columns"]
        if table_contract(name)["keys"] != [key_name]:
            raise StorageError("DS_CHAVE_DIVERGENTE")
        existing = deepcopy(self.records(name))
        by_key = {str(row[key_name]): row for row in existing}
        unique = {}
        for row in records:
            key = str(row.get(key_name) or "").strip()
            if key:
                unique[key] = {**unique.get(key, {}), **row}
        changed = []
        inserted = updated = unchanged = 0
        for key, row in unique.items():
            old = by_key.get(key)
            merged = {c: row.get(c, (old or {}).get(c, "")) for c in headers}
            merged = normalize(name, [merged], self.client.config["segment"])[0]
            if old is not None and not self._record_changed(
                [old.get(c, "") for c in headers],
                [merged[c] for c in headers],
                headers,
                ignore_compare_fields=ignore_compare_fields,
            ):
                unchanged += 1
                continue
            if old is None:
                inserted += 1
            else:
                updated += 1
            changed.append(merged)
            by_key[key] = merged
        self._send(name, changed)
        final = list(by_key.values())
        self._cache[name] = final
        return UpsertResult(
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
            changed_records=changed,
            final_records=final,
        )

    def _replace_table(self, ws, headers, rows, **_kwargs):
        name = ws.title
        spec = table_contract(name)
        if headers != spec["columns"]:
            raise StorageError("DS_SCHEMA_DIVERGENTE")
        records = [dict(zip(headers, row, strict=True)) for row in rows]
        normalized = []
        for offset in range(0, len(records), 1000):
            normalized.extend(
                normalize(
                    name, records[offset : offset + 1000], self.client.config["segment"]
                )
            )
        if name in ("BI_Itens", "BI_Clientes_Vendas"):
            scope = {r["venda_chave"] for r in normalized} | getattr(
                self, "_cancelled_sales", set()
            )
            normalized.extend(
                r for r in self.records(name) if r["venda_chave"] not in scope
            )
        elif name == "BI_Clientes":
            present = {r["cliente_chave"] for r in normalized}
            normalized.extend(
                r for r in self.records(name) if r["cliente_chave"] not in present
            )
        keyed = {record_key(name, row): row for row in normalized}
        if len(keyed) != len(normalized):
            raise StorageError("DS_CHAVE_DUPLICADA")
        current = {record_key(name, row): row for row in self.records(name)}
        # Atualizado_em descreve a última alteração do conteúdo. BI_Status e
        # Controle continuam registrando o corte/checkpoint de cada execução.
        from decimal import Decimal

        for key, record in list(keyed.items()):
            previous = current.get(key)
            if previous is None:
                continue
            same = True
            for field in headers:
                if field == "atualizado_em":
                    continue
                left, right = previous[field], record[field]
                if spec["types"][field] == "number" and left != "" and right != "":
                    equal = Decimal(left) == Decimal(right)
                else:
                    equal = left == right
                if not equal:
                    same = False
                    break
            if same:
                keyed[key] = previous
        normalized = list(keyed.values())
        if current == keyed:
            return False
        if name in ("BI_Itens", "BI_Clientes_Vendas", "BI_Clientes"):
            self._send(
                name,
                [r for k, r in keyed.items() if current.get(k) != r],
                list(set(current) - set(keyed)),
            )
            self._cache[name] = normalized
            return True
        self.client.call(
            "/v1/substituicoes",
            dict(
                revision=self.revision,
                name=name,
                expected=dict(count=len(keyed), sha256=digest(sorted(keyed))),
            ),
        )
        self._send(name, normalized)
        self._cache[name] = normalized
        return True

    def upsert_pharmacy_orders(self, orders, items):
        from bi_postgres_client import sales_scope

        excluded = {r["pedido_id"]: r for r in self.records("Exclusoes_Publicacao")}
        filtered = []
        removed_ids = set()
        canonical = {
            r["id"]: json.loads(r["record"])
            for r in self.records("Cache_history_orders")
        }
        from order_history import financial_record_digest

        for row in orders:
            oid = str(row.get("pedido_id", ""))
            if oid in excluded:
                if (
                    oid not in canonical
                    or financial_record_digest(canonical[oid])
                    != excluded[oid]["original_sha256"]
                ):
                    raise StorageError("DS_EXCLUSAO_REQUER_CONFERENCIA_DO_FATO")
                removed_ids.add(oid)
            else:
                filtered.append(row)
        orders = filtered
        items = [r for r in items if str(r.get("pedido_id", "")) not in removed_ids]
        self._cancelled_sales = set(sales_scope(orders, []))
        return super().upsert_pharmacy_orders(orders, items)

    def _clear_scope_records(self, ws, records, key_name, keys, **_kwargs):
        removed = [
            record_key(ws.title, r)
            for r in self.records(ws.title)
            if str(r.get(key_name) or "") in keys
        ]
        self._send(ws.title, [], removed)
        self._cache[ws.title] = [
            r for r in self.records(ws.title) if str(r.get(key_name) or "") not in keys
        ]

    def _sanitize_scope_rows(self, ws, sanitizer, *, values=None, **_kwargs):
        rows = [sanitizer(deepcopy(r)) for r in self.records(ws.title)]
        result = self._upsert_records_detailed(
            ws, rows, table_contract(ws.title)["keys"][0]
        )
        return result.updated

    def set_controls(self, values):
        from datetime import UTC, datetime

        headers = table_contract("Controle")["columns"]
        now = datetime.now(UTC).isoformat()
        records = [
            dict(zip(headers, [key, str(value), now], strict=True))
            for key, value in values.items()
        ]
        self._upsert_records_detailed(self.control, records, "chave")

    def get_control(self, key):
        for row in self.records("Controle"):
            if row["chave"] == key:
                return row["valor"]
        return ""

    def append_history(self, records, existing_uuids_before_sync):
        from geography import normalize_geography
        from pharmacy_scope import sanitize_contact_order

        records = [
            dict(
                sanitize_contact_order(normalize_geography(r)),
                acao="Atualizado"
                if r.get("contact_uuid") in existing_uuids_before_sync
                else "Inserido",
                sincronizado_em=self.now_iso(),
            )
            for r in records
        ]
        name = "Historico_Alteracoes"
        spec = table_contract(name)
        current = {record_key(name, r): r for r in self.records(name)}
        new = []
        for row in records:
            row = {c: row.get(c, "") for c in spec["columns"]}
            row = normalize(name, [row], self.client.config["segment"])[0]
            key = record_key(name, row)
            if key in current:
                if current[key] != row:
                    raise StorageError("DS_EVENTO_REUTILIZADO")
            else:
                new.append(row)
                current[key] = row
        self._send(name, new)
        self._cache[name] = list(current.values())

    def existing_event_ids(self):
        return self.load_event_ids()

    def append_event(self, values):
        headers = REGISTRY["Eventos_Anuncios"]["columns"]
        self._upsert_records_detailed(
            self.events, [dict(zip(headers, values, strict=True))], "event_id"
        )

    def load_event_ids(self):
        return {r["event_id"] for r in self.records("Eventos_Anuncios")}

    def native_meta_context(self):
        self.client.verify()
        return dict(
            segment=self.client.config["segment"],
            dashboard=self._hub_id + "/dashboard",
            operations=self._hub_id + "/operacao",
            history=self._hub_id + "/historico",
        )

    def native_meta_read(self, title, headers):
        self._native_meta_headers(title, headers)
        return dict(
            exists=True,
            book_id=self._hub_id
            + ("/dashboard" if title.startswith("BI_") else "/operacao"),
            worksheet_id=title,
            values=self.values(title),
        )

    def native_meta_inputs(self):
        return {
            k: deepcopy(self.records(n))
            for k, n in [
                ("contacts", "Base_Contatos"),
                ("orders", "Pedidos_FarmaLider"),
                ("items", "Itens_Pedidos_FarmaLider"),
            ]
        }

    def native_meta_upsert_chunk(self, title, headers, records, *, expected_snapshot):
        if self.native_meta_read(title, headers) != expected_snapshot:
            raise StorageError("DS_REVISAO_META_DIVERGENTE")
        self._upsert_records_detailed(self._known_sheets[title], records, "chave")
        return self.native_meta_read(title, headers)

    def native_meta_confirm(self, title, headers, records, *, expected_snapshot):
        current = self.native_meta_read(title, headers)
        if current != expected_snapshot:
            raise StorageError("DS_REVISAO_META_DIVERGENTE")
        by_key = {r["chave"]: r for r in self.records(title)}
        if any(
            any(
                str(by_key.get(r["chave"], {}).get(c, "")) != str(r.get(c, ""))
                for c in headers
            )
            for r in records
        ):
            raise StorageError("DS_CONFERENCIA_META_DIVERGENTE")
        return current

    def finish(self, *, complete):
        if not complete:
            raise StorageError("DS_FONTES_INCOMPLETAS_RETOMAR")
        manifest = dict(
            schema_hash=SCHEMA_HASH, batches=self._receipts, complete_sources=True
        )
        self.client.call("/v1/selar", dict(revision=self.revision, manifest=manifest))
        result = self.client.call(
            "/v1/confirmar",
            dict(revision=self.revision, manifest=manifest, complete=True),
        )
        if result.get("state") != "READY":
            raise StorageError("DS_REVISAO_NAO_CONFIRMADA")
        self._finished = True
        return result
