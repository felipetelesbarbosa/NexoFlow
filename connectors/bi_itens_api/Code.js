/* Fonte privada FARMA: exclusivamente API de leitura, sem credenciais de publicação. */
var PG_READ_PROTOCOL='bi_itens_farma_leitura_1';
var PG_READ_TARGET='nexoflow_datastudio_piloto.farma.produtos_itens_datastudio';
var PG_DISTINCT='produtos_distintos_periodo';
var PG_READ_ERRORS=['BI_PG_CONSULTA_INVALIDA','BI_PG_DESTINO_DIVERGENTE','BI_PG_CAMPOS_INVALIDOS','BI_PG_PERIODO_INVALIDO','BI_PG_FILTRO_NAO_SUPORTADO','BI_PG_CARTAO_EXATO_SEPARADO','BI_PG_VISAO_SCHEMA_DIVERGENTE','BI_PG_LEITURA_PUBLICACAO_PENDENTE','BI_PG_VISAO_GRAO_INVALIDO','BI_PG_LEITURA_LIMITE','BI_PG_VISAO_LINHAGEM_NAO_CONFIRMADA'];
function getAuthType(){var cc=DataStudioApp.createCommunityConnector();return cc.newAuthTypeResponse().setAuthType(cc.AuthType.KEY).build();}
function isAdminUser(){return false;}
function resetAuth(){PropertiesService.getUserProperties().deleteProperty('NF_READ_TOKEN');}
function setCredentials(request){
  var token=String(request && request.key || '');
  if(token.length<32)return {errorCode:'INVALID_CREDENTIALS'};
  PropertiesService.getUserProperties().setProperty('NF_READ_TOKEN',token);
  if(isAuthValid())return {errorCode:'NONE'};
  resetAuth();return {errorCode:'INVALID_CREDENTIALS'};
}
function isAuthValid(){try{var r=pgCall_('get','/consulta/destino');return r.protocol===PG_READ_PROTOCOL && r.target===PG_READ_TARGET && r.segment==='FARMA';}catch(e){return false;}}
function getConfig(){
 var cc=DataStudioApp.createCommunityConnector(),config=cc.getConfig();
 config.newInfo().setId('escopo').setText('FarmaLíder — BI_Itens pela API privada. A fonte anterior permanece preservada até homologação.');
 config.setDateRangeRequired(true);return config.build();
}
function pgFields_(){
 var cc=DataStudioApp.createCommunityConnector(),fields=cc.getFields();
 PgItemSchema.forEach(function(s){var f=s[1]==='metric'?fields.newMetric():fields.newDimension();f.setId(s[0]).setName(s[0]).setType(s[1]==='date'?cc.FieldType.YEAR_MONTH_DAY:['metric','number'].includes(s[1])?cc.FieldType.NUMBER:cc.FieldType.TEXT);if(s[1]==='metric')f.setAggregation(cc.AggregationType.SUM);});
 fields.newMetric().setId(PG_DISTINCT).setName('Produtos distintos no período (SKU informado)').setType(cc.FieldType.NUMBER).setIsReaggregatable(false);
 return fields;
}
function getSchema(){
 try{var r=pgCall_('get','/consulta/destino');if(r.protocol!==PG_READ_PROTOCOL || r.target!==PG_READ_TARGET || r.segment!=='FARMA')throw Error('NF_PG_DESTINO');return {schema:pgFields_().build()};}catch(e){pgError_(e);}
}
function pgError_(error){
 var code=String(error && error.message || '');
 if(!/^(?:NF_PG_[A-Z_]+|BI_PG_[A-Z_]+)$/.test(code))code='NF_PG_LEITURA';
 DataStudioApp.createCommunityConnector().newUserError().setText('Fonte FARMA PostgreSQL indisponível ('+code+'). Nenhum total parcial foi retornado. Confira a API privada e o estado da publicação.').throwException();
}
function pgCall_(method,path,payload){
 var props=PropertiesService.getScriptProperties().getProperties();
 var endpoint=String(props.NF_READ_ENDPOINT || '').replace(/\/$/,'');
 var token=PropertiesService.getUserProperties().getProperty('NF_READ_TOKEN');
 if(!/^https:\/\/[A-Za-z0-9.-]+(?::443)?$/.test(endpoint) || !props.NF_ACCESS_CLIENT_ID || !props.NF_ACCESS_CLIENT_SECRET || !token)throw Error('NF_PG_CONFIGURACAO');
 var started=Date.now();
 for(var attempt=0;attempt<3;attempt++){
  var options={method:method,headers:{Authorization:'Bearer '+token,'CF-Access-Client-Id':props.NF_ACCESS_CLIENT_ID,'CF-Access-Client-Secret':props.NF_ACCESS_CLIENT_SECRET},muteHttpExceptions:true,followRedirects:false};
  if(payload!==undefined){options.contentType='application/json';options.payload=JSON.stringify(payload);}
  var response;
  try{response=UrlFetchApp.fetch(endpoint+path,options);}catch(e){if(attempt===2)throw Error('NF_PG_REDE');Utilities.sleep(1000*Math.pow(2,attempt));continue;}
  var status=response.getResponseCode();
  if([429,500,502,503,504].includes(status) && attempt<2 && Date.now()-started<180000){Utilities.sleep(1000*Math.pow(2,attempt));continue;}
  if(status!==200){
   var body;try{body=JSON.parse(response.getContentText());}catch(e){body={};}
   if(status===409 && PG_READ_ERRORS.includes(body.error))throw Error(body.error);
   throw Error(status===401 || status===403?'NF_PG_AUTENTICACAO':'NF_PG_SERVICO');
  }
  if(response.getContentText().length>12000000)throw Error('NF_PG_LIMITE');
  try{return JSON.parse(response.getContentText());}catch(e){throw Error('NF_PG_RESPOSTA');}
 }
 throw Error('NF_PG_SERVICO');
}
function getData(request){
 try{
  var all=pgFields_(),allowed=PgItemSchema.map(function(s){return s[0];}).concat([PG_DISTINCT]);
  if(!request || !Array.isArray(request.fields) || !request.fields.length || request.fields.some(function(f){return !allowed.includes(f.name);}))throw Error('NF_PG_CAMPOS');
  var period=request.dateRange;
  if(!period || !/^\d{4}-\d{2}-\d{2}$/.test(period.startDate) || !/^\d{4}-\d{2}-\d{2}$/.test(period.endDate))throw Error('NF_PG_PERIODO');
  var names=request.fields.filter(function(f){return f.forFilterOnly!==true;}).map(function(f){return f.name;});
  var selected=all.forIds(names);names=selected.asArray().map(function(f){return f.getId();});
  var r=pgCall_('post','/consulta/farma/bi-itens',{protocol:PG_READ_PROTOCOL,target:PG_READ_TARGET,segment:'FARMA',fields:names,start:period.startDate,end:period.endDate,filters:request.dimensionsFilters || []});
  if(r.protocol!==PG_READ_PROTOCOL || r.target!==PG_READ_TARGET || !['READY','LEGADO'].includes(r.state) || r.filtersApplied!==true || !Number.isSafeInteger(r.revision) || r.revision<0 || typeof r.cut_at!=='string' || !/^\d{4}-\d{2}-\d{2}T/.test(r.cut_at) || !Number.isFinite(Date.parse(r.cut_at)) || JSON.stringify(r.fields)!==JSON.stringify(names) || !Array.isArray(r.rows) || r.rows.length>200000)throw Error('NF_PG_CONTRATO');
  var types={};PgItemSchema.forEach(function(s){types[s[0]]=s[1];});types[PG_DISTINCT]='metric';
  var rows=r.rows.map(function(row){
   if(!row || !Array.isArray(row.values) || row.values.length!==names.length)throw Error('NF_PG_LINHA');
   return {values:row.values.map(function(value,i){
    if(value===null || value===undefined)throw Error('NF_PG_TIPO');
    var type=types[names[i]];
    if(type==='metric' || type==='number'){
     if(!['string','number'].includes(typeof value) || !/^-?\d+(?:\.\d+)?$/.test(String(value)) || !Number.isFinite(Number(value)))throw Error('NF_PG_TIPO');
     return Number(value);
    }
    if(typeof value!=='string' || type==='date' && !/^\d{8}$/.test(value))throw Error('NF_PG_TIPO');
    return value;
   })};
  });
  console.info(JSON.stringify({diagnostico:'NF_PG_CONSULTA',campos:names,inicio:period.startDate,fim:period.endDate,grupos_filtro:(request.dimensionsFilters || []).length,linhas:rows.length,revisao:r.revision,corte:r.cut_at}));
  return {schema:selected.build(),rows:rows,filtersApplied:true};
 }catch(e){pgError_(e);}
}
