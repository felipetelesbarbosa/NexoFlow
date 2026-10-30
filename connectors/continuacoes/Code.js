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
    if (spec[1] === 'number') field.setAggregation(/(idade|ranking|taxa|pct|disponivel|informada|identificada|pendente|ticket_medio|historico_completo)/.test(spec[0]) ? cc.AggregationType.MAX : cc.AggregationType.SUM);
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
    var table = NexoTables.read(String(params.spreadsheetId || '').trim(), [params.tabela], {api: api_(), hash: hash_, widths: widths, segment: params.segmento, accept: function (title, header, row) {
      var index = header.indexOf("data");
      if (!request.dateRange || index < 0) return true;
      var value = date_(row[index]), start = date_(request.dateRange.startDate), end = date_(request.dateRange.endDate);
      if (!value || !start || !end || start > end) throw new Error("Data inválida na tabela BI.");
      return value >= start && value <= end;
    }})[0];
    if (NexoTables.stable(table[0]) !== NexoTables.stable(spec.map(function (s) { return s[0]; }))) throw new Error('Cabeçalho da tabela difere da versão do conector.');
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
