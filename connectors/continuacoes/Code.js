/* Conector privado de tabelas BI distribuídas; não grava dados. */
function getAuthType() {
  var cc = DataStudioApp.createCommunityConnector();
  return cc.newAuthTypeResponse().setAuthType(cc.AuthType.NONE).build();
}
function isAdminUser() { return false; }
function getConfig(request) {
  var params=request && request.configParams || {};
  var cc = DataStudioApp.createCommunityConnector(), config = cc.getConfig();
  config.newTextInput().setId('spreadsheetId').setName('ID do Dashboard NexoFlow');
  var segment = config.newSelectSingle().setId('segmento').setName('Segmento').setIsDynamic(true);
  ['FARMA', 'PET'].forEach(function (value) { segment.addOption(config.newOptionBuilder().setLabel(value).setValue(value)); });
  var table = config.newSelectSingle().setId('tabela').setName('Tabela BI').setIsDynamic(true);
  Object.keys(NexoSchemas).forEach(function (title) { table.addOption(config.newOptionBuilder().setLabel(title).setValue(title)); });
  var cut=config.newSelectSingle().setId('recorte_historico').setName('Resumo histórico: grão (somente BI_Historico_Resumo)');
  ['MES','ANO','TOTAL','SEM_EMISSAO'].forEach(function (value) {cut.addOption(config.newOptionBuilder().setLabel(value).setValue(value));});
  var complete=['FARMA','PET'].includes(params.segmento) && Object.prototype.hasOwnProperty.call(NexoSchemas,params.tabela);
  config.setIsSteppedConfig(!complete);
  config.setDateRangeRequired(requiresPeriod_(params));
  return config.build();
}
function requiresPeriod_(params) { return params.segmento==='FARMA' && params.tabela==='BI_Itens'; }
function fields_(title,params) {
  if (!NexoSchemas[title]) throw new Error('Selecione uma tabela BI válida.');
  var cc = DataStudioApp.createCommunityConnector(), fields = cc.getFields();
  NexoSchemas[title].forEach(function (spec) {
    var field = spec[1] === 'number' ? fields.newMetric() : fields.newDimension();
    field.setId(spec[0]).setName(spec[0]);
    field.setType(spec[1] === 'date' ? cc.FieldType.YEAR_MONTH_DAY : spec[1].startsWith('number') ? cc.FieldType.NUMBER : cc.FieldType.TEXT);
    if (spec[1] === 'number') field.setAggregation(title==='BI_Historico_Resumo' ? (spec[0]==='clientes' ? cc.AggregationType.MAX : cc.AggregationType.SUM) : /((?:^|_)idade(?:$|_)|ranking|taxa|pct|disponivel|informada|identificada|pendente|ticket_medio|historico_completo|^clientes$)/.test(spec[0]) ? cc.AggregationType.MAX : cc.AggregationType.SUM);
  });
  // Distintos são calculados uma vez no universo filtrado, nunca somados por dia/parte.
  if (title==='BI_Itens' && params && params.segmento==='FARMA') {
    fields.newMetric().setId('produtos_distintos_periodo').setName('Produtos distintos no período (SKU informado)').setType(cc.FieldType.NUMBER).setIsReaggregatable(false);
  }
  return fields;
}
function getSchema(request) {
  var params=request.configParams||{}, title=params.tabela, api=api_();
  // Vinculação verificável antes do primeiro lote: valida origem, nunca retorna fatos.
  try {
  NexoTables.read(String(params.spreadsheetId||'').trim(),[title],{
    api:api,hash:hash_,schemas:NexoSchemas,segment:params.segmento,schemaOnly:true
  });
  return {schema:fields_(title,params).build()};
  } catch(error) { reportError_(DataStudioApp.createCommunityConnector(),error,api); }
}
function api_(startedAt) {
  return NexoTables.googleApi(Sheets,{
    startedAt:startedAt,
    sleep:typeof Utilities.sleep==='function'?function(ms){Utilities.sleep(ms);}:undefined,
    warn:function(info){console.warn(JSON.stringify(info));}
  });
}
function reportError_(cc,error,api) {
  var text=String(error.message || '');
  var safe=error.nexoValidation || !error.nexoDiagnostic && /^(Selecione tabela|Campo solicitado|Cabeçalho da tabela|Medida BI|Data inválida|Continuações:)/.test(text);
  // Nunca registrar message/stack da exceção Google: podem conter URL ou valores.
  console.error(JSON.stringify(NexoTables.diagnostic(error,api)));
  cc.newUserError().setText((safe?text+' ':'')+NexoTables.diagnosticText(error,api)).throwException();
}
function hash_(text) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8).map(function (b) { return ('0' + ((b + 256) % 256).toString(16)).slice(-2); }).join('');
}
function date_(value) {
  if (value === '' || value === null || value === undefined) return null;
  if (typeof value==='string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)) {
    var instant=new Date(value);
    if (isNaN(instant.getTime())) throw new Error('Data inválida na tabela BI.');
    var parts=new Intl.DateTimeFormat('en-US',{timeZone:'America/Belem',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(instant);
    var calendar={};parts.forEach(function(p){calendar[p.type]=p.value;});
    return calendar.year+calendar.month+calendar.day;
  }
  var text = typeof value === 'number' ? new Date(Date.UTC(1899, 11, 30) + Math.floor(value) * 86400000).toISOString().slice(0, 10) : String(value).slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text) || isNaN(Date.parse(text)) || new Date(text).toISOString().slice(0, 10) !== text) throw new Error('Data inválida na tabela BI.');
  return text.replace(/-/g, '');
}
// Aplicação conservadora: somente o indicador numérico conhecido do piloto FARMA.
// Outros filtros continuam integralmente no Data Studio (all-or-none).
function itemFilters_(request,params) {
  var groups=request.dimensionsFilters;
  var delegated={applied:false,reason:'DELEGADO',accept:function(){return true;}};
  if (params.segmento!=='FARMA' || params.tabela!=='BI_Itens' || !Array.isArray(groups) || !groups.length) return delegated;
  var valid=groups.every(function(group){return Array.isArray(group) && group.length && group.every(function(f){
    return f && f.fieldName==='sku_informado' && ['INCLUDE','EXCLUDE'].includes(f.type) && ['EQUALS','IN_LIST'].includes(f.operator) && Array.isArray(f.values) && f.values.length && (f.operator!=='EQUALS' || f.values.length===1) && f.values.every(function(v){return v===0 || v===1 || v==='0' || v==='1';});
  });});
  if (!valid) return delegated;
  return {applied:true,reason:'SKU_ANTES_AGREGACAO',accept:function(header,row){
    var value=row[header.indexOf('sku_informado')];
    return groups.every(function(group){return group.some(function(f){var matches=f.values.some(function(v){return value===Number(v);});return f.type==='INCLUDE'?matches:!matches;});});
  }};
}
function queryTrace_(request,params,plan,count) {
  // Só estrutura autorizada: sem valores de filtros, registros ou ID de destino.
  function day(value){var text=String(value || '');return /^\d{4}-\d{2}-\d{2}$/.test(text)?text:null;}
  var shape=Array.isArray(request.dimensionsFilters)?request.dimensionsFilters.slice(0,25).map(function(group){return Array.isArray(group)?group.slice(0,25).map(function(f){f=f || {};return {campo:NexoSchemas.BI_Itens.some(function(s){return s[0]===f.fieldName;})?f.fieldName:'OUTRO',operador:['EQUALS','IN_LIST','CONTAINS','REGEXP_PARTIAL_MATCH','BETWEEN','IS_NULL'].includes(f.operator)?f.operator:'OUTRO',tipo:['INCLUDE','EXCLUDE'].includes(f.type)?f.type:'OUTRO'};}):[];}):[];
  return {diagnostico:'consulta_bi_itens_v1',resultado:request.fields.some(function(f){return f.name==='produtos_distintos_periodo';})?'DISTINTOS_CALCULADOS':'ITENS_DETALHADOS',periodo_exigido:requiresPeriod_(params),amostra:!!(request.scriptParams && request.scriptParams.sampleExtraction===true),filtros:shape,segmento:params.segmento,campos:request.fields.map(function(f){return {nome:f.name,somente_filtro:f.forFilterOnly===true};}),inicio:day(request.dateRange && request.dateRange.startDate),fim:day(request.dateRange && request.dateRange.endDate),grupos_filtro:Array.isArray(request.dimensionsFilters)?request.dimensionsFilters.length:0,filtros_aplicados:plan.applied,tratamento:plan.reason,linhas_resposta:count};
}
function getData(request) {
  var cc = DataStudioApp.createCommunityConnector();
  try {
    var params = request.configParams || {}, spec = NexoSchemas[params.tabela];
    if (!spec || !['FARMA', 'PET'].includes(params.segmento)) throw new Error('Selecione tabela e segmento válidos.');
    if (requiresPeriod_(params)) {
      var period=request.dateRange;
      if (!period || !period.startDate || !period.endDate) throw new Error('Continuações: período não recebido para BI_Itens FARMA. Reconecte a fonte com a configuração de período atualizada e confira a dimensão data do componente.');
      if (typeof period.startDate!=='string' || typeof period.endDate!=='string' || !/^\d{4}-\d{2}-\d{2}$/.test(period.startDate) || !/^\d{4}-\d{2}-\d{2}$/.test(period.endDate)) throw new Error('Data inválida no período de BI_Itens FARMA.');
      var periodStart=date_(period.startDate), periodEnd=date_(period.endDate);
      if (!periodStart || !periodEnd || periodStart>periodEnd) throw new Error('Data inválida no período de BI_Itens FARMA.');
    }
    var fields = fields_(params.tabela,params), names = request.fields.map(function (f) { return f.name; });
    var exactCount=params.segmento==='FARMA' && params.tabela==='BI_Itens' && names.includes('produtos_distintos_periodo');
    if (names.some(function (name) { return !(exactCount && name==='produtos_distintos_periodo') && !spec.some(function (s) { return s[0] === name; }); })) throw new Error('Campo solicitado não pertence à tabela.');
    var itemFilters=itemFilters_(request,params);
    if (exactCount) {
      if (request.fields.some(function(f){return f.name!=='produtos_distintos_periodo' && !(f.name==='sku_informado' && f.forFilterOnly===true && itemFilters.applied);} )) throw new Error('Continuações: use produtos_distintos_periodo em cartão separado, sem dimensões ou outras métricas.');
      if (request.dimensionsFilters && (!Array.isArray(request.dimensionsFilters) || request.dimensionsFilters.length && !itemFilters.applied)) throw new Error('Continuações: filtro não suportado para o cartão exato; nenhum total foi retornado.');
    }
    if (itemFilters.applied) names=names.filter(function(name){return request.fields.some(function(f){return f.name===name && f.forFilterOnly!==true;});});
    var selected = fields.forIds(names);
    names = selected.asArray().map(function (f) { return f.getId(); });
    var widths = {}; widths[params.tabela] = spec.length;
    var queryStarted=Date.now(), signature=null, api=api_(queryStarted), linked=null;
    function fence(value) { if (signature!==null && signature!==value) throw new Error('Continuações: publicação mudou entre as fontes.'); signature=value; }
    if (params.tabela==='Historico_Itens') {
      if (!request.dateRange) throw new Error('Continuações: selecione um período para o detalhe de itens.');
      linked=new Set();
      NexoTables.read(String(params.spreadsheetId||'').trim(),['Historico_Pedidos'],{
        api:api,hash:hash_,widths:{Historico_Pedidos:NexoSchemas.Historico_Pedidos.length},schemas:NexoSchemas,date:date_,segment:params.segmento,onManifest:fence,startedAt:queryStarted,
        accept:function (_title,header,row) {
          var day=date_(row[header.indexOf('data')]);
          if (day && day>=date_(request.dateRange.startDate) && day<=date_(request.dateRange.endDate)) linked.add(String(row[header.indexOf('pedido_id')]));
          if (linked.size>200000) throw new Error('Continuações: mais de 200 mil pedidos no detalhe; reduza o período.');
          return false;
        }
      });
    }
    var table = NexoTables.read(String(params.spreadsheetId || '').trim(), [params.tabela], {api: api, hash: hash_, widths: widths, schemas:NexoSchemas,date:date_,onManifest:fence,startedAt:queryStarted, segment: params.segmento, accept: function (title, header, row) {
      if (itemFilters.applied && !itemFilters.accept(header,row)) return false;
      if (linked) return linked.has(String(row[header.indexOf('pedido_id')]));
      if (title==='BI_Historico_Resumo') {
        var cut=params.recorte_historico||'MES';
        if (!['MES','ANO','TOTAL','SEM_EMISSAO'].includes(cut)) throw new Error('Continuações: selecione um grão de resumo válido.');
        if (row[header.indexOf('tipo_recorte')]!==cut) return false;
        if (request.dateRange && cut!=='SEM_EMISSAO') {
          var begin=date_(row[header.indexOf('periodo_inicio')]), end=date_(row[header.indexOf('periodo_fim')]);
          var requestedStart=date_(request.dateRange.startDate),requestedEnd=date_(request.dateRange.endDate);
          if (begin && end && (requestedEnd<begin || requestedStart>end)) return false;
          if (begin && end && (requestedStart>begin || requestedEnd<end)) throw new Error('Continuações: filtro corta um recorte agregado. Use resumo mais detalhado ou Histórico de Pedidos.');
        }
        return true;
      }
      var index = header.indexOf("data");
      if (!request.dateRange || index < 0) return true;
      var value = date_(row[index]), start = date_(request.dateRange.startDate), end = date_(request.dateRange.endDate);
      if (!start || !end || start > end) throw new Error("Data inválida na tabela BI.");
      if (!value && title==='Historico_Pedidos') return false; // Conferir SEM_EMISSAO no resumo.
      if (!value) throw new Error("Data inválida na tabela BI.");
      return value >= start && value <= end;
    }})[0];
    if (NexoTables.stable(table[0]) !== NexoTables.stable(spec.map(function (s) { return s[0]; }))) throw new Error('Cabeçalho da tabela difere da versão do conector.');
    if (params.tabela==='BI_Historico_Resumo' && names.includes('clientes') && table.length>2 && !names.includes('competencia')) throw new Error('Continuações: clientes distintos não são aditivos. Use ANO ou TOTAL em um único recorte, ou detalhe por competência.');
    if (exactCount) {
      var distinct=new Set(),codeIndex=table[0].indexOf('produto_codigo'),flagIndex=table[0].indexOf('sku_informado');
      table.slice(1).forEach(function(row){
        var code=row[codeIndex];
        if (row[flagIndex]===1 && code!=='' && code!==null && code!==undefined) distinct.add(String(code));
      });
      var metric=fields.forIds(['produtos_distintos_periodo']);
      var exactResponse={schema:metric.build(),rows:distinct.size?[{values:[distinct.size]}]:[],filtersApplied:itemFilters.applied};
      if (typeof console.info==='function') console.info(JSON.stringify(queryTrace_(request,params,itemFilters,exactResponse.rows.length)));
      if (api.checkDeadline) api.checkDeadline('RESULTADO');
      return exactResponse;
    }
    var positions = names.map(function (name) { return table[0].indexOf(name); });
    var response={schema: selected.build(), rows: table.slice(1).map(function (row) {
      return {values: positions.map(function (i) {
        var value = row[i];
        if (value === '' || value === undefined || value === null) return null;
        if (spec[i][1] === 'date') return date_(value);
        if (spec[i][1] === 'text') return String(value);
        if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('Medida BI sem tipo numérico; execute uma nova carga Analytics.');
        return value;
      })};
    }), filtersApplied: itemFilters.applied};
    if (params.tabela==='BI_Itens' && params.segmento==='FARMA' && typeof console.info==='function') console.info(JSON.stringify(queryTrace_(request,params,itemFilters,response.rows.length)));
    if (api.checkDeadline) api.checkDeadline('RESULTADO');
    return response;
  } catch (error) {
    reportError_(cc,error,api);
  }
}
