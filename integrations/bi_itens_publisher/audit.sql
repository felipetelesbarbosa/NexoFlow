-- Somente leitura. Guardar a saída em relatório privado; não enviar DSN/senhas.
BEGIN READ ONLY;
SELECT current_database(), current_user;
SELECT column_name,data_type,is_nullable,numeric_precision,numeric_scale
FROM information_schema.columns WHERE table_schema='farma' AND table_name='bi_itens'
ORDER BY ordinal_position;
SELECT a.attname AS primary_key FROM pg_index i JOIN pg_attribute a
ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey)
WHERE i.indrelid='farma.bi_itens'::regclass AND i.indisprimary;
SELECT count(*) AS linhas,count(DISTINCT item_chave) AS chaves,
 count(DISTINCT venda_chave) AS vendas,count(DISTINCT cliente_chave) AS clientes,
 min(data) AS inicio,max(data) AS fim,sum(quantidade) AS unidades,
 sum(receita_item) AS receita FROM farma.bi_itens;
SELECT date_trunc('month',data)::date AS mes,count(*) AS linhas,
 sum(quantidade) AS unidades,sum(receita_item) AS receita
FROM farma.bi_itens GROUP BY 1 ORDER BY 1;
SELECT table_schema,table_name,privilege_type,grantee
FROM information_schema.table_privileges
WHERE table_schema IN ('farma','nexoflow_publicacao') ORDER BY 1,2,4,3;
SELECT column_name,data_type FROM information_schema.columns
WHERE table_schema='farma' AND table_name='produtos_itens' ORDER BY ordinal_position;
SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='farma.bi_itens'::regclass;
SELECT count(*) AS user_triggers FROM pg_trigger WHERE tgrelid='farma.bi_itens'::regclass AND NOT tgisinternal AND tgenabled<>'D';
COMMIT;

-- Pré/pós-migração: a visão API pode ainda não existir. Nenhuma escrita.
BEGIN READ ONLY;
SELECT name AS objeto,to_regclass(name) IS NOT NULL AS presente
FROM (VALUES ('farma.produtos_itens'),('farma.produtos_itens_datastudio')) v(name);
SELECT c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod) AS tipo_original
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
WHERE n.nspname='farma' AND c.relname IN ('bi_itens','produtos_itens','produtos_itens_datastudio')
ORDER BY c.relname,a.attnum;
SELECT c.relname,c.relowner::regrole AS proprietario,c.relacl
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='farma' AND c.relname IN ('bi_itens','produtos_itens','produtos_itens_datastudio')
ORDER BY c.relname;
COMMIT;
