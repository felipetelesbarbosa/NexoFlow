"""Pré-voo somente leitura de vendas operacionais sem cobertura histórica.

Não modifica o corte nem recompõe BI silenciosamente. O histórico mantém sua
conferência própria e sua precedência por venda inteira nas visões financeiras.
"""

from __future__ import annotations

import hashlib
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from ds_backend.contract import StorageError


class StaleItems(StorageError):
    def __init__(self, counts):
        super().__init__("DS_BI_ITENS_DEFASADOS")
        self.counts = counts


def sale_key(order):
    return hashlib.sha256(("venda:FARMALIDER:" + str(order)).encode()).hexdigest()[:32]


def centavos(value):
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n < 0:
            return None
        result = int((n * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        return result if result < 2**63 else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


def positive(value):
    try:
        n = Decimal(str(value))
        return int(n.is_finite() and n > 0)
    except (InvalidOperation, ValueError):
        return 0


SQLITE_CHECK = """WITH omitidas AS MATERIALIZED (
 SELECT nf_venda(json_extract(v,'$.pedido_id')) AS venda
 FROM linhas WHERE t IN ('Historico_Pedidos','Exclusoes_Publicacao') GROUP BY 1
), itens AS MATERIALIZED (
 SELECT json_extract(v,'$.venda_chave') AS venda,
 count(*) AS n,count(DISTINCT json_extract(v,'$.item_chave')) AS chaves,
 sum(nf_centavos(json_extract(v,'$.receita_item'))) AS centavos,
 min(CASE WHEN nf_positivo(json_extract(v,'$.quantidade'))=1
   AND nf_centavos(json_extract(v,'$.receita_item')) IS NOT NULL
   AND coalesce(json_extract(v,'$.item_chave'),'')<>'' THEN 1 ELSE 0 END) AS validos,
 min(json_extract(v,'$.data')) AS inicio,max(json_extract(v,'$.data')) AS fim,
 min(json_extract(v,'$.cliente_chave')) AS cliente_min,
 max(json_extract(v,'$.cliente_chave')) AS cliente_max
 FROM linhas WHERE t='BI_Itens' GROUP BY 1
), vendas AS MATERIALIZED (
 SELECT json_extract(v,'$.venda_chave') AS venda,json_extract(v,'$.data') AS data,
 json_extract(v,'$.cliente_chave') AS cliente,
 nf_centavos(json_extract(v,'$.faturamento_produtos')) AS centavos
 FROM linhas WHERE t='BI_Clientes_Vendas'
)
SELECT v.data,count(*) AS pedidos FROM vendas v
LEFT JOIN omitidas h ON h.venda=v.venda LEFT JOIN itens i ON i.venda=v.venda
WHERE h.venda IS NULL AND (coalesce(v.venda,'')='' OR coalesce(v.data,'')=''
 OR v.centavos IS NULL OR i.n IS NULL OR i.validos<>1 OR i.n<>i.chaves
 OR v.centavos<>i.centavos OR v.data<>i.inicio OR v.data<>i.fim
 OR v.cliente IS NOT i.cliente_min OR v.cliente IS NOT i.cliente_max)
GROUP BY v.data ORDER BY v.data"""


def assert_export_items(db):
    """Só SELECT + funções locais; funciona também com PRAGMA query_only=ON."""
    db.create_function("nf_venda", 1, sale_key, deterministic=True)
    db.create_function("nf_centavos", 1, centavos, deterministic=True)
    db.create_function("nf_positivo", 1, positive, deterministic=True)
    counts = [dict(data=r[0], pedidos=r[1]) for r in db.execute(SQLITE_CHECK)]
    if counts:
        raise StaleItems(counts)
