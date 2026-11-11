const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const schemas = require('../connectors/continuacoes/Schemas.js');
const paths = ['../connectors/continuacoes/Tables.js','../connectors/looker_abc/Tables.js'];
const hub = 'dashboard_legado_1234567890';
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
function fixture(reader, segment='FARMA') {
  const specs=schemas.BI_Itens, header=specs.map(s=>s[0]);
  const row=specs.map(([name,type])=>type==='number'?2:name==='data'?'2026-11-02':name==='item_chave'?'item-sintetico':'sintetico');
  const rows=[row];
  const root={sheets:[{properties:{sheetId:7,title:'NexoFlow_Continuidade',gridProperties:{rowCount:100,columnCount:3}}},{properties:{sheetId:8,title:'BI_Itens',gridProperties:{rowCount:2,columnCount:12}}}],developerMetadata:[{metadataKey:'nexoflow_continuation_origin_v1',metadataValue:JSON.stringify({hub,segment,role:'dashboard'}),visibility:'DOCUMENT',location:{spreadsheet:true}}]};
  const index=[['tipo','chave','valor'],['config','principal',JSON.stringify({format:1,hub,enabled:true,segment,roots:{dashboard:hub,operacao:'operations_fixture_1234567890',historico:'history_fixture_1234567890'},connector_tables:[]})],['parte','BI_Itens#0',JSON.stringify({title:'BI_Itens',number:0,book_id:hub,sheet_id:8,width:12,schema:hash(reader.stable(header))})]];
  const api={meta:()=>structuredClone(root),values:(_id,range)=>structuredClone(range.includes('NexoFlow_Continuidade')?index:range.includes('A1:L1')?[header]:rows)};
  const run=()=>reader.read(hub,['BI_Itens'],{api,hash,schemas,widths:{BI_Itens:12},segment});
  return {root,index,rows,header,api,run};
}
for(const path of paths){
 const reader=require(path);
 test(path+': lê somente legado principal estável sem fabricar READY',()=>{
   for(const segment of ['FARMA','PET']){
     const f=fixture(reader,segment), before=JSON.stringify(f.index);
     assert.deepEqual(f.run()[0],[f.header,...f.rows]);
     assert.equal(JSON.stringify(f.index),before);
     assert.equal(f.index.some(r=>r[0]==='estado'),false);
   }
 });
 test(path+': WRITING, partes extras, origem trocada e intenção continuam bloqueados',()=>{
   for(const scenario of ['writing','extra','origin','intent','schema','segment','ready']){
     const f=fixture(reader);
     if(scenario==='writing')f.index.push(['estado','BI_Itens',JSON.stringify({state:'WRITING'})]);
     if(scenario==='extra')f.index.push(['parte','BI_Itens#1',JSON.stringify({...JSON.parse(f.index[2][2]),number:1})]);
     if(scenario==='origin')f.index[2][2]=JSON.stringify({...JSON.parse(f.index[2][2]),book_id:'foreign_fixture_1234567890'});
     if(scenario==='intent')f.index.push(['criacao','BI_Itens#1',JSON.stringify({state:'PREPARED'})]);
     if(scenario==='segment')f.root.developerMetadata[0].metadataValue=JSON.stringify({hub,segment:'PET',role:'dashboard'});
     if(scenario==='ready')f.index.push(['estado','BI_Itens',JSON.stringify({state:'READY',parts:[]})]);
     if(scenario==='schema')f.index[2][2]=JSON.stringify({...JSON.parse(f.index[2][2]),schema:'f'.repeat(64)});
     assert.throws(f.run,/Continuações:/,scenario);
   }
 });
 test(path+': bloqueia gravador ativo ou iniciado durante a leitura',()=>{
   const marker={metadataId:191126102,metadataKey:'nexoflow_continuation_writer_v1',metadataValue:JSON.stringify({owner:'a'.repeat(32),expires:Date.now()/1000+300}),visibility:'DOCUMENT',location:{spreadsheet:true}};
   for(const during of [false,true]){
     const f=fixture(reader), original=f.api.values;
     if(!during)f.root.developerMetadata.push(marker);
     else f.api.values=(id,range)=>{const result=original(id,range);if(range.includes('A2:'))f.root.developerMetadata.push(marker);return result;};
     assert.throws(f.run,/gravador|carga ativa/);
   }
 });
 test(path+': conferência inicial não autoriza cruzamento ABC ainda sem READY',()=>{
   const f=fixture(reader);
   assert.throws(()=>reader.read(hub,['BI_Itens','BI_Clientes_Vendas'],{api:f.api,hash,schemas,widths:{BI_Itens:12,BI_Clientes_Vendas:9},segment:'FARMA'}),/sem confirmação/);
 });
 test(path+': recusa chaves duplicadas e mutação de manifesto',()=>{
   const f=fixture(reader);f.rows.push([...f.rows[0]]);f.root.sheets[1].properties.gridProperties.rowCount=3;
   assert.throws(f.run,/chave/);
   const malformed=fixture(reader);malformed.rows[0][malformed.header.indexOf('quantidade')]='2';
   assert.throws(malformed.run,/numérico/);
   const changed=fixture(reader), original=changed.api.values;
   changed.api.values=(id,range)=>{const result=original(id,range);if(range.includes('A2:'))changed.index.push(['estado','BI_Itens',JSON.stringify({state:'WRITING'})]);return result;};
   assert.throws(changed.run,/mudou durante/);
 });
}
test('leitor de continuações e ABC continuam idênticos',()=>assert.equal(fs.readFileSync('connectors/continuacoes/Tables.js','utf8'),fs.readFileSync('connectors/looker_abc/Tables.js','utf8')));
test('getData real confere recortes e tipos com a raiz legada, sem estado fabricado',()=>{
 const vm=require('node:vm'), reader=require(paths[0]);
 const f=fixture(reader), fields=[];
 function field(){return {id:'',setId(id){this.id=id;return this;},setName(){return this;},setType(){return this;},setAggregation(){return this;},getId(){return this.id;}};}
 const builder={newMetric(){const x=field();fields.push(x);return x;},newDimension(){const x=field();fields.push(x);return x;},forIds(names){const selected=fields.filter(x=>names.includes(x.id));return {asArray:()=>selected,build:()=>selected.map(x=>({name:x.id}))};}};
 const ctx={NexoSchemas:schemas,NexoTables:reader,Date,Utilities:{DigestAlgorithm:{SHA_256:'sha256'},Charset:{UTF_8:'utf8'},computeDigest:(_algorithm,text)=>[...crypto.createHash('sha256').update(text).digest()]},Sheets:{Spreadsheets:{get:id=>f.api.meta(id),Values:{get:(id,range)=>({values:f.api.values(id,range)})}}},DataStudioApp:{createCommunityConnector:()=>({getFields:()=>builder,FieldType:{YEAR_MONTH_DAY:'date',NUMBER:'number',TEXT:'text'},AggregationType:{MAX:'max',SUM:'sum'},newUserError:()=>({setText:text=>({throwException:()=>{throw Error(text);}})})})}};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync('connectors/continuacoes/Code.js','utf8'),ctx);
 const before=JSON.stringify(f.index);
 for(const [start,end,count] of [['2026-11-01','2026-11-03',1],['2026-11-02','2026-11-02',1],['2026-11-30','2026-11-30',0]]){
   fields.length=0;
   const result=ctx.getData({configParams:{spreadsheetId:hub,segmento:'FARMA',tabela:'BI_Itens'},fields:[{name:'data'},{name:'quantidade'},{name:'receita_item'}],dateRange:{startDate:start,endDate:end}});
   assert.equal(result.rows.length,count);
   if(count)assert.deepEqual(Array.from(result.rows[0].values),['20261102',2,2]);
 }
 assert.equal(JSON.stringify(f.index),before);
});
