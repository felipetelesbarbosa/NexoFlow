from copy import deepcopy
from uuid import uuid4

import pytest

from ds_backend.adapter import PostgresStore
from ds_backend.contract import StorageError, digest
from tests.datastudio.test_contract import row


class MemoryClient:
    def __init__(self):
        self.config = dict(segment="FARMA")
        self.expected_target = "synthetic.farma"
        self.tables = {}
        self.receipts = {}
        self.replacements = set()
        self.reads = self.writes = 0

    def begin(self, *_args):
        return dict(revision=str(uuid4()))

    def rows(self, name, revision):
        yield from deepcopy(self.tables.get(name, []))

    def send(self, revision, name, rows, remove=None):
        from ds_backend.contract import record_key

        rows = deepcopy(rows)
        current = {record_key(name, r): r for r in self.tables.get(name, [])}
        current.update({record_key(name, r): r for r in rows})
        for key in remove or []:
            current.pop(key, None)
        self.tables[name] = list(current.values())
        receipt = dict(id=str(uuid4()), hash=digest(rows), state="CONFIRMADO")
        self.receipts[receipt["id"]] = receipt["hash"]
        return receipt

    def call(self, path, data):
        if path == "/v1/substituicoes":
            self.replacements.add(data["name"])
            return {}
        if path == "/v1/selar":
            return dict(state="SELADA")
        assert path == "/v1/confirmar"
        assert data["manifest"]["batches"] == self.receipts
        return dict(state="READY")

    def close(self):
        pass

    def verify(self):
        return {}


def test_contact_upsert_control_and_no_google_io(monkeypatch):
    import gspread

    monkeypatch.setattr(
        gspread, "service_account", lambda **_: pytest.fail("Google não deve abrir")
    )
    client = MemoryClient()
    store = PostgresStore(client)
    contact = row("Base_Contatos", contact_uuid="synthetic-contact")
    first = store.upsert_contacts_detailed([contact])
    assert first.inserted == 1
    store.append_history(first.changed_records, set())
    assert len(store.records("Historico_Alteracoes")) == 1
    second = store.upsert_contacts_detailed([contact])
    assert second.unchanged == 1
    store.set_controls(dict(ultima_sincronizacao_sucesso_utc="2026-11-02T12:00:00Z"))
    assert (
        store.get_control("ultima_sincronizacao_sucesso_utc") == "2026-11-02T12:00:00Z"
    )
    assert store.finish(complete=True)["state"] == "READY"


def test_remote_cache_commit_and_rollback_do_not_touch_existing_sqlite(tmp_path):
    from ds_backend.cache import connect

    client = MemoryClient()
    store = PostgresStore(client)
    with connect(store) as db:
        db.execute("INSERT INTO profile VALUES(?)", ("FARMA",))
        db.execute(
            "INSERT INTO creations(id,status) VALUES(?,?)", ("synthetic", "pending")
        )
    assert client.tables["Cache_creations"][0]["status"] == "pending"
    db = connect(store)
    with pytest.raises(ValueError), db:
        db.execute("UPDATE creations SET status='not-confirmed'")
        raise ValueError("synthetic")
    db.close()
    assert client.tables["Cache_creations"][0]["status"] == "pending"
    # Outro PC reconstrói a mesma observação do servidor, sem copiar SQLite local.
    other = PostgresStore(client)
    with connect(other) as db:
        assert db.execute("SELECT id,status FROM creations").fetchall() == [
            ("synthetic", "pending")
        ]


def test_cache_failure_does_not_commit_local_checkpoint():
    from ds_backend.cache import connect

    client = MemoryClient()
    store = PostgresStore(client)
    db = connect(store)

    def fail(*_a, **_k):
        raise StorageError("DS_RESPOSTA_NAO_CONFIRMADA_RETOMAR")

    client.send = fail
    with pytest.raises(StorageError), db:
        db.execute(
            "INSERT INTO creations(id,status) VALUES(?,?)", ("synthetic", "pending")
        )
    assert db.execute("SELECT * FROM creations").fetchall() == []
    db.close()


def test_global_financial_summary_keeps_old_purchase_and_distinct_customer():
    from ds_backend.history import regenerate

    client = MemoryClient()
    store = PostgresStore(client)
    # Mesmo cliente em dois meses: duas compras, um comprador no TOTAL.
    for oid, day, amount in [
        ("1", "2026-10-02", "10.01"),
        ("2", "2026-11-02", "20.02"),
    ]:
        client.tables.setdefault("Historico_Pedidos", []).append(
            row(
                "Historico_Pedidos",
                chave="FARMA:" + oid,
                segmento="FARMA",
                pedido_id=oid,
                cliente_id="customer-synthetic",
                data=day,
                estado="valido",
                produtos=amount,
                frete="0.00",
                faturamento=amount,
                vigente="Sim",
            )
        )
        client.tables.setdefault("Historico_Itens", []).append(
            row(
                "Historico_Itens",
                chave="FARMA:" + oid + ":1",
                segmento="FARMA",
                pedido_id=oid,
                item_id="1",
                sku="001",
                produto="Synthetic",
                quantidade="1",
                valor=amount,
                frete="Não",
                estado="valido",
                vigente="Sim",
            )
        )
    regenerate(store)
    assert store.records("BI_LTV_Clientes")[0]["ltv_observado"] == "30.03"
    total = next(
        r for r in store.records("BI_Historico_Resumo") if r["tipo_recorte"] == "TOTAL"
    )
    assert (total["pedidos"], total["clientes"], total["faturamento"]) == (
        "2",
        "1",
        "30.03",
    )
    # Cancelamento de um pedido não apaga o outro nem soma os meses como clientes.
    store._cache["Historico_Pedidos"][1] = dict(
        store._cache["Historico_Pedidos"][1],
        estado="cancelado",
        produtos="0.00",
        faturamento="0.00",
    )
    regenerate(store)
    assert store.records("BI_LTV_Clientes")[0]["ltv_observado"] == "10.01"
    assert (
        next(
            r
            for r in store.records("BI_Historico_Resumo")
            if r["tipo_recorte"] == "TOTAL"
        )["clientes"]
        == "1"
    )


def test_published_financial_fact_is_not_replaced_by_missing_items_or_exclusion():
    from ds_backend.history import protect_published

    client = MemoryClient()
    store = PostgresStore(client)
    old = row(
        "Historico_Pedidos",
        chave="FARMA:1",
        segmento="FARMA",
        pedido_id="1",
        cliente_id="synthetic",
        data="2020-04-20",
        estado="valido",
        produtos="10.00",
        frete="0.00",
        faturamento="10.00",
        vigente="Sim",
    )
    client.tables["Historico_Pedidos"] = [old]
    tables = {
        "Historico_Pedidos": [
            dict(old, estado="pendente", produtos="0.00", faturamento="0.00")
        ],
        "Historico_Itens": [],
        "BI_Cobertura_Historica": [],
    }
    filtered, issues = protect_published(store, tables)
    assert (
        not filtered["Historico_Pedidos"]
        and issues[0]["reason"] == "COMPRA_VALIDA_PRESERVADA"
    )
    store._cache["Historico_Pedidos"] = [dict(old, vigente="Não")]
    tables["Historico_Pedidos"] = [old]
    assert (
        protect_published(store, tables)[1][0]["reason"]
        == "EXCLUSAO_PUBLICADA_PRESERVADA"
    )


def test_detail_delta_preserves_old_sale_and_skips_timestamp_only_run():
    from ds_backend.contract import REGISTRY

    client = MemoryClient()
    store = PostgresStore(client)
    old = row(
        "BI_Itens",
        item_chave="old-item",
        venda_chave="old-sale",
        produto_codigo="0001",
        quantidade="1",
        receita_item="10.00",
        atualizado_em="2026-11-01T12:00:00Z",
    )
    current = row(
        "BI_Itens",
        item_chave="new-item",
        venda_chave="new-sale",
        produto_codigo="0002",
        quantidade="1",
        receita_item="20.00",
        atualizado_em="2026-11-02T12:00:00Z",
    )
    client.tables["BI_Itens"] = [old]
    headers = REGISTRY["BI_Itens"]["columns"]
    ws = store._known_sheets["BI_Itens"]
    assert store._replace_table(ws, headers, [[current[c] for c in headers]])
    assert {r["item_chave"] for r in store.records("BI_Itens")} == {
        "old-item",
        "new-item",
    }
    count = len(client.receipts)
    changed = dict(current, atualizado_em="2026-11-03T12:00:00Z")
    assert not store._replace_table(ws, headers, [[changed[c] for c in headers]])
    assert len(client.receipts) == count
    store._cancelled_sales = {"old-sale"}
    assert store._replace_table(ws, headers, [[changed[c] for c in headers]])
    assert {r["item_chave"] for r in store.records("BI_Itens")} == {"new-item"}
