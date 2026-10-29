"""Pedidos observados: armazenamento privado por segmento e entrega idempotente ao BI."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from runtime_profile import segment

DB_ROOT: Path | None = None


@contextmanager
def connect():
    from config import LOG_DIR

    root = DB_ROOT / segment() if DB_ROOT is not None else LOG_DIR / "privado"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "clientes_observados.sqlite"
    db = sqlite3.connect(path, timeout=30)
    try:
        path.chmod(0o600)
        db.executescript("""
            CREATE TABLE IF NOT EXISTS profile (segment TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS orders (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, cpf TEXT NOT NULL,
              payload TEXT NOT NULL, digest TEXT NOT NULL, first_seen TEXT NOT NULL,
              last_seen TEXT NOT NULL, synced TEXT NOT NULL DEFAULT '', linked TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS creations (
              id TEXT PRIMARY KEY, status TEXT NOT NULL, uuid TEXT NOT NULL DEFAULT '');
        """)
        with db:
            stored = db.execute("SELECT segment FROM profile").fetchall()
            if not stored:
                db.execute("INSERT INTO profile(segment) VALUES(?)", (segment(),))
            elif stored != [(segment(),)]:
                raise ValueError(
                    "Histórico local pertence a outro segmento; não será utilizado."
                )
            yield db
    finally:
        db.close()


def record_directory(directory, at):
    from analytics import normalize_cpf

    with connect() as db:
        for cid, snapshot in directory.snapshots.items():
            oid = str(snapshot["ultimoPedido"]["id"])
            if directory.order_by_id(oid) is None:
                continue
            raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
            digest = hashlib.sha256(raw.encode()).hexdigest()
            existing = db.execute(
                "SELECT owner FROM orders WHERE id=?", (oid,)
            ).fetchone()
            if existing and existing[0] != cid:
                # Identidade conflitante não pode sobrescrever um histórico válido.
                continue
            db.execute(
                """INSERT INTO orders(id,owner,cpf,payload,digest,first_seen,last_seen)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                payload=excluded.payload,digest=excluded.digest,cpf=excluded.cpf,last_seen=excluded.last_seen
                WHERE julianday(excluded.last_seen)>=julianday(orders.last_seen)""",
                (
                    oid,
                    cid,
                    normalize_cpf(snapshot["cliente"]["cpf"]),
                    raw,
                    digest,
                    at,
                    at,
                ),
            )


def history_rows(
    contacts, existing_orders, *, captured_at, quarter=None, existing_items=None
):
    """Sem novas chamadas HTTP. Uma compra externa não vira atribuição à Weni."""
    from analytics import get_fields, is_valid_cpf, normalize_cpf
    from farmalider_integration import resolve_contact_order
    from pedido_utils import business_order_datetime

    by_cpf = {}
    for contact in contacts:
        by_cpf.setdefault(normalize_cpf(get_fields(contact).get("cpf")), []).append(
            contact
        )
    old = {r.get("pedido_id"): r for r in existing_orders}
    orders, items, receipts = [], [], []
    with connect() as db:
        records = db.execute(
            "SELECT id,owner,cpf,payload,digest,first_seen,synced,linked FROM orders"
        ).fetchall()
    for oid, owner, cpf, raw, digest, first, synced, linked in records:
        if quarter is not None and int(owner) % 4 != quarter - 1:
            continue
        matches = by_cpf.get(cpf, [])
        if len(matches) > 1:
            continue
        contact = matches[0] if matches else None
        uuid = str((contact or {}).get("uuid") or "")
        if synced == digest and linked == uuid:
            continue
        snapshot = json.loads(raw)
        if contact is None:
            if not is_valid_cpf(cpf):
                continue
            contact = {
                "uuid": "",
                "name": snapshot["cliente"].get("nome", ""),
                "fields": {"cpf": cpf, "telefone": snapshot["cliente"].get("celular")},
            }
        header = snapshot["ultimoPedido"]
        adapter = SimpleNamespace(
            customer_directory=None,
            get_cliente_by_cpf=lambda value, s=snapshot: s,
            get_pedido=lambda value, s=snapshot: {
                "capa": s["ultimoPedido"],
                "itens": s["itens"],
            },
        )
        order, detail = resolve_contact_order(
            contact, farm_client=adapter, captured_at=captured_at
        )
        if order is None or order.get("status_confirmacao") not in {
            "CONFIRMADO_API",
            "CANCELADO_API",
        }:
            continue
        previous = old.get(oid)
        date = business_order_datetime(header.get("emissao"))
        now = business_order_datetime(captured_at)
        if previous and date and now and (now.date() - date.date()).days > 20:
            # Fechamento financeiro antigo permanece; apenas o vínculo pode mudar.
            order = dict(previous, contact_uuid=uuid)
            detail = [
                dict(item, contact_uuid=uuid)
                for item in (existing_items or [])
                if item.get("pedido_id") == oid
            ]
        else:
            suffix = (
                "_IDENTIDADE_VALIDADA"
                if str(order.get("origem_pedido", "")).endswith("_IDENTIDADE_VALIDADA")
                else ""
            )
            order["origem_pedido"] = "FARMALIDER_HISTORICO_OBSERVADO" + suffix
            order["capturado_em"] = first
            for key in order:
                if key.startswith(("primeiro_anuncio_", "ultimo_anuncio_")):
                    order[key] = ""
        orders.append(order)
        items.extend(detail)
        receipts.append((digest, uuid, oid, digest))
    return orders, items, receipts


def acknowledge(receipts):
    if not receipts:
        return
    with connect() as db:
        db.executemany(
            "UPDATE orders SET synced=?,linked=? WHERE id=? AND digest=?", receipts
        )


def merge_history(
    current_orders, current_items, history_orders, history_items, existing_orders
):
    """Consulta atual prevalece; primeira captura e IDs dos pedidos permanecem estáveis."""
    from pedido_utils import business_order_datetime

    current = {row["pedido_chave"] for row in current_orders}
    extra = {row["pedido_chave"] for row in history_orders} - current
    orders = current_orders + [
        row for row in history_orders if row["pedido_chave"] in extra
    ]
    items = current_items + [
        row for row in history_items if row["pedido_chave"] in extra
    ]
    first = {}
    for row in existing_orders + history_orders:
        key, captured = row.get("pedido_chave"), row.get("capturado_em")
        date = business_order_datetime(captured)
        if key and date and (key not in first or date < first[key][0]):
            first[key] = date, captured
    for row in orders:
        if row["pedido_chave"] in first:
            row["capturado_em"] = first[row["pedido_chave"]][1]
    return orders, items
