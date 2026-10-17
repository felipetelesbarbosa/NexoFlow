/* NexoFlow 1.0. Conector privado, somente leitura, executado no Google Apps Script. */
function getAuthType() {
  var cc = DataStudioApp.createCommunityConnector();
  return cc.newAuthTypeResponse().setAuthType(cc.AuthType.NONE).build();
}
function isAdminUser() { return false; }
function getConfig() {
  var cc = DataStudioApp.createCommunityConnector(), c = cc.getConfig();
  c.newTextInput().setId('spreadsheetId').setName('ID da planilha BI do NexoFlow').setHelpText('Informe somente o ID da planilha que contém BI_Itens e BI_Clientes_Vendas.');
  c.newSelectSingle().setId('tabela').setName('Visão da Curva ABC')
    .addOption(c.newOptionBuilder().setLabel('Produtos e classes A/B/C').setValue('abc'))
    .addOption(c.newOptionBuilder().setLabel('Resumo do período').setValue('resumo'))
    .addOption(c.newOptionBuilder().setLabel('Produtos comprados juntos').setValue('juntos'));
  c.setDateRangeRequired(true);
  return c.build();
}
function fieldSpecs_(mode) {
  var common = [['periodo_inicio', 'date'], ['periodo_fim', 'date']];
  if (mode === 'abc') return common.concat([
    ['produto_chave','text'], ['produto_codigo','text'], ['produto_nome','text'], ['categoria','text'],
    ['unidades','sum'], ['receita_produtos','money'], ['pedidos','sum'], ['ranking_receita','number'], ['ranking_unidades','number'],
    ['participacao_receita_pct','sum'], ['participacao_acumulada_pct','number'], ['classe_abc','text'], ['abc_disponivel','number'], ['atualizado_em','text']
  ]);
  if (mode === 'resumo') return common.concat([
    ['skus_distintos','sum'], ['faturamento_produtos','money'], ['participacao_top5_receita_pct','number'], ['abc_disponivel','number'], ['atualizado_em','text']
  ]);
  if (mode === 'juntos') return common.concat([
    ['produto_a_codigo','text'], ['produto_a_nome','text'], ['produto_b_codigo','text'], ['produto_b_nome','text'], ['pedidos_juntos','sum'], ['atualizado_em','text']
  ]);
  throw new Error('Selecione uma visão válida da Curva ABC.');
}
function fields_(mode) {
  var cc = DataStudioApp.createCommunityConnector(), f = cc.getFields();
  fieldSpecs_(mode).forEach(function (s) {
    var field = (s[1] === 'text' || s[1] === 'date') ? f.newDimension() : f.newMetric();
    field.setId(s[0]).setName(s[0]);
    if (s[1] === 'date') field.setType(cc.FieldType.YEAR_MONTH_DAY);
    else if (s[1] === 'text') field.setType(cc.FieldType.TEXT);
    else {
      field.setType(s[1] === 'money' ? cc.FieldType.CURRENCY_BRL : cc.FieldType.NUMBER);
      field.setAggregation((s[1] === 'sum' || s[1] === 'money') ? cc.AggregationType.SUM : cc.AggregationType.MAX);
    }
  });
  return f;
}
function getSchema(request) { return {schema: fields_(request.configParams.tabela).build()}; }
function readTable_(ss, name, requiredMaxColumn) {
  var sheet = ss.getSheetByName(name);
  if (!sheet || sheet.getLastRow() < 1) throw new Error('Aba BI obrigatória ausente.');
  // Limite explícito: falhar em vez de entregar uma amostra como se fosse toda a base.
  if (sheet.getLastRow() > 150000 || sheet.getLastColumn() > requiredMaxColumn) throw new Error('A origem excede o limite de leitura desta versão do conector.');
  var values = sheet.getRange(1, 1, sheet.getLastRow(), sheet.getLastColumn()).getValues(), zone = ss.getSpreadsheetTimeZone();
  return values.map(function (r, i) {
    return r.map(function (v, j) {
      if (!(v instanceof Date)) return v;
      return Utilities.formatDate(v, zone, i > 0 && values[0][j] === 'atualizado_em' ? "yyyy-MM-dd'T'HH:mm:ssXXX" : 'yyyy-MM-dd');
    });
  });
}
function getData(request) {
  var cc = DataStudioApp.createCommunityConnector();
  try {
    var params = request.configParams || {}, id = String(params.spreadsheetId || '').trim();
    if (!/^[a-zA-Z0-9_-]{20,100}$/.test(id)) throw new Error('Informe um ID de planilha válido.');
    if (!request.dateRange) throw new Error('A consulta precisa do período selecionado no relatório.');
    var mode = params.tabela, fields = fields_(mode), names = request.fields.map(function (f) { return f.name; });
    var valid = new Set(fieldSpecs_(mode).map(function (s) { return s[0]; }));
    if (names.some(function (name) { return !valid.has(name); })) throw new Error('O relatório solicitou um campo desconhecido.');
    var requestedFields = fields.forIds(names);
    names = requestedFields.asArray().map(function (f) { return f.getId(); });
    var ss = SpreadsheetApp.openById(id);
    var result = NexoAbc.calculate(readTable_(ss, 'BI_Itens', 12), readTable_(ss, 'BI_Clientes_Vendas', 9), request.dateRange.startDate, request.dateRange.endDate);
    return {
      schema: requestedFields.build(),
      rows: result[mode].map(function (r) { return {values: names.map(function (name) {
        var value = r[name];
        return name === 'periodo_inicio' || name === 'periodo_fim' ? value.replace(/-/g, '') : value;
      })}; }),
      filtersApplied: false
    };
  } catch (error) {
    // Mensagens produzidas pelo motor não contêm registros. Erros Google ficam privados.
    var safe = /^(Data inválida|Valor monetário|Cabeçalho|Chave obrigatória|Registros conflitantes|O início|Item sem|Versão da carga|Quantidade inválida|Valor acima|As bases|Pedido com|Selecione|Aba BI|A origem excede|Informe um ID|A consulta precisa|O relatório solicitou)/.test(String(error.message));
    cc.newUserError().setText(safe ? error.message : 'Não foi possível ler a planilha BI. Confira o acesso e tente novamente.').throwException();
  }
}
