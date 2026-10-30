const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const vm = require('node:vm');
const reader = require('../connectors/continuacoes/Tables.js');
const hash = text => crypto.createHash('sha256').update(text).digest('hex');
const hub = 'dashboard_test_1234567890', extra = 'continuacao_test_1234567890';
function fixture() {
  const headers = ['item_chave', 'valor'];
  const stamp = () => ({metadataKey:'nexoflow_continuation_origin_v1',metadataValue:JSON.stringify({hub,segment:'PET',role:'dashboard'}),visibility:'DOCUMENT',location:{spreadsheet:true}});
  const root = {sheets:[{properties:{sheetId:1,title:'NexoFlow_Continuidade',gridProperties:{rowCount:100,columnCount:3}}},{properties:{sheetId:2,title:'BI_Itens',gridProperties:{rowCount:2,columnCount:2}}}],developerMetadata:[stamp()]};
  const part = {sheets:[{properties:{sheetId:3,title:'BI_Itens',gridProperties:{rowCount:2,columnCount:2}}}],developerMetadata:[stamp()]};
  const index = [
    ['tipo','chave','valor'],
    ['config','principal',JSON.stringify({format:1,hub,enabled:true,segment:'PET',roots:{dashboard:hub,operacao:'op',historico:'hist'}})],
    ['arquivo',extra,JSON.stringify({role:'dashboard',number:1,source:hub})],
    ...[hub,extra].map((book_id,number)=>['parte',`BI_Itens#${number}`,JSON.stringify({title:'BI_Itens',number,book_id,sheet_id:number+2,width:2,schema:hash(reader.stable(headers))})]),
    ['estado','BI_Itens',JSON.stringify({state:'READY',revision:'a',parts:[{number:0,rows:1},{number:1,rows:1}]})]
  ];
  let reads = 0;
  const api = {meta:id=>structuredClone(id===hub?root:part), values:(id,range)=> {
    reads++;
    if(range.includes('NexoFlow_Continuidade')) return structuredClone(index);
    if(range.includes('A1:B1')) return [headers];
    return [[id===hub?'a':'b',id===hub?10:20]];
  }};
  return {root,part,index,headers,api,run:()=>reader.read(hub,['BI_Itens'],{api,hash,widths:{BI_Itens:2},segment:'PET'}),get reads(){return reads;}};
}
test('lê todas as partes e não duplica o cabeçalho',()=>{
  const f=fixture(); assert.deepEqual(f.run()[0],[f.headers,['a',10],['b',20]]);
});
test('recusa arquivo trocado por outro segmento',()=>{
  const f=fixture();f.part.developerMetadata[0].metadataValue=JSON.stringify({hub,segment:'FARMA',role:'dashboard'});assert.throws(f.run,/segmento/);
});
test('recusa lacuna, cabeçalho alterado e parte física repetida',()=>{
  for(const change of ['gap','schema','duplicate']) {
    const f=fixture(), p=JSON.parse(f.index[4][2]);
    if(change==='gap'){p.number=2;f.index[4][1]='BI_Itens#2';}
    if(change==='schema')p.schema='a'.repeat(64);
    if(change==='duplicate'){p.book_id=hub;p.sheet_id=2;}
    f.index[4][2]=JSON.stringify(p);assert.throws(f.run,/Continuações:/);
  }
});
test('não retorna tabela em atualização ou com contagem inconsistente',()=>{
  for(const state of [{state:'WRITING'}, {state:'READY',parts:[{number:0,rows:2},{number:1,rows:1}]}]) {
    const f=fixture();f.index[5][2]=JSON.stringify(state);assert.throws(f.run,/Continuações:/);
  }
});
test('detecta alteração do índice durante a leitura',()=>{
  const f=fixture(), read=f.api.values;
  f.api.values=(id,r)=>{if(r.includes('BI_Itens')&&id===extra)f.index[5][2]=JSON.stringify({state:'WRITING'});return read(id,r);};assert.throws(f.run,/mudou durante/);
});
test('conector ABC distribui a leitura pelo mesmo código',()=>{
  assert.equal(fs.readFileSync('connectors/looker_abc/Tables.js','utf8'),fs.readFileSync('connectors/continuacoes/Tables.js','utf8'));
});
test('getData real preserva campo solicitado, zero numérico e data Sheets',()=>{
  const specs=require('../connectors/continuacoes/Schemas.js');
  const ctx={NexoSchemas:specs,NexoTables:{read:()=>[[['data','pedidos','pedidos_confirmados_api','clientes_compradores','unidades_vendidas','faturamento_produtos','faturamento_frete','faturamento_total','faturamento','faturamento_confirmado_api','ticket_medio','taxa_confirmacao_pct','atualizado_em'],[46324,0,0,0,0,0,0,0,0,0,0,0,'agora']]],stable:reader.stable},Sheets:{},Utilities:{},Date,DataStudioApp:{createCommunityConnector:()=>({getFields:()=>fields,FieldType:{YEAR_MONTH_DAY:'date',NUMBER:'number',TEXT:'text'},AggregationType:{MAX:'max',SUM:'sum'},newUserError:()=>({setText:t=>({throwException:()=>{throw Error(t);}})})})}};
  let selected=[];
  const field=()=>({setId(x){this.id=x;return this;},setName(){return this;},setType(){return this;},setAggregation(){return this;},getId(){return this.id;}});
  const all=[];const fields={newMetric:()=>{const f=field();all.push(f);return f;},newDimension:()=>{const f=field();all.push(f);return f;},forIds:n=>{selected=all.filter(f=>n.includes(f.id));return {asArray:()=>selected,build:()=>selected.map(f=>({name:f.id}))};}};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync('connectors/continuacoes/Code.js','utf8'),ctx);
  const result=ctx.getData({configParams:{spreadsheetId:hub,segmento:'PET',tabela:'BI_Vendas'},fields:[{name:'data'},{name:'pedidos'}]});
  assert.equal(result.rows[0].values[1],0);assert.match(result.rows[0].values[0],/^\d{8}$/);assert.equal(result.filtersApplied,false);
});
test('filtro de período é aplicado antes do acúmulo e preserva contagens físicas',()=>{
  const f=fixture();
  const result=reader.read(hub,['BI_Itens'],{api:f.api,hash,widths:{BI_Itens:2},segment:'PET',accept:(_title,_header,row)=>row[1]>=20});
  assert.deepEqual(result[0],[f.headers,['b',20]]);
});
test('índice ativado no meio da leitura antiga impede resultado incompleto',()=>{
  const f=fixture(); let calls=0;
  const api={meta:id=>{const value=f.api.meta(id);if(id===hub && calls++===0)value.sheets=value.sheets.filter(s=>s.properties.title!=='NexoFlow_Continuidade');return value;},values:f.api.values};
  assert.throws(()=>reader.read(hub,['BI_Itens'],{api,hash,widths:{BI_Itens:2},segment:'PET',legacy:true}),/mudou durante/);
});
