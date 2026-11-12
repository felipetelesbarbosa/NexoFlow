"""Publicador Windows com outbox privada; o banco nunca é exposto ao cliente."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import requests

from bi_postgres_contract import (
    MAX_ROWS,
    PROTOCOL,
    TARGET,
    PublicationError,
    digest,
    normalize_rows,
    validate_payload,
)
from config import BASE_DIR, LOG_DIR
from runtime_profile import segment


def _save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def sales_scope(orders, rows=None):
    from analytics import _order_customer_identity_verified
    from looker_bi import opaque_key
    from pedido_utils import is_order_cancelled

    # Ausência no builder não equivale a cancelamento. Só vendas efetivamente
    # publicáveis e cancelamentos oficiais explícitos autorizam reconciliação.
    return sorted(
        {r[1] for r in (rows or [])}
        | {
            opaque_key("venda", str(o["pedido_chave"]))
            for o in orders
            if o.get("pedido_chave")
            and o.get("status_confirmacao") == "CANCELADO_API"
            and _order_customer_identity_verified(o)
            and (
                is_order_cancelled(o)
                or o.get("status_validacao") == "CANCELADO_SEM_ITENS"
            )
        }
    )


def batches(rows, sales, session_id, complete, *, target_rows=1000):
    # Validação integral antes do primeiro envio. Um pedido nunca é dividido.
    normalized = []
    for start in range(0, len(rows), MAX_ROWS):
        normalized.extend(normalize_rows(rows[start : start + MAX_ROWS]))
    if len({r["item_chave"] for r in normalized}) != len(normalized):
        raise PublicationError("BI_PG_CHAVE_DUPLICADA")
    groups = {key: [] for key in sales}
    for original, row in zip(rows, normalized, strict=True):
        if row["venda_chave"] not in groups:
            raise PublicationError("BI_PG_ITEM_FORA_ESCOPO")
        groups[row["venda_chave"]].append(original)
    parts = []
    active, keys = [], []
    for key in sorted(groups):
        group = groups[key]
        if len(group) > MAX_ROWS:
            raise PublicationError("BI_PG_PEDIDO_EXCEDE_LOTE")
        if keys and (len(active) + len(group) > target_rows or len(keys) >= 1000):
            parts.append((keys, active))
            active = []
            keys = []
        keys.append(key)
        active.extend(group)
    if keys:
        parts.append((keys, active))
    if not parts:
        parts.append(([], []))
    result = []
    for keys, items in parts:
        payload = {
            "protocol": PROTOCOL,
            "target": TARGET,
            "segment": "FARMA",
            "batch_id": str(uuid4()),
            "session_id": session_id,
            "complete": complete,
            "sales": keys,
            "rows": items,
        }
        validate_payload(payload)
        if len(json.dumps(payload, ensure_ascii=False).encode()) > 7_500_000:
            raise PublicationError("BI_PG_PEDIDO_EXCEDE_PAYLOAD")
        result.append(payload)
    return result


class Publisher:
    def __init__(
        self,
        credentials,
        state_path: Path,
        *,
        simulate=True,
        transport=None,
        sleeper=time.sleep,
    ):
        required = {
            "endpoint",
            "publish_token",
            "access_client_id",
            "access_client_secret",
        }
        if (
            not isinstance(credentials, dict)
            or not required.issubset(credentials)
            or any(
                not isinstance(credentials[k], str) or not credentials[k].strip()
                for k in required
            )
        ):
            raise PublicationError("BI_PG_CREDENCIAIS_AUSENTES")
        parsed = urlsplit(credentials["endpoint"])
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or len(credentials["publish_token"]) < 32
        ):
            raise PublicationError("BI_PG_CANAL_INVALIDO")
        self.endpoint = credentials["endpoint"].rstrip("/")
        self.endpoint_hash = digest(self.endpoint)
        self.path = Path(state_path)
        self.simulate = simulate
        self.http = transport or requests.Session()
        self.sleep = sleeper
        self.headers = {
            "Authorization": "Bearer " + credentials["publish_token"],
            "CF-Access-Client-Id": credentials["access_client_id"],
            "CF-Access-Client-Secret": credentials["access_client_secret"],
        }
        self.state = {}
        self.session_id = ""
        self._guard = None

    def _lock(self):
        if self._guard is not None:
            return
        from recompra_lock import RecompraLockError, execution_file_lock

        guard = execution_file_lock(
            self.path.with_suffix(".lock"),
            protocol="nexoflow-bi-postgres-outbox-v1",
            operation="outbox BI_Itens PostgreSQL",
        )
        try:
            guard.__enter__()
        except (RecompraLockError, OSError):
            raise PublicationError(
                "BI_PG_OUTBOX_EM_USO_OU_BLOQUEADA; aguarde a outra rotina e preserve a trava"
            ) from None
        self._guard = guard

    def request(self, method, path, payload=None, *, missing=False) -> Any:
        for attempt in range(3):
            try:
                response = self.http.request(
                    method,
                    self.endpoint + path,
                    headers=self.headers,
                    json=payload,
                    timeout=(10, 90),
                    allow_redirects=False,
                )
                if response.status_code == 404 and missing:
                    return None
                if response.status_code in {429, 500, 502, 503, 504}:
                    if attempt < 2:
                        self.sleep(2**attempt)
                        continue
                    raise PublicationError("BI_PG_SERVICO_PENDENTE; outbox preservada")
                if response.status_code == 409 and len(response.content) <= 64_000:
                    body = response.json()
                    safe = body.get("error") if isinstance(body, dict) else None
                    if safe in {
                        "BI_PG_LOTE_ANTIGO",
                        "BI_PG_SCHEMA_DIVERGENTE",
                        "BI_PG_LOTE_DIVERGENTE_OU_REVERTIDO",
                        "BI_PG_LOTE_REVERTIDO",
                        "BI_PG_ESCOPO_REUTILIZADO",
                        "BI_PG_ITEM_TROCOU_DE_PEDIDO",
                        "BI_PG_BANCO_DIVERGENTE",
                    }:
                        raise PublicationError(safe + "; outbox preservada")
                if response.status_code != 200 or len(response.content) > 64_000:
                    raise PublicationError(
                        "BI_PG_HTTP_NAO_CONFIRMADO; confira acesso e destino"
                    )
                value = response.json()
                if not isinstance(value, dict):
                    raise PublicationError("BI_PG_RESPOSTA_INVALIDA")
                return value
            except (requests.RequestException, ValueError) as error:
                if isinstance(error, PublicationError):
                    raise
                if attempt == 2:
                    raise PublicationError(
                        "BI_PG_RESPOSTA_INCERTA; retome a mesma outbox"
                    ) from None
                self.sleep(2**attempt)
        raise PublicationError("BI_PG_RESPOSTA_INCERTA")

    def confirm(self, payload, receipt):
        expected = digest(validate_payload(payload))
        if (
            not isinstance(receipt, dict)
            or any(
                receipt.get(k) != payload[k]
                for k in ("target", "protocol", "batch_id", "session_id")
            )
            or receipt.get("digest") != expected
            or receipt.get("confirmed") is not True
            or receipt.get("state") != "CONFIRMADO"
        ):
            raise PublicationError(
                "BI_PG_COMPROVANTE_DIVERGENTE; checkpoint preservado"
            )
        for key in (
            "inseridos",
            "atualizados",
            "mantidos",
            "removidos",
            "remocoes_bloqueadas",
        ):
            if type(receipt.get(key)) is not int or receipt[key] < 0:
                raise PublicationError("BI_PG_CONTAGENS_INVALIDAS")
        if sum(receipt[k] for k in ("inseridos", "atualizados", "mantidos")) != len(
            payload["rows"]
        ):
            raise PublicationError("BI_PG_CONTAGENS_DIVERGENTES")
        if type(receipt.get("revision")) is not int or receipt["revision"] <= 0:
            raise PublicationError("BI_PG_REVISAO_INVALIDA")
        if not payload["complete"] and receipt["removidos"]:
            raise PublicationError("BI_PG_REMOCAO_EM_PARCIAL")

    def resume(self):
        entries = self.state.get("batches", [])
        if self.state.get("plan_hash") != digest(entries):
            raise PublicationError("BI_PG_OUTBOX_ALTERADA")
        manifest = [
            {"batch_id": p["batch_id"], "digest": digest(validate_payload(p))}
            for p in entries
        ]
        complete = entries[0]["complete"]
        registered = self.request(
            "POST",
            "/publicacao/farma/bi-itens/planos",
            {
                "session_id": self.state["session_id"],
                "manifest": manifest,
                "complete": complete,
            },
        )
        if registered.get("session_id") != self.state["session_id"] or registered.get(
            "digest"
        ) != digest(
            {
                "manifest": sorted(manifest, key=lambda e: e["batch_id"]),
                "complete": complete,
            }
        ):
            raise PublicationError("BI_PG_PLANO_DIVERGENTE")
        receipts = self.state.setdefault("receipts", {})
        for payload in entries:
            validate_payload(payload)
            if payload["batch_id"] in receipts:
                self.confirm(payload, receipts[payload["batch_id"]])
                continue
            receipt = self.request(
                "GET",
                "/publicacao/farma/bi-itens/lotes/" + payload["batch_id"],
                missing=True,
            )
            recovered = receipt is not None
            if receipt is None:
                receipt = self.request(
                    "POST", "/publicacao/farma/bi-itens/lotes", payload
                )
            self.confirm(payload, receipt)
            receipts[payload["batch_id"]] = receipt
            _save(self.path, self.state)  # Só depois de confirmar COMMIT e digest.
            logging.info(
                "BI_Itens PostgreSQL: lote confirmado (%s); inseridos=%s; atualizados=%s; mantidos=%s; removidos=%s.",
                "recibo recuperado, sem novo POST"
                if recovered
                else "resposta do servidor",
                receipt["inseridos"],
                receipt["atualizados"],
                receipt["mantidos"],
                receipt["removidos"],
            )
        final = self.request(
            "POST",
            "/publicacao/farma/bi-itens/planos",
            {
                "session_id": self.state["session_id"],
                "manifest": manifest,
                "complete": complete,
            },
        )
        if final.get("state") != ("READY" if complete else "PARCIAL") or final.get(
            "digest"
        ) != registered.get("digest"):
            raise PublicationError(
                "BI_PG_PLANO_NAO_CONCLUIDO; checkpoint global preservado"
            )
        self.state["status"] = "CONFIRMADO"
        self.state["server_state"] = final["state"]
        _save(self.path, self.state)
        return list(receipts.values())

    def recover(self, *, archive_closed=False):
        self._lock()
        destination = self.request("GET", "/publicacao/destino")
        if (
            destination.get("target") != TARGET
            or destination.get("protocol") != PROTOCOL
        ):
            raise PublicationError("BI_PG_DESTINO_DIVERGENTE")
        try:
            previous = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise PublicationError("BI_PG_OUTBOX_AUSENTE_OU_INVALIDA") from None
        if previous.get("endpoint_hash") != self.endpoint_hash or previous.get(
            "plan_hash"
        ) != digest(previous.get("batches")):
            raise PublicationError("BI_PG_OUTBOX_ALTERADA")
        status = self.request(
            "GET", "/publicacao/farma/bi-itens/sessoes/" + previous["session_id"]
        )
        if (
            status.get("target") != TARGET
            or status.get("session_id") != previous["session_id"]
        ):
            raise PublicationError("BI_PG_SESSAO_DIVERGENTE")
        if archive_closed:
            closed = status.get("state") == "REVERTIDO" or (
                status.get("state") != "WRITING"
                and status.get("revision", 0) < status.get("watermark", 0)
            )
            if not closed:
                raise PublicationError("BI_PG_SESSAO_NAO_ENCERRADA")
            preserved = self.path.with_name(
                "outbox-encerrada-" + previous["session_id"] + ".json"
            )
            if not preserved.exists():
                _save(preserved, previous)
            previous["status"] = "ENCERRADA_PELO_SERVIDOR"
            previous["server_closure"] = status
            _save(self.path, previous)
            return {"status": "ENCERRADA_PELO_SERVIDOR", "checkpoint_avancado": False}
        self.state = previous
        if self.simulate:
            return {
                "status": previous.get("status"),
                "server_state": status["state"],
                "lotes_confirmados": len(previous.get("receipts", {})),
            }
        if previous.get("status") == "PENDENTE":
            self.resume()
            status = self.request(
                "GET", "/publicacao/farma/bi-itens/sessoes/" + previous["session_id"]
            )
        return {
            "status": self.state["status"],
            "server_state": status["state"],
            "lotes_confirmados": len(self.state.get("receipts", {})),
        }

    def start(self):
        self._lock()
        destination = self.request("GET", "/publicacao/destino")
        if (
            destination.get("protocol"),
            destination.get("target"),
            destination.get("segment"),
        ) != (PROTOCOL, TARGET, "FARMA"):
            raise PublicationError("BI_PG_DESTINO_DIVERGENTE")
        if self.path.exists():
            try:
                previous = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise PublicationError("BI_PG_OUTBOX_ILEGIVEL") from None
            if previous.get("endpoint_hash") != self.endpoint_hash:
                raise PublicationError("BI_PG_CANAL_ALTERADO; preserve a outbox")
            if previous.get("status") == "PENDENTE":
                if self.simulate:
                    raise PublicationError(
                        "BI_PG_OUTBOX_PENDENTE; simulação não aplica lotes"
                    )
                self.state = previous
                self.resume()
                archive = self.path.with_name(
                    "outbox-" + self.state["session_id"] + ".json"
                )
                if not archive.exists():
                    _save(archive, self.state)
            elif previous.get("status") == "CONFIRMADO":
                archive = self.path.with_name(
                    "outbox-" + previous["session_id"] + ".json"
                )
                if not archive.exists():
                    _save(archive, previous)
        self.session_id = str(uuid4())
        if not self.simulate:
            receipt = self.request(
                "POST",
                "/publicacao/farma/bi-itens/sessoes",
                {"session_id": self.session_id},
            )
            if (
                receipt.get("session_id") != self.session_id
                or receipt.get("target") != TARGET
            ):
                raise PublicationError("BI_PG_SESSAO_DIVERGENTE")
        # A sessão é reservada antes da coleta. O servidor rejeita sessões antigas.

    def publish(self, rows, sales, *, complete):
        entries = batches(rows, sales, self.session_id, complete)
        if self.simulate:
            receipts = [
                self.request("POST", "/publicacao/farma/bi-itens/simular", p)
                for p in entries
            ]
            for payload, receipt in zip(entries, receipts, strict=True):
                if (
                    receipt.get("state") != "SIMULADO"
                    or receipt.get("confirmed") is not False
                    or receipt.get("digest") != digest(validate_payload(payload))
                ):
                    raise PublicationError("BI_PG_SIMULACAO_DIVERGENTE")
            logging.info(
                "BI_Itens PostgreSQL: SIMULAÇÃO; lotes=%s; inseridos=%s; atualizados=%s; mantidos=%s. Nenhum checkpoint de publicação avançado.",
                len(entries),
                sum(r["inseridos"] for r in receipts),
                sum(r["atualizados"] for r in receipts),
                sum(r["mantidos"] for r in receipts),
            )
            return {"simulated": True, "receipts": receipts}
        self.state = {
            "session_id": self.session_id,
            "endpoint_hash": self.endpoint_hash,
            "status": "PENDENTE",
            "batches": entries,
            "plan_hash": digest(entries),
            "receipts": {},
        }
        _save(self.path, self.state)
        return {"simulated": False, "complete": complete, "receipts": self.resume()}

    def close(self):
        try:
            self.http.close()
        finally:
            if self._guard is not None:
                guard, self._guard = self._guard, None
                guard.__exit__(None, None, None)


def open_publisher(settings):
    destination = getattr(settings, "BI_ITENS_DESTINO", "sheets")
    if destination == "sheets":
        return None
    if destination != "postgres" or segment() != "FARMA":
        raise PublicationError("BI_PG_SEGMENTO_OU_DESTINO_INVALIDO")
    mode = getattr(settings, "BI_ITENS_POSTGRES_MODO", "simular")
    if mode not in {"simular", "aplicar"}:
        raise PublicationError("BI_PG_MODO_INVALIDO")
    path = Path(str(getattr(settings, "BI_ITENS_POSTGRES_CREDENTIALS_FILE", "")))
    if not path.is_absolute():
        path = BASE_DIR / path
    try:
        credentials = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise PublicationError("BI_PG_ARQUIVO_DE_CREDENCIAIS_AUSENTE") from None
    return Publisher(
        credentials,
        LOG_DIR / "privado" / "bi_postgres" / "outbox.json",
        simulate=mode == "simular",
    )


def publish_other_looker_tables(store, tables):
    """Roteamento explícito; mantém o gravador assinado e suas guardas em bytes."""
    from looker_bi import SCHEMAS, TEXT_COLUMNS

    if set(tables) != set(SCHEMAS):
        raise PublicationError("BI_PG_CONJUNTO_BI_INCOMPLETO")
    prepared = {
        title: store._typed_bi_rows(headers, tables[title])
        for title, headers in SCHEMAS.items()
        if title != "BI_Itens"
    }
    for title, values in prepared.items():
        ws = getattr(store, "looker_" + title)
        store._replace_table(ws, SCHEMAS[title], values, force=True)
        store._format_bi_columns(ws, SCHEMAS[title], text_columns=TEXT_COLUMNS)
        logging.info(
            "Google Sheets: %s atualizada (%s registro(s)).", title, len(values)
        )
