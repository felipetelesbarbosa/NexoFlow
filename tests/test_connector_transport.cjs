const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const vm = require('node:vm');
const reader = require('../connectors/continuacoes/Tables.js');
const schemas = require('../connectors/continuacoes/Schemas.js');
const hub = 'dashboard_sintetico_500000';
const hash = s => crypto.createHash('sha256').update(s).digest('hex');
const secret = 'https://private.invalid/?token=segredo-ficticio nome-cliente-ficticio';
function error(code, message=secret) { return Object.assign(new Error(message), {code}); }
function fixture({dense=false, quota=Infinity, batch=true}={}) {
  const header=schemas.BI_Itens.map(s=>s[0]);
  const root={sheets:[{properties:{sheetId:7,title:'NexoFlow_Continuidade',gridProperties:{rowCount:100,columnCount:3}}},{properties:{sheetId:8,title:'BI_Itens',gridProperties:{rowCount:500000,columnCount:12}}}],developerMetadata:[{metadataKey:'nexoflow_continuation_origin_v1',metadataValue:JSON.stringify({hub,segment:'FARMA',role:'dashboard'}),visibility:'DOCUMENT',location:{spreadsheet:true}}]};
  const index=[['tipo','chave','valor'],['config','principal',JSON.stringify({format:1,hub,enabled:true,segment:'FARMA',roots:{dashboard:hub,operacao:'operations_synthetic_12345678',historico:'history_synthetic_1234567890'}})],['parte','BI_Itens#0',JSON.stringify({title:'BI_Itens',number:0,book_id:hub,sheet_id:8,width:12,schema:hash(reader.stable(header))})]];
  const clock={ms:0}, counts={calls:0,metadata:0,headers:0,manifest:0,bodies:0,quota:0,ranges:0}, sleeps=[], logs=[];
  let requests=[];
  function charge(kind) {
    counts.calls++;counts[kind]++;
    requests=requests.filter(t=>t>clock.ms-60000);
    if(requests.length>=quota){counts.quota++;throw error(429,'Quota exceeded '+secret);}
    requests.push(clock.ms);clock.ms+=10;
  }
  function row(n) { return schemas.BI_Itens.map(([name,type])=>name==='item_chave'?'item-'+n:name==='data'?(dense && n%1000?'2026-10-01':'2026-11-02'):name==='quantidade'?2:name==='receita_item'?1.25:name==='valor_unitario'?0.625:name==='atualizado_em'?'2026-11-11T00:00:00-03:00':type.startsWith('number')?1:'sintetico'); }
  function values(range) {
    if(range.includes('NexoFlow_Continuidade'))return structuredClone(index);
    if(/!A1:L1$/.test(range))return [structuredClone(header)];
    const [,lo,hi]=/!A(\d+):L(\d+)$/.exec(range), start=Number(lo), end=Number(hi);
    if(dense)return Array.from({length:end-start+1},(_,i)=>row(start+i));
    // Um fato depois de milhares de blocos vazios também precisa ser lido.
    const positions=[2,3,500000].filter(n=>n>=start && n<=end);
    if(!positions.length)return [];
    return Array.from({length:positions.at(-1)-start+1},(_,i)=>positions.includes(start+i)?row(start+i):[]);
  }
  const raw={meta:()=>{charge('metadata');return structuredClone(root);},values:(_id,range)=>{charge(range.includes('NexoFlow_Continuidade')?'manifest':/!A1:L1$/.test(range)?'headers':'bodies');return values(range);}};
  if(batch)raw.batchValues=(_id,ranges)=>{charge('bodies');counts.ranges+=ranges.length;return ranges.map(values);};
  const options={now:()=>clock.ms,startedAt:clock.ms,sleep:ms=>{sleeps.push(ms);clock.ms+=ms;},random:()=>0,warn:d=>logs.push(d)};
  function run(start='2026-11-01',end='2026-11-03', transport=true){
    const api=transport?reader.transport(raw,{...options,startedAt:clock.ms}):raw;
    const result=reader.read(hub,['BI_Itens'],{api,now:options.now,hash,schemas,widths:{BI_Itens:12},segment:'FARMA',accept:(_t,h,r)=>r[h.indexOf('data')]>=start && r[h.indexOf('data')]<=end});
    return {result,api};
  }
  return {root,index,header,raw,options,clock,counts,sleeps,logs,run,values};
}
test('500 mil linhas: caminho por GET excede cota de 60/min sem devolver resultado',()=>{
  const f=fixture({quota:60,batch:false});
  assert.throws(()=>f.run(undefined,undefined,false),e=>e.code===429);
  assert.equal(f.counts.calls,61);assert.equal(f.counts.quota,1);
});
test('500 mil linhas: 125 intervalos em 16 batchGet, com todas as cercas e sem perder fatos após vazios',()=>{
  const f=fixture({quota:60}), before=JSON.stringify(f.index), {result,api}=f.run();
  assert.equal(result[0].length,4);assert.equal(new Set(result[0].slice(1).map(r=>r[0])).size,3);
  assert.equal(f.counts.bodies,16);assert.equal(f.counts.ranges,125);assert.equal(f.counts.calls,22);
  assert.equal(api.stats().chamadas,22);assert.equal(f.counts.quota,0);assert.equal(f.counts.headers,2);
  assert.equal(f.counts.manifest,2);assert.equal(f.counts.metadata,2);assert.equal(JSON.stringify(f.index),before);
});
test('grade densa: 499.999 chaves validadas, filtro e centavos completos, sem amostragem',()=>{
  const f=fixture({dense:true}), {result}=f.run('2026-11-02','2026-11-02'), rows=result[0].slice(1);
  assert.equal(rows.length,500);assert.equal(rows.reduce((n,r)=>n+r[f.header.indexOf('quantidade')],0),1000);
  assert.equal(rows.reduce((n,r)=>n+Math.round(r[f.header.indexOf('receita_item')]*100),0),62500);
  assert.equal(f.counts.bodies,16);assert.equal(f.counts.ranges,125);
});
test('três recortes compartilham cota simulada: uma 429 recuperada com espera, inclusive período vazio',()=>{
  const f=fixture({quota:60});
  assert.equal(f.run().result[0].length,4);
  assert.equal(f.run('2026-11-02','2026-11-02').result[0].length,4);
  assert.equal(f.run('2026-11-30','2026-11-30').result[0].length,1);
  assert.equal(f.counts.quota,1);assert.deepEqual(f.sleeps,[65000]);assert.equal(f.counts.calls,67);
  assert.equal(f.logs[0].codigo,'NF_BI_COTA');assert.ok(!JSON.stringify(f.logs).includes(secret));
});
for(const code of [429,500,503,504])test(`falha ${code} depois de dados: repete só a leitura e não duplica linhas`,()=>{
  const f=fixture(), batch=f.raw.batchValues;let calls=0;
  f.raw.batchValues=(id,ranges)=>{if(++calls===2)throw error(code);return batch(id,ranges);};
  const {result,api}=f.run();assert.equal(result[0].length,4);assert.equal(api.stats().retentativas,1);
  assert.equal(f.sleeps.length,1);assert.ok(f.clock.ms<240000);
});
for(const code of [400,401,403,404])test(`HTTP ${code}: sem repetição cega nem totais parciais`,()=>{
  const f=fixture();f.raw.meta=()=>{throw error(code);};
  assert.throws(()=>f.run(),e=>{
    const d=reader.diagnostic(e);assert.equal(d.http,code);assert.equal(d.chamadas,1);assert.equal(d.retentativas,0);
    assert.equal(d.codigo,code===400?'NF_BI_REQUISICAO':code===404?'NF_BI_ORIGEM':'NF_BI_PERMISSAO');
    assert.ok(!JSON.stringify(d).includes(secret));return true;
  });
  assert.equal(f.sleeps.length,0);
});
test('403 com razão explícita de cota é distinguido de acesso negado',()=>{
  const f=fixture();let calls=0;f.raw.meta=()=>{if(++calls===1)throw error(403,'Rate limit exceeded '+secret);return structuredClone(f.root);};
  assert.equal(f.run().result[0].length,4);assert.equal(f.logs[0].codigo,'NF_BI_COTA');
});
test('timeout, Retry-After e prazo: não dormir nem emitir nova chamada após esgotar orçamento',()=>{
  const f=fixture();let calls=0;
  f.raw.meta=()=>{calls++;throw Object.assign(error(429),{headers:{'Retry-After':'180'}});};
  assert.throws(()=>f.run(),e=>e.nexoDiagnostic.codigo==='NF_BI_COTA');
  assert.equal(calls,2);assert.deepEqual(f.sleeps,[180000]);
  const g=fixture();g.raw.meta=()=>{g.clock.ms+=240001;return structuredClone(g.root);};
  assert.throws(()=>g.run(),e=>e.nexoDiagnostic.codigo==='NF_BI_PRAZO');assert.equal(g.counts.bodies,0);
  const h=fixture();let attempt=0;h.raw.meta=()=>{if(++attempt===1)throw Error('Request timed out '+secret);return structuredClone(h.root);};
  assert.equal(h.run().result[0].length,4);assert.equal(h.logs[0].codigo,'NF_BI_TIMEOUT');assert.deepEqual(h.sleeps,[2000]);
});
test('falha transitória persistente é limitada a três tentativas, com diagnóstico público sanitizado',()=>{
  const f=fixture();f.raw.batchValues=()=>{throw error(503);};
  assert.throws(()=>f.run(),e=>{
    assert.equal(e.nexoDiagnostic.chamadas,6);assert.equal(e.nexoDiagnostic.retentativas,2);
    const text=reader.diagnosticText(e);assert.match(text,/NF_BI_SERVICO; etapa=BLOCOS_DADOS/);assert.match(text,/Nenhum total parcial/);
    assert.ok(!text.includes(secret));return true;
  });assert.deepEqual(f.sleeps,[2000,4000]);
});
test('durante leitura em blocos: cabeçalho, manifesto, origem, trava e chave alterados bloqueiam tudo',()=>{
  for(const change of ['header','manifest','origin','lock','duplicate','missing']){
    const f=fixture(), batch=f.raw.batchValues;let altered=false;
    f.raw.batchValues=(id,ranges)=>{
      const result=batch(id,ranges);
      if(!altered){
        altered=true;
        if(change==='header')f.header[1]='alterado';
        if(change==='manifest')f.index.push(['estado','BI_Itens',JSON.stringify({state:'WRITING'})]);
        if(change==='origin')f.root.developerMetadata[0].metadataValue=JSON.stringify({hub,segment:'PET',role:'dashboard'});
        if(change==='lock')f.root.developerMetadata.push({metadataId:191126102,metadataKey:'nexoflow_continuation_writer_v1',metadataValue:JSON.stringify({owner:'a'.repeat(32),expires:f.clock.ms/1000+60}),visibility:'DOCUMENT',location:{spreadsheet:true}});
        if(change==='duplicate')result[0][1][0]=result[0][0][0];
        if(change==='missing')result.pop();
      }return result;
    };
    assert.throws(()=>f.run(),/Continuações:/,change);
  }
});
function connector(f) {
  const fields=[], messages=[];
  function field(){return {setId(id){this.id=id;return this;},setName(){return this;},setType(){return this;},setAggregation(){return this;},getId(){return this.id;}};}
  const builder={newMetric(){const x=field();fields.push(x);return x;},newDimension(){const x=field();fields.push(x);return x;},forIds(names){const all=fields.filter(x=>names.includes(x.id));return {asArray:()=>all,build:()=>all.map(x=>({name:x.id}))};}};
  const Values={get:(id,range)=>({values:f.raw.values(id,range)})};
  // Um batchGet = uma requisição, não uma para cada valueRange da resposta.
  Values.batchGet=(id,p)=>{const blocks=f.raw.batchValues(id,p.ranges);return {valueRanges:p.ranges.map((range,i)=>({range,majorDimension:'ROWS',values:blocks[i]}))};};
  class FakeDate extends Date { static now(){return f.clock.ms;} }
  const ctx={NexoSchemas:schemas,NexoTables:reader,Date:FakeDate,console:{error:s=>messages.push(s),warn:s=>messages.push(s)},Utilities:{sleep:f.options.sleep,DigestAlgorithm:{SHA_256:'sha256'},Charset:{UTF_8:'utf8'},computeDigest:(_a,text)=>[...crypto.createHash('sha256').update(text).digest()]},Sheets:{Spreadsheets:{get:id=>f.raw.meta(id),Values}},DataStudioApp:{createCommunityConnector:()=>({getFields:()=>builder,FieldType:{YEAR_MONTH_DAY:'date',NUMBER:'number',TEXT:'text'},AggregationType:{MAX:'max',SUM:'sum'},newUserError:()=>({setText:text=>({throwException:()=>{throw Error(text);}})})})}};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync('connectors/continuacoes/Code.js','utf8'),ctx);
  // Mantém o transporte real e injeta só relógio/espera, sem dormir nos testes.
  ctx.api_=()=>reader.googleApi(ctx.Sheets,{...f.options,startedAt:f.clock.ms,warn:d=>messages.push(JSON.stringify(d))});
  const request={configParams:{spreadsheetId:hub,segmento:'FARMA',tabela:'BI_Itens'},fields:[{name:'data'},{name:'quantidade'},{name:'receita_item'}],dateRange:{startDate:'2026-11-01',endDate:'2026-11-03'}};
  return {ctx,request,messages,Values};
}
test('getData real em grade de 500 mil linhas: batchGet com schema, filtros e tipos, API somente leitura',()=>{
  const f=fixture({quota:60}), {ctx,request}=connector(f), result=ctx.getData(request);
  assert.equal(result.rows.length,3);assert.deepEqual(Array.from(result.rows[0].values),['20261102',2,1.25]);
  assert.equal(f.counts.calls,22);assert.equal(f.counts.bodies,16);assert.equal(f.counts.quota,0);
  const one=connector(f);one.request.dateRange={startDate:'2026-11-02',endDate:'2026-11-02'};assert.equal(one.ctx.getData(one.request).rows.length,3);
  const empty=connector(f);empty.request.dateRange={startDate:'2026-11-30',endDate:'2026-11-30'};assert.equal(empty.ctx.getData(empty.request).rows.length,0);
  assert.equal(f.counts.calls,67);assert.equal(f.counts.quota,1);assert.deepEqual(f.sleeps,[65000]);
});
test('getData mostra categorias e etapa sem exceção Google, URLs ou registros, inclusive falha após primeiro bloco',()=>{
  for(const code of [403,429,500,504]){
    const f=fixture(), {ctx,request,messages}=connector(f), batch=f.raw.batchValues;let calls=0;
    f.raw.batchValues=(id,ranges)=>{if(++calls>1)throw error(code);return batch(id,ranges);};
    assert.throws(()=>ctx.getData(request),e=>{
      assert.match(e.message,/NF_BI_(PERMISSAO|COTA|SERVICO|TIMEOUT); etapa=BLOCOS_DADOS/);
      assert.match(e.message,/Nenhum total parcial/);assert.ok(!e.message.includes(secret));return true;
    });assert.ok(messages.length>0);assert.ok(!messages.join().includes(secret));
  }
});
test('batchGet incompleto, fora de ordem, linha excedente ou dimensão errada não produz sucesso',()=>{
  for(const kind of ['missing','range','dimension','type','excessRows']){
    const f=fixture(), {ctx,request,Values}=connector(f), original=Values.batchGet;
    Values.batchGet=(id,p)=>{const result=original(id,p);if(kind==='missing')result.valueRanges.pop();if(kind==='range')result.valueRanges[0].range=p.ranges[1];if(kind==='dimension')result.valueRanges[0].majorDimension='COLUMNS';if(kind==='type')result.valueRanges[0].values='invalido';if(kind==='excessRows')result.valueRanges[0].values=Array(4001).fill([]);return result;};
    assert.throws(()=>ctx.getData(request),/NF_BI_VALIDACAO/,kind);
  }
});

test('BI_Itens READY: chaves duplicadas entre partes são recusadas',()=>{
  const f=fixture(), child='dashboard_continuation_12345678', part=JSON.parse(f.index[2][2]);
  f.index.push(['arquivo',child,JSON.stringify({role:'dashboard',number:1,source:hub})]);
  f.index.push(['parte','BI_Itens#1',JSON.stringify({...part,number:1,book_id:child})]);
  f.index.push(['estado','BI_Itens',JSON.stringify({state:'READY',parts:[{number:0,rows:3},{number:1,rows:3}]})]);
  assert.throws(()=>f.run(),/chave de item/);
});
test('escopos dos dois projetos continuam estritamente de leitura',()=>{
  for(const project of ['continuacoes','looker_abc']){
    const manifest=JSON.parse(fs.readFileSync(`connectors/${project}/appsscript.json`,'utf8'));
    assert.deepEqual(manifest.oauthScopes,['https://www.googleapis.com/auth/spreadsheets.readonly']);
  }
});
test('getData ABC real usa batchGet, preserva representação de datas e confere as duas tabelas READY',()=>{
  const f=fixture(), ordersHeader=schemas.BI_Clientes_Vendas.map(s=>s[0]);
  const orders=[['sintetico','cliente-sintetico','sintetico','2026-11-02',1,3.75,0,3.75,'2026-11-11T00:00:00-03:00']];
  f.root.sheets.push({properties:{sheetId:9,title:'BI_Clientes_Vendas',gridProperties:{rowCount:2,columnCount:9}}});
  f.index.push(['parte','BI_Clientes_Vendas#0',JSON.stringify({title:'BI_Clientes_Vendas',number:0,book_id:hub,sheet_id:9,width:9,schema:hash(reader.stable(ordersHeader))})]);
  f.index.push(['estado','BI_Itens',JSON.stringify({state:'READY',parts:[{number:0,rows:3}]})]);
  f.index.push(['estado','BI_Clientes_Vendas',JSON.stringify({state:'READY',parts:[{number:0,rows:1}]})]);
  const previousValues=f.raw.values, previousBatch=f.raw.batchValues;
  f.raw.values=(id,range)=>range.includes('BI_Clientes_Vendas')?range.includes('A1:I1')?[ordersHeader]:orders:previousValues(id,range);
  f.raw.batchValues=(id,ranges)=>ranges[0].includes('BI_Clientes_Vendas')?[orders]:previousBatch(id,ranges);
  const {ctx,Values,messages}=connector(f), get=Values.get, batchGet=Values.batchGet;
  Values.get=(id,range,p)=>{assert.equal(p.dateTimeRenderOption,'FORMATTED_STRING');return get(id,range,p);};
  Values.batchGet=(id,p)=>{assert.equal(p.dateTimeRenderOption,'FORMATTED_STRING');return batchGet(id,p);};
  ctx.NexoTables={...reader,googleApi:(s,options)=>reader.googleApi(s,{...options,now:f.options.now,random:()=>0})};
  ctx.NexoAbc=require('../connectors/looker_abc/AbcCore.js');
  vm.runInContext(fs.readFileSync('connectors/looker_abc/Code.js','utf8'),ctx);
  const request={configParams:{spreadsheetId:hub,tabela:'resumo'},fields:[{name:'skus_distintos'},{name:'faturamento_produtos'}],dateRange:{startDate:'2026-11-01',endDate:'2026-11-03'}};
  const result=ctx.getData(request);
  assert.equal(result.rows.length,1);assert.deepEqual(Array.from(result.rows[0].values),[1,3.75]);
  f.raw.meta=()=>{throw error(403);};
  assert.throws(()=>ctx.getData(request),/NF_BI_PERMISSAO; etapa=METADADOS/);
  assert.ok(!messages.join().includes(secret));
});
