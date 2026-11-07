# Auditoria pontual privada de concentração de valores

Executar pelo Work na instalação 1.5.22, sobre a cópia consistente do SQLite
FARMA usada no preparo. Não chamar API, não alterar fatos e não publicar a saída.
O resumo recebido contém apenas agregados: não permite confirmar grandes pedidos
legítimos nem erros de quantidade/preço. As concentrações não invalidam por si só
as compras que passaram pelas regras oficiais. Manter essa ressalva na liberação.

Em PowerShell na raiz instalada:

```powershell
$env:NEXOFLOW_PERFIL='FARMA'
$env:PYTHONPATH='app;.'
@'
import heapq, json
from decimal import Decimal
from pathlib import Path
from history_snapshot import readonly, sha256
from pedido_utils import business_order_datetime
from dedup_io import save_private
source = Path('logs/privado/farma-copia.sqlite')  # caminho do backup consistente
before = sha256(source)
tops = {month: {'receita': [], 'unidades': []} for month in ('2026-04', '2025-06')}
with readonly(source, 'FARMA') as store:
    for order_id, raw in store.db.execute('SELECT id,record FROM history_orders WHERE segment=?', ('FARMA',)):
        r = json.loads(raw)
        date = business_order_datetime(r.get('date'))
        month = date.strftime('%Y-%m') if date else ''
        if month not in tops or r.get('state') != 'valido':
            continue
        products = [i for i in r.get('items', []) if not i.get('freight')]
        units = sum((Decimal(str(i['quantity'])) for i in products), Decimal(0))
        detail = dict(pedido=order_id, data=r.get('date'), origem=r.get('source'),
                      produtos_centavos=r['products_cents'], frete_centavos=r['freight_cents'],
                      faturamento_centavos=r['revenue_cents'], unidades=str(units),
                      itens=[{k: i.get(k) for k in ('id','sku','quantity','unit','total_cents')} for i in products])
        for metric, value in (('receita', r['revenue_cents']), ('unidades', units)):
            top = tops[month][metric]
            heapq.heappush(top, (value, order_id, detail))
            if len(top) > 20:
                heapq.heappop(top)
    out = {month: {metric: [v[2] for v in sorted(top, reverse=True)] for metric, top in metrics.items()} for month, metrics in tops.items()}
    ids = {r['pedido'] for metrics in out.values() for rows in metrics.values() for r in rows}
    revisions = [dict(pedido=i, old_digest=a, new_digest=b, modo=m, instante=t)
                 for i,a,b,m,t in store.db.execute('SELECT id,old_digest,new_digest,mode,at FROM history_revisions WHERE segment=?', ('FARMA',)) if i in ids]
if sha256(source) != before:
    raise RuntimeError('A cópia mudou durante a inspeção; repetir sobre novo backup consistente.')
save_private(Path('logs/privado/auditoria-pontual-farma.json'), dict(
    segmento='FARMA', sqlite_sha256=before, limite_por_ranking=20,
    meses=out, revisoes=revisions, qualidade='CONCENTRACAO_PENDENTE_DE_REVISAO'))
print('Relatório privado gerado; nenhum pedido, cliente ou valor individual foi exibido.')
'@ | .\.venv\Scripts\python.exe -
```

A rotina percorre fatos uma vez, mantém só os maiores 20 pedidos de cada métrica
por mês e inspeciona revisões desses IDs. Os rankings se sobrepõem; não somá-los.
O arquivo contém IDs de pedido/SKU e valores: restringir ACL e nunca anexar ao
GitHub/CI. Nenhum nome, CPF, telefone ou endereço é solicitado/exibido.

Conferir em particular: quantidade × preço unitário versus total do item,
lançamentos técnicos de frete fora dos produtos, frete oficial, desconto/total
explícito da evidência disponível, origem e revisões anteriores. Preço/quantidade
fora da média não prova defeito; não arredondar ou reduzir os valores para forçar
uma média. Se os dados normalizados não explicarem a origem, preparar uma leitura
mínima do pedido específico para autorização operacional separada; nenhuma nova
consulta comercial é executada por este procedimento. Preservar fatos e pendências.

Depois, comparar os agregados da cópia atual com o resumo de referência e registrar
no fechamento quais concentrações foram verificadas, quais permanecem abertas,
os hashes do snapshot/revisão e o corte. A conferência de Sheets deve continuar
fechando exatamente com os valores originais publicados, inclusive nas concentrações.
