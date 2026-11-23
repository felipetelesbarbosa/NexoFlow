"""Conferência de pendências de fechamento antigo com fatos sintéticos."""

from copy import deepcopy

import pytest

from ds_backend.adapter import PostgresStore
from ds_backend.history import protect_published
from tests.datastudio.test_adapter import MemoryClient
from tests.datastudio.test_contract import row


def history_sale(segment="FARMA"):
    client = MemoryClient()
    client.config["segment"] = segment
    header = row(
        "Historico_Pedidos",
        chave=f"{segment}:42",
        segmento=segment,
        pedido_id="42",
        cliente_id="987",
        data="2020-04-20",
        estado="valido",
        produtos="21.00",
        frete="2.00",
        faturamento="23.00",
        vigente="Sim",
    )
    items = [
        row(
            "Historico_Itens",
            chave=f"{segment}:42:{item_id}",
            segmento=segment,
            pedido_id="42",
            item_id=item_id,
            sku="001",
            produto="Descrição preservada",
            quantidade="1.00",
            valor=value,
            frete="Não",
            estado="valido",
            vigente="Sim",
        )
        for item_id, value in (("1", "10.00"), ("2", "11.00"))
    ]
    client.tables.update(Historico_Pedidos=[header], Historico_Itens=items)
    incoming = deepcopy(client.tables)
    incoming["BI_Cobertura_Historica"] = []
    incoming["Historico_Itens"].reverse()
    incoming["Historico_Itens"][0].update(
        produto="Descrição observada", quantidade="1", valor="11.0"
    )
    return PostgresStore(client), incoming


@pytest.mark.parametrize("cached_origin", ["PUBLICADA", "CACHE_HERDADO"])
def test_label_change_preserves_published_sale_and_provenance(cached_origin):
    store, incoming = history_sale()
    store.client.tables["Historico_Pedidos"][0]["origem"] = "PUBLICADA"
    incoming["Historico_Pedidos"][0]["origem"] = cached_origin
    published = deepcopy(store.client.tables)
    filtered, issues = protect_published(store, incoming, inherited_unobserved={"42"})
    assert [issue["id"] for issue in issues] == ["42"]
    assert issues[0]["preserved_description"] is True
    assert filtered["Historico_Pedidos"] == filtered["Historico_Itens"] == []
    assert store.client.tables == published


@pytest.mark.parametrize(
    ("section", "changes"),
    [
        ("Historico_Itens", {"valor": "11.01"}),
        ("Historico_Itens", {"quantidade": "2"}),
        ("Historico_Itens", {"sku": "1"}),
        ("Historico_Itens", {"frete": "Sim"}),
        ("Historico_Itens", {"item_id": "3", "chave": "FARMA:42:3"}),
        ("Historico_Itens", {"estado": "cancelado"}),
        ("Historico_Pedidos", {"estado": "cancelado"}),
        ("Historico_Pedidos", {"cliente_id": "988"}),
        ("Historico_Pedidos", {"data": "2020-04-21"}),
        ("Historico_Pedidos", {"frete": "1.99", "faturamento": "22.99"}),
    ],
)
def test_new_material_difference_keeps_inherited_order_blocked(section, changes):
    store, incoming = history_sale()
    incoming[section][0].update(changes)
    filtered, issues = protect_published(store, incoming, inherited_unobserved={"42"})
    assert len(issues) == 1 and not issues[0].get("preserved_description")
    assert filtered["Historico_Pedidos"] == filtered["Historico_Itens"] == []


@pytest.mark.parametrize("ambiguous", ["duplicate", "missing"])
def test_missing_or_duplicate_item_cannot_prove_a_description_only_change(ambiguous):
    store, incoming = history_sale()
    if ambiguous == "duplicate":
        # Repeated keys on *both* sides must fail even if their quantities match.
        for items in (
            store.client.tables["Historico_Itens"],
            incoming["Historico_Itens"],
        ):
            items[0].update(item_id="1", chave="FARMA:42:1")
            items[1].update(item_id="1", chave="FARMA:42:1")
    else:
        incoming["Historico_Itens"].pop()
    filtered, issues = protect_published(store, incoming, inherited_unobserved={"42"})
    assert len(issues) == 1 and not issues[0].get("preserved_description")
    assert not filtered["Historico_Pedidos"] and not filtered["Historico_Itens"]


@pytest.mark.parametrize(("segment", "eligible"), [("FARMA", set()), ("PET", {"42"})])
def test_unapproved_order_or_segment_remains_blocking(segment, eligible):
    store, incoming = history_sale(segment)
    filtered, issues = protect_published(store, incoming, inherited_unobserved=eligible)
    assert len(issues) == 1 and not issues[0].get("preserved_description")
    assert not filtered["Historico_Pedidos"] and not filtered["Historico_Itens"]


@pytest.mark.parametrize(
    "case",
    ["inherited", "financial", "new", "reobserved", "incomplete_page", "other_reason"],
)
def test_history_collection_and_publication_against_ready_cache(
    case, monkeypatch, tmp_path
):
    from types import SimpleNamespace

    from analytics_history_sync import run as publish_history
    from customer_observations import connect
    from ds_backend import runtime
    from ds_backend.contract import StorageError, normalize
    from order_history import normalize_order
    from order_history_sheets import iter_tables
    from order_history_store import HistoryStore, analytics_history
    from tests.test_order_history import NOW, Source, order

    client = MemoryClient()
    store = PostgresStore(client)
    monkeypatch.setattr(runtime, "CURRENT_STORE", store)
    monkeypatch.setattr("ds_backend.client.configured", lambda: True)
    monkeypatch.setattr("config.LOG_DIR", tmp_path)
    monkeypatch.setattr("farmalider_customers.directory_for", lambda _: None)
    monkeypatch.setenv("NEXOFLOW_PERFIL", "FARMA")
    monkeypatch.delenv("NEXOFLOW_HISTORY_INICIO", raising=False)
    monkeypatch.delenv("NEXOFLOW_HISTORY_FIM", raising=False)
    old_order = order(42, segment="FARMA", day="2020-04-20")
    reason = "FECHAMENTO_ANTIGO_REQUER_RECONCILIACAO"
    with connect() as db:
        cache = HistoryStore(db, "FARMA")
        cache.upsert(
            normalize_order(old_order, "FARMA", NOW), now=NOW, mode="historica"
        )
        if case != "new":
            db.execute(
                "INSERT INTO history_issues VALUES(?,?,?)", ("FARMA", "42", reason)
            )
        for name, record in iter_tables(cache):
            if name in ("Historico_Pedidos", "Historico_Itens"):
                client.tables.setdefault(name, []).extend(
                    normalize(name, [record], "FARMA")
                )

    header = client.tables["Historico_Pedidos"][0]
    header["origem"] = "ORIGEM_DA_PUBLICACAO_ANTERIOR"
    item = client.tables["Historico_Itens"][0]
    item["produto"] = "Descrição da publicação anterior"
    if case == "financial":
        item["valor"] = header["produtos"] = header["faturamento"] = "81.00"
    published_item = dict(item)
    published_header = dict(header)
    # Seed a fresh server revision with only the previous revision's tables.
    published_tables = deepcopy(client.tables)
    client = MemoryClient()
    client.tables = published_tables
    store = PostgresStore(client)
    monkeypatch.setattr(runtime, "CURRENT_STORE", store)
    if case == "reobserved":
        monkeypatch.setenv("NEXOFLOW_HISTORY_INICIO", "2020-04-20")
        monkeypatch.setenv("NEXOFLOW_HISTORY_FIM", "2020-04-20")
        source = Source([old_order])
    else:
        count = 2 if case == "incomplete_page" else 1
        source = Source([order(60 + i, segment="FARMA") for i in range(count)])
    settings = SimpleNamespace(
        ARMAZENAMENTO_BACKEND="postgres",
        FARMALIDER_HISTORY_ENABLED=True,
        FARMALIDER_HISTORY_PAGE_LIMIT=1,
        FARMALIDER_HISTORY_MAX_PAGES=1,
    )
    _, _, collected = analytics_history(source, [], [], [], now=NOW, settings=settings)
    expected_reason = reason
    if case == "other_reason":
        expected_reason = "EMISSAO_INVALIDA"
        with connect() as db:
            db.execute(
                "UPDATE history_issues SET reason=? WHERE segment='FARMA' AND id='42'",
                (expected_reason,),
            )
    publication = publish_history(settings, storage=store, collection=collected)
    if case == "incomplete_page":
        assert collected["status"] == "incompleta"
        assert publication["error"] == "DS_JANELA_INCOMPLETA"
    else:
        assert collected["status"] == "extraida"
        assert publication["preserved_descriptions"] == int(case == "inherited")
        assert publication["blocking_reasons"] == (
            {} if case == "inherited" else {expected_reason: 1}
        )
    assert publication["partial"] is (case != "inherited")
    complete = not publication["partial"]
    if case == "inherited":
        assert collected["pendencias"] == 1
        assert store.finish(complete=complete)["state"] == "READY"
    else:
        with pytest.raises(StorageError, match="DS_FONTES_INCOMPLETAS_RETOMAR"):
            store.finish(complete=complete)
    assert published_header in client.tables["Historico_Pedidos"]
    assert published_item in client.tables["Historico_Itens"]
    with connect() as db:
        assert db.execute(
            "SELECT reason FROM history_issues WHERE segment='FARMA' AND id='42'"
        ).fetchone() == (expected_reason,)
