"""Cadastro FARMA e leituras privadas por execução; não confirma compras."""

from __future__ import annotations

import json
import logging
import sqlite3
import tempfile
from collections import defaultdict
from concurrent.futures import Future
from copy import deepcopy
from datetime import date
from pathlib import Path
from threading import Lock
from typing import Any

CUSTOMER_FIELDS = (
    "id",
    "cpf",
    "nome",
    "celular",
    "email",
    "sexo",
    "nascimento",
    "cadastro",
)
ADDRESS_FIELDS = ("id", "clienteId", "principal", "cep", "uf", "cidade", "bairro")
DIRECTORY_SOURCE = "FARMALIDER_CLIENTES_FARMA"


def positive_id(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    text = str(value).strip()
    return str(int(text)) if text.isascii() and text.isdigit() and int(text) > 0 else ""


def _cpf_key(value: Any) -> str:
    from analytics import normalize_cpf
    from farmalider_integration import cpf_cadastro_status

    return "" if cpf_cadastro_status(value) else normalize_cpf(value)


class CustomerDirectory:
    """Índice de candidatos; ausência nunca equivale a ausência de compras."""

    def __init__(self, payload: Any):
        if not isinstance(payload, list) or any(
            not isinstance(c, dict) for c in payload
        ):
            raise ValueError("A listagem FARMA deve ser uma lista de cadastros.")
        self.by_cpf: dict[str, list[dict]] = defaultdict(list)
        self.by_numeric_cpf: dict[str, list[dict]] = defaultdict(list)
        self.by_id: dict[str, dict] = {}
        self.conflicted_ids: set[str] = set()
        self.skipped = 0
        self.received = len(payload)
        seen: dict[str, dict] = {}
        variants = []
        for raw in payload:
            cid = positive_id(raw.get("id"))
            if not cid:
                self.skipped += 1
                continue
            record = {key: raw.get(key) for key in CUSTOMER_FIELDS}
            addresses = raw.get("enderecos")
            record["enderecos"] = (
                [
                    {key: address.get(key) for key in ADDRESS_FIELDS}
                    for address in addresses
                    if isinstance(address, dict)
                ]
                if isinstance(addresses, list)
                else []
            )
            if cid in seen:
                if seen[cid] == record:
                    continue
                self.conflicted_ids.add(cid)
            else:
                seen[cid] = record
            variants.append(record)
        for record in variants:
            cid = positive_id(record["id"])
            key = _cpf_key(record["cpf"])
            if not key:
                self.skipped += 1
                continue
            self.by_cpf[key].append(record)
            if type(record["cpf"]) is int:
                self.by_numeric_cpf[key.lstrip("0")].append(record)
            if cid not in self.conflicted_ids:
                self.by_id[cid] = record

    def candidates(self, cpf: str) -> list[dict]:
        key = _cpf_key(cpf)
        if not key:
            return []
        records = [
            *self.by_cpf.get(key, []),
            *self.by_numeric_cpf.get(key.lstrip("0"), []),
        ]
        unique = {}
        for record in records:
            serialized = json.dumps(record, sort_keys=True, ensure_ascii=False)
            unique[serialized] = record
        return deepcopy(list(unique.values()))

    def constrain(self, cpf: str, candidates: list[dict]) -> tuple[list[dict], str]:
        records = self.candidates(cpf)
        ids = {positive_id(record["id"]) for record in records}
        if ids & self.conflicted_ids:
            return [], "CPF_IDENTIDADE_AMBIGUA"
        if not ids:
            # Listagem pode estar desatualizada/incompleta: a consulta individual
            # continua sendo necessária, sem declarar CPF inválido ou remover grupos.
            return candidates, ""
        matching = [
            c
            for c in candidates
            if positive_id(c["cliente"].get("id")) in ids
            or not positive_id(c["cliente"].get("id"))
        ]
        return (matching, "") if matching else ([], "CLIENTE_ID_DIVERGENTE_API")

    def metrics(self) -> dict[str, int]:
        return {
            "cadastros_recebidos": self.received,
            "cadastros_indexados": len(self.by_id),
            "ids_divergentes": len(self.conflicted_ids),
            "cadastros_nao_utilizaveis": self.skipped,
        }


class ExecutionReadCache:
    """SQLite temporário evita reter todos os pedidos/itens na memória."""

    def __init__(self):
        self.folder = tempfile.TemporaryDirectory(
            prefix="nexoflow_farma_leituras_", ignore_cleanup_errors=True
        )
        self.path = Path(self.folder.name) / "leituras.sqlite"
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.path.chmod(0o600)
        self.db.execute("PRAGMA page_size = 4096")
        self.db.execute("PRAGMA max_page_count = 32768")  # Até 128 MiB no disco.
        self.db.execute("PRAGMA cache_size = -2048")
        self.db.execute("PRAGMA journal_mode = MEMORY")
        # É apenas cache descartável, nunca estado de aplicação ou auditoria.
        self.db.execute("PRAGMA synchronous = OFF")
        self.db.execute(
            "CREATE TABLE reads (kind TEXT, key TEXT, payload TEXT, PRIMARY KEY(kind,key))"
        )
        self.lock = Lock()
        self.pending: dict[tuple[str, str], Future] = {}
        self.hits = 0
        self.disabled = False
        self.write_disabled = False

    def read(self, kind: str, key: str, fetch):
        identity = kind, str(key)
        with self.lock:
            if not self.disabled:
                try:
                    row = self.db.execute(
                        "SELECT payload FROM reads WHERE kind=? AND key=?", identity
                    ).fetchone()
                    if row is not None:
                        self.hits += 1
                        return json.loads(row[0])
                except (sqlite3.Error, ValueError):
                    self.disabled = True
                    logging.warning(
                        "FarmaLíder: cache temporário indisponível; leituras continuam pela API."
                    )
            future = self.pending.get(identity)
            owner = future is None
            if owner:
                future = Future()
                self.pending[identity] = future
            else:
                self.hits += 1
        if future is None:
            raise RuntimeError("Fila interna de leituras indisponível.")
        if owner:
            try:
                value = fetch()
                with self.lock:
                    if not self.disabled and not self.write_disabled:
                        try:
                            self.db.execute(
                                "INSERT OR REPLACE INTO reads VALUES (?,?,?)",
                                (*identity, json.dumps(value, ensure_ascii=False)),
                            )
                            self.db.commit()
                        except (sqlite3.Error, TypeError, ValueError):
                            self.write_disabled = True
                            logging.warning(
                                "FarmaLíder: cache temporário sem gravação; resposta oficial preservada."
                            )
                future.set_result(value)
            except BaseException as exc:
                future.set_exception(exc)
            finally:
                with self.lock:
                    self.pending.pop(identity, None)
        return deepcopy(future.result())

    def close(self):
        with self.lock:
            pending = list(self.pending.values())
        for future in pending:
            try:
                future.result()
            except BaseException:
                pass  # O consumidor recebe a falha original da própria leitura.
        with self.lock:
            self.db.close()
        try:
            self.folder.cleanup()
        except OSError:
            logging.warning(
                "FarmaLíder: limpeza do cache privado pendente; a operação concluída foi preservada."
            )


def directory_for(farm) -> CustomerDirectory | None:
    directory = getattr(farm, "customer_directory", None)
    return directory if isinstance(directory, CustomerDirectory) else None


def prepare_customers(farm, expected_contacts: int | None):
    from farmalider_client import FarmaliderClient

    if isinstance(farm, FarmaliderClient):
        farm.prepare_customer_directory(expected_contacts=expected_contacts)


def selected_customer(farm, contact: dict) -> dict | None:
    from analytics import get_fields, normalize_cpf
    from farmalider_integration import select_cliente_response, weni_customer_identity

    directory = directory_for(farm)
    if directory is None:
        return None
    cpf = normalize_cpf(get_fields(contact).get("cpf"))
    records = directory.candidates(cpf)
    if not records:
        return None
    result, payload = select_cliente_response(
        cpf,
        records,
        weni_identity=weni_customer_identity(contact),
        customer_directory=directory,
    )
    return (
        payload["cliente"]
        if payload and result[0] in {"CPF_CONFIRMADO", "CPF_INVALIDO_ENCONTRADO"}
        else None
    )


def enrichment(fields: dict, customer: dict, as_of: date) -> dict[str, str]:
    """Somente lacunas; nenhuma alteração de CPF, URN, nome, pedido ou consentimento."""
    from geography import normalize_geography

    result = {}
    gender = {"M": "Masculino", "F": "Feminino"}.get(
        str(customer.get("sexo") or "").strip().upper()
    )
    if gender and not str(fields.get("genero") or "").strip():
        result["genero"] = gender
    try:
        birth = date.fromisoformat(str(customer.get("nascimento") or "")[:10])
        age = (
            as_of.year
            - birth.year
            - ((as_of.month, as_of.day) < (birth.month, birth.day))
        )
    except ValueError:
        age = 0
    if 1 <= age <= 120:
        majority = "Sim" if age >= 18 else "Não"
        old_age = str(fields.get("idade") or "").strip()
        old_majority = str(fields.get("maior_de_18_anos") or "").strip().casefold()
        if (not old_age or old_age == str(age)) and (
            not old_majority or old_majority == majority.casefold()
        ):
            if not old_age:
                result["idade"] = str(age)
            if not old_majority:
                result["maior_de_18_anos"] = majority
    addresses = customer.get("enderecos") or []
    principal = [
        a for a in addresses if isinstance(a, dict) and a.get("principal") == 1
    ]
    if (
        positive_id(customer.get("id"))
        and len(principal) == 1
        and positive_id(principal[0].get("clienteId"))
        == positive_id(customer.get("id"))
    ):
        address = principal[0]
        candidate = normalize_geography(
            {
                "cidade": address.get("cidade"),
                "estado": address.get("uf"),
                "bairro": address.get("bairro"),
                "cep": address.get("cep"),
            }
        )
        current = normalize_geography(fields)
        keys = ("cidade", "estado", "bairro", "cep")
        if all(
            not str(current.get(k) or "").strip()
            or str(current.get(k)).strip() == str(candidate.get(k) or "").strip()
            for k in keys
        ):
            for key in keys:
                value = str(candidate.get(key) or "").strip()
                if value and not str(fields.get(key) or "").strip():
                    if key != "cep" or (
                        len(value) == 8 and value.isascii() and value.isdigit()
                    ):
                        result[key] = value
    return result
