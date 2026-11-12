"""Deduplicação sobre chaves PostgreSQL, reutilizando os validadores existentes."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from ds_backend.contract import REGISTRY, StorageError, record_key
from ds_backend.migration import private_json


class PostgresDedup:
    continuity = None

    def __init__(self, store):
        self.pg = store
        self.layout = SimpleNamespace(
            dashboard=store._hub_id + "/dashboard",
            operations=store._hub_id + "/operacao",
            history=store._hub_id + "/historico",
            values=lambda: [["backend", "postgres"], ["target", store._hub_id]],
        )

    def close(self):
        pass  # a sessão pertence à rotina Weni, não à auditoria auxiliar

    def capture(self, targets):
        from dedup_sheets import SOURCE_TABS

        tables = {}
        ledger = set()
        orders = {}
        item_keys = set()
        for title in SOURCE_TABS:
            rows = self.pg.records(title)
            if title == "Pedidos_FarmaLider":
                from farmalider_integration import _positive_id

                orders = {r["pedido_chave"]: _positive_id(r["pedido_id"]) for r in rows}
                ledger.update(set(orders.values()) - {""})
            if title == "Itens_Pedidos_FarmaLider":
                item_keys.update(r["pedido_chave"] for r in rows)
            headers = REGISTRY[title]["columns"]
            tables[title] = dict(
                id=title,
                book=self.layout.operations,
                source_title=title,
                headers=headers,
                cells={
                    str(i + 2): [
                        {"userEnteredValue": {"stringValue": str(row.get(c, "") or "")}}
                        for c in headers
                    ]
                    for i, row in enumerate(rows)
                    if row["contact_uuid"] in targets
                },
            )
        tables["Pedidos_FarmaLider"]["item_order_keys"] = sorted(item_keys)
        tables["Itens_Pedidos_FarmaLider"]["ledger_orders"] = orders
        return tables, ledger

    @staticmethod
    def context_for(*args):
        from dedup_sheets import DedupSheets

        return DedupSheets.context_for(*args)

    def cleanup(self, pairs, canonicals, directory):
        from dedup_sheets import record, requests_for, verify_transaction

        targets = {p[k] for p in pairs for k in ("duplicate_uuid", "canonical_uuid")}
        tables, ledger = self.capture(targets)
        for pair in pairs:
            refs, owners, reasons = self.context_for(
                tables, pair["duplicate_uuid"], pair["cpf"], ledger
            )
            if (
                reasons
                or owners - {pair["customer_id"]}
                or not refs <= set(pair["orders"])
            ):
                raise StorageError("DS_DEDUP_FONTE_ALTERADA")
            if (
                sum(
                    record(tables["Base_Contatos"], cells)["contact_uuid"]
                    == pair["canonical_uuid"]
                    for cells in tables["Base_Contatos"]["cells"].values()
                )
                != 1
            ):
                raise StorageError("DS_DEDUP_BASE_AMBIGUA")
        requests, _keys = requests_for(tables, pairs, canonicals)
        from dedup_io import digest

        entry = dict(
            state="sending",
            backup=tables,
            requests=[q for group in requests.values() for q in group],
        )
        entry["requests_sha256"] = digest(entry["requests"])
        private_json(Path(directory) / "postgres-cleanup.json", entry)
        for title, operations in requests.items():
            before = deepcopy(self.pg.records(title))
            after = deepcopy(before)
            headers = REGISTRY[title]["columns"]
            for operation in operations:
                if "updateCells" in operation:
                    item = operation["updateCells"]
                    position = item["range"]["startRowIndex"] - 1
                    col = item["range"]["startColumnIndex"]
                    after[position][headers[col]] = item["rows"][0]["values"][0][
                        "userEnteredValue"
                    ]["stringValue"]
                else:
                    position = operation["deleteDimension"]["range"]["startIndex"] - 1
                    del after[position]
            updated = {record_key(title, r): r for r in after}
            previous = {record_key(title, r): r for r in before}
            self.pg._send(
                title,
                [r for k, r in updated.items() if previous.get(k) != r],
                list(set(previous) - set(updated)),
            )
            self.pg._cache[title] = after
        fresh, _ = self.capture(targets)
        verify_transaction(entry, fresh, {p["duplicate_uuid"] for p in pairs})
        entry["state"] = "verified"
        private_json(Path(directory) / "postgres-cleanup.json", entry)

    def refresh_bi(self, removed, delivery_keys, directory):
        from datetime import UTC, datetime

        from dedup_bi import SOURCE_TITLES, TARGET_TITLES, diff_table, prepare_targets

        sources = {n: self.pg.values(n) for n in SOURCE_TITLES}
        current = {n: self.pg.values(n) for n in TARGET_TITLES}
        targets, _ = prepare_targets(
            sources,
            current,
            dict(
                historico_observado_desde=self.pg.get_control(
                    "historico_observado_desde"
                )
            ),
            removed_uuids=set(removed),
            updated_at=datetime.now(UTC).isoformat(),
        )
        plans = {
            n: diff_table(
                n,
                current[n],
                targets[n],
                removed_uuids=set(removed),
                allowed_delivery_removals=frozenset(delivery_keys),
            )
            for n in targets
        }
        private_json(Path(directory) / "postgres-bi-revisao.json", dict(tables=plans))
        for name, plan in plans.items():
            headers = plan["after"][0]
            rows = plan["after"][1:]
            self.pg._replace_table(self.pg._known_sheets[name], headers, rows)


def open_dedup(settings, legacy):
    from ds_backend.client import enabled

    if not enabled(settings):
        return legacy(str(settings.GOOGLE_SPREADSHEET_ID))
    from ds_backend.runtime import CURRENT_STORE

    if CURRENT_STORE is None:
        raise StorageError("DS_DEDUP_EXIGE_SESSAO_POSTGRES")
    return PostgresDedup(CURRENT_STORE)
