const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(callback){
 const calls=[],logs=[],sleeps=[],stored={NF_READ_TOKEN:'reader-synthetic-token-xxxxxxxxxxxxxxxxxxxxxxxx'};
 const script={NF_READ_ENDPOINT:'https://reader.example.test',NF_ACCESS_CLIENT_ID:'reader.access',NF_ACCESS_CLIENT_SECRET:'reader-access-fixture'};
 function fields(){const all=[];function field(role){const f={role,setId(v){this.id=v;return this;},setName(){return this;},setType(v){this.type=v;return this;},setAggregation(v){this.aggregation=v;return this;},setIsReaggregatable(v){this.reaggregatable=v;return this;},getId(){return this.id;}};all.push(f);return f;}return {newMetric:()=>field('metric'),newDimension:()=>field('dimension'),build:()=>all,forIds:n=>{const rows=all.filter(f=>n.includes(f.id));return {asArray:()=>rows,build:()=>rows.map(f=>({name:f.id,type:f.type}))};}};}
 const cc={getFields:fields,FieldType:{YEAR_MONTH_DAY:'date',NUMBER:'number',TEXT:'text'},AggregationType:{SUM:'sum'},newUserError:()=>({setText(t){return {throwException(){throw Error(t);}};}})};
 const ctx={DataStudioApp:{createCommunityConnector:()=>cc},Date,console:{info:v=>logs.push(v)},Utilities:{sleep:v=>sleeps.push(v)},PropertiesService:{getScriptProperties:()=>({getProperties:()=>script}),getUserProperties:()=>({getProperty:k=>stored[k],setProperty(k,v){stored[k]=v;},deleteProperty(k){delete stored[k];}})},UrlFetchApp:{fetch:(url,options)=>{calls.push({url,options});const r=callback?callback(url,options,calls.length):{};return {getResponseCode:()=>r.status||200,getContentText:()=>JSON.stringify(r.body||{})};}}};
 vm.createContext(ctx);for(const file of ['Schema.js','Code.js'])vm.runInContext(fs.readFileSync('connectors/bi_itens_api/'+file,'utf8'),ctx);
 return {ctx,calls,logs,sleeps,script,stored};
}
function request(fields=['produtos_distintos_periodo']){return {fields:fields.map(name=>({name})),dateRange:{startDate:'2026-11-01',endDate:'2026-11-03'},dimensionsFilters:[[{fieldName:'sku_informado',operator:'EQUALS',type:'INCLUDE',values:['1']}]]};}
function response(options,rows){const p=JSON.parse(options.payload);return {protocol:'bi_itens_farma_leitura_1',target:'nexoflow_datastudio_piloto.farma.produtos_itens',fields:p.fields,rows,filtersApplied:true,revision:3,state:'READY',cut_at:'2026-11-12T12:00:00Z'};}
test('novo leitor preserva IDs da BI_Itens e métrica exata não reagregável',()=>{
 const f=fixture(),fields=f.ctx.pgFields_().build();
 const old=require('../connectors/continuacoes/Schemas.js').BI_Itens.map(s=>s[0]);
 assert.deepEqual(Array.from(fields.slice(0,12),f=>f.id),old);
 assert.equal(fields.find(f=>f.id==='produtos_distintos_periodo').reaggregatable,false);
 assert.equal(fields.find(f=>f.id==='atualizado_em').type,'text');
 assert.equal(fields.find(f=>f.id==='sku_informado').role,'dimension');
});
test('cartão C usa resultado SQL; sem segredo na URL, payload ou diagnóstico',()=>{
 const f=fixture((_u,o)=>({body:response(o,[{values:[216]}])}));
 const r=f.ctx.getData(request());assert.equal(r.rows[0].values[0],216);assert.equal(r.filtersApplied,true);
 const call=f.calls[0];assert.equal(call.options.followRedirects,false);assert.equal(call.options.headers['CF-Access-Client-Id'],'reader.access');
 assert.ok(!call.url.includes(f.stored.NF_READ_TOKEN));assert.ok(!call.options.payload.includes(f.stored.NF_READ_TOKEN));
 assert.ok(!f.logs.join().includes(f.stored.NF_READ_TOKEN));assert.ok(!f.logs.join().includes('reader-access-fixture'));
});
test('detalhe, moeda, códigos com zero e campos usados apenas em filtros',()=>{
 const f=fixture((_u,o)=>({body:response(o,[{values:['000123','134','4753.02']}])}));
 const q=request(['produto_codigo','quantidade','receita_item']);q.fields.push({name:'sku_informado',forFilterOnly:true});
 const r=f.ctx.getData(q);assert.deepEqual(Array.from(r.rows[0].values),['000123',134,4753.02]);
 assert.equal(r.schema.some(s=>s.name==='sku_informado'),false);
});
test('período vazio não vira zero fictício; alteração de estado/schema nunca retorna parcial',()=>{
 const f=fixture((_u,o)=>({body:response(o,[])}));assert.equal(f.ctx.getData(request()).rows.length,0);
 for(const mutation of [r=>r.state='WRITING',r=>r.fields=['receita_item'],r=>r.target='nexoflow_hub',r=>r.rows=[{values:['NaN']}],r=>r.rows=[{values:[1,2]}]]){
  const broken=fixture((_u,o)=>{const r=response(o,[{values:[216]}]);mutation(r);return {body:r};});
  assert.throws(()=>broken.ctx.getData(request()),/Nenhum total parcial/);
 }
});
test('429 e 503 têm repetição limitada; autenticação e publicação pendente não são contornadas',()=>{
 const f=fixture((_u,o,n)=>n<3?{status:429}:{body:response(o,[{values:[90]}])});
 assert.equal(f.ctx.getData(request()).rows[0].values[0],90);assert.deepEqual(f.sleeps,[1000,2000]);
 for(const status of [401,403,409,503]){
  const f=fixture(()=>({status,body:{error:status===409?'BI_PG_LEITURA_PUBLICACAO_PENDENTE':'segredo bruto não deve aparecer'}}));
  assert.throws(()=>f.ctx.getData(request()),e=>e.message.includes('Nenhum total parcial')&&!e.message.includes('segredo bruto'));
  assert.equal(f.calls.length,status===503?3:1);
 }
});
test('campo arbitrário é recusado antes de HTTP',()=>{const f=fixture();assert.throws(()=>f.ctx.getData(request(['credentials'])),/NF_PG_CAMPOS/);assert.equal(f.calls.length,0);});
