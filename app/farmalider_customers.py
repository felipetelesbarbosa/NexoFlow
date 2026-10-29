"""Cadastro e snapshots oficiais FARMA mantidos somente durante a execução."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import tempfile
import unicodedata
from collections import defaultdict
from concurrent.futures import Future
from copy import deepcopy
from datetime import date
from pathlib import Path
from threading import Lock
from typing import Any

from runtime_profile import segment as active_segment

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
ADDRESS_FIELDS = (
    "id",
    "clienteId",
    "principal",
    "cep",
    "uf",
    "cidade",
    "bairro",
    "logradouro",
    "numero",
    "complemento",
)
ORDER_FIELDS = (
    "id",
    "codCliente",
    "emissao",
    "status",
    "formaPagamento",
    "cancelamento",
    "frete",
    "valorTotal",
    "valorTotalPedido",
    "valorTotalCompra",
    "totalPedido",
    "publicId",
    "codFilial",
    "cupom",
    "pedidoWeb",
    "entrega",
    "segmento",
    "cep",
    "uf",
    "cidade",
    "bairro",
    "logradouro",
    "numero",
    "complemento",
)
ITEM_FIELDS = (
    "id",
    "codPedido",
    "codProduto",
    "descricao",
    "quantidade",
    "valor",
    "total",
    "desconto",
    "filialId",
    "categoria",
)
DIRECTORY_SOURCE = "FARMALIDER_CLIENTES_" + active_segment()


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

    def __init__(self, payload: Any, *, segment: str = "FARMA"):
        if segment not in {"FARMA", "PET"}:
            raise ValueError("Segmento deve ser FARMA ou PET.")
        if not isinstance(payload, list) or any(
            not isinstance(c, dict) for c in payload
        ):
            raise ValueError("A listagem FARMA deve ser uma lista de cadastros.")
        self.by_cpf: dict[str, list[dict]] = defaultdict(list)
        self.by_numeric_cpf: dict[str, list[dict]] = defaultdict(list)
        self.by_id: dict[str, dict] = {}
        self.conflicted_ids: set[str] = set()
        self.snapshots: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.conflicted_orders: set[str] = set()
        self.segment = segment
        self.source = f"FARMALIDER_CLIENTES_{segment}"
        self.address_results: dict[str, int] = defaultdict(int)
        self.skipped = 0
        self.received = len(payload)
        seen: dict[str, tuple] = {}
        variants = []
        for raw in payload:
            source = raw.get("cliente", raw)
            if not isinstance(source, dict):
                self.skipped += 1
                continue
            cid = positive_id(source.get("id"))
            if not cid:
                self.skipped += 1
                continue
            record = {key: source.get(key) for key in CUSTOMER_FIELDS}
            addresses = source.get("enderecos")
            record["enderecos"] = (
                [
                    {key: address.get(key) for key in ADDRESS_FIELDS}
                    for address in addresses
                    if isinstance(address, dict)
                ]
                if isinstance(addresses, list)
                else []
            )
            latest = raw.get("ultimoPedido")
            if isinstance(latest, dict):
                record["_ultimo_pedido_endereco"] = {
                    key: latest.get(key)
                    for key in (
                        "id",
                        "codCliente",
                        "emissao",
                        "segmento",
                        *ADDRESS_FIELDS,
                    )
                    if key not in {"clienteId", "principal"}
                }
            snapshot = self._snapshot(record, raw)
            signature = (record, snapshot)
            if cid in seen:
                if seen[cid] == signature:
                    continue
                self.conflicted_ids.add(cid)
            else:
                seen[cid] = signature
            variants.append((record, snapshot))
        for record, snapshot in variants:
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
                result, _ = matching_order_address(record, segment=self.segment)
                self.address_results[result] += 1
                if snapshot is not None:
                    self.snapshots[cid] = snapshot
                    oid = positive_id(snapshot["ultimoPedido"]["id"])
                    order = {
                        "capa": snapshot["ultimoPedido"],
                        "itens": snapshot["itens"],
                        "_nexoflow_source": self.source,
                    }
                    if oid in self.orders and self.orders[oid] != order:
                        self.conflicted_orders.add(oid)
                    self.orders[oid] = order
        for oid in self.conflicted_orders:
            self.orders.pop(oid, None)

    def _snapshot(self, customer: dict, raw: dict) -> dict | None:
        from farmalider_integration import apply_pedido_api_confirmation
        from pedido_utils import (
            business_order_datetime,
            is_order_cancelled,
            is_order_sale,
        )

        latest, items = raw.get("ultimoPedido"), raw.get("itens")
        if not isinstance(latest, dict) or not isinstance(items, list):
            return None
        cid, oid = positive_id(customer["id"]), positive_id(latest.get("id"))
        if not oid or positive_id(latest.get("codCliente")) != cid:
            return None
        segment = str(latest.get("segmento") or "").strip().upper()
        if segment and segment != self.segment:
            return None
        emitted = business_order_datetime(latest.get("emissao"))
        if emitted is None or any(not isinstance(item, dict) for item in items):
            return None
        header = {key: latest[key] for key in ORDER_FIELDS if key in latest}
        copied_items = [
            {key: item[key] for key in ITEM_FIELDS if key in item} for item in items
        ]
        verified, _ = apply_pedido_api_confirmation(
            {"pedido_id": oid},
            [],
            {"capa": header, "itens": copied_items},
            linked_cliente_id=cid,
            confirmed_at=emitted.isoformat(),
        )
        if verified.get("status_validacao") not in {"OK", "CANCELADO_SEM_ITENS"}:
            return None
        if not (is_order_sale(verified) or is_order_cancelled(verified)):
            return None
        return {
            "cliente": customer,
            "ultimoPedido": header,
            "itens": copied_items,
            "_nexoflow_source": self.source,
        }

    def _latest_by_cpf(self, cpf: str) -> list[dict] | None:
        records = self._candidate_records(cpf)
        if not records:
            return None
        ids = {positive_id(record["id"]) for record in records}
        if ids & self.conflicted_ids or any(cid not in self.snapshots for cid in ids):
            return None
        snapshots = [self.snapshots[cid] for cid in sorted(ids)]
        if any(
            positive_id(s["ultimoPedido"]["id"]) in self.conflicted_orders
            for s in snapshots
        ):
            return None
        return snapshots

    def has_latest_snapshot(self, cpf: str) -> bool:
        return self._latest_by_cpf(cpf) is not None

    def latest_by_cpf(self, cpf: str) -> list[dict] | None:
        return deepcopy(self._latest_by_cpf(cpf))

    def order_by_id(self, order_id: str) -> dict | None:
        return deepcopy(self.orders.get(positive_id(order_id)))

    def _candidate_records(self, cpf: str) -> list[dict]:
        key = _cpf_key(cpf)
        if not key:
            return []
        records = [
            *self.by_cpf.get(key, []),
            *self.by_numeric_cpf.get(key.lstrip("0"), []),
        ]
        unique = {id(record): record for record in records}
        return list(unique.values())

    def candidates(self, cpf: str) -> list[dict]:
        return deepcopy(self._candidate_records(cpf))

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

    def metrics(self) -> dict[str, Any]:
        return {
            "cadastros_recebidos": self.received,
            "cadastros_indexados": len(self.by_id),
            "ids_divergentes": len(self.conflicted_ids),
            "cadastros_nao_utilizaveis": self.skipped,
            "snapshots_com_pedido": len(self.snapshots),
            "pedidos_em_memoria": len(self.orders),
            "pedidos_ambiguos": len(self.conflicted_orders),
            "enderecos": dict(self.address_results),
        }


def _address_text(value: Any) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return ""
    value = unicodedata.normalize("NFKD", str(value).casefold())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _address_values(address: dict) -> dict[str, str]:
    from geography import normalize_geography

    geo = normalize_geography(
        {
            "cidade": address.get("cidade"),
            "estado": address.get("uf"),
            "bairro": address.get("bairro"),
            "cep": address.get("cep"),
        }
    )
    street = _address_text(address.get("logradouro")).split()
    aliases = {
        "r": "rua",
        "av": "avenida",
        "tv": "travessa",
        "trav": "travessa",
        "rod": "rodovia",
        "est": "estrada",
        "pca": "praca",
    }
    if street:
        street[0] = aliases.get(street[0], street[0])
    postcode = re.sub(r"\D", "", str(address.get("cep") or ""))
    return {
        "cep": postcode if len(postcode) == 8 and postcode != "00000000" else "",
        "cidade": _address_text(geo.get("cidade")),
        "estado": _address_text(geo.get("estado")),
        "bairro": _address_text(geo.get("bairro")),
        "logradouro": " ".join(street),
        "numero": _address_text(address.get("numero")),
        "complemento": _address_text(address.get("complemento")),
    }


def matching_order_address(
    customer: dict, *, segment: str = "FARMA"
) -> tuple[str, dict | None]:
    """Confere endereço completo; coincidência só de CEP/bairro não comprova vínculo."""
    from pedido_utils import business_order_datetime

    latest = customer.get("_ultimo_pedido_endereco")
    if not isinstance(latest, dict):
        return "SEM_ULTIMO_PEDIDO", None
    if (
        not positive_id(latest.get("id"))
        or not positive_id(customer.get("id"))
        or positive_id(latest.get("codCliente")) != positive_id(customer.get("id"))
        or business_order_datetime(latest.get("emissao")) is None
    ):
        return "PEDIDO_NAO_VERIFICADO", None
    order_segment = str(latest.get("segmento") or "").strip().upper()
    if order_segment and order_segment != segment:
        return "SEGMENTO_DIVERGENTE", None
    target = _address_values(latest)
    required = {"cep", "cidade", "estado", "logradouro", "numero"}
    if any(not target[key] for key in required):
        return "ENDERECO_PEDIDO_INCOMPLETO", None
    addresses = customer.get("enderecos")
    if not isinstance(addresses, list):
        return "ENDERECO_CADASTRAL_AUSENTE", None
    matches = []
    complete_addresses = 0
    for address in addresses:
        if not isinstance(address, dict) or positive_id(
            address.get("clienteId")
        ) != positive_id(customer.get("id")):
            continue
        current = _address_values(address)
        if any(not current[key] for key in required):
            continue
        complete_addresses += 1
        if any(current[key] != target[key] for key in required):
            continue
        if (
            current["bairro"]
            and target["bairro"]
            and current["bairro"] != target["bairro"]
        ):
            continue
        if current["complemento"] != target["complemento"]:
            continue
        matches.append(address)
    if len(matches) == 1:
        return "ENDERECO_CONFIRMADO", matches[0]
    if not complete_addresses:
        return "ENDERECO_CADASTRAL_INCOMPLETO", None
    return ("ENDERECO_AMBIGUO" if matches else "ENDERECO_DIVERGENTE"), None


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
    address_status, address = matching_order_address(customer)
    if address_status == "ENDERECO_CONFIRMADO" and address is not None:
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
