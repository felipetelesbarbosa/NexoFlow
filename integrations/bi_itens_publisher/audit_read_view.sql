-- Pós-migração, administrador/conta de auditoria. Somente agregados; saída privada.
-- A conta leitora da API não precisa receber acesso à tabela ou à visão do Metabase.
BEGIN READ ONLY ISOLATION LEVEL REPEATABLE READ;
SELECT current_database(),transaction_timestamp() AS corte;
SELECT count(*) AS linhas,count(DISTINCT item_chave) AS chaves,
 count(DISTINCT produto_codigo) FILTER(WHERE sku_informado=1) AS skus_informados,
 min(data) AS inicio,max(data) AS fim,sum(quantidade) AS unidades,sum(receita_item) AS receita
FROM farma.produtos_itens_datastudio;
-- Igualdade multiconjunto exata nos doze campos, sem imprimir IDs/linhas individuais.
WITH diferencas AS (
 (SELECT item_chave,venda_chave,cliente_chave,data,produto_codigo,produto_nome,categoria,
   quantidade,valor_unitario,receita_item,sku_informado,atualizado_em FROM farma.bi_itens
  EXCEPT ALL
  SELECT item_chave,venda_chave,cliente_chave,data,produto_codigo,produto_nome,categoria,
   quantidade,valor_unitario,receita_item,sku_informado,atualizado_em FROM farma.produtos_itens_datastudio)
 UNION ALL
 (SELECT item_chave,venda_chave,cliente_chave,data,produto_codigo,produto_nome,categoria,
   quantidade,valor_unitario,receita_item,sku_informado,atualizado_em FROM farma.produtos_itens_datastudio
  EXCEPT ALL
  SELECT item_chave,venda_chave,cliente_chave,data,produto_codigo,produto_nome,categoria,
   quantidade,valor_unitario,receita_item,sku_informado,atualizado_em FROM farma.bi_itens)
)
SELECT count(*) AS linhas_divergentes FROM diferencas;
SELECT a.attname,format_type(a.atttypid,a.atttypmod) AS tabela,
 format_type(b.atttypid,b.atttypmod) AS visao,
 (a.atttypid,a.atttypmod,a.attcollation)=(b.atttypid,b.atttypmod,b.attcollation) AS tipo_preservado
FROM pg_attribute a JOIN pg_attribute b ON a.attname=b.attname
WHERE a.attrelid='farma.bi_itens'::regclass AND b.attrelid='farma.produtos_itens_datastudio'::regclass
 AND a.attnum>0 AND b.attnum>0 AND NOT a.attisdropped AND NOT b.attisdropped
ORDER BY b.attnum;
-- Mesmo grão por item nos sete campos comuns: conciliar três fontes por mês e TOTAL.
WITH fontes AS (
 SELECT 'tabela' AS fonte,data,produto_codigo,quantidade,receita_item,sku_informado FROM farma.bi_itens
 UNION ALL SELECT 'api',data,produto_codigo,quantidade,receita_item,sku_informado FROM farma.produtos_itens_datastudio
 UNION ALL SELECT 'metabase',data,produto_codigo,quantidade,receita_item,sku_informado FROM farma.produtos_itens
), meses AS (SELECT *,date_trunc('month',data)::date AS mes FROM fontes)
SELECT fonte,CASE WHEN grouping(mes)=1 THEN 'TOTAL' ELSE coalesce(mes::text,'SEM_DATA') END AS periodo,
 count(*) AS linhas,count(DISTINCT produto_codigo) FILTER(WHERE sku_informado=1) AS produtos,
 sum(quantidade) AS unidades,sum(receita_item) AS receita
FROM meses GROUP BY GROUPING SETS ((fonte,mes),(fonte)) ORDER BY fonte,grouping(mes),mes;
SELECT state,revision FROM nexoflow_publicacao.estado_leitura;
COMMIT;
