"""Confronta metadados do inventário FARMA com o contrato, sem acessar serviços.

Não autoriza a troca: conexões físicas, fórmulas e resultados dependem do Google.
O arquivo de entrada preservado é evidência fornecida pelo Work, não configuração
executável do publicador ou permissão para expor tabelas privadas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs/inventarios/FARMA_DATA_STUDIO_2026-11-12.md"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))
from integrations.datastudio.read_catalog import READ_REGISTRY  # noqa: E402


def cells(line):
    return [
        part.strip().replace(r"\|", "|") for part in re.split(r"(?<!\\)\|", line)[1:-1]
    ]


def parse(text: str) -> dict[str, Any]:
    sources, blends, components, filters, replacements = [], [], [], [], []
    section = page = ""
    blend = None
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:]
        elif line.startswith("### "):
            if section == "Mesclagens":
                blend = {"name": line[4:].replace(r"\|", "|"), "members": []}
                blends.append(blend)
            elif section == "Componentes do relatório":
                page = line[4:]
        elif section == "Mesclagens" and "gráfico(s) no gerenciador" in line:
            if blend is None:
                raise ValueError("INVENTARIO_MESCLAGEM_SEM_NOME")
            blend["uses"] = int(line.split()[0])
            blend["join_observed"] = line.split(". ", 1)[1]
        elif line.startswith("| "):
            values = cells(line)
            if section == "Fontes" and values[0].startswith("`ds"):
                sources.append(
                    dict(
                        zip(
                            (
                                "alias",
                                "name",
                                "logical_source",
                                "connector",
                                "uses",
                                "observed_fields",
                                "blends",
                            ),
                            values,
                            strict=True,
                        )
                    )
                )
                sources[-1]["alias"] = values[0].strip("`")
                sources[-1]["uses"] = int(values[4])
            elif section == "Mesclagens" and values[0].startswith("`ds"):
                if blend is None:
                    raise ValueError("INVENTARIO_MESCLAGEM_SEM_NOME")
                blend["members"].append(
                    dict(
                        zip(
                            ("source", "dimensions", "metrics", "period", "filters"),
                            values,
                            strict=True,
                        )
                    )
                )
            elif section == "Filtros cadastrados" and values[0] != "Filtro":
                filters.append(
                    dict(
                        zip(("name", "uses", "observed_condition"), values, strict=True)
                    )
                )
            elif section == "Substituições de IDs de campos" and values[0].startswith(
                "`"
            ):
                replacements.append(
                    dict(
                        zip(
                            ("name", "original", "replacement", "type"),
                            values,
                            strict=True,
                        )
                    )
                )
            elif section == "Componentes do relatório" and values[0].startswith("`cd-"):
                components.append(
                    dict(
                        zip(
                            ("id", "type", "source", "configuration"),
                            values,
                            strict=True,
                        ),
                        page=page,
                    )
                )
                components[-1]["id"] = values[0].strip("`")
    return dict(
        sources=sources,
        blends=blends,
        components=components,
        filters=filters,
        field_id_replacements=replacements,
    )


def audit(path=INVENTORY):
    raw = path.read_bytes()
    report = parse(raw.decode("utf-8-sig"))
    registry = READ_REGISTRY
    for source in report["sources"]:
        match = re.match(r"`([^`]+)`", source["logical_source"])
        table = match[1] if match else None
        spec = registry.get(table, {})
        source["target_table"] = table if spec.get("public") else None
        source["contract_status"] = (
            "DISPONIVEL_CONFERIR_CONEXAO_E_CALCULOS"
            if spec.get("public")
            else "PRIVADA_NAO_EXPOSTA"
            if spec
            else "CONJUNTO_DINAMICO_VALIDAR_ADAPTADOR"
            if table is None
            else "TABELA_NAO_MAPEADA"
        )
        source["config"] = {"segmento": "FARMA", "tabela": source["target_table"]}
        if table == "BI_Historico_Resumo":
            cut = re.findall(r"`([^`]+)`", source["logical_source"])[1].replace(
                " ", "_"
            )
            source["config"]["recorte_historico"] = cut
        # Um rótulo observado não prova uma fórmula ou ID original do campo.
        observed = re.findall(r"`([^`]+)`", source["observed_fields"])
        columns = spec.get("read_columns", spec.get("columns", []))
        source["exact_fields_in_contract"] = [f for f in observed if f in columns]
        source["labels_or_fields_to_check"] = [f for f in observed if f not in columns]
        if source["alias"] in ("ds106", "ds107", "ds109", "ds110"):
            source["contract_status"] = "ADAPTADOR_ABC_DISPONIVEL_CONFIRMAR_PARAMETROS"
            source["adapter_candidates"] = {
                "ds106": ["ABC_abc", "ABC_resumo", "ABC_juntos"],
                "ds107": ["ABC_abc"], "ds109": ["ABC_resumo"], "ds110": ["ABC_juntos"],
            }[source["alias"]]
        if source["alias"] == "ds136":
            source["confirmed_header"] = "data segmento conversas_weni resolvidas nao_resolvidas transferidas origem fuso".split()
            source["missing_evidence"] = ["produtor", "chave", "politica_atualizacao", "preenchimento_manual"]
        source["preserve_even_if_unused"] = True
    aliases = {s["alias"] for s in report["sources"]}
    names = {b["name"] for b in report["blends"]}
    for component in report["components"]:
        if component["source"] not in aliases | names | {"—"}:
            raise ValueError("INVENTARIO_COMPONENTE_SEM_FONTE")
        component["currency_check"] = (
            "BRL" if "Receita gerada" in component["configuration"] else None
        )
    for blend in report["blends"]:
        blend["preserve_even_if_unused"] = True
        if any(m["source"].split("`")[1] not in aliases for m in blend["members"]):
            raise ValueError("INVENTARIO_MESCLAGEM_SEM_FONTE")
    report.update(
        schema="nexoflow_inventario_relatorio_1",
        segment="FARMA",
        evidence_date="2026-11-12",
        evidence_sha256=hashlib.sha256(raw).hexdigest(),
        counts=dict(
            sources=len(aliases),
            blends=len(names),
            data_components=sum(c["source"] != "—" for c in report["components"]),
            period_controls=sum(
                c["type"] == "simple-daterangepicker" for c in report["components"]
            ),
            filters=len(report["filters"]),
            field_id_replacements=len(report["field_id_replacements"]),
        ),
        commercial_validation="PENDENTE_NO_GOOGLE",
        permits_cutover=False,
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--saida",
        type=Path,
        help="Matriz de metadados; arquivo novo, sem dados comerciais",
    )
    args = parser.parse_args(argv)
    report = audit()
    if args.saida:
        with args.saida.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    print(
        json.dumps(
            {
                "counts": report["counts"],
                "permits_cutover": False,
                "contract_gaps": [
                    {"alias": s["alias"], "status": s["contract_status"]}
                    for s in report["sources"]
                    if s["target_table"] is None
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0  # Auditoria executada; nunca é um atestado de migração autorizada.


if __name__ == "__main__":
    raise SystemExit(main())
