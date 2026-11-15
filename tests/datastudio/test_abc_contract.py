"""Contrato de leitura ABC e paridade dos empates/fronteiras do núcleo legado."""

import json
import random
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from integrations.datastudio.abc_reader import FIELDS, calculate


def test_abc_field_ids_match_official_connector_schema():
    schema = subprocess.check_output(
        [
            "node",
            "-e",
            "console.log(JSON.stringify(require('./connectors/datastudio_api/Schemas.js').tables))",
        ],
        text=True,
    )
    schema = json.loads(schema)
    for mode, fields in FIELDS.items():
        assert fields == schema["ABC_" + mode]["columns"]
    assert (
        Path("connectors/datastudio_api/AbcCore.js").read_bytes()
        == Path("connectors/looker_abc/AbcCore.js").read_bytes()
    )


@pytest.mark.parametrize(
    "revenues",
    [[80, 15, 5], [80, 10, 10], [40, 40, 15, 5], [0, 0], [1, 1, 1], [95, 3, 2]],
)
def test_classes_ties_percentages_match_legacy(revenues):
    rng = random.Random(17)
    records = []
    items = [
        [
            "item_chave",
            "venda_chave",
            "data",
            "produto_codigo",
            "produto_nome",
            "categoria",
            "quantidade",
            "receita_item",
            "atualizado_em",
        ]
    ]
    orders = [["venda_chave", "data", "faturamento_produtos", "atualizado_em"]]
    for i, revenue in enumerate(revenues):
        key = str(i).zfill(3)
        units = rng.choice([1, 2, 3])
        records.append(
            dict(
                produto=key,
                sku=key,
                nome=key,
                categoria="",
                unidades=units,
                centavos=Decimal(revenue * 100),
                pedidos=1,
            )
        )
        items.append(
            [key, key, "2026-11-02", key, key, "", units, str(revenue), "READY:1"]
        )
        orders.append([key, "2026-11-02", str(revenue), "READY:1"])
    legacy = json.loads(
        subprocess.check_output(
            [
                "node",
                "-e",
                "const fs=require('fs'),c=require('./connectors/looker_abc/AbcCore.js');console.log(JSON.stringify(c.calculate(...JSON.parse(fs.readFileSync(0,'utf8')))));",
            ],
            input=json.dumps([items, orders, "2026-11-01", "2026-11-03"]),
            text=True,
        )
    )
    for mode in ("abc",):
        output = calculate(records, "2026-11-01", "2026-11-03", mode)
        for got, want in zip(output, legacy[mode], strict=True):
            assert set(got) == set(want)
            for k, v in got.items():
                if k == "atualizado_em":
                    assert v == ""
                elif isinstance(v, Decimal):
                    assert float(v) == pytest.approx(want[k], abs=1e-12)
                else:
                    assert v == want[k]
