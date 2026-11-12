/* Contrato definitivo PostgreSQL. Somente leitura, sem dependência do Sheets. */
// Formato de exibição, sem converter o valor em texto "R$" nem alterar centavos.
// Não presumir BRL para gastos Meta: a moeda da conta precisa ser conferida.
var NexoDSCurrencyBRL={
  BI_Clientes_Vendas:['faturamento','faturamento_produtos','frete'],
  BI_Itens:['valor_unitario','receita_item'],
  BI_Historico_Resumo:['produtos','frete','faturamento'],
  BI_LTV_Clientes:['ltv_observado','ticket_medio']
};
function getAuthType() {var cc=DataStudioApp.createCommunityConnector();return cc.newAuthTypeResponse().setAuthType(cc.AuthType.NONE).build();}
function isAdminUser(){return false;}
function getConfig(request){
  var cc=DataStudioApp.createCommunityConnector(),config=cc.getConfig(),p=request&&request.configParams||{};
  var segment=config.newSelectSingle().setId('segmento').setName('Segmento').setIsDynamic(true);
  ['FARMA','PET'].forEach(function(v){segment.addOption(config.newOptionBuilder().setValue(v).setLabel(v));});
  var env=config.newSelectSingle().setId('ambiente').setName('Ambiente').setIsDynamic(true);
  ['homologacao','producao'].forEach(function(v){env.addOption(config.newOptionBuilder().setValue(v).setLabel(v));});
  var table=config.newSelectSingle().setId('tabela').setName('Tabela lógica').setIsDynamic(true);
  Object.keys(NexoDSSchemas).forEach(function(v){table.addOption(config.newOptionBuilder().setValue(v).setLabel(v));});
  var grain=config.newSelectSingle().setId('recorte_historico').setName('Resumo histórico: grão');
  ['MES','ANO','TOTAL','SEM_EMISSAO'].forEach(function(v){grain.addOption(config.newOptionBuilder().setValue(v).setLabel(v));});
  config.setIsSteppedConfig(!NexoDSSchemas[p.tabela]);
  config.setDateRangeRequired(!!(NexoDSSchemas[p.tabela]&&NexoDSSchemas[p.tabela].period)&&!(p.tabela==='BI_Historico_Resumo'&&['TOTAL','SEM_EMISSAO'].includes(p.recorte_historico)));
  return config.build();
}
function dsConfig_(p){
  if(!['FARMA','PET'].includes(p.segmento)||!['producao','homologacao'].includes(p.ambiente)||!NexoDSSchemas[p.tabela])throw new Error('DS_CONFIGURACAO_INVALIDA');
  var raw=PropertiesService.getScriptProperties().getProperty('NFDS_'+p.segmento+'_'+p.ambiente.toUpperCase());
  if(!raw)throw new Error('DS_CREDENCIAL_AUSENTE');
  var c=JSON.parse(raw);
  if(c.protocol!=='nexoflow_datastudio_1'||c.segment!==p.segmento||c.environment!==p.ambiente||!/^https:\/\/[a-z0-9.-]+\/?$/i.test(c.endpoint))throw new Error('DS_CONFIGURACAO_INVALIDA');
  ['api_token','access_client_id','access_client_secret'].forEach(function(k){if(typeof c[k]!=='string'||!c[k])throw new Error('DS_CREDENCIAL_AUSENTE');});
  return c;
}
function dsCall_(c,path,payload){
  var headers={'Authorization':'Bearer '+c.api_token,'CF-Access-Client-Id':c.access_client_id,'CF-Access-Client-Secret':c.access_client_secret};
  var started=Date.now();
  for(var attempt=0;attempt<3;attempt++){
    var options={headers:headers,muteHttpExceptions:true,followRedirects:false};
    if(payload!==undefined){options.method='post';options.contentType='application/json';options.payload=JSON.stringify(payload);}
    var response=UrlFetchApp.fetch(c.endpoint.replace(/\/$/,'')+path,options),status=response.getResponseCode();
    if(status===200){var result=JSON.parse(response.getContentText());return result;}
    if(status===409){
      var rejection={};try{rejection=JSON.parse(response.getContentText());}catch(ignored){}
      // Só códigos conhecidos, nunca texto livre/payload de erro do servidor.
      if(['DS_FILTRO_CORTA_RECORTE_USE_DETALHE','DS_COMPRADORES_EXIGEM_COMPETENCIA_OU_RECORTE_UNICO','DS_COMPRADORES_NAO_SOMAVEIS_ENTRE_MESES','DS_RESUMO_EXIGE_GRAO','DS_RESUMO_TOTAL_NAO_APLICA_DATA','DS_CONSULTA_EXCEDE_LIMITE_USE_RESUMO_OU_PERIODO','DS_RESPOSTA_EXCEDE_LIMITE_USE_RESUMO','DS_SEM_PUBLICACAO_CONFIRMADA'].includes(rejection.error))throw new Error(rejection.error);
    }
    if(![429,502,503,504].includes(status)||attempt===2||Date.now()-started>45000)throw new Error('DS_HTTP_'+status);
    Utilities.sleep(Math.min(4000,1000*Math.pow(2,attempt)));
  }
  throw new Error('DS_RESPOSTA_NAO_CONFIRMADA');
}
function dsVerify_(c){
  var info=dsCall_(c,'/v1/destino');
  var db=c.environment==='producao'?'nexoflow_datastudio':'nexoflow_datastudio_homologacao';
  if(info.protocol!=='nexoflow_datastudio_1'||info.target!==db+'.'+c.segment.toLowerCase()||info.segment!==c.segment||info.environment!==c.environment||info.schema_hash!==NexoDSSchemaHash)throw new Error('DS_CONTRATO_DESTINO_DIVERGENTE');
}
var NexoDSAbcLabels={periodo_rotulo:'Período',produto_nome:'Produto',classe_abc:'Classe',unidades:'Unidades',receita_produtos:'Receita de produtos',participacao_receita:'Participação (%)',participacao_acumulada:'Acumulada (%)',skus_distintos:'Produtos diferentes',faturamento_produtos:'Receita de produtos',participacao_top5_receita:'Top 5 na receita (%)',produtos_classe_a:'Produtos na classe A',produtos_classe_b:'Produtos na classe B',produtos_classe_c:'Produtos na classe C',receita_classe_a:'Receita classe A (%)',receita_classe_b:'Receita classe B (%)',receita_classe_c:'Receita classe C (%)',produto_a_nome:'Produto A',produto_b_nome:'Produto B',pedidos_juntos:'Pedidos juntos'};
function dsFields_(table){
  var cc=DataStudioApp.createCommunityConnector(),fields=cc.getFields(),spec=NexoDSSchemas[table];
  if(!spec)throw new Error('DS_TABELA_NAO_AUTORIZADA');
  spec.columns.forEach(function(name){
    var kind=spec.types[name],metric=kind==='number'&&!spec.dimensions.includes(name),field=metric?fields.newMetric():fields.newDimension();
    var abcKind=spec.abc_kinds&&spec.abc_kinds[name];
    var brl=(NexoDSCurrencyBRL[table]||[]).includes(name)||abcKind==='money';
    field.setId(name).setName(spec.abc_mode?(NexoDSAbcLabels[name]||name):((spec.labels||{})[name]||name)).setType(kind==='date'?cc.FieldType.YEAR_MONTH_DAY:kind==='number'?(brl?cc.FieldType.CURRENCY_BRL:cc.FieldType.NUMBER):cc.FieldType.TEXT);
    if(abcKind==='percent')field.setType(cc.FieldType.PERCENT);
    if(metric)field.setAggregation(abcKind?(['sum','money'].includes(abcKind)?cc.AggregationType.SUM:cc.AggregationType.MAX):(/taxa|pct|idade|ranking|ticket_medio|^clientes$/.test(name)?cc.AggregationType.MAX:cc.AggregationType.SUM));
  });
  if(table==='BI_Itens')fields.newMetric().setId('produtos_distintos_periodo').setName('Produtos distintos no período (SKU informado)').setType(cc.FieldType.NUMBER).setIsReaggregatable(false);
  return fields;
}
function getSchema(request){try{var c=dsConfig_(request.configParams);dsVerify_(c);return {schema:dsFields_(request.configParams.tabela).build()};}catch(e){return dsError_(e);}}
function dsError_(error){
  var code=/^DS_[A-Z0-9_]+$/.test(String(error.message))?error.message:'DS_LEITURA_NAO_CONFIRMADA';
  console.error(JSON.stringify({diagnostico:'datastudio_postgres_1',codigo:code}));
  DataStudioApp.createCommunityConnector().newUserError().setText(code+'. Nenhum total parcial foi retornado. Confira o diagnóstico e o período.').throwException();
}
function getData(request){try{
  var p=request.configParams,c=dsConfig_(p),spec=NexoDSSchemas[p.tabela];
  if(spec.abc_mode)return dsAbcData_(request,c,spec);
  var names=request.fields.map(function(f){return f.name;}),distinct=names.includes('produtos_distintos_periodo');

  if(names.some(function(n){return n!=='produtos_distintos_periodo'&&!spec.columns.includes(n);}))throw new Error('DS_CAMPOS_NAO_AUTORIZADOS');
  var range=request.dateRange||{},filters=[],applied=false,groups=request.dimensionsFilters||[];
  // All-or-none. ORs, exclusões e filtros não reconhecidos permanecem no Data Studio.
  var supported=groups.length&&groups.every(function(g){return Array.isArray(g)&&g.length===1&&g[0].type==='INCLUDE'&&['EQUALS','IN_LIST'].includes(g[0].operator)&&spec.columns.includes(g[0].fieldName)&&Array.isArray(g[0].values)&&g[0].values.length;});
  if(supported){filters=groups.map(function(g){return {field:g[0].fieldName,values:g[0].values};});applied=true;}
  if(distinct&&groups.length&&!supported)throw new Error('DS_FILTRO_AGREGACAO_NAO_SUPORTADO');
  if(applied)names=request.fields.filter(function(f){return !f.forFilterOnly;}).map(function(f){return f.name;});
  if(distinct&&(p.tabela!=='BI_Itens'||names.length!==1))throw new Error('DS_DISTINTOS_EXIGEM_CARTAO_EXCLUSIVO');
  if(distinct)filters.push({field:'sku_informado',values:['1']});
  if(p.tabela==='BI_Historico_Resumo'){
    if(!['MES','ANO','TOTAL','SEM_EMISSAO'].includes(p.recorte_historico))throw new Error('DS_RESUMO_EXIGE_GRAO');
    filters.push({field:'tipo_recorte',values:[p.recorte_historico]});
    if(['TOTAL','SEM_EMISSAO'].includes(p.recorte_historico))range={};
  }
  var payload={table:p.tabela,fields:distinct?['produto_codigo']:names,start:spec.period?(range.startDate||''):'',end:spec.period?(range.endDate||''):'',filters:filters,aggregation:distinct?{produto_codigo:'count_distinct'}:{}};
  if(spec.period&&!(p.tabela==='BI_Historico_Resumo'&&['TOTAL','SEM_EMISSAO'].includes(p.recorte_historico))&&(!payload.start||!payload.end)&&!(request.scriptParams&&request.scriptParams.sampleExtraction))throw new Error('DS_PERIODO_OBRIGATORIO');
  if(request.scriptParams&&request.scriptParams.sampleExtraction&&spec.period&&!payload.start){payload.start='2000-01-01';payload.end='2000-01-01';}
  var result=dsCall_(c,'/v1/consulta',payload);
  var expectedDB=c.environment==='producao'?'nexoflow_datastudio':'nexoflow_datastudio_homologacao';
  if(result.protocol!=='nexoflow_datastudio_1'||result.target!==expectedDB+'.'+c.segment.toLowerCase()||result.segment!==c.segment||result.environment!==c.environment||result.schema_hash!==NexoDSSchemaHash)throw new Error('DS_CONTRATO_DESTINO_DIVERGENTE');
  if(result.complete!==true||!Array.isArray(result.rows)||JSON.stringify(result.fields)!==JSON.stringify(payload.fields))throw new Error('DS_RESPOSTA_INCOMPLETA');
  var fields=dsFields_(p.tabela).forIds(names);
  var rows=result.rows.map(function(r){if(r.length!==payload.fields.length)throw new Error('DS_SCHEMA_DIVERGENTE');return {values:r.map(function(v,i){if(v===null||v==='')return null;var kind=distinct?'number':spec.types[names[i]];if(kind==='number'){var n=Number(v);if(!Number.isFinite(n))throw new Error('DS_NUMERO_INVALIDO');return n;}if(kind==='date'){if(!/^\d{4}-\d{2}-\d{2}$/.test(v))throw new Error('DS_DATA_INVALIDA');return v.replace(/-/g,'');}return String(v);})};});
  return {schema:fields.build(),rows:rows,filtersApplied:!!applied};
}catch(error){return dsError_(error);}}
if(typeof module!=='undefined')module.exports={getData:getData,dsCall:dsCall_,dsConfig:dsConfig_};

// Mesma regra ABC do conector legado, sobre duas projeções da mesma versão READY.
function dsAbcData_(request,c,spec){
  var started=Date.now(),range=request.dateRange||{},names=request.fields.map(function(f){return f.name;});
  if(!range.startDate||!range.endDate)throw new Error('DS_PERIODO_OBRIGATORIO');
  if(names.some(function(n){return !spec.columns.includes(n);}))throw new Error('DS_CAMPOS_NAO_AUTORIZADOS');
  var version=null;
  function load(table,fields){
    if(Date.now()-started>45000)throw new Error('DS_PRAZO_CONSULTA');
    var r=dsCall_(c,'/v1/consulta',{table:table,fields:fields,start:range.startDate,end:range.endDate,filters:[],aggregation:{}});
    var db=c.environment==='producao'?'nexoflow_datastudio':'nexoflow_datastudio_homologacao';
    if(r.protocol!==c.protocol||r.target!==db+'.'+c.segment.toLowerCase()||r.segment!==c.segment||r.environment!==c.environment||r.schema_hash!==NexoDSSchemaHash)throw new Error('DS_CONTRATO_DESTINO_DIVERGENTE');
    if(r.complete!==true||!Array.isArray(r.rows)||JSON.stringify(r.fields)!==JSON.stringify(fields)||!Number.isSafeInteger(r.version)||r.version<1)throw new Error('DS_RESPOSTA_INCOMPLETA');
    if(version!==null&&version!==r.version)throw new Error('DS_VERSAO_ALTERADA_DURANTE_LEITURA');
    version=r.version;
    return [fields.concat(['atualizado_em'])].concat(r.rows.map(function(row){
      if(row.length!==fields.length)throw new Error('DS_SCHEMA_DIVERGENTE');
      return row.concat(['READY:'+version]);
    }));
  }
  var items=load('BI_Itens',['item_chave','venda_chave','data','produto_codigo','produto_nome','categoria','quantidade','receita_item']);
  var orders=load('BI_Clientes_Vendas',['venda_chave','data','faturamento_produtos']);
  var result=NexoAbc.calculate(items,orders,range.startDate,range.endDate);
  if(!result.diagnostics.complete)throw new Error('DS_ABC_BASE_INCOMPLETA');
  if(Date.now()-started>45000)throw new Error('DS_PRAZO_CONSULTA');
  var responseSchema=dsFields_(request.configParams.tabela).forIds(names).build();
  names=responseSchema.map(function(f){return f.name;});
  return {schema:responseSchema,filtersApplied:false,
    rows:result[spec.abc_mode].map(function(row){return {values:names.map(function(n){
      // A versão READY comprova consistência; não inventa horário de atualização.
      if(n==='atualizado_em')return '';
      return spec.types[n]==='date'?row[n].replace(/-/g,''):row[n];
    })};})};
}
