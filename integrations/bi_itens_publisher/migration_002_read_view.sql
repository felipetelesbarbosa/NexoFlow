-- Migração aditiva 002: visão exclusiva da API. Não altera fatos ou a visão Metabase.
-- Executar na transação do administrador do piloto; nenhuma concessão ao Metabase.
SET LOCAL search_path = pg_catalog;
DO $$
DECLARE
 columns_expected text[] := ARRAY[
  'item_chave','venda_chave','cliente_chave','data','produto_codigo','produto_nome',
  'categoria','quantidade','valor_unitario','receita_item','sku_informado','atualizado_em'
 ];
 source_oid oid := to_regclass('farma.bi_itens');
 view_oid oid := to_regclass('farma.produtos_itens_datastudio');
 expected_definition text;
BEGIN
 IF current_database()<>'nexoflow_datastudio_piloto' THEN
  RAISE EXCEPTION 'BI_PG_BANCO_DIVERGENTE';
 END IF;
 IF source_oid IS NULL THEN RAISE EXCEPTION 'BI_PG_DESTINO_AUSENTE'; END IF;
 IF (SELECT array_agg(attname::text ORDER BY attname) FROM pg_attribute
     WHERE attrelid=source_oid AND attnum>0 AND NOT attisdropped)
    IS DISTINCT FROM (SELECT array_agg(c ORDER BY c) FROM unnest(columns_expected) c) THEN
  RAISE EXCEPTION 'BI_PG_SCHEMA_DIVERGENTE';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_index i JOIN pg_attribute a
    ON a.attrelid=i.indrelid AND a.attnum=i.indkey[0]
    WHERE i.indrelid=source_oid AND i.indisprimary AND i.indnkeyatts=1
    AND i.indisvalid AND a.attname='item_chave') THEN
  RAISE EXCEPTION 'BI_PG_CHAVE_PRIMARIA_DIVERGENTE';
 END IF;
 IF view_oid IS NULL THEN
  CREATE VIEW farma.produtos_itens_datastudio AS
   SELECT item_chave,venda_chave,cliente_chave,data,produto_codigo,produto_nome,
          categoria,quantidade,valor_unitario,receita_item,sku_informado,atualizado_em
   FROM farma.bi_itens;
  REVOKE ALL ON farma.produtos_itens_datastudio FROM PUBLIC;
  view_oid := to_regclass('farma.produtos_itens_datastudio');
 END IF;
 -- Repetir preserva OID/owner/ACL. Não substituir outra definição, mesmo com 12 colunas.
 expected_definition := 'SELECT' ||
  (SELECT string_agg('bi_itens.' || quote_ident(c),',' ORDER BY n)
   FROM unnest(columns_expected) WITH ORDINALITY AS x(c,n)) || 'FROMfarma.bi_itens;';
 IF (SELECT relkind FROM pg_class WHERE oid=view_oid)<>'v' THEN
  RAISE EXCEPTION 'BI_PG_VISAO_API_CONFLITANTE';
 END IF;
 IF regexp_replace(pg_get_viewdef(view_oid,false),'[[:space:]]','','g')
    NOT IN (expected_definition,replace(expected_definition,'bi_itens.','')) THEN
  RAISE EXCEPTION 'BI_PG_VISAO_API_CONFLITANTE';
 END IF;
 IF EXISTS(SELECT 1 FROM pg_attribute a JOIN pg_attribute b ON b.attname=a.attname
   AND b.attrelid=source_oid AND b.attnum>0 AND NOT b.attisdropped
   WHERE a.attrelid=view_oid AND a.attnum>0 AND NOT a.attisdropped
   AND (a.atttypid,a.atttypmod,a.attcollation) IS DISTINCT FROM
       (b.atttypid,b.atttypmod,b.attcollation)) THEN
  RAISE EXCEPTION 'BI_PG_VISAO_SCHEMA_DIVERGENTE';
 END IF;
END $$;
