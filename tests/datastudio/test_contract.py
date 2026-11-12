from decimal import Decimal

import pytest

from ds_backend.contract import REGISTRY, StorageError, normalize, record_key, target


def row(name, **values):
    return {c: values.get(c, "") for c in REGISTRY[name]["columns"]}


def test_contract_preserves_text_and_decimal():
    value = row(
        "BI_Itens",
        item_chave="i",
        produto_codigo="00123",
        quantidade="2",
        valor_unitario="0.10",
        receita_item="0.20",
        data="2026-11-02",
        sku_informado=1,
    )
    result = normalize("BI_Itens", [value], "FARMA")[0]
    assert result["produto_codigo"] == "00123"
    assert Decimal(result["receita_item"]) == Decimal("0.20")
    assert record_key("BI_Itens", result) == record_key("BI_Itens", value)
    with pytest.raises(StorageError):
        normalize("BI_Itens", [dict(value, receita_item=float("nan"))], "FARMA")
    with pytest.raises(StorageError):
        target("producao", "OUTRA")


def test_history_segment_is_not_a_destination_hint():
    value = row("Historico_Pedidos", chave="PET:1", segmento="PET")
    with pytest.raises(StorageError, match="SEGMENTO"):
        normalize("Historico_Pedidos", [value], "FARMA")


def test_composite_dimensions_allow_unknown_ad_without_inventing_identifier():
    value = row("BI_Ads", data_snapshot="2026-11-02", tipo_atribuicao="ultimo")
    assert normalize("BI_Ads", [value], "FARMA")[0]["anuncio_id"] == ""


def test_compacted_checkpoint_keeps_hash_and_rejects_corruption():
    from ds_backend.states import pack, unpack

    value = {
        "contacts": {
            "synthetic-" + str(i): {"status": "pending", "snapshot": "x" * 40}
            for i in range(10000)
        }
    }
    packed = pack(value)
    assert packed["encoding"] == "zlib_json_1"
    assert unpack(packed) == value
    with pytest.raises(StorageError):
        unpack(dict(packed, sha256="0" * 64))


def test_paged_read_refuses_mixed_publication_versions():
    from ds_backend.client import Client

    client = Client.__new__(Client)
    pages = iter(
        [
            dict(version=1, rows=[{"key": "a"}], next="a"),
            dict(version=2, rows=[{"key": "b"}], next=None),
        ]
    )
    client.call = lambda *_: next(pages)
    iterator = client.rows("BI_Itens", None)
    assert next(iterator) == {"key": "a"}
    with pytest.raises(StorageError, match="VERSAO_ALTERADA"):
        next(iterator)


def test_period_fields_are_civil_dates_not_arbitrary_timestamp_text():
    for spec in REGISTRY.values():
        assert spec["period"] is None or spec["types"][spec["period"]] == "date"
