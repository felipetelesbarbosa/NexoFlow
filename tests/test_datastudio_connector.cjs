const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(callback){
 const calls=[],logs=[],sleeps=[];
 const secret={protocol:'nexoflow_datastudio_1',segment:'FARMA',environment:'homologacao',endpoint:'https://reader.example.invalid',api_token:'synthetic-reader-only-token',access_client_id:'synthetic.access',access_client_secret:'synthetic-access-secret'};
 function fields(){const all=[];function field(role){const f={role,setId(v){this.id=v;return this;},setName(){return this;},setType(v){this.type=v;return this;},setAggregation(v){this.aggregation=v;return this;},setIsReaggregatable(v){this.reaggregatable=v;return this;}};all.push(f);return f;}return {newMetric:()=>field('metric'),newDimension:()=>field('dimension'),build:()=>all,forIds:n=>({build:()=>all.filter(f=>n.includes(f.id)).map(f=>({name:f.id,type:f.type}))})};}
 const cc={getFields:fields,FieldType:{YEAR_MONTH_DAY:'date',NUMBER:'number',TEXT:'text',CURRENCY_BRL:'currency_brl',PERCENT:'percent'},AggregationType:{SUM:'sum',MAX:'max'},newUserError:()=>({setText(t){return {throwException(){throw Error(t)}}}})};
 const ctx={Date,DataStudioApp:{createCommunityConnector:()=>cc},console:{error:v=>logs.push(v)},Utilities:{sleep:v=>sleeps.push(v)},PropertiesService:{getScriptProperties:()=>({getProperty:()=>JSON.stringify(secret)})},UrlFetchApp:{fetch:(url,options)=>{calls.push({url,options});let reply;if(url.endsWith('/v1/destino'))reply={body:{protocol:secret.protocol,target:'nexoflow_datastudio_homologacao.farma',segment:'FARMA',environment:'homologacao',schema_hash:ctx.NexoDSSchemaHash}};else reply=callback(JSON.parse(options.payload),calls.length);return {getResponseCode:()=>reply.status||200,getContentText:()=>JSON.stringify(reply.body||{})};}}};
 vm.createContext(ctx);for(const f of ['Schemas.js','AbcCore.js','Code.js'])vm.runInContext(fs.readFileSync('connectors/datastudio_api/'+f,'utf8'),ctx);return {ctx,calls,logs,sleeps,secret};
}
function request(names=['produtos_distintos_periodo']){return {configParams:{segmento:'FARMA',ambiente:'homologacao',tabela:'BI_Itens'},fields:names.map(name=>({name})),dateRange:{startDate:'2026-11-01',endDate:'2026-11-03'},dimensionsFilters:[[{fieldName:'sku_informado',operator:'EQUALS',type:'INCLUDE',values:['1']}]]};}
function result(p,rows){return {body:{protocol:"nexoflow_datastudio_1",target:"nexoflow_datastudio_homologacao.farma",segment:"FARMA",environment:"homologacao",schema_hash:require("../connectors/datastudio_api/Schemas.js").hash,fields:p.fields,rows:rows,complete:true,version:1}};}
test('schema preserva IDs, datas, atualizado_em Texto e SKU sem agregação',()=>{
 const f=fixture(),fields=f.ctx.dsFields_('BI_Itens').build(),original=require('../connectors/continuacoes/Schemas.js').BI_Itens;
 assert.deepEqual(Array.from(fields.slice(0,12),f=>f.id),original.map(f=>f[0]));
 assert.equal(fields.find(f=>f.id==='atualizado_em').type,'text');assert.equal(fields.find(f=>f.id==='sku_informado').role,'dimension');assert.equal(fields.find(f=>f.id==='produtos_distintos_periodo').reaggregatable,false);
 assert.ok(!f.ctx.NexoDSSchemas.Controle&&!f.ctx.NexoDSSchemas.Cache_orders);
});
test('distintos em todo o período vêm do SQL; credenciais fora dos logs e payload',()=>{
 const f=fixture(p=>{assert.equal(p.aggregation.produto_codigo,'count_distinct');return result(p,[[216]]);});
 const r=f.ctx.getData(request());assert.equal(r.rows[0].values[0],216);assert.equal(r.filtersApplied,true);
 for(const c of f.calls){assert.equal(c.options.followRedirects,false);assert.ok(!c.url.includes(f.secret.api_token));assert.ok(!(c.options.payload||'').includes(f.secret.api_token));}
 assert.ok(!f.logs.join().includes(f.secret.api_token));
});
test('detalhe, zeros à esquerda, moeda e período vazio',()=>{
 const f=fixture(p=>result(p,[['000123','134','4753.02']]));
 assert.deepEqual(Array.from(f.ctx.getData(request(['produto_codigo','quantidade','receita_item'])).rows[0].values),['000123',134,4753.02]);
 const empty=fixture(p=>result(p,[]));assert.equal(empty.ctx.getData(request(['produto_codigo'])).rows.length,0);
});
test('falhas não expõem totais parciais; transientes têm retentativa limitada',()=>{
 for(const code of [401,403,409,429,503]){
  const f=fixture(()=>({status:code,body:{error:'raw-token-must-not-appear'}}));
  assert.throws(()=>f.ctx.getData(request()),e=>e.message.includes('Nenhum total parcial')&&!e.message.includes('raw-token'));
  assert.equal(f.sleeps.length,[429,503].includes(code)?2:0);
 }
 const f=fixture(p=>({body:{fields:p.fields,rows:[[216]],complete:false}}));assert.throws(()=>f.ctx.getData(request()),/Nenhum total parcial/);
});
test('rejeita agregação com filtro não suportado e marca não autorizada',()=>{
 const f=fixture(p=>result(p,[[216]])),r=request();r.dimensionsFilters[0][0].operator='REGEXP_PARTIAL_MATCH';
 assert.throws(()=>f.ctx.getData(r),/DS_FILTRO_AGREGACAO_NAO_SUPORTADO/);
 r.configParams.segmento='OUTRO';assert.throws(()=>f.ctx.getData(r),/DS_CONFIGURACAO_INVALIDA/);
});
test('filtro aplicado não devolve campos solicitados só para filtrar; resumo exige grão',()=>{
 const f=fixture(p=>result(p,[[90]])),r=request();r.fields.push({name:'sku_informado',forFilterOnly:true});
 assert.equal(f.ctx.getData(r).schema.length,1);
 const summary=request(['pedidos']);summary.configParams.tabela='BI_Historico_Resumo';summary.dimensionsFilters=[];
 assert.throws(()=>f.ctx.getData(summary),/DS_RESUMO_EXIGE_GRAO/);
});

test('Receita gerada preserva valor decimal e o tipo moeda BRL; atualizado_em continua Texto',()=>{
 const f=fixture(p=>result(p,[['103.87','2026-11-12T10:00:00-03:00']]));
 const fields=f.ctx.dsFields_('BI_Clientes_Vendas').build();
 assert.equal(fields.find(f=>f.id==='faturamento').type,'currency_brl');
 assert.equal(fields.find(f=>f.id==='atualizado_em').type,'text');
 const r=request(['faturamento','atualizado_em']);r.configParams.tabela='BI_Clientes_Vendas';r.dimensionsFilters=[];
 assert.equal(f.ctx.getData(r).rows[0].values[0],103.87);
 assert.equal(f.ctx.dsFields_('BI_Meta_Resultados').build().find(f=>f.id==='investimento_original').type,'number');
});

test('aliases TOTAL/MES/ANO/SEM_EMISSAO mantêm grãos separados e filtros FARMA são enviados',()=>{
 for(const grain of ['TOTAL','MES','ANO','SEM_EMISSAO']){
   const f=fixture(p=>{assert.equal(p.filters[0].field,'tipo_recorte');assert.equal(p.filters[0].values[0],grain);assert.equal(p.start,['TOTAL','SEM_EMISSAO'].includes(grain)?'':'2026-11-01');return result(p,[]);});
   const r=request(['faturamento']);r.configParams.tabela='BI_Historico_Resumo';r.configParams.recorte_historico=grain;r.dimensionsFilters=[];
   assert.equal(f.ctx.getData(r).rows.length,0);
 }
 const f=fixture(p=>{assert.deepEqual(JSON.parse(JSON.stringify(p.filters)),[{field:'classificacao',values:['FARMA']}]);return result(p,[['12.34',null]]);});
 const r=request(['receita_confirmada','investimento_atribuivel']);r.configParams.tabela='BI_Meta_Resultados';r.dimensionsFilters=[[{type:'INCLUDE',operator:'EQUALS',fieldName:'classificacao',values:['FARMA']}]];
 assert.deepEqual(Array.from(f.ctx.getData(r).rows[0].values),[12.34,null]);
});

test('guarda de recorte chega ao Work sem expor mensagem livre do servidor',()=>{
 const f=fixture(()=>({status:409,body:{error:'DS_FILTRO_CORTA_RECORTE_USE_DETALHE',detail:'PRIVATE-MUST-NOT-APPEAR'}}));
 assert.throws(()=>f.ctx.getData(request()),/DS_FILTRO_CORTA_RECORTE_USE_DETALHE/);
 assert.ok(!f.logs.join().includes('PRIVATE-MUST-NOT-APPEAR'));
 const bad=fixture(()=>({status:409,body:{error:'DS_PRIVATE-MUST-NOT-APPEAR'}}));
 assert.throws(()=>bad.ctx.getData(request()),/DS_HTTP_409/);
 assert.ok(!bad.logs.join().includes('PRIVATE-MUST-NOT-APPEAR'));
});

test('ABC PostgreSQL muda com o período; pares não somam item duplicado',()=>{
 function run(mode,start,end){
  const f=fixture(p=>result(p,p.table==='BI_Itens'?
    [['i1','s1','2026-11-01','01','A','','1','80'],['i2','s1','2026-11-01','02','B','','1','20'],['i3','s2','2026-11-02','02','B','','1','100']].filter(r=>r[2]>=start&&r[2]<=end):
    [['s1','2026-11-01','100'],['s2','2026-11-02','100']].filter(r=>r[1]>=start&&r[1]<=end)));
  const r=request(mode==='abc'?['produto_codigo','receita_produtos','classe_abc']:mode==='juntos'?['produto_a_codigo','produto_b_codigo','pedidos_juntos']:['skus_distintos','faturamento_produtos']);
  r.configParams.tabela='ABC_'+mode;r.dateRange={startDate:start,endDate:end};r.dimensionsFilters=[];
  return JSON.parse(JSON.stringify(f.ctx.getData(r)));
 }
 assert.deepEqual(run('abc','2026-11-01','2026-11-01').rows.map(r=>r.values),[['01',80,'A'],['02',20,'B']]);
 assert.deepEqual(run('abc','2026-11-01','2026-11-02').rows.map(r=>r.values),[['02',120,'A'],['01',80,'A']]);
 assert.deepEqual(run('juntos','2026-11-01','2026-11-02').rows.map(r=>r.values),[['01','02',1]]);
 assert.deepEqual(run('resumo','2026-11-01','2026-11-02').rows.map(r=>r.values),[[2,200]]);
 assert.deepEqual(run('abc','2026-11-30','2026-11-30').rows,[]);
});
test('ABC recusa falha, limite, resposta parcial e versões diferentes',()=>{
 for(const variant of ['version','partial','failure','limit']){
  const f=fixture((p,n)=>{
   if(variant==='failure')return {status:403};
   if(variant==='limit')return {status:409,body:{error:'DS_CONSULTA_EXCEDE_LIMITE_USE_RESUMO_OU_PERIODO'}};
   const r=result(p,[]);r.body.version=variant==='version'?n:1;r.body.complete=variant!=='partial';return r;
  });
  const r=request(['produto_codigo']);r.configParams.tabela='ABC_abc';r.dimensionsFilters=[];
  assert.throws(()=>f.ctx.getData(r),/Nenhum total parcial/);
 }
});
test('projeções do inventário são tipadas sem expor payloads privados',()=>{
 const f=fixture();
 assert.equal(f.ctx.dsFields_('Itens_Pedidos_FarmaLider').build().find(f=>f.id==='quantidade').type,'number');
 for(const bad of ['cpf','telefone','ultimo_pedido_raw','primeiro_anuncio_clique_id'])assert.ok(!f.ctx.NexoDSSchemas.Pedidos_FarmaLider.columns.includes(bad));
 const original={};vm.createContext(original);vm.runInContext(fs.readFileSync('connectors/looker_abc/Code.js','utf8'),original);
 for(const mode of ['abc','resumo','juntos'])assert.deepEqual(Array.from(f.ctx.NexoDSSchemas['ABC_'+mode].columns),Array.from(original.fieldSpecs_(mode),f=>f[0]));
});

test('ABC não devolve totais de itens sem pedido completo e alinha ordem do SDK',()=>{
 const f=fixture(p=>result(p,p.table==='BI_Itens'?[['i1','s1','2026-11-01','01','A','','1','10']]:[['s1','2026-11-01','20']]));
 const r=request(['classe_abc','produto_codigo']);r.configParams.tabela='ABC_abc';r.dimensionsFilters=[];
 assert.throws(()=>f.ctx.getData(r),/DS_ABC_BASE_INCOMPLETA/);
 const good=fixture(p=>result(p,p.table==='BI_Itens'?[['i1','s1','2026-11-01','01','A','','1','10']]:[['s1','2026-11-01','10']]));
 const response=good.ctx.getData(r);
 assert.deepEqual(Array.from(response.schema,f=>f.name),['produto_codigo','classe_abc']);
 assert.deepEqual(Array.from(response.rows[0].values),['01','A']);
});

test('ds72 mantém ID e Texto sem agregação, aplicando elegibilidade antes da resposta',()=>{
 const f=fixture(p=>{
   assert.equal(p.table,'Pedidos_FarmaLider');
   assert.deepEqual(p.filters,[{field:'calc_gf73fvq57d',values:['Sim']}]);
   assert.deepEqual(p.fields,['contact_uuid']);
   return result(p,[['synthetic-contact'],['synthetic-contact']]);
 });
 const field=f.ctx.dsFields_('Pedidos_FarmaLider').build().find(f=>f.id==='calc_gf73fvq57d');
 assert.equal(field.type,'text');assert.equal(field.role,'dimension');assert.equal(field.aggregation,undefined);
 const r=request(['contact_uuid']);r.configParams.tabela='Pedidos_FarmaLider';
 r.dimensionsFilters=[[{fieldName:'calc_gf73fvq57d',operator:'EQUALS',type:'INCLUDE',values:['Sim']}]];
 r.fields.push({name:'calc_gf73fvq57d',forFilterOnly:true});
 const resultData=f.ctx.getData(r);assert.equal(resultData.filtersApplied,true);
 assert.equal(resultData.schema.length,1);assert.equal(resultData.rows.length,2);
 // COUNT_DISTINCT pertence à métrica da mesclagem: o leitor não apaga pedidos repetidos por contato.
 assert.equal(new Set(resultData.rows.map(r=>r.values[0])).size,1);
});
