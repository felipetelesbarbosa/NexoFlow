"""Publicação revisada com índice em disco e comprovantes por intervalo.

O transporte é uma porta explícita para Sheets: testes nunca abrem rede.
As linhas, coordenadas e backups deste módulo são sempre diagnósticos privados.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from dedup_io import save_private
from history_capacity import allocate
from order_history import HistoryError, digest
from order_history_sheets import NUMERIC, SCHEMAS, normalized_cells

FORMAT = "historico_publicacao_v2"
BATCH_ROWS = 200
DDL = """
CREATE TABLE meta(k TEXT PRIMARY KEY,v TEXT NOT NULL);
CREATE TABLE incoming(t TEXT,k TEXT,v TEXT,PRIMARY KEY(t,k));
CREATE TABLE baseline(t TEXT,k TEXT,p INTEGER,r INTEGER,v TEXT,PRIMARY KEY(t,k),UNIQUE(t,p,r));
CREATE TABLE operations(t TEXT,k TEXT,p INTEGER,r INTEGER,b TEXT,a TEXT,batch INTEGER,PRIMARY KEY(t,k),UNIQUE(t,p,r));
CREATE TABLE batches(n INTEGER PRIMARY KEY,t TEXT,p INTEGER,body TEXT,state TEXT DEFAULT 'pending');
"""


def put(db, key, value):
    db.execute(
        "INSERT OR REPLACE INTO meta VALUES(?,?)",
        (key, json.dumps(value, ensure_ascii=False)),
    )
    db.commit()


def get(db, key) -> Any:
    row = db.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def pack(title, row, segment):
    if (
        set(row) != set(SCHEMAS[title])
        or row["segmento"] != segment
        or not row["chave"]
    ):
        raise HistoryError("LINHA_OU_SEGMENTO_INVALIDO")
    if any(
        not isinstance(value, str) for key, value in row.items() if key not in NUMERIC
    ):
        raise HistoryError("CAMPO_TEXTO_COM_TIPO_INVALIDO")
    if row["vigente"] not in ("Sim", "Não") or (
        title == "Historico_Itens" and row["frete"] not in ("Sim", "Não")
    ):
        raise HistoryError("MARCADOR_HISTORICO_INVALIDO")
    return json.dumps(normalized_cells(row), sort_keys=True, ensure_ascii=False)


def rows_hash(db, table):
    result = hashlib.sha256()
    for title, key, raw in db.execute(f"SELECT t,k,v FROM {table} ORDER BY t,k"):
        result.update(json.dumps([title, key, raw], ensure_ascii=False).encode())
    return result.hexdigest()


def publisher_signature():
    root = Path(__file__).parent
    files = [
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
    ]
    return digest(
        {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}
    )


def journal_signature(db):
    result = hashlib.sha256()
    for query in (
        "SELECT t,k,p,r,v FROM baseline ORDER BY t,k",
        "SELECT t,k,p,r,b,a,batch FROM operations ORDER BY t,k",
        "SELECT n,t,p,body FROM batches ORDER BY n",
    ):
        for row in db.execute(query):
            result.update(json.dumps(list(row), ensure_ascii=False).encode())
    return result.hexdigest()


def add_retirements(db, segment, evidence):
    for title, key, raw in db.execute(
        "SELECT b.t,b.k,b.v FROM baseline b LEFT JOIN incoming i ON i.t=b.t AND i.k=b.k WHERE i.k IS NULL"
    ):
        row = json.loads(raw)
        if title == "Historico_Pedidos" and row["vigente"] != "Não":
            exceptions = (evidence or {}).get("publication_exclusions", [])
            fields = (
                "segmento",
                "pedido_id",
                "cliente_id",
                "data",
                "estado",
                "produtos",
                "frete",
                "faturamento",
            )
            actual = normalized_cells({field: row[field] for field in fields})
            authorized = any(
                entry.get("segmento") == segment
                and entry.get("pedido_id") == row["pedido_id"]
                and normalized_cells(entry.get("pedido_original", {})) == actual
                for entry in exceptions
            )
            if not authorized:
                raise HistoryError("BASE_LOCAL_INCOMPLETA_RECONCILIAR")
        row["vigente"] = "Não"
        db.execute(
            "INSERT INTO incoming VALUES(?,?,?)",
            (title, key, pack(title, row, segment)),
        )


class Publication:
    def __init__(self, remote, segment, directory):
        if segment not in ("FARMA", "PET"):
            raise HistoryError("SEGMENTO_INVALIDO")
        self.remote, self.segment, self.directory = remote, segment, Path(directory)

    def prepare(self, rows, *, evidence=None):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        revision = uuid4().hex
        directory = self.directory / revision
        directory.mkdir(mode=0o700)
        path = directory / "plano.sqlite"
        with closing(sqlite3.connect(path)) as db:
            path.chmod(0o600)
            db.executescript(DDL)
            metadata = self.remote.describe(SCHEMAS)
            if metadata["context"]["segment"] != self.segment:
                raise HistoryError("DESTINO_DE_OUTRO_SEGMENTO")
            for title, row in rows:
                if title not in SCHEMAS:
                    raise HistoryError("TABELA_NAO_AUTORIZADA")
                raw = pack(title, row, self.segment)
                try:
                    db.execute(
                        "INSERT INTO incoming VALUES(?,?,?)", (title, row["chave"], raw)
                    )
                except sqlite3.IntegrityError:
                    raise HistoryError("CHAVE_LOCAL_DUPLICADA") from None
            db.commit()
            for part in metadata["parts"]:
                title = part["title"]
                used = 1
                count = 0
                for position, cells in self.remote.scan(part, SCHEMAS[title]):
                    if not any(value not in ("", None) for value in cells):
                        continue
                    if position != used + 1 or len(cells) > len(SCHEMAS[title]):
                        raise HistoryError("LACUNA_OU_LINHA_FISICA_INVALIDA")
                    row = dict(
                        zip(
                            SCHEMAS[title],
                            cells + [""] * (len(SCHEMAS[title]) - len(cells)),
                            strict=True,
                        )
                    )
                    raw = pack(title, row, self.segment)
                    try:
                        db.execute(
                            "INSERT INTO baseline VALUES(?,?,?,?,?)",
                            (title, str(row["chave"]), part["number"], position, raw),
                        )
                    except sqlite3.IntegrityError:
                        raise HistoryError("CHAVE_REMOTA_DUPLICADA") from None
                    used = position
                    count += 1
                if (
                    part.get("confirmed_rows") is not None
                    and part["confirmed_rows"] != count
                ):
                    raise HistoryError("CONTAGEM_MANIFESTO_DIVERGENTE")
                part["used_rows"] = used
            db.commit()
            verify_snapshot = getattr(self.remote, "verify_snapshot", None)
            if verify_snapshot is not None:
                verify_snapshot(metadata)
            input_digest = rows_hash(db, "incoming")
            add_retirements(db, self.segment, evidence)
            db.commit()
            additions = {
                title: db.execute(
                    "SELECT count(*) FROM incoming i LEFT JOIN baseline b ON b.t=i.t AND b.k=i.k WHERE i.t=? AND b.k IS NULL",
                    (title,),
                ).fetchone()[0]
                for title in SCHEMAS
            }
            capacity = allocate(
                SCHEMAS,
                additions,
                metadata["parts"],
                metadata["books"],
                metadata["roots"],
                threshold=metadata["threshold"],
                max_rows=metadata["max_rows"],
            )
            reserve = getattr(self.remote, "capacity_reserve", None)
            if reserve is not None:
                for _ in range(10):
                    reserved = reserve(capacity, metadata)
                    books = {
                        book: cells + reserved.get(book, 0)
                        for book, cells in metadata["books"].items()
                    }
                    revised = allocate(
                        SCHEMAS,
                        additions,
                        metadata["parts"],
                        books,
                        metadata["roots"],
                        threshold=metadata["threshold"],
                        max_rows=metadata["max_rows"],
                    )
                    revised["reserved_index_cells"] = reserved
                    if revised == capacity:
                        break
                    capacity = revised
                else:
                    raise HistoryError("PLANO_DE_CAPACIDADE_NAO_ESTABILIZOU")
            self.remote.preflight(capacity, metadata)
            for title in SCHEMAS:
                for key, raw, p, r, before in db.execute(
                    "SELECT i.k,i.v,b.p,b.r,b.v FROM incoming i LEFT JOIN baseline b ON b.t=i.t AND b.k=i.k WHERE i.t=? AND b.k IS NOT NULL AND i.v!=b.v ORDER BY b.p,b.r",
                    (title,),
                ):
                    db.execute(
                        "INSERT INTO operations(t,k,p,r,b,a) VALUES(?,?,?,?,?,?)",
                        (title, key, p, r, before, raw),
                    )
                cursor = db.execute(
                    "SELECT i.k,i.v FROM incoming i LEFT JOIN baseline b ON b.t=i.t AND b.k=i.k WHERE i.t=? AND b.k IS NULL ORDER BY i.k",
                    (title,),
                )
                for reservation in capacity["ranges"][title]:
                    for position in range(
                        reservation["start"], reservation["start"] + reservation["rows"]
                    ):
                        key, raw = next(cursor)
                        db.execute(
                            "INSERT INTO operations(t,k,p,r,b,a) VALUES(?,?,?,?,?,?)",
                            (title, key, reservation["part"], position, "null", raw),
                        )
            seq = 0
            for title in SCHEMAS:
                pending: list[dict[str, Any]] = []
                part = None
                size = 0

                def flush(title, part):
                    nonlocal seq, pending, size
                    if pending:
                        seq += 1
                        db.execute(
                            "INSERT INTO batches(n,t,p,body) VALUES(?,?,?,?)",
                            (seq, title, part, json.dumps(pending, ensure_ascii=False)),
                        )
                        db.executemany(
                            "UPDATE operations SET batch=? WHERE t=? AND p=? AND r=?",
                            [(seq, title, part, e["row"]) for e in pending],
                        )
                        pending = []
                        size = 0

                for p, r, b, a in db.execute(
                    "SELECT p,r,b,a FROM operations WHERE t=? ORDER BY p,r", (title,)
                ):
                    entry = dict(row=r, before=json.loads(b), after=json.loads(a))
                    width = len(json.dumps(entry, ensure_ascii=False).encode())
                    if width > 1_000_000:
                        raise HistoryError("LINHA_EXCEDE_LIMITE_DE_LOTE")
                    if (
                        p != part
                        or len(pending) >= BATCH_ROWS
                        or size + width > 1_000_000
                    ):
                        flush(title, part)
                        part = p
                    pending.append(entry)
                    size += width
                flush(title, part)
            db.commit()
            stats = {}
            for title in SCHEMAS:
                stats[title] = dict(
                    inserted=additions[title],
                    updated=db.execute(
                        "SELECT count(*) FROM operations WHERE t=? AND b!='null' AND json_extract(a,'$.vigente')='Sim'",
                        (title,),
                    ).fetchone()[0],
                    inactivated=db.execute(
                        "SELECT count(*) FROM operations WHERE t=? AND json_extract(a,'$.vigente')='Não'",
                        (title,),
                    ).fetchone()[0],
                    unchanged=db.execute(
                        "SELECT count(*) FROM incoming i JOIN baseline b ON b.t=i.t AND b.k=i.k WHERE i.t=? AND i.v=b.v",
                        (title,),
                    ).fetchone()[0],
                )
            for book in capacity["books"]:
                book["before"] = metadata["books"].get(book["book"], 0)
            review: dict[str, Any] = dict(
                format=FORMAT,
                publisher_signature=publisher_signature(),
                journal_signature=journal_signature(db),
                metadata_signature=digest(metadata),
                table_stats=stats,
                revision=revision,
                segment=self.segment,
                context=metadata["context"],
                source_digest=rows_hash(db, "incoming"),
                journal=str(path.resolve()),
                input_digest=input_digest,
                capacity=capacity,
                batches=seq,
                changed_rows=db.execute("SELECT count(*) FROM operations").fetchone()[
                    0
                ],
                evidence=evidence or {},
                batch_hashes=[
                    digest([t, p, body])
                    for t, p, body in db.execute(
                        "SELECT t,p,body FROM batches ORDER BY n"
                    )
                ],
            )
            if review["evidence"].get("conference"):
                from history_conference import compare, from_published, summarize

                prepared = summarize(from_published(db, "incoming"), self.segment)
                if compare(review["evidence"]["conference"], prepared)["diferencas"]:
                    raise HistoryError("TRANSFORMACAO_DIVERGE_DO_SQLITE")
            review["digest"] = digest(review)
            put(db, "review", review)
            put(db, "metadata", metadata)
            put(db, "manifest", metadata["manifest"])
            put(db, "parts", metadata["parts"])
            put(db, "started", False)
            return review

    def verify_input(self, rows, review):
        with closing(sqlite3.connect("")) as db:
            db.execute("CREATE TABLE incoming(t TEXT,k TEXT,v TEXT,PRIMARY KEY(t,k))")
            for title, row in rows:
                db.execute(
                    "INSERT INTO incoming VALUES(?,?,?)",
                    (title, row["chave"], pack(title, row, self.segment)),
                )
            if rows_hash(db, "incoming") != review["input_digest"]:
                raise HistoryError("DADOS_ALTERADOS_APOS_REVISAO")

    def _open_local(self, review):
        if review.get("format") != FORMAT or review.get("segment") != self.segment:
            raise HistoryError("REVISAO_INCOMPATIVEL_PREPARAR_NOVAMENTE")
        original = dict(review)
        checksum = original.pop("digest", None)
        if checksum != digest(original):
            raise HistoryError("REVISAO_ALTERADA")
        path = Path(review["journal"]).resolve()
        # Uma revisão não pode apontar a um banco de outro diretório privado.
        if not path.is_relative_to(self.directory.resolve()):
            raise HistoryError("JOURNAL_FORA_DO_DIRETORIO_PRIVADO")
        source = review.get("evidence", {})
        if source.get("path"):
            from history_snapshot import sha256

            if sha256(source["path"]) != source["sha256"]:
                raise HistoryError("COPIA_SQLITE_ALTERADA_APOS_REVISAO")
        db = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)
        if (
            get(db, "review") != review
            or rows_hash(db, "incoming") != review["source_digest"]
            or journal_signature(db) != review["journal_signature"]
            or digest(get(db, "metadata")) != review["metadata_signature"]
        ):
            db.close()
            raise HistoryError("PLANO_LOCAL_ALTERADO")
        return db

    def _open(self, review):
        db = self._open_local(review)
        current = publisher_signature()
        if review.get("publisher_signature") != current:
            from history_reconciliation import compatible

            if not compatible(db, review, current):
                db.close()
                raise HistoryError(
                    "PUBLICADOR_ALTERADO: retome com o código da revisão ou reconcilie o plano antes de preparar outra revisão"
                )
        return db

    def _binding(self, db):
        """Duas fases também para o manifesto, inclusive queda entre POST e recibo."""
        actual = self.remote.manifest()
        expected = get(db, "manifest")
        pending = get(db, "manifest_pending")
        if actual == pending:
            put(db, "manifest", actual)
            put(db, "manifest_pending", None)
        elif actual != expected:
            raise HistoryError("MANIFESTO_ALTERADO_APOS_REVISAO")
        if self.remote.context() != get(db, "review")["context"]:
            raise HistoryError("DESTINOS_ALTERADOS")
        self.remote.bind(
            before=lambda value: put(db, "manifest_pending", value),
            after=lambda value: (
                put(db, "manifest", value),
                put(db, "manifest_pending", None),
            ),
        )

    def apply(self, review, *, max_batches=None):
        if max_batches is not None and (
            type(max_batches) is not int or max_batches < 1
        ):
            raise HistoryError("MAX_LOTES_INVALIDO")
        started_at = perf_counter()
        service = getattr(self.remote, "store", None)
        before_reads = getattr(service, "_read_requests", 0)
        before_writes = getattr(service, "_write_requests", 0)
        with closing(self._open(review)) as db:
            self._binding(db)
            self.remote.acquire()
            # Transporte valida novamente pasta, permissões e capacidade antes
            # de inicializar qualquer tabela ou criar continuação.
            self.remote.preflight(review["capacity"], get(db, "metadata"))
            if not review["changed_rows"] and not review["capacity"]["creations"]:
                self._verify_current(db, get(db, "parts"), complete=True)
                return dict(
                    applied_rows=0,
                    applied_batches=0,
                    remaining_batches=0,
                    status="conferida",
                    revision=review["revision"],
                )
            self._verify_current(db, get(db, "parts"))
            if (
                get(db, "finished")
                and not db.execute(
                    "SELECT 1 FROM batches WHERE state!='done'"
                ).fetchone()
            ):
                self._verify_current(db, get(db, "parts"), complete=True)
                self._conference(db, review, get(db, "parts"))
                return dict(
                    applied_rows=0,
                    applied_batches=0,
                    remaining_batches=0,
                    status="conferida",
                    revision=review["revision"],
                )
            self.remote.begin(review["revision"], SCHEMAS)
            put(db, "started", True)
            parts = get(db, "parts")
            for planned in review["capacity"]["creations"]:
                if any(
                    p["title"] == planned["title"] and p["number"] == planned["number"]
                    for p in parts
                ):
                    continue
                actual = self.remote.ensure_part(planned, SCHEMAS[planned["title"]])
                parts.append(actual)
                put(db, "parts", parts)
            # Índice completo é relido uma vez por retomada; evita duplicidade
            # em outra parte e detecta deslocamento de linhas fora do lote.
            applied = 0
            batches = 0
            written_rows = 0
            reconciled_rows = 0
            for number, title, part, body, state in db.execute(
                "SELECT n,t,p,body,state FROM batches ORDER BY n"
            ):
                if state == "done":
                    continue
                if state == "restoring":
                    raise HistoryError("ROLLBACK_PENDENTE_RETOMAR_ROLLBACK")
                if max_batches is not None and batches >= max_batches:
                    break
                self._binding(db)
                target = next(
                    p for p in parts if p["title"] == title and p["number"] == part
                )
                if digest([title, part, body]) != review["batch_hashes"][number - 1]:
                    raise HistoryError("PLANO_DE_LOTE_ALTERADO")
                entries = json.loads(body)
                before = [e["before"] for e in entries]
                after = [e["after"] for e in entries]
                current = self.remote.read_rows(
                    target, SCHEMAS[title], [e["row"] for e in entries]
                )
                if current == after:
                    if state != "sending":
                        raise HistoryError("LOTE_ALTERADO_SEM_INTENCAO")
                    reconciled_rows += len(entries)
                elif current == before:
                    geometry = getattr(
                        self.remote,
                        "geometry",
                        lambda part: dict(
                            rows=part["allocated_rows"],
                            columns=part.get("cols", part["width"]),
                        ),
                    )(target)
                    backup = dict(
                        format=FORMAT,
                        revision=review["revision"],
                        batch=number,
                        part=target,
                        headers=SCHEMAS[title],
                        entries=entries,
                        geometry_before=geometry,
                        created_rows=max(
                            0, max(e["row"] for e in entries) - geometry["rows"]
                        ),
                        created_part=any(
                            p["title"] == title and p["number"] == part
                            for p in review["capacity"]["creations"]
                        ),
                        before_hash=digest(before),
                        after_hash=digest(after),
                    )
                    save_private(
                        Path(review["journal"]).parent / f"lote_{number:08d}.json",
                        backup,
                    )
                    db.execute(
                        "UPDATE batches SET state='sending' WHERE n=?", (number,)
                    )
                    db.commit()
                    self.remote.write_rows(
                        target, SCHEMAS[title], entries, field="after"
                    )
                    written_rows += len(entries)
                    if (
                        self.remote.read_rows(
                            target, SCHEMAS[title], [e["row"] for e in entries]
                        )
                        != after
                    ):
                        raise HistoryError("GRAVACAO_NAO_CONFIRMADA")
                else:
                    raise HistoryError("CELULAS_ALTERADAS_APOS_REVISAO")
                db.execute("UPDATE batches SET state='done' WHERE n=?", (number,))
                db.commit()
                applied += len(entries)
                batches += 1
            remaining = db.execute(
                "SELECT count(*) FROM batches WHERE state!='done'"
            ).fetchone()[0]
            if not remaining:
                self._verify_current(db, parts, complete=True)
                self._conference(db, review, parts)
                self.remote.finish(review["revision"], parts)
                put(db, "finished", True)
            return dict(
                applied_rows=applied,
                applied_batches=batches,
                remaining_batches=remaining,
                status="pausada" if remaining else "conferida",
                revision=review["revision"],
                written_rows=written_rows,
                reconciled_rows=reconciled_rows,
                seconds=round(perf_counter() - started_at, 3),
                read_attempts=getattr(service, "_read_requests", 0) - before_reads,
                write_attempts=getattr(service, "_write_requests", 0) - before_writes,
                backup_bytes=sum(
                    p.stat().st_size
                    for p in Path(review["journal"]).parent.glob("lote_*.json")
                ),
            )

    def _verify_current(self, db, parts, *, complete=False, tolerant=False):
        """Comparação linear em disco; nunca um snapshot completo por lote."""
        mismatches = {}
        db.execute("DROP TABLE IF EXISTS observed")
        db.execute("CREATE TEMP TABLE observed(t TEXT,k TEXT,v TEXT,PRIMARY KEY(t,k))")
        db.execute("DROP TABLE IF EXISTS visited")
        db.execute(
            "CREATE TEMP TABLE visited(t TEXT,p INTEGER,r INTEGER,PRIMARY KEY(t,p,r))"
        )
        for part in parts:
            title = part["title"]
            # Estado esperado em cada posição já confirmada/sending tem
            # precedência sobre o snapshot-base; novas posições ficam nulas.
            for position, cells in self.remote.scan(part, SCHEMAS[title]):
                db.execute(
                    "INSERT INTO visited VALUES(?,?,?)",
                    (title, part["number"], position),
                )
                old = db.execute(
                    "SELECT v FROM baseline WHERE t=? AND p=? AND r=?",
                    (title, part["number"], position),
                ).fetchone()
                op = db.execute(
                    "SELECT o.a,b.state,b.n FROM operations o JOIN batches b ON b.n=o.batch WHERE o.t=? AND o.p=? AND o.r=?",
                    (title, part["number"], position),
                ).fetchone()
                actual = None
                if any(v not in ("", None) for v in cells):
                    actual = json.loads(
                        pack(
                            title,
                            dict(
                                zip(
                                    SCHEMAS[title],
                                    cells + [""] * (len(SCHEMAS[title]) - len(cells)),
                                    strict=True,
                                )
                            ),
                            self.segment,
                        )
                    )
                before = json.loads(old[0]) if old else None
                expected = json.loads(op[0]) if op and op[1] == "done" else before
                if actual != expected and not (
                    op
                    and op[1] in ("sending", "restoring")
                    and actual == json.loads(op[0])
                ):
                    key = (title, part["number"])
                    trace = mismatches.setdefault(
                        key, dict(table=title, part=part["number"], rows=0, examples=[])
                    )
                    trace["rows"] += 1
                    if len(trace["examples"]) < 3:
                        trace["examples"].append(
                            dict(
                                row=position,
                                batch=op[2] if op else None,
                                expected_hash=digest(expected),
                                observed_hash=digest(actual),
                            )
                        )
                    if not tolerant:
                        save_private(
                            Path(get(db, "review")["journal"]).parent
                            / "divergencia_intervalo.json",
                            dict(
                                scope="primeira divergência; conferência interrompida",
                                parts=list(mismatches.values()),
                            ),
                        )
                        raise HistoryError(
                            "PARTE_ALTERADA_OU_RESPOSTA_INCERTA: consultar divergencia_intervalo.json no pacote privado da revisão"
                        )
                if actual:
                    try:
                        db.execute(
                            "INSERT INTO observed VALUES(?,?,?)",
                            (
                                title,
                                actual["chave"],
                                json.dumps(actual, sort_keys=True, ensure_ascii=False),
                            ),
                        )
                    except sqlite3.IntegrityError:
                        raise HistoryError("CHAVE_DUPLICADA_ENTRE_PARTES") from None
        # O transporte pode omitir linhas fisicamente vazias. Uma linha apagada
        # também é alteração externa, inclusive quando não teria novo POST.
        for title, part, position in db.execute("""
            SELECT b.t,b.p,b.r FROM baseline b LEFT JOIN visited v ON v.t=b.t AND v.p=b.p AND v.r=b.r WHERE v.r IS NULL
            UNION
            SELECT o.t,o.p,o.r FROM operations o JOIN batches b ON b.n=o.batch LEFT JOIN visited v ON v.t=o.t AND v.p=o.p AND v.r=o.r WHERE b.state='done' AND v.r IS NULL
        """):
            if not tolerant:
                raise HistoryError("LINHA_REMOVIDA_APOS_REVISAO")
            trace = mismatches.setdefault(
                (title, part), dict(table=title, part=part, rows=0, examples=[])
            )
            trace["rows"] += 1
            if len(trace["examples"]) < 3:
                trace["examples"].append(dict(row=position, missing=True))
        if complete and rows_hash(db, "observed") != rows_hash(db, "incoming"):
            raise HistoryError("CONFERENCIA_FINAL_DIVERGENTE")
        db.commit()
        self._binding(db)
        if mismatches:
            save_private(
                Path(get(db, "review")["journal"]).parent
                / "divergencia_intervalo.json",
                dict(
                    scope="todas as partes conferidas", parts=list(mismatches.values())
                ),
            )
        return list(mismatches.values())

    def _conference(self, db, review, parts, *, strict=True):
        from decimal import Decimal

        from history_conference import compare, from_published, summarize

        context = dict(
            revision=review["revision"],
            manifest=get(db, "manifest"),
            parts=[dict(table=p["title"], number=p["number"]) for p in parts],
            coverage="plano integral",
            publisher=FORMAT,
        )
        expected = review["evidence"].get("conference") or summarize(
            from_published(db, "incoming"), self.segment, context=context
        )
        observed = summarize(
            from_published(db), self.segment, context=context, tolerate_financial=True
        )
        report = compare(expected, observed)
        total = observed["recortes"][-1]["faturamento_centavos"]
        ltv = 0
        for (raw,) in db.execute("SELECT v FROM observed WHERE t='BI_LTV_Clientes'"):
            row = json.loads(raw)
            if row["vigente"] == "Sim":
                cents = Decimal(row["ltv_observado"]) * 100
                if cents != cents.to_integral_value():
                    raise HistoryError("LTV_FORA_DE_CENTAVOS")
                ltv += int(cents)
        report["ltv_centavos"] = ltv
        report["diferenca_pedidos_ltv_centavos"] = ltv - total
        save_private(
            Path(review["journal"]).parent / "historico_conferencia_v1.json", report
        )
        if strict and (report["diferencas"] or ltv != total):
            raise HistoryError("CONFERENCIA_FINANCEIRA_DIVERGENTE")
        return report

    def _pilot_conference(self, db, review):
        from history_conference import compare, from_published, summarize

        for name, source in (
            ("pilot_expected", "incoming"),
            ("pilot_observed", "observed"),
        ):
            db.execute(f"DROP TABLE IF EXISTS {name}")
            db.execute(
                f"CREATE TEMP TABLE {name}(t TEXT,k TEXT,v TEXT,PRIMARY KEY(t,k))"
            )
            db.execute(
                f"INSERT INTO {name} SELECT t,k,v FROM {source} WHERE t='Historico_Pedidos' AND k IN (SELECT o.k FROM operations o JOIN batches b ON b.n=o.batch WHERE o.t='Historico_Pedidos' AND b.state='done')"
            )
            db.execute(
                f"INSERT INTO {name} SELECT s.t,s.k,s.v FROM {source} s WHERE s.t='Historico_Itens' AND json_extract(s.v,'$.pedido_id') IN (SELECT json_extract(v,'$.pedido_id') FROM {name} WHERE t='Historico_Pedidos')"
            )
        context = dict(
            revision=review["revision"],
            coverage="somente pedidos cujos lotes estão confirmados; itens e LTV podem estar pendentes",
        )
        expected = summarize(
            from_published(db, "pilot_expected"), self.segment, context=context
        )
        actual = summarize(
            from_published(db, "pilot_observed"),
            self.segment,
            context=context,
            tolerate_financial=True,
        )
        report = compare(expected, actual)
        report["ltv_conference"] = "indisponível até fechar a publicação integral"
        report["scope"] = "piloto; não representa a base inteira"
        return report

    def check(self, review):
        with closing(self._open(review)) as db:
            self._binding(db)
            parts = get(db, "parts")
            mismatches = self._verify_current(db, parts, tolerant=True)
            remaining = db.execute(
                "SELECT count(*) FROM batches WHERE state!='done'"
            ).fetchone()[0]
            scope = [
                dict(batch=n, table=t, part=p, rows=len(json.loads(body)))
                for n, t, p, body in db.execute(
                    "SELECT n,t,p,body FROM batches WHERE state='done' ORDER BY n"
                )
            ]
            report: dict[str, Any]
            if remaining:
                report = dict(
                    status=(
                        "piloto parcial conferido"
                        if scope
                        else "nenhum lote confirmado; piloto ainda não validado"
                    ),
                    confirmed_batches=len(scope),
                    remaining_batches=remaining,
                    scope=scope,
                    financial_closure="pendente até concluir todas as tabelas",
                    revision=review["revision"],
                )
                uncertain = db.execute(
                    "SELECT count(*) FROM batches WHERE state IN ('sending','restoring')"
                ).fetchone()[0]
                report["uncertain_batches"] = uncertain
                if uncertain:
                    report["status"] = (
                        "resposta incerta; conferência não autoriza conclusão"
                    )
            else:
                report = dict(
                    status="conferida",
                    confirmed_batches=len(scope),
                    remaining_batches=0,
                    scope=scope,
                    conference=self._conference(db, review, parts, strict=False),
                )
            report["interval_differences"] = mismatches
            if not remaining and (
                mismatches
                or report["conference"]["diferencas"]
                or report["conference"]["diferenca_pedidos_ltv_centavos"]
            ):
                report["status"] = "divergente"
            if remaining:
                report["conference"] = self._pilot_conference(db, review)
                if mismatches:
                    report["status"] = "divergente"
            save_private(
                Path(review["journal"]).parent / "conferencia_publicacao.json", report
            )
            return report

    def rollback(self, review, batch):
        with closing(self._open(review)) as db:
            self._binding(db)
            self.remote.acquire()
            self.remote.preflight(review["capacity"], get(db, "metadata"))
            row = db.execute(
                "SELECT t,p,body,state FROM batches WHERE n=?", (batch,)
            ).fetchone()
            if row is None or row[3] not in ("done", "restoring"):
                raise HistoryError("LOTE_NAO_CONFIRMADO")
            title, part, body, _ = row
            if digest([title, part, body]) != review["batch_hashes"][batch - 1]:
                raise HistoryError("PLANO_DE_LOTE_ALTERADO")
            target = next(
                p
                for p in get(db, "parts")
                if p["title"] == title and p["number"] == part
            )
            entries = json.loads(body)
            actual = self.remote.read_rows(
                target, SCHEMAS[title], [e["row"] for e in entries]
            )
            if row[3] == "restoring" and actual == [e["before"] for e in entries]:
                db.execute("UPDATE batches SET state='pending' WHERE n=?", (batch,))
                db.commit()
                return dict(status="restaurado", batch=batch, rows=len(entries))
            if actual != [e["after"] for e in entries]:
                raise HistoryError("ROLLBACK_BLOQUEADO_POR_EDICAO_POSTERIOR")
            self.remote.begin(review["revision"], SCHEMAS)
            put(db, "finished", False)
            db.execute("UPDATE batches SET state='restoring' WHERE n=?", (batch,))
            db.commit()
            self.remote.write_rows(target, SCHEMAS[title], entries, field="before")
            if self.remote.read_rows(
                target, SCHEMAS[title], [e["row"] for e in entries]
            ) != [e["before"] for e in entries]:
                raise HistoryError("ROLLBACK_NAO_CONFIRMADO")
            db.execute("UPDATE batches SET state='pending' WHERE n=?", (batch,))
            db.commit()
            return dict(status="restaurado", batch=batch, rows=len(entries))
