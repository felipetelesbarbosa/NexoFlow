"""Porta Sheets do histórico: protocolo lógico sobre o manifesto oficial."""

from __future__ import annotations

import json
from copy import deepcopy

from gspread.exceptions import WorksheetNotFound

from order_history import HistoryError
from order_history_sheets import normalized_cells, typed_cells
from sheets_continuation import ContinuationIndex, allocated_cells, fingerprint
from sheets_partitions import roots_for
from sheets_provisioning import DRIVE
from sheets_storage import storage_role


class SheetsTransport:
    def __init__(self, store):
        self.store = store
        manager = getattr(store, "_continuity", None)
        if manager is None:
            raise HistoryError(
                "CONTINUACOES_NAO_CONFIGURADAS: execute nexo armazenamento configurar"
            )
        from order_history_sheets import SCHEMAS

        self.manager = manager
        self.schemas = SCHEMAS
        self.writing = False

    def context(self):
        return self.store.native_meta_context()

    def manifest(self):
        values = self.store._read_with_retry(
            "conferir manifesto do histórico", self.manager.sheet.get_all_values
        )
        index = ContinuationIndex.parse(
            values,
            hub=self.store._hub_id,
            segment=self.context()["segment"],
            roots=roots_for(self.store),
        )
        self.manager.index = index
        self.manager.persisted_hash = fingerprint(values)
        return fingerprint(values)

    def bind(self, *, before, after):
        self.manager.before_manifest_write = lambda values: before(fingerprint(values))
        self.manager.after_manifest_write = lambda values: after(fingerprint(values))

    def acquire(self):
        self.manager.require()
        self.writing = True

    def _drive(self, book):
        return self.store._read_with_retry(
            "conferir acesso privado do arquivo",
            lambda: self.store.client.http_client.request(
                "get",
                DRIVE + "/files/" + book,
                params={
                    "fields": "id,version,parents,capabilities(canEdit),trashed",
                    "supportsAllDrives": "true",
                },
            ).json(),
        )

    def _origin(self, meta, role):
        from sheets_continuation import FILE_MARKER_KEY

        tags = [
            m
            for m in meta.get("developerMetadata", [])
            if m.get("metadataKey") == FILE_MARKER_KEY
        ]
        try:
            valid = (
                len(tags) == 1
                and tags[0].get("visibility") == "DOCUMENT"
                and tags[0].get("location", {}).get("spreadsheet") is True
            )
            stamp = json.loads(tags[0]["metadataValue"]) if valid else {}
        except (ValueError, KeyError, TypeError):
            stamp = {}
        if not isinstance(stamp, dict) or any(
            stamp.get(k) != v
            for k, v in dict(
                hub=self.store._hub_id, segment=self.context()["segment"], role=role
            ).items()
        ):
            raise HistoryError("ORIGEM_DO_ARQUIVO_NAO_COMPROVADA")

    def _physical(self, part):
        from sheets_continuation import Part

        known = self.manager.index.table_parts(part["title"])
        registered = next((p for p in known if p.number == part["number"]), None)
        if registered and (registered.book_id, registered.sheet_id) != (
            part["book"],
            part["sheet"],
        ):
            raise HistoryError("COORDENADAS_DIVERGEM_DO_MANIFESTO")
        if (
            registered is None
            and part["book"] != roots_for(self.store)[storage_role(part["title"])]
        ):
            raise HistoryError("PARTE_NAO_REGISTRADA")
        descriptor = Part(
            part["title"],
            part["number"],
            part["book"],
            part["sheet"],
            part["width"],
            fingerprint(self.schemas[part["title"]]),
        )
        return self.manager.worksheet(descriptor)

    def describe(self, schemas):
        self.schemas = schemas
        context = self.context()
        manifest = self.manifest()
        config = self.manager.index.config
        if config.get("history_publication", {}).get("state") == "WRITING":
            raise HistoryError("PUBLICACAO_PENDENTE_RETOME_A_REVISAO_ORIGINAL")
        parts = []
        books = {}
        layouts = {}
        versions = {}
        access_proofs = {}
        ids = set(roots_for(self.store).values()) | set(self.manager.index.files)
        for book_id in sorted(ids):
            book = self.manager._book(book_id)
            meta = self.store._read_with_retry(
                "conferir grade global do histórico", book.fetch_sheet_metadata
            )
            from sheets_continuation import FILE_MARKER_KEY

            role = (
                next(
                    (r for r, b in roots_for(self.store).items() if b == book_id), None
                )
                or self.manager.index.files[book_id]["role"]
            )
            tags = [
                m
                for m in meta.get("developerMetadata", [])
                if m.get("metadataKey") == FILE_MARKER_KEY
            ]
            if (
                len(tags) != 1
                or tags[0].get("visibility") != "DOCUMENT"
                or tags[0].get("location", {}).get("spreadsheet") is not True
            ):
                raise HistoryError("ORIGEM_DO_ARQUIVO_NAO_COMPROVADA")
            try:
                stamp = json.loads(tags[0]["metadataValue"])
            except (ValueError, KeyError):
                raise HistoryError("MARCADOR_DE_ORIGEM_INVALIDO") from None
            if any(
                stamp.get(k) != v
                for k, v in {
                    "hub": self.store._hub_id,
                    "segment": context["segment"],
                    "role": role,
                }.items()
            ):
                raise HistoryError("ARQUIVO_DE_OUTRA_MARCA_OU_PAPEL")
            books[book_id] = allocated_cells(meta)
            layouts[book_id] = meta
            access = self._drive(book_id)
            if (
                access.get("trashed")
                or access.get("capabilities", {}).get("canEdit") is not True
            ):
                raise HistoryError("ARQUIVO_SEM_PERMISSAO_DE_EDICAO")
            versions[book_id] = access.get("version")
            access_proofs[book_id] = sorted(access.get("parents", []))
            if versions[book_id] is None:
                raise HistoryError("VERSAO_FISICA_DO_ARQUIVO_INDISPONIVEL")
        for title, headers in schemas.items():
            self.store._headers_cache[title] = headers
            registered = self.manager.index.table_parts(title)
            root = roots_for(self.store)[storage_role(title)]
            coordinates = {(p.book_id, p.sheet_id) for p in registered}
            for book_id, layout in layouts.items():
                if book_id == root:
                    continue
                if any(
                    s["properties"]["title"] == title
                    and (book_id, s["properties"]["sheetId"]) not in coordinates
                    for s in layout["sheets"]
                ):
                    raise HistoryError("ABA_ORFA_FORA_DO_PAPEL_AUTORIZADO")
            root_sheets = [
                s["properties"]
                for s in layouts[root]["sheets"]
                if s["properties"]["title"] == title
            ]
            if (
                registered
                and root_sheets
                and not any(
                    p.book_id == root and p.sheet_id == root_sheets[0]["sheetId"]
                    for p in registered
                )
            ):
                raise HistoryError("ABA_RAIZ_ORFA_FORA_DO_MANIFESTO")
            if not registered and root_sheets:
                from sheets_continuation import Part

                registered = [
                    Part(
                        title,
                        0,
                        root,
                        root_sheets[0]["sheetId"],
                        len(headers),
                        fingerprint(headers),
                    )
                ]
            state = self.manager.index.status.get(title)
            if state and state["state"] != "READY":
                raise HistoryError("TABELA_EM_PUBLICACAO")
            for part in registered:
                ws = self.manager.worksheet(part)
                self._header(ws, headers)
                if part.schema != fingerprint(headers):
                    raise HistoryError("CABECALHO_DIVERGENTE")
                known = (
                    next(
                        (
                            v["rows"]
                            for v in state["parts"]
                            if v["number"] == part.number
                        ),
                        None,
                    )
                    if state
                    else None
                )
                parts.append(
                    dict(
                        title=title,
                        number=part.number,
                        book=part.book_id,
                        sheet=part.sheet_id,
                        width=len(headers),
                        cols=ws.col_count,
                        allocated_rows=ws.row_count,
                        used_rows=1,
                        confirmed_rows=known,
                    )
                )
        return dict(
            context=context,
            manifest=manifest,
            parts=parts,
            books=books,
            layouts=layouts,
            index_rows=self.manager.sheet.row_count,
            index_sheet=self.manager.sheet.id,
            index_used=len(self.manager.index.values()),
            versions=versions,
            access_proofs=access_proofs,
            roots=roots_for(self.store),
            threshold=config["threshold"],
            max_rows=config["max_part_rows"],
        )

    def verify_snapshot(self, metadata):
        if self.manifest() != metadata["manifest"]:
            raise HistoryError("MANIFESTO_MUDOU_DURANTE_LEITURA")
        if any(
            self._drive(book).get("version") != version
            for book, version in metadata["versions"].items()
        ):
            raise HistoryError("ARQUIVO_MUDOU_DURANTE_LEITURA")

    def capacity_reserve(self, capacity, metadata):
        # Manifesto, arquivos, estados e uma intenção de criação por vez.
        needed = (
            metadata["index_used"]
            + 2 * len(capacity["creations"])
            + len(self.schemas)
            + 2
        )
        if needed >= 10000:
            raise HistoryError("INDICE_EXCEDE_LIMITE_DO_CONECTOR")
        growth = max(0, needed - metadata["index_rows"]) * 3
        if metadata["books"][self.store._hub_id] + growth > 20_000_000:
            raise HistoryError("INDICE_CONTINUIDADE_SEM_ESPACO")
        return {self.store._hub_id: growth}

    def preflight(self, capacity, metadata):
        self.schemas = (
            {p["title"]: self.schemas.get(p["title"], []) for p in capacity["parts"]}
            if self.schemas
            else self.schemas
        )
        # Uma instância reaberta recebe o registro controlado, nunca campos da revisão.
        if not self.schemas or any(not v for v in self.schemas.values()):
            from order_history_sheets import SCHEMAS

            self.schemas = SCHEMAS
        if self.context() != metadata["context"]:
            raise HistoryError("DESTINOS_ALTERADOS")
        self._capacity = capacity
        self._existing = metadata["parts"]
        configured = self.manager.index.config
        for planned in capacity["creations"]:
            title = planned["title"]
            if title not in configured["connector_tables"]:
                raise HistoryError(
                    "FONTE_NAO_CONFIRMADA_NO_CONECTOR: atualize o conector e confirme a tabela no armazenamento"
                )
            if planned["book"].startswith("new:"):
                if self.manager.provider is None:
                    self.manager.provider = self.manager.provider_factory()
                role = storage_role(title)
                proof = self.manager.provider.prepare_intent(
                    metadata["roots"][role],
                    "0" * 32,
                    hub=self.store._hub_id,
                    segment=metadata["context"]["segment"],
                    role=role,
                    number=1,
                )
                # Esta leitura comprova OAuth, pasta e compartilhamentos antes
                # da primeira escrita. _create_part reconfirma na criação.
                expected = metadata.setdefault("permissions", {}).get(role)
                current = dict(
                    parents=sorted(proof["parents"]),
                    permissions=sorted(
                        proof["permissions"],
                        key=lambda p: (p["type"], p["emailAddress"]),
                    ),
                )
                if expected is not None and current != expected:
                    raise HistoryError("PASTA_OU_PERMISSOES_ALTERADAS")
                metadata["permissions"][role] = current
        # A capacidade física pode ter sido consumida por uma edição externa.
        # O writer reconfere crescimento exato antes de cada reserva.
        for book_id in metadata["books"]:
            access = self._drive(book_id)
            if (
                access.get("trashed")
                or access.get("capabilities", {}).get("canEdit") is not True
                or sorted(access.get("parents", []))
                != metadata["access_proofs"][book_id]
            ):
                raise HistoryError("PASTA_OU_PERMISSOES_ALTERADAS")
            book = self.manager._book(book_id)
            meta = self.store._read_with_retry(
                "revalidar grade do arquivo", book.fetch_sheet_metadata
            )
            role = (
                next((r for r, b in metadata["roots"].items() if b == book_id), None)
                or self.manager.index.files[book_id]["role"]
            )
            self._origin(meta, role)
            previous = {
                s["properties"]["sheetId"]: s["properties"]
                for s in metadata["layouts"][book_id]["sheets"]
            }
            targets = {
                (p.get("sheet"), p["title"]): p
                for p in capacity["parts"]
                if p["book"] == book_id
            }
            for s in meta["sheets"]:
                p = s["properties"]
                old = previous.get(p["sheetId"])
                if old is None:
                    if not any(
                        v["title"] == p["title"] and v.get("create")
                        for v in targets.values()
                    ):
                        raise HistoryError("ABA_NAO_PREVISTA_APOS_REVISAO")
                    continue
                desired = targets.get((p["sheetId"], p["title"]))
                allowed = deepcopy(old)
                if (
                    book_id == self.store._hub_id
                    and p["sheetId"] == metadata["index_sheet"]
                ):
                    maximum = (
                        metadata["index_rows"]
                        + capacity.get("reserved_index_cells", {}).get(book_id, 0) // 3
                    )
                    if (
                        not metadata["index_rows"]
                        <= p["gridProperties"]["rowCount"]
                        <= maximum
                        or p["gridProperties"]["columnCount"] != 3
                    ):
                        raise HistoryError("GRADE_DO_INDICE_ALTERADA")
                    allowed["gridProperties"]["rowCount"] = p["gridProperties"][
                        "rowCount"
                    ]
                if desired:
                    grid = p["gridProperties"]
                    before = old["gridProperties"]
                    if (
                        grid["columnCount"] != before["columnCount"]
                        or not before["rowCount"]
                        <= grid["rowCount"]
                        <= desired["allocated_rows"]
                    ):
                        raise HistoryError("GRADE_ALTERADA_APOS_REVISAO")
                    allowed["gridProperties"]["rowCount"] = grid["rowCount"]
                if allowed != p:
                    raise HistoryError("ESTRUTURA_ALTERADA_APOS_REVISAO")
            if len(meta["sheets"]) < len(previous):
                raise HistoryError("ABA_REMOVIDA_APOS_REVISAO")
        # Na retomada, arquivos criados por este plano já podem estar no
        # manifesto, mas ainda não existiam no snapshot de capacidade.
        approved = {(p["title"], p["number"]): p for p in capacity["parts"]}
        for book_id in set(self.manager.index.files) - set(metadata["books"]):
            role = self.manager.index.files[book_id]["role"]
            meta = self.store._read_with_retry(
                "revalidar continuação criada pelo plano",
                self.manager._book(book_id).fetch_sheet_metadata,
            )
            self._origin(meta, role)
            access = self._drive(book_id)
            proof = metadata.get("permissions", {}).get(role)
            if (
                not proof
                or access.get("trashed")
                or access.get("capabilities", {}).get("canEdit") is not True
                or sorted(access.get("parents", [])) != proof["parents"]
            ):
                raise HistoryError("PASTA_OU_PERMISSOES_ALTERADAS")
            parts = [
                p for p in self.manager.index.parts.values() if p.book_id == book_id
            ]
            if len(meta["sheets"]) != len(parts):
                raise HistoryError("ABA_ORFA_NA_CONTINUACAO")
            for p in parts:
                plan = approved.get((p.title, p.number))
                if not plan or not plan["book"].startswith("new:"):
                    raise HistoryError("PARTE_NAO_PREVISTA_APOS_REVISAO")
                props = next(
                    (
                        s["properties"]
                        for s in meta["sheets"]
                        if s["properties"]["sheetId"] == p.sheet_id
                    ),
                    None,
                )
                if (
                    not props
                    or props["title"] != p.title
                    or props["gridProperties"]["columnCount"] != p.width
                    or not 1
                    <= props["gridProperties"]["rowCount"]
                    <= plan["allocated_rows"]
                ):
                    raise HistoryError("GRADE_ALTERADA_APOS_REVISAO")

    def verify_reconciliation(self, capacity, metadata, revision):
        """Somente leitura de origens/grades/intenção; não adota ou cria partes."""
        from sheets_partitions import _empty_creation_values

        self.manager.require()
        self.preflight(capacity, metadata)
        for book_id, layout in metadata["layouts"].items():
            current_layout = self.store._read_with_retry(
                "conferir inventário original da reconciliação",
                self.manager._book(book_id).fetch_sheet_metadata,
            )
            if {s["properties"]["sheetId"] for s in current_layout["sheets"]} != {
                s["properties"]["sheetId"] for s in layout["sheets"]
            }:
                raise HistoryError("RECONCILIACAO_NAO_ACEITA_ABAS_NOVAS_NA_RAIZ")
        expected = {
            (p["title"], p["number"], p["book"], p["sheet"]) for p in metadata["parts"]
        }
        actual = {
            (p.title, p.number, p.book_id, p.sheet_id)
            for p in self.manager.index.parts.values()
            if p.title in self.schemas
        }
        if not actual <= expected or set(self.manager.index.files) - set(
            metadata["books"]
        ):
            raise HistoryError("RECONCILIACAO_NAO_ACEITA_PARTES_JA_ATIVADAS")
        publication = self.manager.index.config.get("history_publication", {})
        if publication and publication != dict(state="WRITING", revision=revision):
            raise HistoryError("OUTRA_PUBLICACAO_EM_ANDAMENTO")
        approved = {f"{p['title']}#{p['number']}": p for p in capacity["creations"]}
        proofs = []
        for key, intent in self.manager.index.intents.items():
            planned = approved.get(key)
            if (
                not planned
                or not planned["book"].startswith("new:")
                or intent.get("table") != planned["title"]
                or intent.get("part") != planned["number"]
                or intent.get("schema") != fingerprint(self.schemas[planned["title"]])
                or intent.get("source")
                != metadata["roots"][storage_role(planned["title"])]
                or intent.get("hub") != self.manager.index.config["hub"]
                or intent.get("segment") != self.context()["segment"]
                or intent.get("role") != storage_role(planned["title"])
                or not intent.get("file_id")
                or intent.get("create_state") != "sending"
            ):
                raise HistoryError("INTENCAO_NAO_COMPROVADA_PARA_RECONCILIACAO")
            if self.manager.provider is None:
                self.manager.provider = self.manager.provider_factory()
            provider = self.manager.provider
            file_id = intent["file_id"]
            if provider.locate(intent["operation"]) != file_id:
                raise HistoryError("ARQUIVO_DA_OPERACAO_NAO_COMPROVADO")
            provider.verify_owned(file_id, intent)
            current = provider.prepare_intent(
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

            if current["parents"] != intent["parents"] or permissions(
                current
            ) != permissions(intent):
                raise HistoryError("PASTA_OU_PERMISSOES_ALTERADAS")
            provider.verify(
                file_id,
                hub=intent["hub"],
                segment=intent["segment"],
                role=intent["role"],
            )
            access = provider.verify_private_access(file_id, intent)
            book = self.store._read_with_retry(
                "abrir candidata da reconciliação",
                lambda file_id=file_id: self.store.client.open_by_key(file_id),
            )
            sheets = self.store._read_with_retry(
                "conferir candidata da reconciliação", book.worksheets
            )
            if len(sheets) != 1:
                raise HistoryError("CANDIDATA_COM_ABAS_INESPERADAS")
            ws = sheets[0]
            values = self.store._read_with_retry(
                "ler candidata sem calcular fórmulas",
                lambda ws=ws: ws.get_all_values(value_render_option="FORMULA"),
            )
            if not _empty_creation_values(values) and not (
                ws.title == planned["title"]
                and values == [self.schemas[planned["title"]]]
            ):
                raise HistoryError("CANDIDATA_CONTEM_FATOS_OU_FORMULAS")
            self.manager._check_creation_structure(book, ws)
            proofs.append(
                dict(
                    intent=fingerprint(intent),
                    access=access,
                    grid=self.store_column_proof(ws),
                )
            )
        self.manager.require()
        return proofs

    @staticmethod
    def store_column_proof(ws):
        return dict(
            sheet=ws.id, title=ws.title, rows=ws.row_count, columns=ws.col_count
        )

    def begin(self, revision, schemas):
        self.schemas = schemas
        state = self.manager.index.config.get("history_publication", {})
        if state.get("state") == "WRITING" and state.get("revision") != revision:
            raise HistoryError("OUTRA_PUBLICACAO_EM_ANDAMENTO")
        if state == dict(state="WRITING", revision=revision):
            return
        self.manager.index.config["history_publication"] = dict(
            state="WRITING", revision=revision
        )
        for raw in self._existing:
            if not self.manager.index.table_parts(raw["title"]):
                self.manager.register_root(self._physical(raw), schemas[raw["title"]])
        for title in schemas:
            if self.manager.index.table_parts(title):
                self.manager.index.status[title] = dict(
                    state="WRITING", revision=revision
                )
        self.manager.save()

    def ensure_part(self, planned, headers):
        title = planned["title"]
        number = planned["number"]
        known = self.manager.index.table_parts(title)
        if len(known) > number:
            part = known[number]
            ws = self.manager.worksheet(part)
        elif planned["book"].startswith("new:"):
            created = self.manager._create_part(title, headers)
            part, ws = created.part, created.worksheet
        else:
            book = self.manager._book(planned["book"])
            try:
                ws = book.worksheet(title)
            except WorksheetNotFound:
                ws = self.store._write_with_retry(
                    "criar cabeçalho histórico reservado",
                    lambda: book.add_worksheet(title=title, rows=1, cols=len(headers)),
                )
            values = self.store._read_with_retry(
                "conferir adoção de cabeçalho",
                lambda: ws.get(
                    f"A1:{self.manager.store_column(len(headers))}1",
                    value_render_option="FORMULA",
                ),
            )
            if values not in ([], [headers]):
                raise HistoryError("ABA_CRIADA_COM_CONTEUDO_DIVERGENTE")
            if values == []:
                self.store._write_with_retry(
                    "cabeçalho histórico",
                    lambda: ws.update(
                        range_name=f"A1:{self.manager.store_column(len(headers))}1",
                        values=[headers],
                        value_input_option="RAW",
                    ),
                )
            part = self.manager.register_root(ws, headers)[0]
            self.manager.index.status[title] = dict(
                state="WRITING",
                revision=self.manager.index.config["history_publication"]["revision"],
            )
            self.manager.save()
        if part.schema != fingerprint(headers):
            raise HistoryError("SCHEMA_ALTERADO_NA_CRIACAO")
        return dict(
            title=title,
            number=number,
            book=part.book_id,
            sheet=part.sheet_id,
            width=len(headers),
            cols=ws.col_count,
            allocated_rows=ws.row_count,
            used_rows=1,
        )

    def _header(self, ws, headers):
        raw = self.store._read_with_retry(
            "conferir cabeçalho físico completo",
            lambda: ws.get(
                f"A1:{self.manager.store_column(ws.col_count)}1",
                value_render_option="FORMULA",
            ),
        )
        actual = list(raw[0]) if raw else []
        while actual and actual[-1] in ("", None):
            actual.pop()
        if actual != headers:
            raise HistoryError("CABECALHO_ALTERADO_APOS_REVISAO")

    def scan(self, part, headers):
        self.manager.handles.pop((part["book"], part["sheet"]), None)
        ws = self._physical(part)
        self._header(ws, headers)
        # Uma varredura por fase, em blocos; não get_all_values por lote.
        for start in range(2, ws.row_count + 1, 2000):
            if self.writing:
                self.manager.require()
            end = min(ws.row_count, start + 1999)
            data = self.store._read_with_retry(
                "ler bloco do histórico",
                lambda start=start, end=end: ws.get(
                    f"A{start}:{self.manager.store_column(ws.col_count)}{end}",
                    value_render_option="FORMULA",
                ),
            )
            for offset, row in enumerate(data):
                cells = list(row)
                while cells and cells[-1] in ("", None):
                    cells.pop()
                yield start + offset, cells

    def read_rows(self, part, headers, positions):
        self.manager.require()
        ws = self._physical(part)
        self._header(ws, headers)
        ranges = [
            f"'{part['title']}'!A{r}:{self.manager.store_column(len(headers))}{r}"
            for r in positions
        ]
        result = self.store._read_with_retry(
            "conferir intervalos do lote",
            lambda: self.manager._book(part["book"]).values_batch_get(
                ranges, params={"valueRenderOption": "FORMULA"}
            ),
        )
        groups = result.get("valueRanges", [])
        if len(groups) != len(positions):
            raise HistoryError("RESPOSTA_DE_INTERVALOS_INCOMPLETA")
        rows = []
        for group in groups:
            values = group.get("values", [])
            cells = values[0] if values else []
            if len(values) > 1 or len(cells) > len(headers):
                raise HistoryError("INTERVALO_DIVERGENTE")
            rows.append(
                normalized_cells(
                    dict(
                        zip(
                            headers,
                            cells + [""] * (len(headers) - len(cells)),
                            strict=True,
                        )
                    )
                )
                if any(v not in ("", None) for v in cells)
                else None
            )
        return rows

    def geometry(self, part):
        book = self.manager._book(part["book"])
        meta = self.store._read_with_retry(
            "conferir estrutura do backup de lote", book.fetch_sheet_metadata
        )
        p = next(
            s["properties"]
            for s in meta["sheets"]
            if s["properties"]["sheetId"] == part["sheet"]
        )
        if p["title"] != part["title"]:
            raise HistoryError("PARTE_RENOMEADA")
        return dict(
            rows=p["gridProperties"]["rowCount"],
            columns=p["gridProperties"]["columnCount"],
        )

    def write_rows(self, part, headers, entries, *, field):
        self.manager.require()
        ws = self._physical(part)
        book = self.manager._book(part["book"])
        maximum = max(e["row"] for e in entries)
        meta = self.store._read_with_retry(
            "capacidade antes da reserva do lote", book.fetch_sheet_metadata
        )
        props = next(
            s["properties"]
            for s in meta["sheets"]
            if s["properties"]["sheetId"] == ws.id
        )
        actual_rows = props["gridProperties"]["rowCount"]
        actual_cols = props["gridProperties"]["columnCount"]
        if actual_cols != part["cols"]:
            raise HistoryError("COLUNAS_ALTERADAS_APOS_REVISAO")
        if maximum > actual_rows:
            if (
                allocated_cells(meta) + (maximum - actual_rows) * actual_cols
                > self.manager.index.config["threshold"]
            ):
                raise HistoryError("CAPACIDADE_CONSUMIDA_APOS_REVISAO")
            self.store._write_with_retry(
                "reservar coordenadas do lote", lambda: ws.resize(rows=maximum)
            )
        requests = []
        for entry in entries:
            row = typed_cells(entry[field]) if entry[field] is not None else {}
            cells = []
            for name in headers:
                value = row.get(name, "")
                cells.append(
                    {
                        "userEnteredValue": {"numberValue": value}
                        if isinstance(value, (int, float))
                        else {"stringValue": str(value)}
                    }
                )
            requests.append(
                {
                    "updateCells": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": entry["row"] - 1,
                            "endRowIndex": entry["row"],
                            "startColumnIndex": 0,
                            "endColumnIndex": len(headers),
                        },
                        "rows": [{"values": cells}],
                        "fields": "userEnteredValue",
                    }
                }
            )
        # Não usar retries de inserção. O journal e as coordenadas determinísticas
        # reconciliam respostas incertas antes de uma nova tentativa.
        self.store._wait_before_write()
        self.store._write_requests += 1
        try:
            book.batch_update({"requests": requests})
        except Exception as exc:
            from gspread.exceptions import APIError

            if not isinstance(exc, APIError) or exc.response.status_code not in (
                400,
                401,
                403,
                404,
                409,
                429,
            ):
                self.manager.lease.note_uncertain()
            raise

    def finish(self, revision, parts):
        for title in self.schemas:
            counts = []
            for p in sorted(
                (p for p in parts if p["title"] == title), key=lambda p: p["number"]
            ):
                rows = sum(
                    1
                    for _, r in self.scan(p, self.schemas[title])
                    if any(v not in ("", None) for v in r)
                )
                counts.append(dict(number=p["number"], rows=rows))
            self.manager.index.status[title] = dict(
                state="READY", revision=revision, parts=counts
            )
        self.manager.index.config["history_publication"] = dict(
            state="READY", revision=revision
        )
        self.manager.save()
