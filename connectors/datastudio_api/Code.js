/* Contrato definitivo PostgreSQL. Somente leitura, sem dependência do Sheets. */
// Formato de exibição, sem converter o valor em texto "R$" nem alterar centavos.
// Não presumir BRL para gastos Meta: a moeda da conta precisa ser conferida.
var NexoDSCurrencyBRL={
  BI_Clientes_Vendas:['faturamento','faturamento_produtos','frete'],
  BI_Itens:['valor_unitario','receita_item'],
  BI_Historico_Resumo:['produtos','frete','faturamento'],
  BI_LTV_Clientes:['ltv_observado','ticket_medio'],
  Pedidos_Atribuiveis_Meta:['pedido_faturamento_total']
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
  Object.keys(NexoDSSchemas).filter(function(v){return !NexoDSSchemas[v].segment || NexoDSSchemas[v].segment===p.segmento;}).forEach(function(v){table.addOption(config.newOptionBuilder().setValue(v).setLabel(v));});
  if (!['Compradores_Operacionais', 'Pedidos_Atribuiveis_Meta', 'Contatos_Atribuicao_Meta', 'Produtos_Mais_Vendidos', 'BI_Publico_Resumo','Anuncios_Veiculados_FARMA','Resumo_Anuncios_Veiculados_FARMA'].includes(p.tabela)) {
    var query=config.newSelectSingle().setId('modo_consulta').setName('Leitura: detalhe ou somas homologadas');
    ['detalhe','somas'].forEach(function(v){query.addOption(config.newOptionBuilder().setValue(v).setLabel(v));});
  }
  if(p.tabela==='ABC_juntos'){
    var scope=config.newSelectSingle().setId('pares_escopo').setName('Compras juntas: universo completo ou Top explícito');
    ['COMPLETO','TOP'].forEach(function(v){scope.addOption(config.newOptionBuilder().setValue(v).setLabel(v));});
    var top=config.newSelectSingle().setId('pares_limite').setName('Top de pares (exibir o escopo no título do gráfico)');
    ['10','25','50','100','250','500','1000'].forEach(function(v){top.addOption(config.newOptionBuilder().setValue(v).setLabel(v));});
  }
  if(p.tabela!=='Produtos_Mais_Vendidos'){
    var grain=config.newSelectSingle().setId('recorte_historico').setName('Resumo histórico: grão');
    ['MES','ANO','TOTAL','SEM_EMISSAO'].forEach(function(v){grain.addOption(config.newOptionBuilder().setValue(v).setLabel(v));});
  }
  config.setIsSteppedConfig(!NexoDSSchemas[p.tabela]);
  config.setDateRangeRequired(!!(NexoDSSchemas[p.tabela]&&NexoDSSchemas[p.tabela].period)&&!(p.tabela==='BI_Historico_Resumo'&&['TOTAL','SEM_EMISSAO'].includes(p.recorte_historico)));
  return config.build();
}
function dsConfig_(p){
  if (['Pedidos_Atribuiveis_Meta', 'Contatos_Atribuicao_Meta'].includes(p.tabela) && p.segmento !== 'FARMA') throw new Error('DS_CONFIGURACAO_INVALIDA');
  if(!['FARMA','PET'].includes(p.segmento)||!['producao','homologacao'].includes(p.ambiente)||!NexoDSSchemas[p.tabela])throw new Error('DS_CONFIGURACAO_INVALIDA');
  if(p.tabela==='Produtos_Mais_Vendidos' && p.segmento!=='FARMA')throw new Error('DS_TABELA_NAO_AUTORIZADA');
  if(NexoDSSchemas[p.tabela].segment && NexoDSSchemas[p.tabela].segment!==p.segmento)throw new Error('DS_INSIGHTS_SEGMENTO');
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
    var failure = 'DS_HTTP_' + status;
    if(status===409 || status===503){
      var rejection={};try{rejection=JSON.parse(response.getContentText()) || {};}catch(ignored){}
      if(status===503 && rejection.error==='DS_PERMISSAO')throw new Error('DS_PERMISSAO');
      if(status===503 && rejection.error==='DS_BANCO_INDISPONIVEL')failure='DS_BANCO_INDISPONIVEL';
      // Só códigos conhecidos, nunca texto livre/payload de erro do servidor.
      if(status===409 && path==='/v1/produtos' && ['DS_PRODUTOS_BASE_INVALIDA','DS_FILTRO_INVALIDO','DS_REVISAO_ALTERADA','DS_CAMPOS_NAO_AUTORIZADOS','DS_PERIODO_INVALIDO'].includes(rejection.error))throw new Error(rejection.error);
      if(status===409 && ['DS_FILTRO_CORTA_RECORTE_USE_DETALHE','DS_COMPRADORES_EXIGEM_COMPETENCIA_OU_RECORTE_UNICO','DS_COMPRADORES_NAO_SOMAVEIS_ENTRE_MESES','DS_RESUMO_EXIGE_GRAO','DS_RESUMO_TOTAL_NAO_APLICA_DATA','DS_CONSULTA_EXCEDE_LIMITE_USE_RESUMO_OU_PERIODO','DS_RESPOSTA_EXCEDE_LIMITE_USE_RESUMO','DS_SEM_PUBLICACAO_CONFIRMADA','DS_ABC_BASE_INCOMPLETA','DS_INSIGHTS_COBERTURA_INCOMPLETA','DS_INSIGHTS_VISAO_AUSENTE','DS_PUBLICO_VISAO_AUSENTE','DS_DESTINOS_VISAO_AUSENTE','DS_ANUNCIOS_GRAO_AMBIGUO','DS_DESTINOS_CONTAGEM_DIVERGENTE','DS_INSIGHTS_PERIODO_OBRIGATORIO','DS_ABC_PEDIDO_EXCEDE_LIMITE_PARES','DS_ABC_PRECISAO_EXCEDIDA','DS_BI_PEDIDO_OPERACIONAL_AMBIGUO','DS_CONSULTA_TEMPO_LIMITE'].includes(rejection.error))throw new Error(rejection.error);
    }
    if(![429,502,503,504].includes(status)||attempt===2||Date.now()-started>45000)throw new Error(failure);
    Utilities.sleep(Math.min(4000,1000*Math.pow(2,attempt)));
  }
  throw new Error('DS_RESPOSTA_NAO_CONFIRMADA');
}
function dsVerify_(c){
  dsCheckDestination_(c,dsCall_(c,'/v1/destino'));
}
function dsCheckDestination_(c,info){
  var db=c.environment==='producao'?'nexoflow_datastudio':'nexoflow_datastudio_homologacao';
  if(!info||info.protocol!=='nexoflow_datastudio_1'||info.target!==db+'.'+c.segment.toLowerCase()||info.segment!==c.segment||info.environment!==c.environment||info.schema_hash!==NexoDSSchemaHash)throw new Error('DS_CONTRATO_DESTINO_DIVERGENTE');
}
var NexoDSAbcLabels={periodo_rotulo:'Período',produto_nome:'Produto',classe_abc:'Classe',unidades:'Unidades',receita_produtos:'Receita de produtos',participacao_receita:'Participação (%)',participacao_acumulada:'Acumulada (%)',skus_distintos:'Produtos diferentes',faturamento_produtos:'Receita de produtos',participacao_top5_receita:'Top 5 na receita (%)',produtos_classe_a:'Produtos na classe A',produtos_classe_b:'Produtos na classe B',produtos_classe_c:'Produtos na classe C',receita_classe_a:'Receita classe A (%)',receita_classe_b:'Receita classe B (%)',receita_classe_c:'Receita classe C (%)',produto_a_nome:'Produto A',produto_b_nome:'Produto B',pedidos_juntos:'Pedidos juntos'};
var NexoDSAdsLabels={
  data:'Data', anuncio_id:'ID do anúncio', campanha_nome:'Campanha', anuncios:'Anúncios veiculados',
  investimento_original:'Investimento em anúncios', conversas_meta:'Conversas iniciadas nos anúncios',
  conversas_meta_informadas:'Conversas informadas pela Meta',
  pedidos_apos_conversa_7d:'Pedidos em até 7 dias (outro atendimento)',
  receita_apos_conversa_7d:'Receita dos pedidos em até 7 dias',
  cpa_conversa_anuncio:'Custo por pedido na conversa do anúncio',
  roas_conversa_anuncio:'Retorno sobre anúncios na conversa original',
  dias_comerciais_parciais:'Registros de anúncios com dados parciais'
};
var NexoDSFarmaLabels={
  Anuncios_Veiculados_FARMA:NexoDSAdsLabels,
  Resumo_Anuncios_Veiculados_FARMA:NexoDSAdsLabels,
  BI_Clientes_Vendas:{cliente:'Nome do cliente',data:'Data da compra',pedidos:'Pedidos válidos',faturamento:'Receita gerada',faturamento_produtos:'Receita de produtos',frete:'Frete'},
  BI_Clientes:{cliente:'Nome do cliente',pedidos_identificados:'Pedidos identificados',faturamento_identificado:'Receita identificada',ultima_compra_identificada:'Última compra identificada'},
  BI_LTV_Clientes:{pedidos:'Pedidos válidos no histórico',ltv_observado:'Receita histórica por cliente',ticket_medio:'Valor médio por pedido',primeira_compra:'Primeira compra',ultima_compra:'Última compra',cobertura:'Cobertura do histórico'},
  Base_Contatos:{nome:'Nome do contato',farmalider_cliente_nome:'Nome do cliente no cadastro FarmaLíder',pedido_data:'Data do pedido',pedido_status_nome:'Situação do pedido'}
};
function dsFields_(table,segment){
  var cc=DataStudioApp.createCommunityConnector(),fields=cc.getFields(),spec=NexoDSSchemas[table];
  if(!spec)throw new Error('DS_TABELA_NAO_AUTORIZADA');
  var friendly=segment==='FARMA' && NexoDSFarmaLabels[table] || {};
  spec.columns.forEach(function(name){
    var kind=spec.types[name],metric=kind==='number'&&!spec.dimensions.includes(name),field=metric?fields.newMetric():fields.newDimension();
    var metricKind=(spec.abc_kinds||spec.metric_kinds||{})[name];
    var brl=(NexoDSCurrencyBRL[table]||[]).includes(name)||['money','money_max'].includes(metricKind);
    var label=friendly[name]||(spec.abc_mode?NexoDSAbcLabels[name]:(spec.labels||{})[name])||name;
    field.setId(name).setName(label).setType(kind==='date'?cc.FieldType.YEAR_MONTH_DAY:kind==='number'?(brl?cc.FieldType.CURRENCY_BRL:cc.FieldType.NUMBER):cc.FieldType.TEXT);
    if(metricKind==='percent')field.setType(cc.FieldType.PERCENT);
    if(metric)field.setAggregation(metricKind?(['sum','money'].includes(metricKind)?cc.AggregationType.SUM:cc.AggregationType.MAX):(/taxa|pct|idade|ranking|ticket_medio|^clientes$/.test(name)?cc.AggregationType.MAX:cc.AggregationType.SUM));
  });
  if(table==='BI_Itens')fields.newMetric().setId('produtos_distintos_periodo').setName('Produtos distintos no período (SKU informado)').setType(cc.FieldType.NUMBER).setIsReaggregatable(false);
  return fields;
}
function getSchema(request){try{var c=dsConfig_(request.configParams);dsVerify_(c);return {schema:dsFields_(request.configParams.tabela,c.segment).build()};}catch(e){return dsError_(e,request&&request.configParams);}}
function dsError_(error,params){
  var code=/^DS_[A-Z0-9_]+$/.test(String(error.message))?error.message:'DS_LEITURA_NAO_CONFIRMADA';
  console.error(JSON.stringify({diagnostico:'datastudio_postgres_1',codigo:code}));
  var message=code+'. Nenhum total parcial foi retornado. Confira o diagnóstico e o período.';
  if(params && params.segmento==='FARMA'){
    if(['DS_PRAZO_CONSULTA','DS_CONSULTA_TEMPO_LIMITE'].includes(code)){
      message='A consulta demorou mais que o previsto. Tente atualizar o relatório.';
    }else if(['DS_PERIODO_OBRIGATORIO','DS_INSIGHTS_PERIODO_OBRIGATORIO','DS_PERIODO_INVALIDO'].includes(code)){
      message='Selecione um período válido.';
    }else if(['DS_CONSULTA_EXCEDE_LIMITE_USE_RESUMO_OU_PERIODO','DS_RESPOSTA_EXCEDE_LIMITE_USE_RESUMO'].includes(code)){
      message='O período selecionado tem dados demais para este gráfico. Selecione um período menor.';
    }else if(['DS_SEM_PUBLICACAO_CONFIRMADA','DS_ABC_BASE_INCOMPLETA','DS_INSIGHTS_COBERTURA_INCOMPLETA'].includes(code)){
      message='Sem dados suficientes para o período selecionado.';
    }else{
      message='Falha ao carregar os dados. Tente atualizar o relatório.';
    }
  }
  DataStudioApp.createCommunityConnector().newUserError().setText(message).throwException();
}
function getData(request){try{
  var p=request.configParams,c=dsConfig_(p),spec=NexoDSSchemas[p.tabela];
  var publicTable=['BI_Publico','BI_Publico_Resumo','Compradores_Operacionais'].includes(p.tabela);
  var publicStarted=publicTable?Date.now():0;
  if(spec.product_modes)return dsProductsData_(request,c,spec);
  if(spec.abc_mode)return dsAbcData_(request,c,spec);
  if(p.tabela==='Pedidos_Atribuiveis_Meta'||p.tabela==='Contatos_Atribuicao_Meta')return dsAdData_(request,c,spec);
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
  names=dsFields_(p.tabela,c.segment).forIds(names).build().map(function(f){return f.name;});
  var buyers = p.tabela === 'Compradores_Operacionais';
  var sumAggregation=buyers||p.tabela==='BI_Publico_Resumo' ? {} : dsSums_(p,spec,names,groups,supported,distinct);
  var payload={table:p.tabela,fields:distinct?['produto_codigo']:names,start:spec.period?(range.startDate||''):'',end:spec.period?(range.endDate||''):'',filters:filters,aggregation:distinct?{produto_codigo:'count_distinct'}:sumAggregation};
  if (buyers) {
    // Agrupa no PostgreSQL antes dos limites de linhas e bytes. A coluna
    // contada é a chave obrigatória do pedido; o vínculo continua pelo UUID.
    payload.table = 'Pedidos_FarmaLider';
    payload.fields = ['contact_uuid', 'calc_gf73fvq57d', 'pedido_chave'];
    payload.filters.push({field: 'calc_gf73fvq57d', values: ['Sim']});
    payload.aggregation = {pedido_chave: 'count'};
  }
  if(spec.period&&!(p.tabela==='BI_Historico_Resumo'&&['TOTAL','SEM_EMISSAO'].includes(p.recorte_historico))&&(!payload.start||!payload.end)&&!(request.scriptParams&&request.scriptParams.sampleExtraction))throw new Error('DS_PERIODO_OBRIGATORIO');
  // Uma amostra de schema sem período não escolhe nem inventa um dia da Weni.
  if(p.tabela==='BI_Weni_Conversas_Diarias'&&request.scriptParams&&request.scriptParams.sampleExtraction&&!payload.start){
    dsVerify_(c);
    return {schema:dsFields_(p.tabela,c.segment).forIds(names).build(),rows:[],filtersApplied:false};
  }
  if(request.scriptParams&&request.scriptParams.sampleExtraction&&spec.period&&!payload.start){payload.start='2000-01-01';payload.end='2000-01-01';}
  var result=dsCheckedQuery_(c,payload);
  var publicFetched=publicTable?Date.now():0;
  var fields=dsFields_(p.tabela,c.segment).forIds(names);
  var data = buyers ? dsBuyerRows_(result.rows, payload.fields, names) : result.rows;
  var rows=dsFormatRows_(data,names,spec,distinct);
  if(publicTable&&typeof console.info==='function'){
    console.info(JSON.stringify({
      diagnostico:'publico_farma',tabela:p.tabela,versao:result.version,
      linhas:rows.length,campos:names.length,filtros:groups.length,
      filtros_aplicados:!!applied,api_ms:publicFetched-publicStarted,
      formato_ms:Date.now()-publicFetched
    }));
  }
  return {schema:fields.build(),rows:rows,filtersApplied:!!applied};
}catch(error){return dsError_(error,request&&request.configParams);}}
if(typeof module!=='undefined')module.exports={getData:getData,dsCall:dsCall_,dsConfig:dsConfig_};

function dsCheckedQuery_(c,payload){
  var result=dsCall_(c,'/v1/consulta',payload);
  var expectedDB=c.environment==='producao'?'nexoflow_datastudio':'nexoflow_datastudio_homologacao';
  if(result.protocol!=='nexoflow_datastudio_1'||result.target!==expectedDB+'.'+c.segment.toLowerCase()||result.segment!==c.segment||result.environment!==c.environment||result.schema_hash!==NexoDSSchemaHash)throw new Error('DS_CONTRATO_DESTINO_DIVERGENTE');
  if(!Number.isSafeInteger(result.version)||result.version<1||result.complete!==true||!Array.isArray(result.rows)||JSON.stringify(result.fields)!==JSON.stringify(payload.fields))throw new Error('DS_RESPOSTA_INCOMPLETA');
  return result;
}

function dsFormatRows_(data,names,spec,distinct){
  return data.map(function(r){if(r.length!==names.length)throw new Error('DS_SCHEMA_DIVERGENTE');return {values:r.map(function(v,i){if(v===null||v==='')return null;var kind=distinct?'number':spec.types[names[i]];if(kind==='number'){var n=Number(v);if(!Number.isFinite(n))throw new Error('DS_NUMERO_INVALIDO');return n;}if(kind==='date'){if(!/^\d{4}-\d{2}-\d{2}$/.test(v))throw new Error('DS_DATA_INVALIDA');return v.replace(/-/g,'');}return String(v);})};});
}

// America/Belem inclui horário de verão histórico e o antigo horário médio local.
// Só reutilize um deslocamento quando os dois extremos do dia UTC coincidirem.
var dsAdZoneFormatter_;
var dsAdZoneDays_ = new Map();

function dsAdOffset_(second) {
  function fromZone(at) {
    if (!dsAdZoneFormatter_) dsAdZoneFormatter_ = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/Belem', timeZoneName: 'longOffset'
    });
    var zone = dsAdZoneFormatter_.formatToParts(new Date(at * 1000)).find(function(p) {
      return p.type === 'timeZoneName';
    }).value;
    var parts = /^GMT([+-])(\d\d):(\d\d)(?::(\d\d))?$/.exec(zone);
    if (!parts) throw new Error('DS_DATA_INVALIDA');
    var seconds = Number(parts[2]) * 3600 + Number(parts[3]) * 60 + Number(parts[4] || 0);
    return parts[1] === '+' ? seconds : -seconds;
  }
  var day = Math.floor(second / 86400);
  if (!dsAdZoneDays_.has(day)) {
    var first = fromZone(day * 86400), last = fromZone(day * 86400 + 86399);
    if (dsAdZoneDays_.size >= 4096) dsAdZoneDays_.clear();
    dsAdZoneDays_.set(day, first === last ? first : null);
  }
  var cached = dsAdZoneDays_.get(day);
  return cached === null ? fromZone(second) : cached;
}

function dsAdDate_(value) {
  if (value === null || (typeof value === 'string' && !value.trim())) return null;
  if (typeof value !== 'string') throw new Error('DS_DATA_INVALIDA');
  var raw = value.trim();
  var br = /^(\d{1,2})([/-])(\d{1,2})\2(\d{2}|\d{4})\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$/.exec(raw);
  var year, month, day, hour = 0, minute = 0, second = 0, micro = 0, zone = null;
  function clock(text) {
    var match = /^(\d{2})(?:(:?)(\d{2})(?:\2(\d{2}))?)?(?:[.,](\d+))?$/.exec(text);
    if (!match) throw new Error('DS_DATA_INVALIDA');
    return [Number(match[1]), Number(match[3] || 0), Number(match[4] || 0),
      Number((match[5] || '').slice(0, 6).padEnd(6, '0'))];
  }
  if (br) {
    year = Number(br[4]);
    if (br[4].length === 2) year += year <= 68 ? 2000 : 1900;
    month = Number(br[3]); day = Number(br[1]); hour = Number(br[5]);
    minute = Number(br[6]); second = Number(br[7] || 0);
  } else {
    var iso = /^(\d{4})(-?)(\d{2})\2(\d{2})(?:[T ]([^Z+-]+)(Z|[+-].+)?)?$/.exec(raw);
    if (!iso) throw new Error('DS_DATA_INVALIDA');
    year = Number(iso[1]); month = Number(iso[3]); day = Number(iso[4]);
    if (iso[5]) {
      var time = clock(iso[5]);
      hour = time[0]; minute = time[1]; second = time[2]; micro = time[3]; zone = iso[6] || null;
    }
  }
  var date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(hour, minute, second, 0);
  if (year < 1 || date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 ||
      date.getUTCDate() !== day || date.getUTCHours() !== hour || date.getUTCMinutes() !== minute ||
      date.getUTCSeconds() !== second) throw new Error('DS_DATA_INVALIDA');
  var wall = date.getTime() / 1000, utc = wall;
  var localDay = date.toISOString().slice(0, 10);
  if (zone === null) {
    // fold=0 do ZoneInfo escolhe o deslocamento anterior tanto na lacuna
    // quanto na hora repetida. Fora da transição, a primeira tentativa basta.
    var before = dsAdOffset_(wall - 86400);
    utc -= before;
    if (dsAdOffset_(utc) !== before) {
      var after = dsAdOffset_(wall + 86400);
      if (dsAdOffset_(wall - after) === after) utc = wall - after;
    }
  } else {
    if (zone !== 'Z') {
      var offset = clock(zone.slice(1)), sign = zone[0] === '+' ? 1 : -1;
      var adjustment = offset[0] * 3600 + offset[1] * 60 + offset[2];
      if (adjustment >= 86400) throw new Error('DS_DATA_INVALIDA');
      // O fromisoformat considera UTC um offset com parte inteira toda zero.
      utc -= sign * adjustment;
      if (adjustment) micro -= sign * offset[3];
      var carry = Math.floor(micro / 1000000);
      utc += carry; micro -= carry * 1000000;
    }
    var localized = new Date((utc + dsAdOffset_(utc)) * 1000);
    if (localized.getUTCFullYear() < 1 || localized.getUTCFullYear() > 9999) throw new Error('DS_DATA_INVALIDA');
    localDay = localized.toISOString().slice(0, 10);
  }
  var instant = new Date(utc * 1000);
  if (instant.getUTCFullYear() < 1 || instant.getUTCFullYear() > 9999) throw new Error('DS_DATA_INVALIDA');
  return {instant: instant.toISOString().slice(0, 19) + '.' + String(micro).padStart(6, '0') + 'Z', day: localDay};
}

function dsAdData_(request, c, spec) {
  var started = Date.now();
  function read(table, fields, filters) {
    if (Date.now() - started > 45000) throw new Error('DS_PRAZO_CONSULTA');
    var result = dsCheckedQuery_(c, {table: table, fields: fields, filters: filters,
      start: '', end: '', aggregation: {}});
    if (Date.now() - started > 45000) throw new Error('DS_PRAZO_CONSULTA');
    if (result.rows.length > 50000) throw new Error('DS_CONSULTA_EXCEDE_LIMITE_USE_RESUMO_OU_PERIODO');
    if (!result.rows.every(function(row) { return Array.isArray(row) && row.length === fields.length; })) {
      throw new Error('DS_SCHEMA_DIVERGENTE');
    }
    return result;
  }

  var requested = request.fields;
  if (!requested.length || requested.some(function(f) { return !spec.columns.includes(f.name); })) {
    throw new Error('DS_CAMPOS_NAO_AUTORIZADOS');
  }
  var left = request.configParams.tabela === 'Contatos_Atribuicao_Meta';
  var groups = request.dimensionsFilters || [];
  var idFilters = groups.filter(function(g) {
    return Array.isArray(g) && g.length === 1 && g[0].type === 'INCLUDE' &&
      g[0].fieldName === 'pedido_id' && ['EQUALS', 'IN_LIST'].includes(g[0].operator) &&
      Array.isArray(g[0].values) && g[0].values.length && g[0].values.every(function(v) { return typeof v === 'string'; });
  }).map(function(g) { return new Set(g[0].values); });
  var applied = !left && groups.length > 0 && idFilters.length === groups.length;
  if (!applied) idFilters = [];
  var selected = requested.filter(function(f) { return !applied || !f.forFilterOnly; });
  var schema = dsFields_(request.configParams.tabela,c.segment).forIds(selected.map(function(f) { return f.name; })).build();
  var names = schema.map(function(f) { return f.name; });
  var baseFields = ['pedido_id', 'pedido_data', 'primeiro_anuncio_data'];
  var cohort = 'coorte_primeiro_anuncio', attributed = 'pedido_apos_anuncio';
  var range = request.dateRange || {};
  if (left) {
    if (!range.startDate && !range.endDate && request.scriptParams && request.scriptParams.sampleExtraction) {
      dsVerify_(c);
      return {schema: schema, rows: [], filtersApplied: false};
    }
    if (!range.startDate || !range.endDate) throw new Error('DS_PERIODO_OBRIGATORIO');
    if (![range.startDate, range.endDate].every(function(day) {
      return typeof day === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(day) && dsAdDate_(day).day === day;
    }) || range.startDate > range.endDate) throw new Error('DS_PERIODO_INVALIDO');
    names.forEach(function(name) {
      if (![cohort, attributed].includes(name) && !baseFields.includes(name)) baseFields.push(name);
    });
  }
  var base = read('Base_Contatos', baseFields, [{field: 'primeiro_anuncio_origem', values: ['Meta Ads']}]);
  var candidates = new Set(), contacts = [];
  base.rows.forEach(function(row) {
    var id = row[0];
    if (!left && (id === null || id === '' || !idFilters.every(function(allowed) { return allowed.has(id); }))) return;
    var ad = dsAdDate_(row[2]);
    if (left && (!ad || ad.day < range.startDate || ad.day > range.endDate)) return;
    var key = null;
    if (ad && id !== null && id !== '') {
      if (typeof id !== 'string') throw new Error('DS_SCHEMA_DIVERGENTE');
      if (id.trim()) {
        var purchase = dsAdDate_(row[1]);
        if (purchase && purchase.instant >= ad.instant) key = id;
      }
    }
    if (left) {
      contacts.push(names.map(function(name) {
        if (name === cohort) return ad.day;
        if (name === attributed) return key;
        return row[baseFields.indexOf(name)];
      }));
    } else if (key !== null) candidates.add(key);
  });
  if (left) {
    var result = {schema: schema, filtersApplied: false, rows: dsFormatRows_(contacts, names, spec, false)};
    if (Utilities.newBlob(JSON.stringify(result)).getBytes().length > 7000000) {
      throw new Error('DS_RESPOSTA_EXCEDE_LIMITE_USE_RESUMO');
    }
    if (Date.now() - started > 45000) throw new Error('DS_PRAZO_CONSULTA');
    return result;
  }
  // Sem período de venda aqui: inclusive o cabeçalho posterior ao fim da coorte.
  // O limite de valores por filtro da API é 100. Nunca expor um lote parcial.
  var ids = Array.from(candidates);
  var orderFields = Array.from(new Set(['pedido_id', 'venda_valida'].concat(names)));
  var indices = names.map(function(name) { return orderFields.indexOf(name); });
  var response = {schema: schema, filtersApplied: applied, rows: []};
  var bytes = Utilities.newBlob(JSON.stringify(response)).getBytes().length;
  for (var i = 0; i < ids.length; i += 100) {
    var batch = ids.slice(i, i + 100);
    var headers = read('BI_Pedidos', orderFields, [{field: 'pedido_id', values: batch}]);
    if (headers.version !== base.version) throw new Error('DS_REVISAO_ALTERADA');
    var seen = new Set();
    var eligible = [];
    headers.rows.forEach(function(row) {
      if (!batch.includes(row[0])) throw new Error('DS_RESPOSTA_INCOMPLETA');
      var valid = row[1];
      if (valid === null || valid === '') return;
      if ((typeof valid !== 'string' && typeof valid !== 'number') || !Number.isFinite(Number(valid))) {
        throw new Error('DS_NUMERO_INVALIDO');
      }
      if (Number(valid) <= 0) return;
      if (seen.has(row[0])) throw new Error('DS_BI_PEDIDO_OPERACIONAL_AMBIGUO');
      seen.add(row[0]);
      eligible.push(indices.map(function(j) { return row[j]; }));
    });
    var rows = dsFormatRows_(eligible, names, spec, false);
    if (rows.length) {
      bytes += Utilities.newBlob(JSON.stringify(rows)).getBytes().length - 2 + (response.rows.length ? 1 : 0);
      if (bytes > 7000000) throw new Error('DS_RESPOSTA_EXCEDE_LIMITE_USE_RESUMO');
      rows.forEach(function(row) { response.rows.push(row); });
    }
  }
  if (Date.now() - started > 45000) throw new Error('DS_PRAZO_CONSULTA');
  return response;
}

function dsBuyerRows_(rows, fields, names) {
  var indices = names.map(function(name) { return fields.indexOf(name); });
  var projected = [];
  rows.forEach(function(row) {
    if (!Array.isArray(row) || row.length !== fields.length || row[1] !== 'Sim' ||
        !Number.isSafeInteger(row[2]) || row[2] < 1) {
      throw new Error('DS_RESPOSTA_INCOMPLETA');
    }
    // Um grupo sem contato não identifica um comprador. Preserve a chave
    // textual exata dos demais grupos para a igualdade com a Base_Contatos.
    if (row[0] === null) return;
    if (typeof row[0] !== 'string') throw new Error('DS_SCHEMA_DIVERGENTE');
    if (row[0].trim()) projected.push(indices.map(function(i) { return row[i]; }));
  });
  return projected;
}

function dsProductNames_(groups) {
  // No Looker as condições de um grupo são OR; os grupos combinam-se por AND.
  if (!Array.isArray(groups) || groups.length > 16) throw new Error('DS_FILTRO_AGREGACAO_NAO_SUPORTADO');
  var selected = null;
  var conditions = 0;
  groups.forEach(function(group) {
    if (!Array.isArray(group) || !group.length) throw new Error('DS_FILTRO_AGREGACAO_NAO_SUPORTADO');
    conditions += group.length;
    if (conditions > 16) throw new Error('DS_FILTRO_AGREGACAO_NAO_SUPORTADO');
    var values = new Set();
    group.forEach(function(filter) {
      if (!filter || filter.fieldName !== 'produto_nome' || filter.type !== 'INCLUDE' ||
          !['EQUALS','IN_LIST'].includes(filter.operator) || !Array.isArray(filter.values) ||
          filter.values.length > 100 || (filter.operator === 'EQUALS' && filter.values.length !== 1)) {
        throw new Error('DS_FILTRO_AGREGACAO_NAO_SUPORTADO');
      }
      filter.values.forEach(function(name) {
        if (typeof name !== 'string' || name.indexOf('\0') !== -1) throw new Error('DS_FILTRO_INVALIDO');
        values.add(name);
      });
      if (values.size > 100) throw new Error('DS_FILTRO_INVALIDO');
    });
    selected = selected === null ? Array.from(values) : selected.filter(function(name) { return values.has(name); });
  });
  return selected;
}

function dsProductMode_(fields, spec) {
  var mode = 'resumo';
  if (fields.includes('posicao_unidades_top5')) mode = 'unidades';
  else if (fields.includes('posicao_receita_top5') || fields.includes('participacao_acumulada')) mode = 'receita';
  else if (fields.includes('produto_codigo')) mode = 'ranking';
  else if (fields.includes('produto_nome')) mode = 'nomes';
  if (!fields.every(function(field) { return spec.product_modes[mode].includes(field); })) {
    throw new Error('DS_CAMPOS_NAO_AUTORIZADOS');
  }
  return mode;
}

function dsProductDate_(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  var t = Date.parse(value + 'T00:00:00Z');
  return Number.isFinite(t) && value.slice(0,4) !== '0000' && new Date(t).toISOString().slice(0,10) === value;
}

function dsProductValue_(name, kind, value, start) {
  if (kind === 'date') {
    if (value !== start) throw new Error('DS_DATA_INVALIDA');
    return value.replace(/-/g, '');
  }
  if (kind === 'text') {
    if (value !== null && typeof value !== 'string') throw new Error('DS_SCHEMA_DIVERGENTE');
    return value;
  }
  if (value === null && name === 'participacao_acumulada') return null;
  if (typeof value !== 'number' &&
      (typeof value !== 'string' || !/^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(value))) {
    throw new Error('DS_NUMERO_INVALIDO');
  }
  var numeric = Number(value);
  if (!Number.isFinite(numeric)) throw new Error('DS_NUMERO_INVALIDO');
  if (['produtos_distintos_periodo','registros'].includes(name) &&
      (!Number.isSafeInteger(numeric) || numeric < 0)) throw new Error('DS_NUMERO_INVALIDO');
  return numeric;
}

function dsProductsData_(request, config, spec) {
  var started = Date.now();
  var requested = request.fields;
  if (!Array.isArray(requested) || !requested.length ||
      requested.some(function(f) { return !f || !spec.columns.includes(f.name); }) ||
      new Set(requested.map(function(f) { return f.name; })).size !== requested.length) {
    throw new Error('DS_CAMPOS_NAO_AUTORIZADOS');
  }
  var names = dsProductNames_(request.dimensionsFilters || []);
  var fields = requested.filter(function(f) {
    if (!f.forFilterOnly) return true;
    if (names === null || f.name !== 'produto_nome') throw new Error('DS_FILTRO_AGREGACAO_NAO_SUPORTADO');
    return false;
  }).map(function(f) { return f.name; });
  if (!fields.length) throw new Error('DS_CAMPOS_NAO_AUTORIZADOS');
  var schema = dsFields_(request.configParams.tabela,config.segment).forIds(fields).build();
  fields = schema.map(function(f) { return f.name; });
  var range = request.dateRange || {};
  var sample = request.scriptParams && request.scriptParams.sampleExtraction;
  if (sample && ((!range.startDate && !range.endDate) || fields.length === spec.columns.length)) {
    // O extrator de esquema pode pedir campos de vários grãos na mesma amostra.
    dsVerify_(config);
    return {schema:schema, rows:[], filtersApplied:names !== null};
  }
  if (!range.startDate || !range.endDate) throw new Error('DS_PERIODO_OBRIGATORIO');
  if (!dsProductDate_(range.startDate) || !dsProductDate_(range.endDate) || range.startDate > range.endDate) {
    throw new Error('DS_PERIODO_INVALIDO');
  }
  var mode = dsProductMode_(fields, spec);
  var result = dsCall_(config, '/v1/produtos', {
    mode:mode, fields:fields, start:range.startDate, end:range.endDate, names:names
  });
  if (Date.now() - started > 45000) throw new Error('DS_PRAZO_CONSULTA');
  dsCheckDestination_(config, result);
  if (!Number.isSafeInteger(result.version) || result.version < 1 || result.complete !== true ||
      JSON.stringify(result.fields) !== JSON.stringify(fields) || !Array.isArray(result.rows) ||
      result.rows.length > 50000 || (mode === 'resumo' && result.rows.length !== 1) ||
      (['receita','unidades'].includes(mode) && result.rows.length > 5)) {
    throw new Error('DS_RESPOSTA_INCOMPLETA');
  }
  var rows = result.rows.map(function(row, position) {
    if (!Array.isArray(row) || row.length !== fields.length) throw new Error('DS_SCHEMA_DIVERGENTE');
    return {values:row.map(function(value, i) {
      var name = fields[i], converted = dsProductValue_(name, spec.types[name], value, range.startDate);
      if (['posicao_receita_top5','posicao_unidades_top5'].includes(name) && converted !== position + 1) {
        throw new Error('DS_RESPOSTA_INCOMPLETA');
      }
      return converted;
    })};
  });
  return {schema:schema, rows:rows, filtersApplied:names !== null};
}

// Modo explícito: não inferir SUM para taxas, compradores, LTV ou métricas Meta.
// Fontes existentes sem parâmetro continuam em detalhe; não mudar blends por inferência.
var NexoDSSums={
  BI_Itens:['quantidade','receita_item'],
  BI_Clientes_Vendas:['pedidos','faturamento_produtos','frete','faturamento'],
  Itens_Pedidos_FarmaLider:['quantidade','valor_total'],
  BI_Pedidos:['pedido_valor','pedido_frete','pedido_faturamento_total','venda_valida'],
  Historico_Pedidos:['produtos','frete','faturamento'],
  Historico_Itens:['quantidade','valor']
};
function dsSums_(p,spec,names,groups,supported,distinct){
  if(!p.modo_consulta||p.modo_consulta==='detalhe'||distinct)return {};
  if(p.modo_consulta!=='somas'||!NexoDSSums[p.tabela])throw new Error('DS_MODO_AGREGACAO_NAO_SUPORTADO');
  if(groups.length&&!supported)throw new Error('DS_FILTRO_AGREGACAO_NAO_SUPORTADO');
  var aggregation={};
  names.forEach(function(n){
    if(spec.types[n]==='number'&&!spec.dimensions.includes(n)){
      if(!NexoDSSums[p.tabela].includes(n))throw new Error('DS_METRICA_NAO_ADITIVA');
      aggregation[n]='sum';
    }
  });
  if(!Object.keys(aggregation).length)throw new Error('DS_SOMAS_EXIGEM_METRICA_ADITIVA');
  return aggregation;
}
// O servidor agrega produtos/pares e valida itens/vendas no mesmo snapshot READY.
// Filtros de classe são posteriores ao cálculo completo, como no conector legado.
function dsAbcData_(request,c,spec){
  var started=Date.now();
  var range=request.dateRange||{},names=request.fields.map(function(f){return f.name;});
  if(!range.startDate||!range.endDate)throw new Error('DS_PERIODO_OBRIGATORIO');
  if(names.some(function(n){return !spec.columns.includes(n);}))throw new Error('DS_CAMPOS_NAO_AUTORIZADOS');
  var responseSchema=dsFields_(request.configParams.tabela,c.segment).forIds(names).build();
  names=responseSchema.map(function(f){return f.name;});
  var p=request.configParams,top=null;
  if(spec.abc_mode==='juntos'&&p.pares_escopo&&p.pares_escopo!=='COMPLETO'){
    if(p.pares_escopo!=='TOP'||!['10','25','50','100','250','500','1000'].includes(p.pares_limite))throw new Error('DS_TOP_PARES_INVALIDO');
    if((request.dimensionsFilters||[]).length)throw new Error('DS_TOP_PARES_FILTRO_NAO_SUPORTADO');
    top=Number(p.pares_limite);
  }
  var payload={fields:names,start:range.startDate,end:range.endDate};
  if(top===null)payload.mode=spec.abc_mode;else payload.top=top;
  var r=dsCall_(c,top===null?'/v1/abc':'/v1/abc/pares',payload);
  if(top!==null){
    var sc=r.scope;
    if(!sc||sc.kind!=='TOP_PARES'||sc.requested!==top||!Number.isSafeInteger(sc.universe_pairs)||sc.universe_pairs<0||sc.selected_pairs!==Math.min(top,sc.universe_pairs)||!Array.isArray(r.rows)||r.rows.length!==sc.selected_pairs||sc.all_pairs_returned!==(sc.universe_pairs===sc.selected_pairs))throw new Error('DS_RESPOSTA_INCOMPLETA');
    console.error(JSON.stringify({diagnostico:'top_pares_v1',versao:r.version,selecionados:sc.selected_pairs,universo:sc.universe_pairs}));
  }else if(r.scope)throw new Error('DS_RESPOSTA_INCOMPLETA');
  if(Date.now()-started>45000)throw new Error('DS_PRAZO_CONSULTA');
  var db=c.environment==='producao'?'nexoflow_datastudio':'nexoflow_datastudio_homologacao';
  if(r.protocol!==c.protocol||r.target!==db+'.'+c.segment.toLowerCase()||r.segment!==c.segment||r.environment!==c.environment||r.schema_hash!==NexoDSSchemaHash)throw new Error('DS_CONTRATO_DESTINO_DIVERGENTE');
  if(r.complete!==true||!Array.isArray(r.rows)||JSON.stringify(r.fields)!==JSON.stringify(names)||!Number.isSafeInteger(r.version)||r.version<1)throw new Error('DS_RESPOSTA_INCOMPLETA');
  return {schema:responseSchema,filtersApplied:false,rows:r.rows.map(function(row){
    if(row.length!==names.length)throw new Error('DS_SCHEMA_DIVERGENTE');
    return {values:row.map(function(v,i){
      if(v===null)return null;
      if(spec.types[names[i]]==='number'){var n=Number(v);if(v===''||!Number.isFinite(n))throw new Error('DS_NUMERO_INVALIDO');return n;}
      if(spec.types[names[i]]==='date'){if(!/^\d{4}-\d{2}-\d{2}$/.test(v))throw new Error('DS_DATA_INVALIDA');return v.replace(/-/g,'');}
      return String(v);
    })};
  })};
}
