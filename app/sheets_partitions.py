"""Leitura e gravação de tabelas lógicas distribuídas em continuações Sheets."""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sheets_continuation import (
    ContinuationError,
    ContinuationIndex,
    Part,
    SheetsLease,
    additional_rows,
    allocated_cells,
    fingerprint,
    stamp_book,
)
from sheets_provisioning import DRIVE, CreationRejected, MyDriveProvisioner


def roots_for(store):
    layout = getattr(store, "_storage_layout", None)
    hub = store._hub_id
    return {
        "dashboard": hub,
        "operacao": layout.operations if layout else hub,
        "historico": layout.history if layout else hub,
    }


def role_for(title):
    return (
        "dashboard"
        if title.startswith("BI_")
        else "historico"
        if title == "Historico_Alteracoes"
        else "operacao"
    )


@dataclass
class TableSnapshot:
    part: Part
    worksheet: Any
    values: list[list[Any]]


class RolloverManager:
    def __init__(self, store, index_sheet, index, *, provisioner_factory=None):
        self.store = store
        self.sheet = index_sheet
        self.index = index
        self.lease = SheetsLease(store.book)
        self.books = {store._hub_id: store.book, **getattr(store, "_storage_books", {})}
        self.handles = {}
        self.provider = None
        self.provider_factory = provisioner_factory or self._new_provider
        self.persisted_hash = fingerprint(index.values())
        self.metadata = {}
        from project_paths import ROOT
        from runtime_profile import scoped_path

        self.journal_path = ROOT / scoped_path(
            f"logs/privado/continuacao_historico_{fingerprint(store._hub_id)[:12]}.json"
        )

    @classmethod
    def attach(cls, store, index_sheet):
        if index_sheet is None:
            return None
        from runtime_profile import segment

        values = store._read_with_retry(
            "ler índice de continuações", index_sheet.get_all_values
        )
        index = ContinuationIndex.parse(
            values, hub=store._hub_id, segment=segment(), roots=roots_for(store)
        )
        return cls(store, index_sheet, index)

    def close(self):
        try:
            self.lease.release()
        finally:
            if self.provider is not None:
                self.provider.close()

    def _new_provider(self):
        auth = self.store.client.http_client.auth
        email = getattr(auth, "service_account_email", "")
        if not email:
            raise ContinuationError(
                "Não foi possível identificar a conta de serviço para compartilhar a continuação."
            )
        return MyDriveProvisioner(
            self.store.client.http_client.session, email, before_write=self.require
        )

    def require(self):
        self.lease.require(wait_seconds=300)

    def save(self):
        self.require()
        current = self.store._read_with_retry(
            "conferir índice antes de gravar", self.sheet.get_all_values
        )
        if fingerprint(current) != self.persisted_hash:
            raise ContinuationError(
                "O índice de continuações mudou durante a carga; reexecute a rotina."
            )
        values = self.index.values()
        size = max(len(values), len(current), 1)
        if self.sheet.row_count < size:
            self.store._write_with_retry(
                "reservar índice de continuações", lambda: self.sheet.resize(rows=size)
            )
        # Um único updateCells atualiza o índice e limpa o excedente atomicamente.
        body = {
            "requests": [
                {
                    "updateCells": {
                        "range": {
                            "sheetId": self.sheet.id,
                            "startRowIndex": 0,
                            "endRowIndex": size,
                            "startColumnIndex": 0,
                            "endColumnIndex": 3,
                        },
                        "rows": [
                            {
                                "values": [
                                    {"userEnteredValue": {"stringValue": str(value)}}
                                    for value in row
                                ]
                            }
                            for row in values
                        ],
                        "fields": "userEnteredValue",
                    }
                }
            ]
        }
        self.store._write_with_retry(
            "registrar continuações",
            lambda: self.store.book.batch_update(copy.deepcopy(body)),
        )
        actual = self.store._read_with_retry(
            "confirmar índice de continuações", self.sheet.get_all_values
        )
        if fingerprint(actual) != fingerprint(values):
            raise ContinuationError(
                "A gravação do índice não foi confirmada; preservar os comprovantes."
            )
        self.persisted_hash = fingerprint(values)

    def _book(self, book_id):
        if book_id not in self.books:
            if book_id not in self.index.files:
                raise ContinuationError("Arquivo fora do índice de continuações.")

            def validate():
                return self.store.client.http_client.request(
                    "get",
                    DRIVE + "/files/" + book_id,
                    params={
                        "fields": "id,mimeType,trashed,properties",
                        "supportsAllDrives": "true",
                    },
                ).json()

            info = self.store._read_with_retry(
                "conferir segmento da continuação", validate
            )
            props = info.get("properties", {})
            if (
                info.get("trashed")
                or info.get("mimeType") != "application/vnd.google-apps.spreadsheet"
                or props.get("nexoflow_hub") != self.index.config["hub"]
                or props.get("nexoflow_segment") != self.index.config["segment"]
                or props.get("nexoflow_role") != self.index.files[book_id]["role"]
            ):
                raise ContinuationError(
                    "Continuação não pertence ao segmento e ao dashboard atuais."
                )
            self.books[book_id] = self.store._read_with_retry(
                "abrir continuação", lambda: self.store.client.open_by_key(book_id)
            )
        return self.books[book_id]

    def worksheet(self, part):
        key = (part.book_id, part.sheet_id)
        if key not in self.handles:
            ws = self.store._read_with_retry(
                "localizar aba na continuação",
                lambda: self._book(part.book_id).get_worksheet_by_id(part.sheet_id),
            )
            if ws.title != part.title:
                raise ContinuationError(
                    "A aba da continuação foi renomeada ou substituída."
                )
            self.handles[key] = ws
        return self.handles[key]

    def create_anchor(self, title, headers):
        self.require()
        root_id = roots_for(self.store)[role_for(title)]
        book = self._book(root_id)
        metadata = self.store._read_with_retry(
            "conferir capacidade para nova aba", book.fetch_sheet_metadata
        )
        if allocated_cells(metadata) + len(headers) <= self.index.config["threshold"]:
            return self.store._write_with_retry(
                "criar aba com reserva mínima",
                lambda: book.add_worksheet(title=title, rows=1, cols=len(headers)),
            )
        return self._create_part(title, headers).worksheet

    def register_root(self, ws, headers):
        parts = self.index.table_parts(ws.title)
        if parts:
            if parts[0].schema != fingerprint(headers):
                raise ContinuationError(
                    "O schema mudou depois da criação das continuações; exige migração validada."
                )
            return parts
        book_id = roots_for(self.store)[role_for(ws.title)]
        part = Part(ws.title, 0, book_id, ws.id, len(headers), fingerprint(headers))
        self.index.parts[part.key] = part
        self.handles[(book_id, ws.id)] = ws
        return [part]

    def snapshots(self, ws, *, render="FORMATTED_VALUE", refresh=False):
        headers = getattr(self.store, "_headers_cache", {}).get(ws.title)
        if not headers:
            headers = self.store._read_header_bounded(
                ws, self.store._schema_map().get(ws.title, [])
            )
        parts = self.register_root(ws, headers)
        result = []
        for part in parts:
            if refresh:
                self.handles.pop((part.book_id, part.sheet_id), None)
            physical = self.worksheet(part)
            values = self.store._read_with_retry(
                f"ler {ws.title} | parte {part.number + 1}/{len(parts)}",
                lambda physical=physical: physical.get_all_values(
                    value_render_option=render
                ),
            )
            values = self.store._validated_table_values(values, ws.title)
            if (
                not values
                or list(values[0]) != headers
                or fingerprint(values[0]) != part.schema
            ):
                raise ContinuationError(
                    "Cabeçalho divergente em uma continuação; nenhuma linha será realocada."
                )
            result.append(TableSnapshot(part, physical, values))
        return result

    def read(self, ws, *, render="FORMATTED_VALUE"):
        snapshots = self.snapshots(ws, render=render)
        return [
            snapshots[0].values[0],
            *[row for snapshot in snapshots for row in snapshot.values[1:]],
        ]

    def _capacity(self, part, ws):
        book = self._book(part.book_id)
        metadata = self.store._read_with_retry(
            "conferir células alocadas", book.fetch_sheet_metadata
        )
        self.metadata[part.book_id] = metadata
        return allocated_cells(metadata)

    def _create_part(self, title, headers):
        self.require()
        role = role_for(title)
        if role == "dashboard" and title not in self.index.config["connector_tables"]:
            raise ContinuationError(
                f"{title} precisa de uma continuação. Primeiro conecte essa fonte ao conector NexoFlow "
                "no Data Studio e confirme com nexo armazenamento ativar-data-studio."
            )
        if self.provider is None:
            self.provider = self.provider_factory()
        parts = self.index.table_parts(title)
        number = len(parts)
        key = f"{title}#{number}"
        intent = self.index.intents.get(key)
        first = intent is None
        if first:
            file_number = 1 + max(
                (
                    int(info.get("number", 0))
                    for info in self.index.files.values()
                    if info.get("role") == role
                ),
                default=0,
            )
            source = roots_for(self.store)[role]
            intent = self.provider.prepare_intent(
                source,
                uuid4().hex,
                hub=self.index.config["hub"],
                segment=self.index.config["segment"],
                role=role,
                number=file_number,
            )
            intent["table"] = title
            intent["part"] = number
            intent["schema"] = fingerprint(headers)
            intent["create_state"] = "prepared"
            self.index.intents[key] = intent
            self.save()
        if intent.get("schema") != fingerprint(headers):
            raise ContinuationError(
                "A criação pendente possui outro schema; preserve o índice."
            )
        file_id = intent.get("file_id")
        if not file_id:
            # Persistir a intenção ANTES da chamada; em retomadas, procurar em vez de criar.
            allow_send = intent.get("create_state") in ("prepared", "rejected")
            if allow_send:
                intent["create_state"] = "sending"
                self.save()
            try:
                file_id = self.provider.create(intent, first_attempt=allow_send)
            except CreationRejected:
                intent["create_state"] = "rejected"
                self.save()
                raise
            intent["file_id"] = file_id
            self.save()
        self.provider.verify_owned(file_id, intent)
        current_access = self.provider.prepare_intent(
            intent["source"],
            intent["operation"],
            hub=intent["hub"],
            segment=intent["segment"],
            role=intent["role"],
            number=intent["number"],
        )

        def permissions(data):
            return sorted(
                data["permissions"],
                key=lambda p: (p["type"], p["emailAddress"].casefold()),
            )

        if current_access["parents"] != intent["parents"] or permissions(
            current_access
        ) != permissions(intent):
            raise ContinuationError(
                "A pasta ou os acessos da origem mudaram; nenhuma permissão antiga será reaplicada. Preserve o índice para revisão."
            )
        self.provider.share(file_id, intent)
        self.index.files[file_id] = {
            "role": role,
            "number": intent["number"],
            "source": intent["source"],
        }
        self.provider.verify(
            file_id,
            hub=self.index.config["hub"],
            segment=self.index.config["segment"],
            role=role,
        )
        book = self.store._read_with_retry(
            "abrir nova continuação compartilhada",
            lambda: self.store.client.open_by_key(file_id),
        )
        sheets = self.store._read_with_retry(
            "conferir nova continuação", book.worksheets
        )
        matching = [sheet for sheet in sheets if sheet.title == title]
        if matching:
            ws = matching[0]
            values = self.store._read_with_retry(
                "conferir criação retomada", ws.get_all_values
            )
            if values not in ([], [headers]):
                raise ContinuationError(
                    "A nova continuação recebeu dados antes da ativação; revisar."
                )
        elif len(sheets) == 1 and not self.store._read_with_retry(
            "conferir aba inicial vazia", sheets[0].get_all_values
        ):
            ws = sheets[0]
            self.store._write_with_retry(
                "nomear aba da continuação", lambda: ws.update_title(title)
            )
        elif not sheets:
            ws = self.store._write_with_retry(
                "criar aba da continuação",
                lambda: book.add_worksheet(title=title, rows=1, cols=len(headers)),
            )
        else:
            raise ContinuationError(
                "A criação pendente contém abas inesperadas; preservar para revisão."
            )
        self.store._write_with_retry(
            "dimensionar nova continuação", lambda: ws.resize(rows=1, cols=len(headers))
        )
        self.store._write_with_retry(
            "cabeçalho da continuação",
            lambda: ws.update(
                range_name=f"A1:{self.store_column(len(headers))}1",
                values=[headers],
                value_input_option="RAW",
            ),
        )
        self.store._write_with_retry(
            "fixar cabeçalho da continuação", lambda: ws.freeze(rows=1)
        )
        if self.store._read_with_retry(
            "confirmar cabeçalho da continuação", ws.get_all_values
        ) != [headers]:
            raise ContinuationError("Cabeçalho da continuação não foi confirmado.")
        self.store._write_with_retry(
            "registrar origem da continuação",
            lambda: stamp_book(
                book,
                hub=self.index.config["hub"],
                segment=self.index.config["segment"],
                role=role,
            ),
        )
        part = Part(title, number, file_id, ws.id, len(headers), fingerprint(headers))
        self.index.parts[key] = part
        self.index.status[title] = {"state": "WRITING", "revision": uuid4().hex}
        self.books[file_id] = book
        self.handles[(file_id, ws.id)] = ws
        del self.index.intents[key]
        self.save()
        logging.info(
            "Google Sheets: %s — continuação %s criada e compartilhada; histórico preservado.",
            title,
            number,
        )
        return TableSnapshot(part, ws, [headers])

    @staticmethod
    def store_column(number):
        from google_sheets import column_letter

        return column_letter(number)

    def _available(self, snapshot):
        ws = snapshot.worksheet
        current = len(snapshot.values)
        cells = self._capacity(snapshot.part, ws)
        if cells >= self.index.config["threshold"]:
            return 0
        padding = max(0, ws.row_count - current)
        extra = additional_rows(
            cells,
            ws.col_count,
            threshold=self.index.config["threshold"],
        )
        return max(
            0, min(padding + extra, self.index.config["max_part_rows"] - current)
        )

    def _reserve(self, snapshot, count):
        required = len(snapshot.values) + count
        if required > snapshot.worksheet.row_count:
            self.store._write_with_retry(
                "reservar linhas da continuação",
                lambda: snapshot.worksheet.resize(rows=required),
            )

    def _begin(self, title):
        self.index.status[title] = {"state": "WRITING", "revision": uuid4().hex}
        self.save()

    def finish(self, ws):
        snapshots = self.snapshots(ws, render="UNFORMATTED_VALUE")
        self.index.status[ws.title] = {
            "state": "READY",
            "revision": uuid4().hex,
            "parts": [
                {"number": s.part.number, "rows": len(s.values) - 1} for s in snapshots
            ],
        }
        self.save()

    def upsert(
        self,
        ws,
        records,
        key,
        *,
        ignore_compare_fields=None,
        value_input_option="RAW",
        preserve_types=False,
    ):
        from google_sheets import UpsertResult

        self.require()
        self.resume_history()
        snapshots = self.snapshots(ws, refresh=True)
        known = {}
        for snapshot in snapshots:
            position = snapshot.values[0].index(key)
            for row in snapshot.values[1:]:
                identity = str(row[position]).strip() if len(row) > position else ""
                if identity and identity in known:
                    raise ContinuationError(
                        "Chave duplicada entre continuações; conferir antes de gravar."
                    )
                if identity:
                    known[identity] = snapshot.part.key
        grouped = {s.part.key: [] for s in snapshots}
        additions = []
        for record in records:
            identity = str(record.get(key) or "").strip()
            if not identity:
                continue
            if identity in known:
                grouped[known[identity]].append(record)
            else:
                additions.append(record)
        offset = 0
        while offset < len(additions):
            last = snapshots[-1]
            room = self._available(last)
            if not room:
                last = self._create_part(ws.title, snapshots[0].values[0])
                snapshots.append(last)
                grouped[last.part.key] = []
                room = self._available(last)
                if not room:
                    raise ContinuationError(
                        "A nova continuação não possui capacidade para uma linha."
                    )
            take = min(room, len(additions) - offset)
            self._reserve(last, take)
            grouped[last.part.key].extend(additions[offset : offset + take])
            offset += take
            if offset < len(additions):
                # A parte atual foi reservada por completo neste plano.
                new = self._create_part(ws.title, snapshots[0].values[0])
                snapshots.append(new)
                grouped[new.part.key] = []
        self._begin(ws.title)
        totals = UpsertResult(0, 0, 0, [], [])
        for snapshot in snapshots:
            result = self.store._upsert_records_detailed(
                snapshot.worksheet,
                grouped[snapshot.part.key],
                key,
                existing_values=snapshot.values,
                ignore_compare_fields=ignore_compare_fields,
                value_input_option=value_input_option,
                preserve_types=preserve_types,
                _physical=True,
            )
            totals.inserted += result.inserted
            totals.updated += result.updated
            totals.unchanged += result.unchanged
            totals.changed_records.extend(result.changed_records)
            totals.final_records.extend(result.final_records)
        self.finish(ws)
        return totals

    def replace(self, ws, headers, rows, *, value_input_option="RAW", force=False):
        self.require()
        self.resume_history()
        snapshots = self.snapshots(ws, refresh=True)
        current = [headers, *[row for s in snapshots for row in s.values[1:]]]
        if not force and self.store._normalize_table(
            current
        ) == self.store._normalize_table([headers, *rows]):
            # Dados iguais ainda precisam confirmar uma publicação interrompida
            # ou o primeiro registro do índice após a ativação.
            expected_counts = [
                {"number": snapshot.part.number, "rows": len(snapshot.values) - 1}
                for snapshot in snapshots
            ]
            status = self.index.status.get(ws.title, {})
            if status.get("state") != "READY" or status.get("parts") != expected_counts:
                self.finish(ws)
            return False
        targets = []
        remaining = list(rows)
        for snapshot in snapshots:
            maximum = max(
                0,
                min(
                    snapshot.worksheet.row_count
                    - 1
                    + additional_rows(
                        self._capacity(snapshot.part, snapshot.worksheet),
                        snapshot.worksheet.col_count,
                        threshold=self.index.config["threshold"],
                    ),
                    self.index.config["max_part_rows"] - 1,
                ),
            )
            if (
                self.metadata[snapshot.part.book_id]
                and allocated_cells(self.metadata[snapshot.part.book_id])
                >= self.index.config["threshold"]
            ):
                maximum = min(maximum, max(0, len(snapshot.values) - 1))
            chunk, remaining = remaining[:maximum], remaining[maximum:]
            needed = len(chunk) + 1
            if needed > snapshot.worksheet.row_count:
                self.store._write_with_retry(
                    "reservar tabela BI na continuação",
                    lambda snapshot=snapshot, needed=needed: snapshot.worksheet.resize(
                        rows=needed
                    ),
                )
            targets.append((snapshot, chunk))
        while remaining:
            snapshot = self._create_part(ws.title, headers)
            room = self._available(snapshot)
            if room < 1:
                raise ContinuationError("Continuação sem capacidade para a tabela.")
            chunk, remaining = remaining[:room], remaining[room:]
            self._reserve(snapshot, len(chunk))
            targets.append((snapshot, chunk))
        self._begin(ws.title)
        for snapshot, chunk in targets:
            self.store._replace_table(
                snapshot.worksheet,
                headers,
                chunk,
                value_input_option=value_input_option,
                force=True,
                _physical=True,
            )
        self.finish(ws)
        return True

    def append_history(self, ws, rows):
        if not rows:
            return
        self.require()
        self.resume_history()
        snapshots = self.snapshots(ws, refresh=True)
        remaining = list(rows)
        targets = []
        while remaining:
            snapshot = snapshots[-1]
            room = self._available(snapshot)
            if not room:
                snapshot = self._create_part(ws.title, snapshots[0].values[0])
                snapshots.append(snapshot)
                room = self._available(snapshot)
            if room < 1:
                raise ContinuationError("Continuação sem capacidade para o histórico.")
            chunk, remaining = remaining[:room], remaining[room:]
            self._reserve(snapshot, len(chunk))
            targets.append((snapshot, chunk))
            if remaining:
                snapshots.append(self._create_part(ws.title, snapshots[0].values[0]))
        from dedup_io import save_private

        payload = {
            "hub": self.index.config["hub"],
            "segment": self.index.config["segment"],
            "operation": uuid4().hex,
            "targets": [
                {
                    "part": snapshot.part.key,
                    "start": len(snapshot.values) + 1,
                    "values": chunk,
                }
                for snapshot, chunk in targets
            ],
        }
        payload["sha256"] = fingerprint(payload)
        save_private(self.journal_path, payload)
        self.index.status[ws.title] = {
            "state": "WRITING",
            "revision": payload["operation"],
            "pending_history": {
                "operation": payload["operation"],
                "targets": [
                    {
                        "part": target["part"],
                        "start": target["start"],
                        "rows": len(target["values"]),
                        "sha256": fingerprint(target["values"]),
                    }
                    for target in payload["targets"]
                ],
            },
        }
        self.save()
        self.resume_history()

    def _history_range(self, target, count):
        part = self.index.parts[target["part"]]
        return f"A{target['start']}:{self.store_column(part.width)}{target['start'] + count - 1}"

    @staticmethod
    def _rectangular(values, rows, width):
        return [
            list(values[i])[:width] + [""] * max(0, width - len(values[i]))
            if i < len(values)
            else [""] * width
            for i in range(rows)
        ]

    def resume_history(self):
        pending = self.index.status.get("Historico_Alteracoes", {}).get(
            "pending_history"
        )
        if not self.journal_path.is_file() and not pending:
            return
        self.require()
        payload = None
        if self.journal_path.is_file():
            payload = json.loads(self.journal_path.read_text(encoding="utf-8"))
            expected = payload.pop("sha256", None)
            if (
                expected != fingerprint(payload)
                or payload.get("hub") != self.index.config["hub"]
                or payload.get("segment") != self.index.config["segment"]
            ):
                raise ContinuationError(
                    "Comprovante de histórico inválido ou pertencente a outro segmento."
                )
            if pending and pending["operation"] != payload["operation"]:
                raise ContinuationError(
                    "Há outra aplicação do histórico pendente; preserve os comprovantes."
                )
            targets = payload["targets"]
            for target in targets:
                part = self.index.parts.get(target["part"])
                if part is None or part.title != "Historico_Alteracoes":
                    raise ContinuationError(
                        "Comprovante de histórico aponta para outra tabela."
                    )
                physical = self.worksheet(part)
                first = target["start"]
                for batch in self.store._adaptive_batches(
                    target["values"], max_items=2000
                ):
                    cell_range = self._history_range(
                        {**target, "start": first}, len(batch)
                    )
                    expected_values = self._rectangular(batch, len(batch), part.width)

                    def write(
                        physical=physical,
                        cell_range=cell_range,
                        expected_values=expected_values,
                        width=part.width,
                    ):
                        current = self.store._read_with_retry(
                            "conferir retomada do histórico",
                            lambda: physical.get(
                                cell_range, value_render_option="UNFORMATTED_VALUE"
                            ),
                        )
                        current = self._rectangular(
                            current, len(expected_values), width
                        )
                        if any(
                            actual not in ("", None) and actual != desired
                            for old, new in zip(current, expected_values, strict=True)
                            for actual, desired in zip(old, new, strict=True)
                        ):
                            raise ContinuationError(
                                "O destino do histórico foi ocupado por outros dados; não sobrescrever."
                            )
                        if current == expected_values:
                            return None
                        return physical.update(
                            range_name=cell_range,
                            values=expected_values,
                            value_input_option="RAW",
                        )

                    self.store._write_with_retry(
                        "retomar histórico na continuação", write
                    )
                    first += len(batch)
        else:
            # Outro computador pode confirmar uma entrega completa por hashes,
            # mas precisa do comprovante original para reconstruir linhas ausentes.
            for target in pending["targets"]:
                part = self.index.parts.get(target["part"])
                if part is None or part.title != "Historico_Alteracoes":
                    raise ContinuationError("Índice de histórico pendente inválido.")
                physical = self.worksheet(part)
                cell_range = self._history_range(target, target["rows"])
                actual = self.store._read_with_retry(
                    "confirmar histórico pendente",
                    lambda physical=physical, cell_range=cell_range: physical.get(
                        cell_range, value_render_option="UNFORMATTED_VALUE"
                    ),
                )
                actual = self._rectangular(actual, target["rows"], part.width)
                if fingerprint(actual) != target["sha256"]:
                    raise ContinuationError(
                        "Histórico incompleto: retome a carga no computador que possui o comprovante privado original."
                    )
        self.finish(self.store.history)
        self.journal_path.unlink(missing_ok=True)

    def format(self, ws, headers, text_columns):
        for part in self.index.table_parts(ws.title):
            self.store._format_bi_columns(
                self.worksheet(part), headers, text_columns=text_columns, _physical=True
            )
