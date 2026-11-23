const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(callback){
 const calls=[],logs=[],sleeps=[];
 const secret={protocol:'nexoflow_datastudio_1',segment:'FARMA',environment:'homologacao',endpoint:'https://reader.example.invalid',api_token:'synthetic-reader-only-token',access_client_id:'synthetic.access',access_client_secret:'synthetic-access-secret'};
 function fields(){const all=[];function field(role){const f={role,setId(v){this.id=v;return this;},setName(v){this.label=v;return this;},setType(v){this.type=v;return this;},setAggregation(v){this.aggregation=v;return this;},setIsReaggregatable(v){this.reaggregatable=v;return this;}};all.push(f);return f;}return {newMetric:()=>field('metric'),newDimension:()=>field('dimension'),build:()=>all,forIds:n=>({build:()=>all.filter(f=>n.includes(f.id)).map(f=>({name:f.id,type:f.type}))})};}
 const cc={getFields:fields,FieldType:{YEAR_MONTH_DAY:'date',NUMBER:'number',TEXT:'text',CURRENCY_BRL:'currency_brl',PERCENT:'percent'},AggregationType:{SUM:'sum',MAX:'max'},newUserError:()=>({setText(t){return {throwException(){throw Error(t)}}}})};
 const ctx={Date,DataStudioApp:{createCommunityConnector:()=>cc},console:{error:v=>logs.push(v)},Utilities:{sleep:v=>sleeps.push(v)},PropertiesService:{getScriptProperties:()=>({getProperty:()=>JSON.stringify(secret)})},UrlFetchApp:{fetch:(url,options)=>{calls.push({url,options});let reply;if(url.endsWith('/v1/destino'))reply={body:{protocol:secret.protocol,target:'nexoflow_datastudio_homologacao.farma',segment:'FARMA',environment:'homologacao',schema_hash:ctx.NexoDSSchemaHash}};else reply=callback(JSON.parse(options.payload),calls.length);return {getResponseCode:()=>reply.status||200,getContentText:()=>reply.raw ?? JSON.stringify(reply.body||{})};}}};
 vm.createContext(ctx);for(const f of ['Schemas.js','AbcCore.js','Code.js'])vm.runInContext(fs.readFileSync('connectors/datastudio_api/'+f,'utf8'),ctx);return {ctx,calls,logs,sleeps,secret};
}
function request(names=['produtos_distintos_periodo']){return {configParams:{segmento:'FARMA',ambiente:'homologacao',tabela:'BI_Itens'},fields:names.map(name=>({name})),dateRange:{startDate:'2026-11-01',endDate:'2026-11-03'},dimensionsFilters:[[{fieldName:'sku_informado',operator:'EQUALS',type:'INCLUDE',values:['1']}]]};}
function assertFarmaError(f, req, code, message=/Falha ao carregar os dados|A consulta demorou|Selecione um período|O período selecionado tem dados demais|Sem dados suficientes/){
 const before=f.logs.length;
 assert.throws(()=>f.ctx.getData(req),e=>message.test(e.message)&&!e.message.includes('DS_'));
 assert.equal(f.logs.length,before+1);
 assert.match(JSON.parse(f.logs.at(-1)).codigo,code);
}
function result(p,rows){return {body:{protocol:"nexoflow_datastudio_1",target:"nexoflow_datastudio_homologacao.farma",segment:"FARMA",environment:"homologacao",schema_hash:require("../connectors/datastudio_api/Schemas.js").hash,fields:p.fields,rows:rows,complete:true,version:1}};}
test('schema preserva IDs, datas, atualizado_em Texto e SKU sem agregação',()=>{
 const f=fixture(),fields=f.ctx.dsFields_('BI_Itens').build(),original=require('../connectors/continuacoes/Schemas.js').BI_Itens;
 assert.deepEqual(Array.from(fields.slice(0,12),f=>f.id),original.map(f=>f[0]));
 assert.equal(fields.find(f=>f.id==='atualizado_em').type,'text');assert.equal(fields.find(f=>f.id==='sku_informado').role,'dimension');assert.equal(fields.find(f=>f.id==='produtos_distintos_periodo').reaggregatable,false);
 assert.ok(!f.ctx.NexoDSSchemas.Controle&&!f.ctx.NexoDSSchemas.Cache_orders);
});
test('nomes comerciais FARMA aparecem com os IDs e as agregações atuais',()=>{
 const f=fixture();
 const schema=table=>f.ctx.getSchema({configParams:{...request().configParams,tabela:table}}).schema;
 const ltv=schema('BI_LTV_Clientes').find(field=>field.id==='ltv_observado');
 assert.equal(ltv.label,'Receita histórica por cliente');
 assert.equal(ltv.type,'currency_brl');
 const roas=schema('Resumo_Anuncios_Veiculados_FARMA').find(field=>field.id==='roas_conversa_anuncio');
 assert.equal(roas.label,'Retorno sobre anúncios na conversa original');
 assert.equal(roas.aggregation,'max');
 const labels=segment=>f.ctx.dsFields_('BI_Clientes_Vendas',segment).build();
 assert.equal(labels('FARMA').find(field=>field.id==='cliente').label,'Nome do cliente');
 assert.equal(labels('PET').find(field=>field.id==='cliente').label,
              labels().find(field=>field.id==='cliente').label);
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
  assertFarmaError(f,request(),new RegExp('^DS_HTTP_'+code+'$'));
  assert.equal(f.sleeps.length,[429,503].includes(code)?2:0);
 }
 const f=fixture(p=>({body:{fields:p.fields,rows:[[216]],complete:false}}));assertFarmaError(f,request(),/^DS_CONTRATO_DESTINO_DIVERGENTE$/);
});
test('503 do leitor distingue permissão de indisponibilidade e retoma somente a leitura transitória', () => {
 const denied=fixture(()=>({status:503,body:{error:'DS_PERMISSAO',detail:'private-sentinel'}}));
 assertFarmaError(denied,request(),/^DS_PERMISSAO/);
 assert.equal(denied.calls.length,1);
 assert.deepEqual(denied.sleeps,[]);
 const offline={status:503,body:{error:'DS_BANCO_INDISPONIVEL',detail:'private-sentinel'}};
 const retry=fixture((p,n)=>n<3?offline:result(p,[[17]]));
 assert.equal(retry.ctx.getData(request()).rows[0].values[0],17);
 assert.deepEqual(retry.sleeps,[1000,2000]);
 const exhausted=fixture(()=>offline);
 assertFarmaError(exhausted,request(),/^DS_BANCO_INDISPONIVEL/);
 assert.deepEqual(exhausted.sleeps,[1000,2000]);
 const interrupted=fixture((p,n)=>n===1?offline:{status:503,body:{error:'DS_PERMISSAO'}});
 assertFarmaError(interrupted,request(),/^DS_PERMISSAO/);
 assert.deepEqual(interrupted.sleeps,[1000]);
 const late=fixture(()=>offline);
 let elapsed=0;
 late.ctx.Date=class extends Date {static now(){elapsed+=46000;return elapsed;}};
 assertFarmaError(late,request(),/^DS_BANCO_INDISPONIVEL/);
 assert.deepEqual(late.sleeps,[]);
 for(const f of [denied,retry,exhausted,interrupted,late]) assert.ok(!f.logs.join().includes('private-sentinel'));
});
test('503 genérico conserva apenas o status, mesmo após outra causa ou um corpo inesperado', () => {
 for(const raw of ['<html>private-sentinel</html>','null','{"error":["DS_PERMISSAO"]}',
                   '{"error":"DS_INSIGHTS_COBERTURA_INCOMPLETA"}','{"error":"private-sentinel"}']) {
   const f=fixture((p,n)=>n===1?{status:503,body:{error:'DS_BANCO_INDISPONIVEL'}}:{status:503,raw});
   assertFarmaError(f,request(),/^DS_HTTP_503$/);
   assert.equal(f.calls.length,3);assert.deepEqual(f.sleeps,[1000,2000]);
   assert.ok(!f.logs.join().includes('private-sentinel'));
 }
 const auth=fixture(()=>({status:401,body:{error:'DS_BANCO_INDISPONIVEL'}}));
 assertFarmaError(auth,request(),/^DS_HTTP_401/);
 assert.deepEqual(auth.sleeps,[]);
});
test('rejeita agregação com filtro não suportado e marca não autorizada',()=>{
 const f=fixture(p=>result(p,[[216]])),r=request();r.dimensionsFilters[0][0].operator='REGEXP_PARTIAL_MATCH';
 assertFarmaError(f,r,/^DS_FILTRO_AGREGACAO_NAO_SUPORTADO/);
 r.configParams.segmento='OUTRO';assert.throws(()=>f.ctx.getData(r),/DS_CONFIGURACAO_INVALIDA/);
});
test('filtro aplicado não devolve campos solicitados só para filtrar; resumo exige grão',()=>{
 const f=fixture(p=>result(p,[[90]])),r=request();r.fields.push({name:'sku_informado',forFilterOnly:true});
 assert.equal(f.ctx.getData(r).schema.length,1);
 const summary=request(['pedidos']);summary.configParams.tabela='BI_Historico_Resumo';summary.dimensionsFilters=[];
 assertFarmaError(f,summary,/^DS_RESUMO_EXIGE_GRAO/);
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
 assertFarmaError(f,request(),/^DS_FILTRO_CORTA_RECORTE_USE_DETALHE/);
 assert.ok(!f.logs.join().includes('PRIVATE-MUST-NOT-APPEAR'));
 const bad=fixture(()=>({status:409,body:{error:'DS_PRIVATE-MUST-NOT-APPEAR'}}));
 assertFarmaError(bad,request(),/^DS_HTTP_409/);
 assert.ok(!bad.logs.join().includes('PRIVATE-MUST-NOT-APPEAR'));
});

test('ABC consulta apenas agregados no servidor, sem baixar itens/pedidos',()=>{
 for(const mode of ['abc','resumo','juntos']){
  const f=fixture(p=>{
   assert.equal(p.mode,mode);assert.equal(p.start,'2026-11-01');assert.equal(p.end,'2026-11-03');
   assert.equal(p.table,undefined);assert.equal(p.aggregation,undefined);
   return result(p,[[mode==='abc'?'001':mode==='resumo'?'2':'001']]);
  });
  const r=request([mode==='abc'?'produto_codigo':mode==='resumo'?'skus_distintos':'produto_a_codigo']);
  r.configParams.tabela='ABC_'+mode;r.dimensionsFilters=[];
  const response=f.ctx.getData(r);
  assert.equal(response.rows.length,1);assert.equal(response.filtersApplied,false);
  assert.equal(f.calls.length,1);assert.ok(f.calls[0].url.endsWith('/v1/abc'));
 }
});
test('ABC recusa falha, limite, resposta parcial e versão ausente',()=>{
 for(const variant of ['version','partial','failure','limit','target']){
  const f=fixture(p=>{
   if(variant==='failure')return {status:403};
   if(variant==='limit')return {status:409,body:{error:'DS_CONSULTA_EXCEDE_LIMITE_USE_RESUMO_OU_PERIODO'}};
   const r=result(p,[]);r.body.version=variant==='version'?0:1;r.body.complete=variant!=='partial';
   if(variant==='target')r.body.segment='PET';return r;
  });
  const r=request(['produto_codigo']);r.configParams.tabela='ABC_abc';r.dimensionsFilters=[];
  assertFarmaError(f,r,/^DS_[A-Z0-9_]+$/);
 }
});
test('projeções do inventário são tipadas sem expor payloads privados',()=>{
 const f=fixture();
 assert.equal(f.ctx.dsFields_('Itens_Pedidos_FarmaLider').build().find(f=>f.id==='quantidade').type,'number');
 for(const bad of ['cpf','telefone','ultimo_pedido_raw','primeiro_anuncio_clique_id'])assert.ok(!f.ctx.NexoDSSchemas.Pedidos_FarmaLider.columns.includes(bad));
 const original={};vm.createContext(original);vm.runInContext(fs.readFileSync('connectors/looker_abc/Code.js','utf8'),original);
 for(const mode of ['abc','resumo','juntos'])assert.deepEqual(Array.from(f.ctx.NexoDSSchemas['ABC_'+mode].columns),Array.from(original.fieldSpecs_(mode),f=>f[0]));
});

test('ABC propaga validação financeira e alinha ordem do SDK sem recalcular classe filtrada',()=>{
 const f=fixture(()=>({status:409,body:{error:'DS_ABC_BASE_INCOMPLETA'}}));
 const r=request(['classe_abc','produto_codigo']);r.configParams.tabela='ABC_abc';r.dimensionsFilters=[];
 assertFarmaError(f,r,/^DS_ABC_BASE_INCOMPLETA/);
 const good=fixture(p=>{assert.deepEqual(p.fields,['produto_codigo','classe_abc']);return result(p,[['01','A']]);});
 r.dimensionsFilters=[[{fieldName:'classe_abc',operator:'EQUALS',type:'INCLUDE',values:['A']}]];
 const response=good.ctx.getData(r);
 assert.deepEqual(Array.from(response.schema,f=>f.name),['produto_codigo','classe_abc']);
 assert.deepEqual(Array.from(response.rows[0].values),['01','A']);
 assert.equal(response.filtersApplied,false);
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

test('Compradores_Operacionais usa o histórico inteiro e agrupa no leitor antes da LEFT', () => {
  const f = fixture(p => {
    assert.equal(p.table, 'Pedidos_FarmaLider');
    assert.deepEqual(p.fields, ['contact_uuid', 'calc_gf73fvq57d', 'pedido_chave']);
    assert.deepEqual(p.filters, [{field: 'calc_gf73fvq57d', values: ['Sim']}]);
    assert.deepEqual(p.aggregation, {pedido_chave: 'count'});
    assert.deepEqual([p.start, p.end], ['', '']);
    return result(p, [['001', 'Sim', 50001], [null, 'Sim', 1], [' ', 'Sim', 2]]);
  });
  const r = request(['contact_uuid']);
  r.configParams.tabela = 'Compradores_Operacionais';
  r.dimensionsFilters = [];
  const response = f.ctx.getData(r);
  assert.deepEqual(Array.from(response.schema, f => f.name), ['contact_uuid']);
  assert.deepEqual(Array.from(response.rows, r => Array.from(r.values)), [['001']]);
  assert.equal(f.ctx.NexoDSSchemas.Compradores_Operacionais.period, null);
  assert.equal(f.ctx.NexoDSSchemas.Pedidos_FarmaLider.period, 'data');
});

test('Compradores_Operacionais mantém filtros da fonte e as guardas do leitor', () => {
  const r = request(['calc_gf73fvq57d']);
  r.configParams.tabela = 'Compradores_Operacionais';
  r.fields.push({name:'contact_uuid', forFilterOnly:true});
  r.dimensionsFilters = [[{type:'INCLUDE', operator:'EQUALS', fieldName:'contact_uuid', values:['001']}]];
  const f = fixture(p => {
    assert.deepEqual(p.filters, [
      {field:'contact_uuid', values:['001']},
      {field:'calc_gf73fvq57d', values:['Sim']}
    ]);
    return result(p, [['001', 'Sim', 2]]);
  });
  const response = f.ctx.getData(r);
  assert.equal(response.filtersApplied, true);
  assert.deepEqual(Array.from(response.rows[0].values), ['Sim']);
  const wrong = fixture(p => result(p, [['001', 'Não', 2]]));
  assertFarmaError(wrong,r,/^DS_RESPOSTA_INCOMPLETA/);
  const limited = fixture(() => ({status:409, body:{error:'DS_CONSULTA_EXCEDE_LIMITE_USE_RESUMO_OU_PERIODO'}}));
  assertFarmaError(limited,r,/^DS_CONSULTA_EXCEDE_LIMITE/);
});


test('somas SQL explícitas reduzem volume sem inferir médias/distintos ou alterar fontes antigas',()=>{
 const r=request(['receita_item','produto_codigo','quantidade']);
 r.configParams.modo_consulta='somas';
 const f=fixture(p=>{
  assert.deepEqual(p.fields,['produto_codigo','quantidade','receita_item']);
  assert.deepEqual(p.aggregation,{quantidade:'sum',receita_item:'sum'});
  assert.equal(p.filters[0].field,'sku_informado');return result(p,[['001','60003','6000.30']]);
 });
 const response=f.ctx.getData(r);
 assert.deepEqual(Array.from(response.rows[0].values),['001',60003,6000.3]);
 assert.equal(response.filtersApplied,true);
 const direct=fixture(p=>{assert.deepEqual(p.aggregation,{});return result(p,[]);});
 delete r.configParams.modo_consulta;direct.ctx.getData(r);
 r.configParams.modo_consulta='somas';r.fields=[{name:'valor_unitario'}];
 assertFarmaError(f,r,/^DS_METRICA_NAO_ADITIVA/);
 r.fields=[{name:'quantidade'}];r.dimensionsFilters[0][0].operator='CONTAINS';
 assertFarmaError(f,r,/^DS_FILTRO_AGREGACAO_NAO_SUPORTADO/);
 r.configParams.tabela='BI_LTV_Clientes';r.fields=[{name:'ltv_observado'}];
 assertFarmaError(f,r,/^DS_MODO_AGREGACAO_NAO_SUPORTADO/);
});

test('ABC vazio válido continua vazio; valores malformados não viram zero',()=>{
 const r=request(['produto_codigo']);r.configParams.tabela='ABC_abc';r.dimensionsFilters=[];
 const empty=fixture(p=>result(p,[]));assert.equal(empty.ctx.getData(r).rows.length,0);
 r.fields=[{name:'unidades'}];
 const invalid=fixture(p=>result(p,[['NaN']]));assertFarmaError(invalid,r,/^DS_NUMERO_INVALIDO/);
});

test('ABC mantém prazo e recusa resultado completo que chegou tarde',()=>{
 const f=fixture(p=>result(p,[['001']]));
 let now=0;f.ctx.Date={now:()=>{now+=23000;return now;}};
 const r=request(['produto_codigo']);r.configParams.tabela='ABC_abc';r.dimensionsFilters=[];
 assertFarmaError(f,r,/^DS_PRAZO_CONSULTA$/,/^A consulta demorou mais que o previsto\./);
});

test('Top pares é explícito, tem universo verificado e não permite filtro silencioso',()=>{
 const req=request(['produto_a_codigo','pedidos_juntos']);
 req.configParams.tabela='ABC_juntos';req.configParams.pares_escopo='TOP';req.configParams.pares_limite='25';req.dimensionsFilters=[];
 const f=fixture(p=>{assert.equal(p.top,25);assert.equal(p.mode,undefined);const r=result(p,[['001',2]]);r.body.scope={kind:'TOP_PARES',requested:25,universe_pairs:1,selected_pairs:1,all_pairs_returned:true};return r;});
 assert.equal(f.ctx.getData(req).rows.length,1);assert.ok(f.calls[0].url.endsWith('/v1/abc/pares'));
 assert.ok(f.logs.some(x=>x.includes('top_pares_v1')));
 const bad=fixture(p=>result(p,[['001',2]]));assertFarmaError(bad,req,/^DS_RESPOSTA_INCOMPLETA/);
 req.dimensionsFilters=[[{fieldName:'produto_a_codigo',operator:'EQUALS',values:['001'],type:'INCLUDE'}]];
 assertFarmaError(f,req,/^DS_TOP_PARES_FILTRO_NAO_SUPORTADO/);
});

test('ds136 preserva tipos e zero confirmado, bloqueia lacunas e separa PET',()=>{
 const table='BI_Weni_Conversas_Diarias',r=request(['data','conversas_weni']);
 r.configParams.tabela=table;r.dimensionsFilters=[];
 const f=fixture(p=>result(p,[['2026-11-01',0]]));
 assert.deepEqual(Array.from(f.ctx.getData(r).rows[0].values),['20261101',0]);
 const blocked=fixture(()=>({status:409,body:{error:'DS_INSIGHTS_COBERTURA_INCOMPLETA'}}));
 assertFarmaError(blocked,r,/^DS_INSIGHTS_COBERTURA_INCOMPLETA/);
 delete r.dateRange;
 assertFarmaError(f,r,/^DS_PERIODO_OBRIGATORIO/);
 r.scriptParams={sampleExtraction:true};
 assert.equal(f.ctx.getData(r).rows.length,0);
 assert.ok(f.calls.at(-1).url.endsWith('/v1/destino'));
 r.configParams.segmento='PET';
 assert.throws(()=>f.ctx.getData(r),/DS_INSIGHTS_SEGMENTO/);
});

require('./datastudio/meta_orders.cjs');
require('./datastudio/produtos_periodo.cjs')({fixture, result, assertFarmaError});

test('Público entrega dimensões e contagens aditivas sem linhas de contatos',()=>{
 const f=fixture(p=>{
   assert.equal(p.table,'BI_Publico_Resumo');
   assert.equal(p.start,'');
   assert.deepEqual(JSON.parse(JSON.stringify(p.aggregation)),{});
   assert.deepEqual(JSON.parse(JSON.stringify(p.filters)),[{field:'cidade',values:['Belém']}]);
   return result(p,[p.fields.map(n=>({canal:'whatsapp',idade:'25',contatos:30,compra_identificada:20})[n])]);
 });
 const r=request(['canal','idade','contatos','compra_identificada']);
 r.configParams.tabela='BI_Publico_Resumo';
 r.fields.push({name:'cidade',forFilterOnly:true});
 r.dimensionsFilters=[[{type:'INCLUDE',operator:'EQUALS',fieldName:'cidade',values:['Belém']}]];
 const answer=f.ctx.getData(r);
 assert.equal(answer.filtersApplied,true);
 const row=Object.fromEntries(answer.schema.map((s,i)=>[s.name,answer.rows[0].values[i]]));
 assert.deepEqual(row,{canal:'whatsapp',idade:25,contatos:30,compra_identificada:20});
 const schema=f.ctx.dsFields_('BI_Publico_Resumo').build();
 assert.equal(schema.find(x=>x.id==='idade').role,'dimension');
 assert.equal(schema.find(x=>x.id==='contatos_idade_informada').aggregation,'sum');
 assert.equal(schema.some(x=>x.id==='contato_chave'),false);
});

test('Público devolve a dimensão para filtros que o Looker avalia depois',()=>{
 const f=fixture(p=>{
   assert.deepEqual(JSON.parse(JSON.stringify(p.filters)),[]);
   assert.ok(p.fields.includes('idade'));
   return result(p,[p.fields.map(n=>({idade:25,contatos:30})[n])]);
 });
 const r=request(['contatos']);
 r.configParams.tabela='BI_Publico_Resumo';
 r.fields.push({name:'idade',forFilterOnly:true});
 r.dimensionsFilters=[[{type:'EXCLUDE',operator:'EQUALS',fieldName:'idade',values:[20]}]];
 const answer=f.ctx.getData(r);
 assert.equal(answer.filtersApplied,false);
 assert.equal(answer.schema.find(x=>x.name==='idade').type,'number');
});

test('visão Weni ausente é explícita e não se torna período zerado',()=>{
 const f=fixture(()=>({status:409,body:{error:'DS_INSIGHTS_VISAO_AUSENTE'}}));
 const r=request(['conversas_weni']);
 r.configParams.tabela='BI_Weni_Conversas_Diarias';
 assertFarmaError(f,r,/^DS_INSIGHTS_VISAO_AUSENTE/);
});
