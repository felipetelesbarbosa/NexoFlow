/* Conector privado de tabelas BI distribuídas; não grava dados. */
function getAuthType() {
  var cc = DataStudioApp.createCommunityConnector();
  return cc.newAuthTypeResponse().setAuthType(cc.AuthType.NONE).build();
}
function isAdminUser() { return false; }
function getConfig() {
  var cc = DataStudioApp.createCommunityConnector(), config = cc.getConfig();
  config.newTextInput().setId('spreadsheetId').setName('ID do Dashboard NexoFlow');
  var segment = config.newSelectSingle().setId('segmento').setName('Segmento');
  ['FARMA', 'PET'].forEach(function (value) { segment.addOption(config.newOptionBuilder().setLabel(value).setValue(value)); });
  var table = config.newSelectSingle().setId('tabela').setName('Tabela BI');
  Object.keys(NexoSchemas).forEach(function (title) { table.addOption(config.newOptionBuilder().setLabel(title).setValue(title)); });
  var cut=config.newSelectSingle().setId('recorte_historico').setName('Resumo histórico: grão (somente BI_Historico_Resumo)');
  ['MES','ANO','TOTAL','SEM_EMISSAO'].forEach(function (value) {cut.addOption(config.newOptionBuilder().setLabel(value).setValue(value));});
  config.setDateRangeRequired(false);
  return config.build();
}
function fields_(title) {
  if (!NexoSchemas[title]) throw new Error('Selecione uma tabela BI válida.');
  var cc = DataStudioApp.createCommunityConnector(), fields = cc.getFields();
  NexoSchemas[title].forEach(function (spec) {
    var field = spec[1] === 'number' ? fields.newMetric() : fields.newDimension();
    field.setId(spec[0]).setName(spec[0]);
    field.setType(spec[1] === 'date' ? cc.FieldType.YEAR_MONTH_DAY : spec[1].startsWith('number') ? cc.FieldType.NUMBER : cc.FieldType.TEXT);
    if (spec[1] === 'number') field.setAggregation(title==='BI_Historico_Resumo' ? (spec[0]==='clientes' ? cc.AggregationType.MAX : cc.AggregationType.SUM) : /(idade|ranking|taxa|pct|disponivel|informada|identificada|pendente|ticket_medio|historico_completo|^clientes$)/.test(spec[0]) ? cc.AggregationType.MAX : cc.AggregationType.SUM);
  });
  return fields;
}
function getSchema(request) { return {schema: fields_(request.configParams.tabela).build()}; }
function api_() {
  return {
    meta: function (id) { return Sheets.Spreadsheets.get(id, {fields: 'sheets(properties(sheetId,title,gridProperties)),developerMetadata'}); },
    values: function (id, range) { return Sheets.Spreadsheets.Values.get(id, range, {valueRenderOption: 'UNFORMATTED_VALUE', dateTimeRenderOption: 'SERIAL_NUMBER', majorDimension: 'ROWS'}).values || []; }
  };
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
function getData(request) {
  var cc = DataStudioApp.createCommunityConnector();
  try {
    var params = request.configParams || {}, spec = NexoSchemas[params.tabela];
    if (!spec || !['FARMA', 'PET'].includes(params.segmento)) throw new Error('Selecione tabela e segmento válidos.');
    var fields = fields_(params.tabela), names = request.fields.map(function (f) { return f.name; });
    if (names.some(function (name) { return !spec.some(function (s) { return s[0] === name; }); })) throw new Error('Campo solicitado não pertence à tabela.');
    var selected = fields.forIds(names);
    names = selected.asArray().map(function (f) { return f.getId(); });
    var widths = {}; widths[params.tabela] = spec.length;
    var signature=null, api=api_(), linked=null, queryStarted=Date.now();
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
    var positions = names.map(function (name) { return table[0].indexOf(name); });
    return {schema: selected.build(), rows: table.slice(1).map(function (row) {
      return {values: positions.map(function (i) {
        var value = row[i];
        if (value === '' || value === undefined || value === null) return null;
        if (spec[i][1] === 'date') return date_(value);
        if (spec[i][1] === 'text') return String(value);
        if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('Medida BI sem tipo numérico; execute uma nova carga Analytics.');
        return value;
      })};
    }), filtersApplied: false};
  } catch (error) {
    var text = String(error.message || '');
    var safe = /^(Continuações:|Selecione tabela|Campo solicitado|Cabeçalho da tabela|Medida BI|Data inválida)/.test(text);
    cc.newUserError().setText(safe ? text : 'Não foi possível ler a fonte. Confira o acesso aos arquivos do segmento e tente novamente.').throwException();
  }
}
