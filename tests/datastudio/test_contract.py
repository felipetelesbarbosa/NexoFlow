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
    client.expected_read_version = None
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


def test_pinned_preview_refuses_a_different_version_on_first_page():
    from ds_backend.client import Client

    client = Client.__new__(Client)
    client.expected_read_version = 2
    client.call = lambda *_: dict(version=3, rows=[{"key": "new"}], next=None)
    with pytest.raises(StorageError, match="VERSAO_ALTERADA"):
        list(client.rows("BI_Itens", None))


def test_period_fields_are_civil_dates_not_arbitrary_timestamp_text():
    for spec in REGISTRY.values():
        assert spec["period"] is None or spec["types"][spec["period"]] == "date"


@pytest.mark.parametrize(
    "case,expected_calls",
    [
        ("antes_do_commit", ["POST", "GET", "POST"]),
        ("recibo_atrasado", ["POST", "GET", "POST", "GET"]),
        ("sem_recibo", ["POST", "GET", "POST", "GET"]),
        ("permissao", ["POST", "GET"]),
    ],
)
def test_resposta_incerta_confere_mesmo_lote_antes_de_reenviar(case, expected_calls):
    from uuid import uuid4

    from ds_backend.client import Client
    from ds_backend.contract import digest, normalize

    revision, batch = str(uuid4()), str(uuid4())
    rows = [row("BI_Itens", item_chave="teste")]
    payload = dict(
        revision=revision,
        table="BI_Itens",
        rows=normalize("BI_Itens", rows, "FARMA"),
        remove=[],
    )
    receipt = dict(
        id=batch,
        revision=revision,
        hash=digest(payload),
        state="CONFIRMADO",
        inserted=1,
        updated=0,
        unchanged=0,
        removed=0,
    )
    client = Client.__new__(Client)
    client.config = {"segment": "FARMA"}
    calls = []

    def call(path, data=None):
        if data is not None:
            assert path == "/v1/lotes"
            assert data == dict(
                revision=revision,
                batch_id=batch,
                name="BI_Itens",
                rows=rows,
                remove=[],
                simulate=False,
            )
            calls.append("POST")
            if case == "antes_do_commit" and calls.count("POST") == 2:
                return receipt
            raise StorageError("DS_RESPOSTA_NAO_CONFIRMADA_RETOMAR")
        assert path == "/v1/lotes/" + batch
        calls.append("GET")
        if case == "permissao":
            raise StorageError("DS_PERMISSAO")
        if case == "recibo_atrasado" and calls.count("GET") == 2:
            return receipt
        raise StorageError("DS_LOTE_AUSENTE")

    client.call = call
    if case in ("sem_recibo", "permissao"):
        with pytest.raises(
            StorageError,
            match="DS_LOTE_AUSENTE" if case == "sem_recibo" else "DS_PERMISSAO",
        ):
            client.send(revision, "BI_Itens", rows, batch_id=batch)
    else:
        assert client.send(revision, "BI_Itens", rows, batch_id=batch) == receipt
    assert calls == expected_calls


def test_read_timeout_only_extended_for_final_confirmation():
    from unittest.mock import Mock

    from ds_backend.client import Client

    session = Mock()
    session.request.return_value.status_code = 200
    session.request.return_value.json.return_value = {}
    client = Client.__new__(Client)
    client.session = session
    client.endpoint = "https://example.invalid"
    client.reads = client.writes = 0
    for path, data, timeout in [
        ("/v1/confirmar", {"revision": "test"}, (10, 120)),
        ("/v1/selar", {}, (10, 65)),
        ("/v1/lotes", {}, (10, 65)),
        ("/v1/revisoes/test", None, (10, 65)),
    ]:
        client.call(path, data)
        assert session.request.call_args.kwargs["timeout"] == timeout
