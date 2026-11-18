"""Gera/confere o catálogo Apps Script usando o contrato Python e os tipos legados."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))
from ds_backend.contract import SCHEMA_HASH  # noqa: E402
from integrations.datastudio.read_catalog import (  # noqa: E402
    ELIGIBLE_FIELD,
    PRODUCT_FIELDS,
    READ_REGISTRY,
)


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    old = json.loads(
        subprocess.check_output(
            [
                "node",
                "-e",
                "console.log(JSON.stringify(require('./connectors/continuacoes/Schemas.js')))",
            ],
            cwd=ROOT,
            text=True,
        )
    )
    public = {}
    for name, spec in READ_REGISTRY.items():
        if not spec["public"]:
            continue
        dims = spec.get(
            "dimensions",
            [
                f
                for f, kind in old.get(name, [])
                if kind.startswith("number") and kind != "number"
            ],
        )
        columns = spec.get("read_columns", spec["columns"])
        public[name] = dict(
            {key: value for key, value in spec.items() if key != "optional"},
            columns=columns,
            dimensions=dims,
            types={f: spec["types"][f] for f in columns},
        )
    # Lado direito do LEFT ds74/ds72. O agrupamento usa a API de leitura
    # existente e a regra oficial da visão de pedidos, no histórico inteiro.
    public["Compradores_Operacionais"] = dict(
        columns=["contact_uuid", ELIGIBLE_FIELD],
        types={"contact_uuid": "text", ELIGIBLE_FIELD: "text"},
        labels=public["Pedidos_FarmaLider"]["labels"],
        dimensions=[],
        period=None,
    )
    # A coorte é filtrada pelo primeiro anúncio no lado esquerdo da mesclagem.
    ad_order_fields = [
        "pedido_id",
        "cliente",
        "cliente_chave",
        "data",
        "pedido_produtos",
        "pedido_faturamento_total",
        "venda_valida",
    ]
    public["Pedidos_Atribuiveis_Meta"] = dict(
        segment="FARMA",
        columns=ad_order_fields,
        types={f: public["BI_Pedidos"]["types"][f] for f in ad_order_fields},
        dimensions=[],
        period=None,
    )
    ad_contact_fields = [
        "contact_uuid",
        "primeiro_anuncio_id",
        "primeiro_anuncio_origem",
        "primeiro_anuncio_data",
        "pedido_id",
        "pedido_data",
    ]
    public["Contatos_Atribuicao_Meta"] = dict(
        segment="FARMA",
        columns=[*ad_contact_fields, "coorte_primeiro_anuncio", "pedido_apos_anuncio"],
        types={
            **{f: public["Base_Contatos"]["types"][f] for f in ad_contact_fields},
            "coorte_primeiro_anuncio": "date",
            "pedido_apos_anuncio": "text",
        },
        dimensions=[],
        period="coorte_primeiro_anuncio",
    )
    abc = json.loads(
        subprocess.check_output(
            [
                "node",
                "-e",
                "const fs=require('fs'),vm=require('vm'),c={};vm.createContext(c);vm.runInContext(fs.readFileSync('connectors/looker_abc/Code.js','utf8'),c);console.log(JSON.stringify(Object.fromEntries(['abc','resumo','juntos'].map(m=>[m,c.fieldSpecs_(m)]))))",
            ],
            cwd=ROOT,
            text=True,
        )
    )
    for mode, fields in abc.items():
        public["ABC_" + mode] = dict(
            columns=[f for f, _ in fields],
            types={
                f: "date" if k == "date" else "text" if k == "text" else "number"
                for f, k in fields
            },
            dimensions=[],
            period="periodo_inicio",
            abc_mode=mode,
            abc_kinds=dict(fields),
        )
    products = {
        "periodo_inicio": ("date", "Início do período"),
        "produto_codigo": ("text", "Código do produto"),
        "produto_nome": ("text", "Nome do produto"),
        "quantidade": ("sum", "Unidades"),
        "receita_item": ("money", "Receita de produtos"),
        "participacao_acumulada": ("percent", "Participação acumulada"),
        "registros": ("sum", "Linhas de itens"),
        "produtos_distintos_periodo": (
            "max",
            "Produtos distintos no período (SKU informado)",
        ),
        "posicao_receita_top5": ("max", "Posição no Top 5 por receita"),
        "posicao_unidades_top5": ("max", "Posição no Top 5 por unidades"),
    }
    public["Produtos_Mais_Vendidos"] = dict(
        columns=list(products),
        types={
            f: k if k in {"text", "date"} else "number"
            for f, (k, _) in products.items()
        },
        dimensions=[],
        period="periodo_inicio",
        segment="FARMA",
        product_modes={
            mode: sorted(fields | {"periodo_inicio"})
            for mode, fields in PRODUCT_FIELDS.items()
        },
        metric_kinds={
            f: k for f, (k, _) in products.items() if k not in {"text", "date"}
        },
        labels={f: label for f, (_, label) in products.items()},
    )
    core = ROOT / "connectors/datastudio_api/AbcCore.js"
    original = (ROOT / "connectors/looker_abc/AbcCore.js").read_text(encoding="utf-8")
    if args.check:
        if core.read_text(encoding="utf-8") != original:
            raise SystemExit("Cálculo ABC diverge da referência oficial.")
    else:
        core.write_text(original, encoding="utf-8")
    content = (
        "/* Gerado pelo contrato; executar scripts/sync_datastudio_schema.py --check. */\nvar NexoDSSchemaHash="
        + json.dumps(SCHEMA_HASH)
        + ";\nvar NexoDSSchemas="
        + json.dumps(public, ensure_ascii=False, indent=2)
        + ';\nif(typeof module!=="undefined")module.exports={hash:NexoDSSchemaHash,tables:NexoDSSchemas};\n'
    )
    path = ROOT / "connectors/datastudio_api/Schemas.js"
    if args.check:
        if path.read_text(encoding="utf-8") != content:
            raise SystemExit("Catálogo Data Studio diverge do contrato.")
    else:
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    run()
