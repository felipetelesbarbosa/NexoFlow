"""Metadados públicos; nenhuma linha de cliente, compra ou credencial."""

import json
import subprocess
import sys
from pathlib import Path

from scripts.audit_datastudio_inventory import audit


def test_inventory_preserves_aliases_blends_zero_use_and_component_dependencies():
    report = audit()
    assert report["counts"] == dict(
        sources=37,
        blends=5,
        data_components=75,
        period_controls=8,
        filters=14,
        field_id_replacements=3,
    )
    assert len({c["id"] for c in report["components"]}) == 83
    assert {b["name"] for b in report["blends"] if b["uses"] == 0} == {
        "Produtos de pedidos válidos",
        "Público e compras identificadas",
    }
    aliases = {s["alias"]: s for s in report["sources"]}
    assert [aliases[a]["target_table"] for a in ("ds74", "ds103", "ds123")] == [
        "Base_Contatos"
    ] * 3
    assert aliases["ds141"]["name"] != aliases["ds175"]["name"]
    assert (
        aliases["ds141"]["target_table"]
        == aliases["ds175"]["target_table"]
        == "BI_LTV_Clientes"
    )
    assert all(s["preserve_even_if_unused"] for s in report["sources"])


def test_observed_label_is_not_invented_formula_or_permission_to_expose():
    report = audit()
    aliases = {s["alias"]: s for s in report["sources"]}
    assert "Receita gerada" in aliases["ds80"]["labels_or_fields_to_check"]
    assert "faturamento" in aliases["ds80"]["exact_fields_in_contract"]
    assert (
        aliases["ds136"]["target_table"] is None
    )  # Não aliasar Conversas_Diarias à força.
    assert aliases["ds72"]["contract_status"] == "PRIVADA_NAO_EXPOSTA"
    assert aliases["ds109"]["target_table"] is None  # Resumo ABC dinâmico ≠ snapshot.
    assert not report["permits_cutover"]
    assert report["commercial_validation"] == "PENDENTE_NO_GOOGLE"
    assert len([c for c in report["components"] if c["currency_check"] == "BRL"]) == 3
    assert {
        s["alias"]: s["config"].get("recorte_historico")
        for s in report["sources"]
        if s["alias"] in {"ds139", "ds190", "ds191", "ds192"}
    } == {
        "ds139": "TOTAL",
        "ds190": "MES",
        "ds191": "ANO",
        "ds192": "SEM_EMISSAO",
    }


def test_real_inventory_cli_no_credentials_and_no_overwrite(tmp_path):
    root = Path(__file__).resolve().parents[2]
    target = tmp_path / "inventario.json"
    command = [
        sys.executable,
        str(root / "scripts/audit_datastudio_inventory.py"),
        "--saida",
        str(target),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    assert not json.loads(result.stdout)["permits_cutover"]
    original = target.read_bytes()
    assert json.loads(original)["counts"]["sources"] == 37
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert target.read_bytes() == original
