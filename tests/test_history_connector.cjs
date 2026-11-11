const test=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const vm=require('node:vm');
const reader=require('../connectors/continuacoes/Tables.js');
const schemas=require('../connectors/continuacoes/Schemas.js');
const hash=s=>crypto.createHash('sha256').update(s).digest('hex');
const hub='dashboard_fixture_1234567890', hist='history_fixture_1234567890', extra='extra_fixture_1234567890';
function fixture(title='Historico_Pedidos') {
  const role=title.startsWith('Historico_')?'historico':'dashboard',root=role==='historico'?hist:hub;
  const header=schemas[title].map(s=>s[0]);
  function row(n,overrides={}) {
    const values={chave:'FARMA:'+n,segmento:'FARMA',pedido_id:String(n).padStart(6,'0'),cliente_id:'00001',data:'2026-11-01T02:00:00Z',estado:'valido',frete:9.99,faturamento:89.99,produtos:80,vigente:'Sim',...overrides};
    return header.map(h=>values[h]===undefined?'':values[h]);
  }
  const files={};
  const stamp=r=>({metadataKey:'nexoflow_continuation_origin_v1',metadataValue:JSON.stringify({hub,segment:'FARMA',role:r}),visibility:'DOCUMENT',location:{spreadsheet:true}});
  files[hub]={sheets:[{properties:{sheetId:1,title:'NexoFlow_Continuidade',gridProperties:{rowCount:100,columnCount:3}}}],developerMetadata:[stamp('dashboard')]};
  if(root!==hub) files[root]={sheets:[],developerMetadata:[stamp(role)]};
  const index=[['tipo','chave','valor'],['config','principal',JSON.stringify({format:1,hub,enabled:true,segment:'FARMA',roots:{dashboard:hub,historico:hist,operacao:'op_fixture_1234567890123'},history_publication:{state:'READY',revision:'a'}})]];
  const physical={};const counts=[];
  function add(book,n,rows) {
    if (!files[book]) {files[book]={sheets:[],developerMetadata:[stamp(role)]};index.push(['arquivo',book,JSON.stringify({role,number:n,source:root})]);}
    const sheetId=10+n;
    files[book].sheets.push({properties:{sheetId,title,gridProperties:{rowCount:rows.length+1,columnCount:header.length}}});
    physical[book]=[header,...rows];
    index.push(['parte',title+'#'+n,JSON.stringify({title,number:n,book_id:book,sheet_id:sheetId,width:header.length,schema:hash(reader.stable(header))})]);
    counts.push({number:n,rows:rows.length});
  }
  add(root,0,[row(1)]);add(extra,1,[row(2)]);
  const state=['estado',title,JSON.stringify({state:'READY',revision:'a',parts:counts})];index.push(state);
  let reads=0;
  const api={meta:id=>{if(!files[id])throw Error('parte ausente');return structuredClone(files[id]);},values:(id,range)=>{
    reads++;
    if(range.includes('NexoFlow_Continuidade'))return structuredClone(index);
    const match=range.match(/!A(\d+):[A-Z]+(\d+)$/);if(!match)throw Error('intervalo inesperado');
    return structuredClone(physical[id].slice(Number(match[1])-1,Number(match[2])));
  }};
  function run(options={}) {return reader.read(hub,[title],{api,hash,widths:{[title]:header.length},schemas,segment:'FARMA',...options})[0];}
  return {api,index,files,physical,header,row,run,add,counts,state,get reads(){return reads;}};
}
test('histórico lê papel Histórico e descobre partes novas sem trocar a fonte',()=>{
  const f=fixture();assert.equal(f.run().length,3);
  f.add('nova_parte_fixture_1234567890',2,[f.row(3)]);
  f.state[2]=JSON.stringify({state:'READY',revision:'b',parts:f.counts});
  assert.equal(f.run().length,4);
});
test('não expõe tabela arbitrária nem aceita partes órfãs ou ausentes',()=>{
  const f=fixture();
  assert.throws(()=>reader.read(hub,['Credenciais'],{api:f.api,hash,widths:{Credenciais:2},schemas}),/origem inválida/);
  delete f.files[extra];assert.throws(f.run,/parte ausente/);
});
test('recusa tipo monetário textual, duplicação de chave e segmento diferente',()=>{
  for(const failure of ['money','duplicate','segment']) {
    const f=fixture(),row=f.physical[extra][1];
    if(failure==='money')row[f.header.indexOf('faturamento')]='89,99';
    if(failure==='duplicate')row[0]=f.physical[hist][1][0];
    if(failure==='segment')row[1]='PET';
    assert.throws(f.run,/Continuações:/);
  }
});
test('publicação parcial e cabeçalho alterado nunca retornam total incompleto',()=>{
  const f=fixture();let c=JSON.parse(f.index[1][2]);c.history_publication.state='WRITING';f.index[1][2]=JSON.stringify(c);
  assert.throws(f.run,/publicação/);
  c.history_publication.state='READY';f.index[1][2]=JSON.stringify(c);f.physical[extra][0]=['outro'];
  assert.throws(f.run,/cabeçalho/);
});
function connector(f) {
  const all=[];
  const field=()=>({setId(x){this.id=x;return this;},setName(){return this;},setType(value){this.type=value;return this;},setAggregation(value){this.aggregation=value;return this;},getId(){return this.id;}});
  const fields={build:()=>all,newMetric:()=>{const x=field();x.role='metric';all.push(x);return x;},newDimension:()=>{const x=field();x.role='dimension';all.push(x);return x;},
    forIds:n=>{const selected=all.filter(f=>n.includes(f.id));return {asArray:()=>selected,build:()=>selected.map(f=>({name:f.id}))};}};
  const ctx={NexoSchemas:schemas,NexoTables:reader,Date,Intl,Sheets:{},Utilities:{},DataStudioApp:{createCommunityConnector:()=>({getFields:()=>fields,FieldType:{YEAR_MONTH_DAY:'date',NUMBER:'number',TEXT:'text'},AggregationType:{MAX:'max',SUM:'sum'},newUserError:()=>({setText:t=>({throwException:()=>{throw Error(t);}})})})}};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync('connectors/continuacoes/Code.js','utf8'),ctx);
  ctx.api_=()=>f.api;ctx.hash_=hash;
  return ctx;
}
test('data do histórico respeita Belém e preserva ID com zeros e moeda',()=>{
  const f=fixture(),ctx=connector(f);
  const result=ctx.getData({configParams:{spreadsheetId:hub,segmento:'FARMA',tabela:'Historico_Pedidos'},fields:[{name:'pedido_id'},{name:'data'},{name:'faturamento'}],dateRange:{startDate:'2026-10-31',endDate:'2026-10-31'}});
  assert.equal(result.rows.length,2);assert.equal(result.rows[0].values[0],'000001');assert.equal(result.rows[0].values[1],'20261031');assert.equal(result.rows[0].values[2],89.99);
  const empty=ctx.getData({configParams:{spreadsheetId:hub,segmento:'FARMA',tabela:'Historico_Pedidos'},fields:[{name:'pedido_id'}],dateRange:{startDate:'2026-11-02',endDate:'2026-11-02'}});
  assert.equal(empty.rows.length,0);
});
test('resumo anual usa fonte pequena e bloqueia filtro que corta o recorte',()=>{
  const f=fixture('BI_Historico_Resumo');
  f.physical[hub][1]=f.row(1,{tipo_recorte:'ANO',competencia:'2026',periodo_inicio:'2026-10-01',periodo_fim:'2026-11-07',clientes:1,pedidos:2,faturamento:160});
  f.physical[extra][1]=f.row(2,{tipo_recorte:'MES',competencia:'2026-11',periodo_inicio:'2026-11-01',periodo_fim:'2026-11-07',clientes:1,pedidos:1,faturamento:80});
  const ctx=connector(f),request={configParams:{spreadsheetId:hub,segmento:'FARMA',tabela:'BI_Historico_Resumo',recorte_historico:'ANO'},fields:[{name:'clientes'},{name:'faturamento'}],dateRange:{startDate:'2026-01-01',endDate:'2026-12-31'}};
  const result=ctx.getData(request);assert.equal(result.rows.length,1);assert.equal(result.rows[0].values[0],1);assert.equal(result.rows[0].values[1],160);
  assert.ok(f.reads<20);
  request.dateRange={startDate:'2026-11-01',endDate:'2026-11-07'};assert.throws(()=>ctx.getData(request),/filtro corta/);
});
test('linha inserida fora da contagem confirmada bloqueia total desatualizado',()=>{
  const f=fixture();f.physical[extra].push(f.row(3));
  f.files[extra].sheets[0].properties.gridProperties.rowCount++;
  assert.throws(f.run,/quantidade de linhas/);
});
test('limite de resposta não corta dados silenciosamente',()=>{
  const f=fixture();
  // Chaves únicas e grade sintética: o leitor deve falhar antes de devolver 200.001 linhas.
  const total=200001;f.physical[hist]=[f.header,...Array.from({length:total},(_,n)=>f.row(n+100))];
  f.files[hist].sheets[0].properties.gridProperties.rowCount=total+1;
  f.counts[0].rows=total;f.state[2]=JSON.stringify({state:'READY',revision:'a',parts:f.counts});
  assert.throws(f.run,/200 mil linhas/);
});
test('itens usam pedido oficial e período, com cerca entre as duas fontes',()=>{
  const orders=fixture(),items=fixture('Historico_Itens');
  orders.physical[extra][1][orders.header.indexOf('data')]='2026-11-02T12:00:00-03:00';
  for (const book of [hist,extra]) {
    items.physical[book][1][items.header.indexOf('frete')]='Não';
    items.files[book].sheets[0].properties.sheetId+=20;
    orders.files[book].sheets.push(...items.files[book].sheets);
  }
  for (const record of items.index.filter(r=>r[0]==='parte'||r[0]==='estado')) {
    if(record[0]==='parte') {const data=JSON.parse(record[2]);data.sheet_id+=20;record[2]=JSON.stringify(data);}
    orders.index.push(record);
  }
  let indices=0,change=false;
  const api={meta:orders.api.meta,values:(id,range)=>{
    if(range.includes('NexoFlow_Continuidade')) {
      indices++;if(change&&indices===3) {const c=JSON.parse(orders.index[1][2]);c.history_publication.revision='changed';orders.index[1][2]=JSON.stringify(c);}
      return structuredClone(orders.index);
    }
    return (range.includes("'Historico_Itens'")?items.api:orders.api).values(id,range);
  }};
  const ctx=connector({api}),request={configParams:{spreadsheetId:hub,segmento:'FARMA',tabela:'Historico_Itens'},fields:[{name:'pedido_id'}],dateRange:{startDate:'2026-10-31',endDate:'2026-10-31'}};
  assert.equal(ctx.getData(request).rows.length,1);
  indices=0;change=true;assert.throws(()=>ctx.getData(request),/mudou entre as fontes/);
});

test('orçamento de tempo compartilhado bloqueia a segunda leitura tardia',()=>{
  const f=fixture();
  assert.throws(()=>f.run({startedAt:Date.now()-240001}),/tempo de consulta excedido/);
});
test('quantidade soma itens e não herda MAX de idade',()=>{
  const ctx=connector(fixture('Historico_Itens'));
  const fields=ctx.fields_('Historico_Itens').build();
  const quantity=fields.find(f=>f.id==='quantidade');
  assert.equal(quantity.aggregation,'sum');
  const values=[2,3];
  assert.equal(quantity.aggregation==='sum'?values.reduce((a,b)=>a+b,0):Math.max(...values),5);
});
test('vincula cinco schemas comerciais antes das partes sem liberar leitura parcial FARMA/PET',()=>{
  const titles=['Historico_Pedidos','Historico_Itens','BI_LTV_Clientes','BI_Cobertura_Historica','BI_Historico_Resumo'];
  for(const segment of ['FARMA','PET']) {
    const f=fixture();f.index.splice(2);let config=JSON.parse(f.index[1][2]);
    config.segment=segment;config.connector_tables=[];delete config.history_publication;
    f.index[1][2]=JSON.stringify(config);
    const op=config.roots.operacao;
    f.files[op]={sheets:[],developerMetadata:[{metadataKey:'nexoflow_continuation_origin_v1',metadataValue:JSON.stringify({hub,segment,role:'operacao'}),visibility:'DOCUMENT',location:{spreadsheet:true,locationType:'SPREADSHEET'}}]};
    for(const file of Object.values(f.files)) for(const tag of file.developerMetadata||[]) {const value=JSON.parse(tag.metadataValue);value.segment=segment;tag.metadataValue=JSON.stringify(value);}
    const ctx=connector(f);
    const original=f.api.values;
    f.api.values=(id,range)=>{assert.match(range,/NexoFlow_Continuidade/);return original(id,range);};
    for(const title of titles) {
      assert.equal(connector(f).getSchema({configParams:{spreadsheetId:hub,segmento:segment,tabela:title}}).schema.length,schemas[title].length);
      assert.throws(()=>f.run({segment}),/sem partes confirmadas/);
    }
    assert.equal(JSON.parse(f.index[1][2]).connector_tables.length,0);
    config.history_publication={state:'WRITING'};f.index[1][2]=JSON.stringify(config);
    assert.equal(ctx.getSchema({configParams:{spreadsheetId:hub,segmento:segment,tabela:titles[0]}}).schema.length,15);
    assert.throws(()=>f.run({segment}),/publicação/);
    assert.throws(()=>ctx.getSchema({configParams:{spreadsheetId:hub,segmento:segment==='FARMA'?'PET':'FARMA',tabela:titles[0]}}),/divergente/);
    f.files[op].developerMetadata=[];
    assert.throws(()=>ctx.getSchema({configParams:{spreadsheetId:hub,segmento:segment,tabela:titles[0]}}),/origem não comprovada/);
  }
});
test('métricas aditivas históricas e idade mantêm semânticas distintas',()=>{
  for(const title of ['Historico_Pedidos','Historico_Itens','BI_LTV_Clientes','BI_Cobertura_Historica','BI_Historico_Resumo']) {
    const fields=connector(fixture()).fields_(title).build();
    for(const field of fields.filter(f=>f.type==='number' && f.aggregation!==undefined && ['quantidade','unidades','produtos','frete','faturamento'].includes(f.id))) assert.equal(field.aggregation,'sum',title+'.'+field.id);
  }
  const age=connector(fixture()).fields_('BI_Publico').build().find(f=>f.id==='idade');
  assert.equal(age.type,'number');assert.equal(age.aggregation,undefined);
  const ctx=connector(fixture());ctx.NexoSchemas={Teste:[['idade','number'],['quantidade','number']]};
  const metrics=ctx.fields_('Teste').build();assert.equal(metrics[0].aggregation,'max');assert.equal(metrics[1].aggregation,'sum');
});

test('SKU informado é dimensão numérica, sem SUM/MAX; quantidade e receita permanecem somáveis',()=>{
  const ctx=connector(fixture('BI_Itens'));
  const specs=ctx.fields_('BI_Itens').build();
  const flag=specs.find(f=>f.id==='sku_informado');
  assert.equal(flag.role,'dimension');assert.equal(flag.type,'number');assert.equal(flag.aggregation,undefined);
  for(const id of ['quantidade','receita_item']){
    const field=specs.find(f=>f.id===id);assert.equal(field.role,'metric');assert.equal(field.aggregation,'sum');
  }
  assert.equal(specs.find(f=>f.id==='produto_codigo').type,'text');
  assert.equal(specs.find(f=>f.id==='atualizado_em').type,'text');
});
function skuFixture(){
  const f=fixture('BI_Itens');
  const row=(id,sku,day,flag,q,r)=>f.row(id,{item_chave:'item-'+id,produto_codigo:sku,data:'2026-11-'+day,sku_informado:flag,quantidade:q,receita_item:r});
  f.physical[hub]=[f.header,row(1,'001','01',1,2,10),row(2,'001','02',1,1,5),row(3,'sem-sku-a','02',0,1,2)];
  f.physical[extra]=[f.header,row(4,'001','03',1,3,15),row(5,'002','02',1,1,7),row(6,'sem-sku-b','03',0,1,1)];
  for(const [i,book] of [hub,extra].entries()){
    f.files[book].sheets.find(s=>s.properties.title==='BI_Itens').properties.gridProperties.rowCount=4;
    f.counts[i].rows=3;
  }
  f.state[2]=JSON.stringify({state:'READY',revision:'a',parts:f.counts});return f;
}
test('getData preserva grão de item e campos forFilterOnly para filtro anterior ao COUNT_DISTINCT',()=>{
  for(const [start,end,distinct,units,cents,unfiltered] of [['01','03',2,7,3700,4],['02','02',2,2,1200,3],['30','30',0,0,0,0]]){
    const ctx=connector(skuFixture());
    const request={configParams:{spreadsheetId:hub,segmento:'FARMA',tabela:'BI_Itens'},fields:[{name:'produto_codigo'},{name:'quantidade'},{name:'receita_item'},{name:'sku_informado',forFilterOnly:true}],dateRange:{startDate:'2026-11-'+start,endDate:'2026-11-'+end},dimensionsFilters:[[{fieldName:'sku_informado',type:'INCLUDE',operator:'EQUALS',values:['1']}]]};
    const result=ctx.getData(request), names=result.schema.map(s=>s.name), pos=name=>names.indexOf(name);
    assert.equal(result.filtersApplied,false);assert.ok(pos('sku_informado')>=0);
    const all=result.rows.map(r=>r.values), eligible=all.filter(r=>r[pos('sku_informado')]===1);
    // Modelo da regra de negócio, não uma emulação do otimizador do Data Studio.
    assert.equal(new Set(all.map(r=>r[pos('produto_codigo')])).size,unfiltered);
    assert.equal(new Set(eligible.map(r=>r[pos('produto_codigo')])).size,distinct);
    assert.equal(eligible.reduce((s,r)=>s+r[pos('quantidade')],0),units);
    assert.equal(eligible.reduce((s,r)=>s+Math.round(r[pos('receita_item')]*100),0),cents);
    const card=connector(skuFixture()).getData({...request,fields:[{name:'produto_codigo'},{name:'sku_informado',forFilterOnly:true}]});
    assert.equal(new Set(card.rows.filter(r=>r.values[1]===1).map(r=>r.values[0])).size,distinct);
    if(start==='01')assert.equal(card.rows.length,6); // Não colapsar itens ou somar contagens diárias/por parte.
  }
});
test('dimensão numérica de SKU continua validada mesmo ausente dos campos solicitados',()=>{
  const f=skuFixture();f.physical[hub][1][f.header.indexOf('sku_informado')]='1';
  assert.throws(()=>connector(f).getData({configParams:{spreadsheetId:hub,segmento:'FARMA',tabela:'BI_Itens'},fields:[{name:'produto_codigo'}]}),/numérico/);
});
