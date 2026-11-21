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


def test_farma_weni_simulation_and_failure_do_not_seal(monkeypatch):
    from types import SimpleNamespace

    import project_paths
    from ds_backend import runtime
    from ds_backend.cache import connect

    calls = []

    class TrackedClient(MemoryClient):
        info = {"version": 2, "pending": []}

        def begin(self, *args):
            calls.append("begin")
            return super().begin(*args)

        def call(self, path, data):
            calls.append(path)
            if path == "/v1/estados/ler":
                return {"document": state}
            return super().call(path, data)

    client = TrackedClient()
    monkeypatch.setenv("NEXOFLOW_PERFIL", "FARMA")
    monkeypatch.setattr(runtime, "configured", lambda: True)
    monkeypatch.setattr(runtime.Client, "from_settings", lambda _: client)
    monkeypatch.setattr(
        project_paths,
        "load_private_settings",
        lambda: SimpleNamespace(ARMAZENAMENTO_BACKEND="postgres"),
    )

    @runtime.backend_session("weni")
    def operation(argv):
        if "--dry-run" in argv:
            store = runtime.CURRENT_STORE
            assert store.readonly
            assert client.expected_read_version == 2
            with connect(store) as db:
                db.execute("INSERT INTO profile VALUES(?)", ("FARMA",))
            assert not client.tables
            assert store.revision is None
        return result

    state = None
    result = 1
    assert operation(["--dry-run"]) == 1
    assert not calls
    with pytest.raises(StorageError, match="DS_ESTADO_EXIGE_MIGRACAO_INICIAL"):
        operation(["--apply"])
    assert calls == ["/v1/estados/ler"]
    state = {"cursor": "synthetic"}
    calls.clear()
    assert operation(["--apply"]) == 1
    assert calls == ["/v1/estados/ler", "begin"]
    calls.clear()
    result = 0
    assert operation(["--dry-run"]) == 0
    assert not calls
    assert operation(["--apply"]) == 0
    assert calls == ["/v1/estados/ler", "begin", "/v1/selar", "/v1/confirmar"]


def test_postgres_contact_and_bi_logs_identify_vps_and_ready(caplog):
    from looker_bi import SCHEMAS

    client = MemoryClient()
    store = PostgresStore(client)
    contact = row("Base_Contatos", contact_uuid="synthetic-contact")
    store.upsert_contacts_detailed([contact])
    with caplog.at_level("INFO"):
        _, records, ids = store.load_base_snapshot()
        store.reconcile_pharmacy_scope(include_history=False)
        store.replace_looker_tables({name: [] for name in SCHEMAS})
        assert "READY" not in caplog.text
        store.finish(complete=True)
    assert len(records) == 1 and ids == {"synthetic-contact"}
    assert "Google Sheets" not in caplog.text
    assert "PostgreSQL da VPS" in caplog.text
    assert "READY" in caplog.text
    assert store.request_stats()["total"] == client.reads + client.writes

def test_falha_de_confirmacao_preserva_a_pendencia_e_o_rotulo_do_sheets(caplog, monkeypatch):
    from unittest.mock import Mock

    from google_sheets import GoogleSheetsStore

    client = MemoryClient()
    store = PostgresStore(client)
    monkeypatch.setattr(client, "call", lambda *_: {"state": "SELADA"})
    with caplog.at_level("INFO"):
        with pytest.raises(StorageError, match="DS_REVISAO_NAO_CONFIRMADA"):
            store.finish(complete=True)
        assert "READY" not in caplog.text
        google = Mock()
        google._read_with_retry.return_value = []
        google._values_to_records.return_value = []
        GoogleSheetsStore.load_base_snapshot(google)
        assert "Google Sheets: Base_Contatos pré-carregada" in caplog.text


def test_progresso_historico_so_conta_lotes_com_recibo(caplog, monkeypatch):
    client = MemoryClient()
    store = PostgresStore(client)
    send = client.send
    sizes = []

    def interromper_segundo_lote(revision, name, rows, remove=None):
        sizes.append(len(rows))
        if len(sizes) == 2:
            raise StorageError("DS_RESPOSTA_NAO_CONFIRMADA_RETOMAR")
        return send(revision, name, rows, remove=remove)

    monkeypatch.setattr(client, "send", interromper_segundo_lote)
    contacts = [row("Base_Contatos", contact_uuid=f"synthetic-{i}") for i in range(1001)]
    with caplog.at_level("INFO"), pytest.raises(StorageError, match="NAO_CONFIRMADA"):
        store.append_history(contacts, set())

    assert sizes == [1000, 1]
    assert len(store._receipts) == 1
    assert "leitura de Historico_Alteracoes" in caplog.text
    assert "total ainda desconhecido" in caplog.text
    assert "1000/1001" in caplog.text and "lotes=1/2" in caplog.text
    assert "interrompido" in caplog.messages[-1]
    assert "1001/1001 linhas com recibo" not in caplog.text and "synthetic-0" not in caplog.text
    assert "READY" not in caplog.text


def test_progresso_leitura_incompleta_nao_persiste_parcial(caplog, monkeypatch):
    store = PostgresStore(MemoryClient())

    def partial(name, revision):
        yield row(name, contact_uuid="privado")
        raise StorageError("DS_CURSOR_INVALIDO")

    monkeypatch.setattr(store.client, "rows", partial)
    with caplog.at_level("INFO"), pytest.raises(StorageError, match="DS_CURSOR_INVALIDO"):
        store.records("Historico_Alteracoes")
    assert "1 linhas lidas" in caplog.messages[-1]
    assert "interrompido" in caplog.messages[-1]
    assert "privado" not in caplog.text
    assert "Historico_Alteracoes" not in store._cache


def test_progresso_historico_sucesso_e_sem_mudancas(caplog, monkeypatch):
    client = MemoryClient()
    store = PostgresStore(client)
    monkeypatch.setattr(store, "now_iso", lambda: "2026-11-20T20:00:00Z")
    contacts = [row("Base_Contatos", contact_uuid="synthetic-1")]
    with caplog.at_level("INFO"):
        store.append_history(contacts, set())
        assert "1/1 linhas com recibo | lotes=1/1" in caplog.messages[-1]
        assert "concluído" in caplog.messages[-1]
        caplog.clear()
        store.append_history(contacts, set())
        assert "gravações na revisão" not in caplog.text
        assert "leitura de Historico_Alteracoes" not in caplog.text
        assert len(store._receipts) == 1
        monkeypatch.setattr(client, "rows", lambda *_: pytest.fail("Leitura desnecessária"))
        store._cache.clear()
        store.append_history([], set())


def test_analytics_reconciles_shorter_snapshot_through_postgres_and_replays():
    from ds_backend.contract import record_key
    from tests.test_pharmacy_scope import fixture

    client = MemoryClient()
    store = PostgresStore(client)
    order, items, _ = fixture()
    other, other_items, _ = fixture(order_id="701")
    store.upsert_pharmacy_orders([order, other], items + other_items)
    name = "Itens_Pedidos_FarmaLider"
    kept, untouched = store.records(name)
    stale = dict(kept, item_chave="synthetic-obsolete")
    client.tables[name].append(stale)
    # Outra instância lê a base acumulada pela mesma entrada usada no Analytics.
    store = PostgresStore(client)
    _, result = store.upsert_pharmacy_orders([order], items)
    assert result.removed == 1
    expected = {record_key(name, r) for r in [kept, untouched]}
    assert {record_key(name, r) for r in client.tables[name]} == expected
    assert {record_key(name, r) for r in result.final_records} == expected
    receipts = len(client.receipts)
    _, repeated = store.upsert_pharmacy_orders([order], items)
    assert repeated.removed == 0 and len(client.receipts) == receipts


def test_scope_sanitation_keeps_separate_changes_for_one_contact():
    client = MemoryClient()
    name = "Historico_Alteracoes"
    records = [
        row(
            name,
            contact_uuid="shared",
            sincronizado_em=t,
            acao="Atualizado",
            nome="synthetic",
        )
        for t in ("2026-11-01", "2026-11-02")
    ]
    client.tables[name] = deepcopy(records)
    store = PostgresStore(client)

    def sanitize(record):
        if record["sincronizado_em"] == "2026-11-02":
            record["nome"] = "corrected"
        return record

    assert store._sanitize_scope_rows(store.history, sanitize) == 1
    assert [r["nome"] for r in store.records(name)] == ["synthetic", "corrected"]
    assert store.records(name) == client.tables[name]
    assert store._sanitize_scope_rows(store.history, sanitize) == 0


def test_unconfirmed_item_removal_keeps_cache_and_can_be_retried(monkeypatch):
    from tests.test_pharmacy_scope import fixture

    order, items, _ = fixture()
    store = PostgresStore(MemoryClient())
    _, original = store.upsert_pharmacy_orders([order], items)
    name = "Itens_Pedidos_FarmaLider"
    keep = original.final_records[0]
    stale = dict(keep, item_chave="obsolete")
    store.records(name).append(stale)
    store.client.tables[name].append(deepcopy(stale))
    confirmed_send = store.client.send

    def no_receipt(revision, table, rows, remove=None):
        if remove:
            raise StorageError("DS_RESPOSTA_NAO_CONFIRMADA_RETOMAR")
        return confirmed_send(revision, table, rows, remove)

    with monkeypatch.context() as patch:
        patch.setattr(store.client, "send", no_receipt)
        with pytest.raises(StorageError, match="DS_RESPOSTA_NAO_CONFIRMADA_RETOMAR"):
            store.upsert_pharmacy_orders([order], items)
    assert stale in store.records(name)
    _, retried = store.upsert_pharmacy_orders([order], items)
    assert retried.removed == 1 and retried.final_records == [keep]


def test_analytics_aborts_only_its_own_definitive_preseal_failure():
    from unittest.mock import Mock

    client = MemoryClient()
    client.call = Mock(return_value={"state": "ABORTADA", "facts_preserved": True})
    error = StorageError("DS_OPERACAO_SHEETS_NAO_PERMITIDA")
    for store in (PostgresStore(client, purpose="weni"), PostgresStore(client, readonly=True),
                  PostgresStore(client, revision=str(uuid4()))):
        assert not store.abort_after_fatal_error(error)
    store = PostgresStore(client)
    for pending in ("DS_FONTES_INCOMPLETAS_RETOMAR", "DS_RESPOSTA_NAO_CONFIRMADA_RETOMAR", "DS_RECIBO_DIVERGENTE"):
        assert not store.abort_after_fatal_error(StorageError(pending))
    client.call.assert_not_called()
    assert store.abort_after_fatal_error(error)
    client.call.assert_called_once_with("/v1/analytics/abortar-incompleta", {"revision": store.revision})
    client.call.reset_mock()
    store._finalization_started = True
    assert not store.abort_after_fatal_error(error)
    client.call.assert_not_called()
