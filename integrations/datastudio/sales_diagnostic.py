"""Diagnóstico privado e plano de recuperação somente dry-run; nenhuma escrita SQL.

Executar localmente na VPS com DSN privado administrativo. Não é uma rota da API.
A revisão READY, o corte, fatos, assinaturas e recibos nunca são modificados.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from psycopg import sql

from ds_backend.contract import StorageError, digest, normalize
from ds_backend.migration import Export, private_json
from integrations.datastudio.store import LINEAGE, Store
from looker_bi import SCHEMAS, build_looker_tables, opaque_key

TABLES = (
    "BI_Clientes_Vendas",
    "BI_Itens",
    "Pedidos_FarmaLider",
    "Itens_Pedidos_FarmaLider",
    "Historico_Pedidos",
    "Historico_Itens",
    "Exclusoes_Publicacao",
)

# Esta mesma verificação pode ser usada como preflight de publicações futuras.
# Não altera o publicador instalado nem reabre o READY existente.
CHECK = """WITH i AS MATERIALIZED (
 SELECT venda_chave,count(*) AS n,sum(round(receita_item*100)) AS centavos,
 bool_and(coalesce(quantidade>0 AND receita_item>=0 AND
 receita_item::text NOT IN ('NaN','Infinity','-Infinity') AND
 quantidade::text NOT IN ('NaN','Infinity','-Infinity'),false)) AS validos,
 min(data) AS inicio,max(data) AS fim
 FROM {s}.ds_bi_itens GROUP BY venda_chave
) SELECT v.venda_chave,v.cliente_chave,v.data,v.faturamento_produtos,v.frete,v.faturamento,
 coalesce(i.n,0) AS itens, i.centavos,
 EXISTS(SELECT 1 FROM {s}.ds_historico_pedidos h WHERE
 substring(encode(sha256(convert_to('venda:FARMALIDER:'||h.pedido_id,'UTF8')),'hex'),1,32)=v.venda_chave) AS historico
 FROM {s}.ds_bi_clientes_vendas v LEFT JOIN i USING(venda_chave)
 WHERE v.data BETWEEN %s AND %s AND
 (i.n IS NULL OR NOT i.validos OR v.faturamento_produtos IS NULL OR
 v.faturamento_produtos::text IN ('NaN','Infinity','-Infinity') OR
 abs(round(v.faturamento_produtos*100)-i.centavos)>1 OR
 i.inicio<>v.data OR i.fim<>v.data)
 ORDER BY v.data,v.venda_chave LIMIT %s"""


def cents(value):
    amount = Decimal(str(value))
    if not amount.is_finite():
        raise StorageError("DS_DIAGNOSTICO_VALOR_INVALIDO")
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def sale_of(table, r):
    if table in ("BI_Clientes_Vendas", "BI_Itens"):
        return r.get("venda_chave", "")
    if table in ("Pedidos_FarmaLider", "Itens_Pedidos_FarmaLider"):
        return opaque_key("venda", r.get("pedido_chave", ""))
    return opaque_key("venda", "FARMALIDER:" + r.get("pedido_id", ""))


def raw_expression(table):
    if table in ("BI_Clientes_Vendas", "BI_Itens"):
        return "registro->>'venda_chave'"
    source = (
        "registro->>'pedido_chave'"
        if table.startswith(("Pedidos_", "Itens_"))
        else "'FARMALIDER:'||(registro->>'pedido_id')"
    )
    return (
        "substring(encode(sha256(convert_to('venda:'||("
        + source
        + "),'UTF8')),'hex'),1,32)"
    )


def raw_layer(
    conn, schema, keys, *, version=None
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    output: dict[str, dict[str, list[dict[str, Any]]]] = {
        t: defaultdict(list) for t in TABLES
    }
    for table in TABLES:
        condition = sql.SQL(raw_expression(table) + "=ANY(%s)")
        if version is None:
            query = (
                sql.SQL(
                    "SELECT registro FROM {schema}.nf_atuais WHERE tabela=%s AND "
                ).format(schema=sql.Identifier(schema))
                + condition
            )
            args = (table, keys)
        else:
            query = (
                sql.SQL(LINEAGE + "SELECT registro FROM visiveis WHERE ").format(
                    schema=sql.Identifier(schema)
                )
                + condition
            )
            args = (version, table, keys)
        # Fatos cancelados/tombstones têm registro null e não são candidatos.
        for record in conn.execute(query, args):
            r = record["registro"]
            if r:
                output[table][sale_of(table, r)].append(r)
    return output


def fingerprint(rows):
    return digest(sorted(digest(r) for r in rows))


def candidate(sale, sources, segment) -> dict[str, Any]:
    """Reutiliza o Analytics oficial; não inventa itens nem consulta APIs."""
    key = sale["venda_chave"]
    orders = sources["Pedidos_FarmaLider"][key]
    items = sources["Itens_Pedidos_FarmaLider"][key]
    if sources["Historico_Pedidos"][key] or sources["Exclusoes_Publicacao"][key]:
        return dict(action="RECONCILIAR_HISTORICO_OU_EXCLUSAO", items=[])
    if len(orders) != 1 or not items:
        return dict(action="EXIGE_FONTE_OFICIAL_COMPLETA", items=[])
    tables = build_looker_tables(
        [],
        orders,
        items,
        snapshot_date=str(sale["data"]),
        updated_at="",
        period_start=str(sale["data"]),
        period_end=str(sale["data"]),
    )
    built_sales = [
        dict(zip(SCHEMAS["BI_Clientes_Vendas"], r, strict=True))
        for r in tables["BI_Clientes_Vendas"]
    ]
    built_items = [
        dict(zip(SCHEMAS["BI_Itens"], r, strict=True)) for r in tables["BI_Itens"]
    ]
    if len(built_sales) != 1 or not built_items:
        return dict(action="EXIGE_FONTE_OFICIAL_COMPLETA", items=[])
    built = built_sales[0]
    if (
        any(
            str(built[f]) != str(sale[f])
            for f in ("venda_chave", "cliente_chave", "data")
        )
        or any(
            cents(built[f]) != cents(sale[f])
            for f in ("faturamento_produtos", "frete", "faturamento")
        )
        or sum(cents(r["receita_item"]) for r in built_items)
        != cents(sale["faturamento_produtos"])
    ):
        return dict(action="EXIGE_RECONCILIACAO_FINANCEIRA_IDENTIDADE", items=[])
    # Um candidato não autoriza alteração: precisa de revisão nova, prova da
    # completude oficial do pedido e confirmação dos hashes antes de enviar.
    return dict(
        action="CANDIDATO_REPROJETAR_PEDIDO_COMPLETO",
        items=sorted(
            normalize("BI_Itens", built_items, segment), key=lambda r: r["item_chave"]
        ),
    )


def file_hash(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def diagnose(store, revision, version, start, end, *, export=None) -> dict[str, Any]:
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise StorageError("DS_PERIODO_INVALIDO")
    with store.connect(readonly=True) as conn:
        current = store.active(conn)
        rev = store.revision(conn, revision)
        if current != version or rev["versao"] != version or rev["estado"] != "READY":
            raise StorageError("DS_DIAGNOSTICO_REVISAO_DIVERGENTE")
        conn.execute("SET LOCAL enable_nestloop=off")
        sales = conn.execute(
            sql.SQL(CHECK).format(s=sql.Identifier(store.schema)), (start, end, 1001)
        ).fetchall()
        if len(sales) > 1000:
            raise StorageError("DS_DIAGNOSTICO_EXCEDE_LIMITE_REDUZA_PERIODO")
        keys = [r["venda_chave"] for r in sales]
        active = raw_layer(conn, store.schema, keys)
        facts = raw_layer(conn, store.schema, keys, version=version)
        source_hash = rev["evidencia"].get("source_hash")
    cut, cut_sha = None, None
    if export:
        cut_sha = file_hash(export)
        with closing(Export(export)) as package:
            manifest = package.manifest()
            if (
                manifest["segment"] != store.segment
                or not source_hash
                or digest(manifest) != source_hash
            ):
                raise StorageError("DS_DIAGNOSTICO_CORTE_DIVERGENTE")
            cut = {t: defaultdict(list) for t in TABLES}
            selected = set(keys)
            for table in TABLES:
                for (raw,) in package.db.execute(
                    "SELECT v FROM linhas WHERE t=?", (table,)
                ):
                    r = json.loads(raw)
                    sale = sale_of(table, r)
                    if sale in selected:
                        cut[table][sale].append(r)
        if file_hash(export) != cut_sha:
            raise StorageError("DS_EXPORTACAO_ALTERADA")
    layers_by_day = {}
    details, days = (
        [],
        defaultdict(
            lambda: dict(
                pedidos=0, produtos_centavos=0, frete_centavos=0, faturamento_centavos=0
            )
        ),
    )
    for sale in sales:
        key = sale["venda_chave"]
        layers = {}
        for table in TABLES:
            layers[table] = {
                name: dict(
                    count=len(layer[table][key]), hash=fingerprint(layer[table][key])
                )
                for name, layer in (("atuais", active), ("fatos", facts))
            }
            if cut is not None:
                layers[table]["corte"] = dict(
                    count=len(cut[table][key]), hash=fingerprint(cut[table][key])
                )
        day_layers = layers_by_day.setdefault(str(sale["data"]), {})
        for table, evidence in layers.items():
            totals = day_layers.setdefault(table, {})
            for layer, counts in evidence.items():
                totals[layer] = totals.get(layer, 0) + counts["count"]
        different_current = any(
            layers[t]["atuais"] != layers[t]["fatos"] for t in TABLES
        )
        different_cut = cut is not None and any(
            layers[t]["corte"] != layers[t]["fatos"] for t in TABLES
        )
        cause = (
            "PROJECAO_ATUAL_DIVERGE_FATOS"
            if different_current
            else (
                "FATOS_DIVERGEM_CORTE"
                if different_cut
                else (
                    "INCONSISTENCIA_JA_NO_CORTE_ORIGEM_OU_EXTRACAO_PENDENTE"
                    if cut is not None
                    else "ORIGEM_SEM_CORTE_NAO_COMPROVADA"
                )
            )
        )
        plan: dict[str, Any] = candidate(sale, facts, store.segment)
        if different_current or different_cut:
            plan = dict(action="RECONCILIAR_CAMADAS_ANTES_DE_RECUPERAR", items=[])
        existing = {r["item_chave"]: r for r in active["BI_Itens"][key]}
        inserts = sum(r["item_chave"] not in existing for r in plan["items"])
        updates = sum(
            r["item_chave"] in existing and existing[r["item_chave"]] != r
            for r in plan["items"]
        )
        plan.update(
            inseridos=inserts,
            atualizados=updates,
            mantidos=len(plan["items"]) - inserts - updates,
            remocoes_autorizadas=0,
            aplicavel=False,
        )
        details.append(
            dict(
                venda_chave=key,
                data=str(sale["data"]),
                itens_projetados=sale["itens"],
                cabecalho_historico=sale["historico"],
                causa=cause,
                camadas=layers,
                recuperacao=plan,
            )
        )
        d = days[str(sale["data"])]
        d["pedidos"] += 1
        for field, target in (
            ("faturamento_produtos", "produtos_centavos"),
            ("frete", "frete_centavos"),
            ("faturamento", "faturamento_centavos"),
        ):
            d[target] += cents(sale[field])
    result = dict(
        protocol="ds_diagnostico_vendas_1",
        segment=store.segment,
        target=store.target,
        revision=revision,
        version=version,
        start=start,
        end=end,
        dry_run=True,
        source_hash=source_hash,
        export_sha256=cut_sha,
        export_unchanged=bool(export),
        recorte_sem_vendas_incompletas=not sales,
        autoriza_publicacao=False,
        por_dia=dict(days),
        camadas_por_dia=layers_by_day,
        causas=dict(Counter(r["causa"] for r in details)),
        pedidos=details,
        escrita_real=False,
    )
    result["plan_hash"] = digest(result)
    return result


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn-file", required=True, type=Path)
    parser.add_argument("--segment", required=True, choices=("FARMA", "PET"))
    parser.add_argument(
        "--environment", required=True, choices=("homologacao", "producao")
    )
    parser.add_argument("--revision", required=True)
    parser.add_argument("--version", required=True, type=int)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--export", type=Path)
    parser.add_argument(
        "--export-sha256", help="SHA-256 conferido no Windows antes da transferência"
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.export and (
        not args.export_sha256 or file_hash(args.export) != args.export_sha256.lower()
    ):
        raise StorageError("DS_DIAGNOSTICO_TRANSFERENCIA_NAO_CONFERIDA")
    if args.output.exists():
        raise StorageError("DS_SAIDA_JA_EXISTE")
    store = Store(args.dsn_file.read_text().strip(), args.environment, args.segment)
    result = diagnose(
        store, args.revision, args.version, args.start, args.end, export=args.export
    )
    private_json(args.output, result)
    print(
        json.dumps(
            dict(
                dry_run=True,
                pedidos=len(result["pedidos"]),
                recorte_sem_vendas_incompletas=result["recorte_sem_vendas_incompletas"],
                autoriza_publicacao=False,
                por_dia=result["por_dia"],
                camadas_por_dia=result["camadas_por_dia"],
                causas=result["causas"],
            )
        )
    )
    return 0 if result["recorte_sem_vendas_incompletas"] else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StorageError as exc:
        print(str(exc))
        raise SystemExit(2) from None
    except Exception:
        print(
            "DS_DIAGNOSTICO_FALHOU_SEM_EXPOR_DETALHES; conferir acesso e parâmetros privados"
        )
        raise SystemExit(2) from None
