const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(callback){
 const calls=[],logs=[],sleeps=[];
 const secret={protocol:'nexoflow_datastudio_1',segment:'FARMA',environment:'homologacao',endpoint:'https://reader.example.invalid',api_token:'synthetic-reader-only-token',access_client_id:'synthetic.access',access_client_secret:'synthetic-access-secret'};
 function fields(){const all=[];function field(role){const f={role,setId(v){this.id=v;return this;},setName(){return this;},setType(v){this.type=v;return this;},setAggregation(v){this.aggregation=v;return this;},setIsReaggregatable(v){this.reaggregatable=v;return this;}};all.push(f);return f;}return {newMetric:()=>field('metric'),newDimension:()=>field('dimension'),build:()=>all,forIds:n=>({build:()=>all.filter(f=>n.includes(f.id)).map(f=>({name:f.id,type:f.type}))})};}
 const cc={getFields:fields,FieldType:{YEAR_MONTH_DAY:'date',NUMBER:'number',TEXT:'text'},AggregationType:{SUM:'sum',MAX:'max'},newUserError:()=>({setText(t){return {throwException(){throw Error(t)}}}})};
 const ctx={Date,DataStudioApp:{createCommunityConnector:()=>cc},console:{error:v=>logs.push(v)},Utilities:{sleep:v=>sleeps.push(v)},PropertiesService:{getScriptProperties:()=>({getProperty:()=>JSON.stringify(secret)})},UrlFetchApp:{fetch:(url,options)=>{calls.push({url,options});let reply;if(url.endsWith('/v1/destino'))reply={body:{protocol:secret.protocol,target:'nexoflow_datastudio_homologacao.farma',segment:'FARMA',environment:'homologacao',schema_hash:ctx.NexoDSSchemaHash}};else reply=callback(JSON.parse(options.payload),calls.length);return {getResponseCode:()=>reply.status||200,getContentText:()=>JSON.stringify(reply.body||{})};}}};
 vm.createContext(ctx);for(const f of ['Schemas.js','Code.js'])vm.runInContext(fs.readFileSync('connectors/datastudio_api/'+f,'utf8'),ctx);return {ctx,calls,logs,sleeps,secret};
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
