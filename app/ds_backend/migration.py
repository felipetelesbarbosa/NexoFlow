"""Arquivo privado de corte: exportação consistente, plano e retomada determinística."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from ds_backend.contract import (
    REGISTRY,
    SCHEMA_HASH,
    StorageError,
    digest,
    normalize,
    record_key,
)


def private_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        __import__("os").fsync(handle.fileno())
    temporary.chmod(0o600)
    temporary.replace(path)


class SourceKeyConflict(StorageError):
    """Conflito sem valores, hashes de identidade ou identificadores comerciais."""

    def __init__(self, name, fields, first=None, second=None):
        super().__init__(
            "DS_ORIGEM_CHAVE_DIVERGENTE; tabela="
            + name
            + "; campos="
            + ",".join(fields)
        )
        self.diagnostic = dict(
            code="DS_ORIGEM_CHAVE_DIVERGENTE",
            table=name,
            key_fields=REGISTRY[name]["keys"],
            fields=fields,
            first=first,
            second=second,
        )


class Export:
    """SQLite é apenas pacote/outbox de transporte, não a fonte operacional nova."""

    def __init__(self, path, *, create=False):
        self.path = Path(path)
        if create and self.path.exists():
            raise StorageError("DS_EXPORTACAO_JA_EXISTE")
        self.db = sqlite3.connect(
            str(self.path) if create else self.path.resolve().as_uri() + "?mode=ro",
            uri=not create,
        )
        if create:
            self.path.chmod(0o600)
            self.db.executescript(
                "CREATE TABLE linhas(t TEXT,k TEXT,v TEXT,PRIMARY KEY(t,k));CREATE TABLE contexto(k TEXT PRIMARY KEY,v TEXT);"
            )
        else:
            self.db.execute("PRAGMA query_only=ON")

    def add(self, name, rows, segment, *, locations=None):
        normalized = normalize(name, rows, segment)
        if locations is not None:
            if len(locations) != len(normalized):
                raise StorageError("DS_LOCALIZACAO_ORIGEM_INVALIDA")
            self.db.execute(
                "CREATE TEMP TABLE IF NOT EXISTS origens(t TEXT,k TEXT,v TEXT,PRIMARY KEY(t,k))"
            )
        for index, row in enumerate(normalized):
            key = record_key(name, row)
            encoded = json.dumps(
                row, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            )
            prior = self.db.execute(
                "SELECT v FROM linhas WHERE t=? AND k=?", (name, key)
            ).fetchone()
            if prior and prior[0] != encoded:
                previous = json.loads(prior[0])
                first = None
                if locations is not None:
                    saved = self.db.execute(
                        "SELECT v FROM origens WHERE t=? AND k=?", (name, key)
                    ).fetchone()
                    first = json.loads(saved[0]) if saved else None
                raise SourceKeyConflict(
                    name,
                    [
                        field
                        for field in REGISTRY[name]["columns"]
                        if previous[field] != row[field]
                    ],
                    first,
                    locations[index] if locations is not None else None,
                )
            self.db.execute(
                "INSERT OR IGNORE INTO linhas VALUES(?,?,?)", (name, key, encoded)
            )
            if locations is not None:
                self.db.execute(
                    "INSERT OR IGNORE INTO origens VALUES(?,?,?)",
                    (name, key, json.dumps(locations[index])),
                )

    def seal(self, segment, evidence):
        if evidence.get("scope") not in ("CORTE_COMPLETO", "PILOTO_PEDIDO"):
            raise StorageError("DS_ESCOPO_EXPORTACAO_AUSENTE")
        if evidence.get("state") != "READY" or not evidence.get("revision"):
            raise StorageError("DS_ORIGEM_NAO_READY")
        tables = {}
        for name in REGISTRY:
            hashed = hashlib.sha256()
            count = 0
            for (raw,) in self.db.execute(
                "SELECT v FROM linhas WHERE t=? ORDER BY k", (name,)
            ):
                hashed.update(raw.encode() + b"\n")
                count += 1
            tables[name] = dict(count=count, sha256=hashed.hexdigest())
        manifest = dict(
            segment=segment,
            state="READY",
            schema_hash=SCHEMA_HASH,
            evidence=evidence,
            tables=tables,
        )
        self.db.execute(
            "INSERT INTO contexto VALUES(?,?)",
            ("manifest", json.dumps(manifest, ensure_ascii=False)),
        )
        self.db.commit()
        return manifest

    def manifest(self):
        result = self.db.execute("SELECT v FROM contexto WHERE k='manifest'").fetchone()
        if not result:
            raise StorageError("DS_EXPORTACAO_INCOMPLETA")
        manifest = json.loads(result[0])
        if set(manifest.get("tables", {})) != set(REGISTRY):
            raise StorageError("DS_EXPORTACAO_TABELAS_INCOMPLETAS")
        if manifest.get("schema_hash") != SCHEMA_HASH:
            raise StorageError("DS_SCHEMA_DIVERGENTE")
        if self.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise StorageError("DS_EXPORTACAO_CORROMPIDA")
        # Não confiar só no manifesto: recomputar contagens/hashes antes de enviar.
        for name, spec in manifest["tables"].items():
            hashed = hashlib.sha256()
            count = 0
            for (raw,) in self.db.execute(
                "SELECT v FROM linhas WHERE t=? ORDER BY k", (name,)
            ):
                hashed.update(raw.encode() + b"\n")
                count += 1
            if spec != dict(count=count, sha256=hashed.hexdigest()):
                raise StorageError("DS_EXPORTACAO_ALTERADA")
        return manifest

    def close(self):
        self.db.close()


def prepare(export_path, plan_path, client):
    with closing(Export(export_path)) as source:
        manifest = source.manifest()
    from ds_backend.audit import audit

    audit(export_path)
    if (
        client.config["environment"] == "producao"
        and manifest["evidence"].get("scope") != "CORTE_COMPLETO"
    ):
        raise StorageError("DS_PILOTO_EM_PRODUCAO")
    if manifest["segment"] != client.config["segment"]:
        raise StorageError("DS_SEGMENTO_DIVERGENTE")
    if Path(plan_path).exists():
        raise StorageError("DS_PLANO_JA_EXISTE")
    plan = dict(
        protocol="nexoflow_datastudio_1",
        target=client.expected_target,
        revision=str(uuid4()),
        source=str(Path(export_path).resolve()),
        source_hash=digest(manifest),
        state="PREPARADA",
        server_sha=client.info.get("source_sha"),
        server_version=client.info.get("server_version"),
    )
    private_json(plan_path, plan)
    return plan


def apply(plan_path, client, *, max_batches=None, simulate=False):
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8-sig"))
    if plan["target"] != client.expected_target:
        raise StorageError("DS_PLANO_DESTINO_DIVERGENTE")
    if max_batches is not None and max_batches < 1:
        raise StorageError("DS_LIMITE_LOTES_INVALIDO")
    with closing(Export(plan["source"])) as source:
        manifest = source.manifest()
        if digest(manifest) != plan["source_hash"]:
            raise StorageError("DS_PLANO_ORIGEM_ALTERADA")
        client.call(
            "/v1/revisoes",
            dict(
                revision=plan["revision"],
                purpose="migracao",
                evidence={"source_hash": plan["source_hash"]},
            ),
        )
        receipts = {}
        batches = 0
        counts = dict(inserted=0, updated=0, unchanged=0, removed=0)
        # Retomada não reconsulta APIs comerciais nem depende do número do lote salvo.
        for name in REGISTRY:
            cursor = source.db.execute(
                "SELECT v FROM linhas WHERE t=? ORDER BY k", (name,)
            )
            index = 0
            while chunk := cursor.fetchmany(1000):
                bid = str(uuid5(UUID(plan["revision"]), name + ":" + str(index)))
                index += 1
                try:
                    old = client.call("/v1/lotes/" + bid)
                except StorageError as error:
                    if str(error) != "DS_LOTE_AUSENTE":
                        raise
                    old = None
                if old:
                    receipts[bid] = old["hash"]
                    continue
                receipt = client.send(
                    plan["revision"],
                    name,
                    [json.loads(r[0]) for r in chunk],
                    batch_id=bid,
                    simulate=simulate,
                )
                for field in counts:
                    counts[field] += receipt[field]
                if not simulate:
                    receipts[bid] = receipt["hash"]
                batches += 1
                if max_batches is not None and batches >= max_batches:
                    plan["state"] = "SIMULADA" if simulate else "PAUSADA"
                    private_json(plan_path, plan)
                    return dict(state=plan["state"], batches_this_run=batches, **counts)
        if simulate:
            return dict(state="SIMULADA", batches_this_run=batches, **counts)
        result = client.call(
            "/v1/confirmar",
            dict(
                revision=plan["revision"],
                manifest=dict(
                    schema_hash=SCHEMA_HASH, batches=receipts, complete_sources=True
                ),
                complete=True,
            ),
        )
        plan["state"] = result["state"]
        plan["receipt"] = result
        private_json(plan_path, plan)
        return dict(result, batches_this_run=batches, **counts)


def pilot(export_path, output_path, order_id):
    """Recorte determinístico de UM pedido completo, restrito à homologação."""
    from ds_backend.history import regenerate
    from looker_bi import opaque_key

    with closing(Export(export_path)) as source:
        manifest = source.manifest()
        segment = manifest["segment"]
        selected = {n: [] for n in REGISTRY}

        def records(name):
            for (raw,) in source.db.execute(
                "SELECT v FROM linhas WHERE t=? ORDER BY k", (name,)
            ):
                yield json.loads(raw)

        selected["Historico_Pedidos"] = [
            r
            for r in records("Historico_Pedidos")
            if r["pedido_id"] == order_id and r["vigente"] == "Sim"
        ]
        if (
            len(selected["Historico_Pedidos"]) != 1
            or selected["Historico_Pedidos"][0]["estado"] != "valido"
        ):
            raise StorageError("DS_PILOTO_EXIGE_COMPRA_VALIDA_UNICA")
        sale = opaque_key("venda", "FARMALIDER:" + order_id)
        owner = selected["Historico_Pedidos"][0]["cliente_id"]
        contact = selected["Historico_Pedidos"][0]["contato_weni"]
        for name in (
            "Historico_Itens",
            "Pedidos_FarmaLider",
            "Itens_Pedidos_FarmaLider",
            "BI_Pedidos",
        ):
            selected[name] = [r for r in records(name) if r["pedido_id"] == order_id]
        for name in ("BI_Itens", "BI_Clientes_Vendas"):
            selected[name] = [r for r in records(name) if r["venda_chave"] == sale]
        selected["Base_Contatos"] = [
            r
            for r in records("Base_Contatos")
            if r["contact_uuid"] == contact and contact
        ]
        selected["BI_Clientes"] = [
            r
            for r in records("BI_Clientes")
            if r["cliente_chave"]
            == hashlib.sha256(("farmalider:" + owner).encode()).hexdigest()[:32]
        ]

        class Local:
            client = type("Context", (), {"config": {"segment": segment}})()
            _known_sheets = {n: type("Table", (), {"title": n})() for n in REGISTRY}

            def records(self, name):
                return selected[name]

            def _upsert_records_detailed(self, table, rows, key):
                selected[table.title] = rows

        regenerate(Local())
        with closing(Export(output_path, create=True)) as output:
            for name, rows in selected.items():
                for offset in range(0, len(rows), 1000):
                    output.add(name, rows[offset : offset + 1000], segment)
            return output.seal(
                segment,
                dict(
                    state="READY",
                    revision=manifest["evidence"]["revision"],
                    scope="PILOTO_PEDIDO",
                    source_manifest_hash=digest(manifest),
                ),
            )
