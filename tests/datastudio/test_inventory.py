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
    assert aliases["ds72"]["target_table"] == "Pedidos_FarmaLider"
    assert aliases["ds109"]["target_table"] == "ABC_resumo"  # Dinâmico ≠ snapshot.
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


def test_new_alias_contract_does_not_mutate_windows_storage_or_guess_conversations():
    from ds_backend.contract import REGISTRY
    from integrations.datastudio.read_catalog import READ_REGISTRY

    assert not REGISTRY["Pedidos_FarmaLider"]["public"]
    assert READ_REGISTRY["Pedidos_FarmaLider"]["public"]
    assert REGISTRY["Itens_Pedidos_FarmaLider"]["types"]["quantidade"] == "text"
    assert READ_REGISTRY["Itens_Pedidos_FarmaLider"]["types"]["quantidade"] == "number"
    sources = {s["alias"]: s for s in audit()["sources"]}
    assert sources["ds106"]["target_table"] == "ABC_abc"
    assert sources["ds107"]["target_table"] == "ABC_abc"
    assert sources["ds110"]["target_table"] == "ABC_juntos"
    assert (
        sources["ds136"]["confirmed_header"]
        == "data segmento conversas_weni resolvidas nao_resolvidas transferidas origem fuso".split()
    )
    assert sources["ds136"]["target_table"] is None


def test_work_supplement_confirms_modes_and_keeps_unknown_metadata_explicit():
    sources = {s["alias"]: s for s in audit()["sources"]}
    schemas = json.loads(
        subprocess.check_output(
            [
                "node",
                "-e",
                "console.log(JSON.stringify(require('./connectors/datastudio_api/Schemas.js').tables))",
            ],
            text=True,
        )
    )
    for alias in ("ds106", "ds107", "ds109", "ds110"):
        source = sources[alias]
        meta = source["confirmed_report_metadata"]
        assert set(meta["visible_fields"]) <= set(
            schemas[source["target_table"]]["columns"]
        )
        assert meta["deployment_id"] is None
        assert meta["deployment_version"] is None
        assert meta["local_field_overrides_confirmed"] is False
        assert source["legacy_config"]["date_range_required"] is True
        assert (
            "spreadsheetId" not in source["config"]
        )  # evidência antiga, não dependência nova
    assert len(sources["ds106"]["confirmed_report_metadata"]["visible_fields"]) == 16
    assert len(sources["ds107"]["confirmed_report_metadata"]["visible_fields"]) == 19
    orders = sources["ds72"]["confirmed_report_metadata"]
    assert orders["calculated_field"]["id"] == "calc_gf73fvq57d"
    assert orders["buyers_metric"]["source_field_id"] == "_1277959290_"
    assert orders["buyers_metric"]["blend_output_id"] is None
    assert len(orders["filter"]["blends"]) == 2
    conversations = sources["ds136"]["confirmed_report_metadata"]
    assert conversations["reader_refresh_minutes"] == 15
    assert all(
        conversations[k] is None
        for k in (
            "producer",
            "unique_key",
            "project_in_key",
            "write_and_revision_policy",
            "manual_edits",
            "target_table",
        )
    )
