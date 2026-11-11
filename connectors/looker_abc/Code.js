/* NexoFlow 1.5.13. Conector privado, somente leitura, executado no Google Apps Script. */
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
  var common = [['periodo_inicio', 'date'], ['periodo_fim', 'date'], ['periodo_rotulo','text']];
  if (mode === 'abc') return common.concat([
    ['produto_chave','text'], ['produto_codigo','text'], ['produto_nome','text'], ['categoria','text'],
    ['unidades','sum'], ['receita_produtos','money'], ['pedidos','sum'], ['ranking_receita','number'], ['ranking_unidades','number'],
    ['participacao_receita','percent'], ['participacao_acumulada','percent'], ['participacao_receita_pct','sum'], ['participacao_acumulada_pct','number'], ['classe_abc','text'], ['abc_disponivel','number'], ['atualizado_em','text']
  ]);
  if (mode === 'resumo') return common.concat([
    ['produtos_classe_a','sum'], ['produtos_classe_b','sum'], ['produtos_classe_c','sum'], ['receita_classe_a','percent'], ['receita_classe_b','percent'], ['receita_classe_c','percent'], ['participacao_top5_receita','percent'], ['skus_distintos','sum'], ['faturamento_produtos','money'], ['participacao_top5_receita_pct','number'], ['abc_disponivel','number'], ['atualizado_em','text']
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
    var labels = {periodo_rotulo:'Período', produto_nome:'Produto', classe_abc:'Classe', unidades:'Unidades', receita_produtos:'Receita de produtos', participacao_receita:'Participação (%)', participacao_acumulada:'Acumulada (%)', skus_distintos:'Produtos diferentes', faturamento_produtos:'Receita de produtos', participacao_top5_receita:'Top 5 na receita (%)', produtos_classe_a:'Produtos na classe A', produtos_classe_b:'Produtos na classe B', produtos_classe_c:'Produtos na classe C', receita_classe_a:'Receita classe A (%)', receita_classe_b:'Receita classe B (%)', receita_classe_c:'Receita classe C (%)', produto_a_nome:'Produto A', produto_b_nome:'Produto B', pedidos_juntos:'Pedidos juntos'};
    field.setId(s[0]).setName(labels[s[0]] || s[0]);
    if (s[1] === 'date') field.setType(cc.FieldType.YEAR_MONTH_DAY);
    else if (s[1] === 'text') field.setType(cc.FieldType.TEXT);
    else {
      field.setType(s[1] === 'money' ? cc.FieldType.CURRENCY_BRL : s[1] === 'percent' ? cc.FieldType.PERCENT : cc.FieldType.NUMBER);
      field.setAggregation((s[1] === 'sum' || s[1] === 'money') ? cc.AggregationType.SUM : cc.AggregationType.MAX);
    }
  });
  return f;
}
function getSchema(request) { return {schema: fields_(request.configParams.tabela).build()}; }
function readTables_(id, dateRange, api) {
  var hash = function (text) { return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8).map(function (b) { return ('0' + ((b + 256) % 256).toString(16)).slice(-2); }).join(''); };
  return NexoTables.read(id, ['BI_Itens', 'BI_Clientes_Vendas'], {api: api, hash: hash, widths: {BI_Itens: 12, BI_Clientes_Vendas: 9}, legacy: true, accept: function (title, headers, row) {
    var value = row[headers.indexOf('data')];
    var date = typeof value === 'number' ? new Date(Date.UTC(1899,11,30) + Math.floor(value) * 86400000).toISOString().slice(0,10) : String(value).slice(0,10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || isNaN(Date.parse(date)) || new Date(date).toISOString().slice(0,10) !== date) throw new Error('Data inválida na tabela BI.');
    return !dateRange || (date >= dateRange.startDate && date <= dateRange.endDate);
  }});
}
function getData(request) {
  var cc = DataStudioApp.createCommunityConnector();
  var api=NexoTables.googleApi(Sheets,{startedAt:Date.now(),dateTimeRenderOption:'FORMATTED_STRING',sleep:function(ms){Utilities.sleep(ms);},warn:function(info){console.warn(JSON.stringify(info));}});
  try {
    var params = request.configParams || {}, id = String(params.spreadsheetId || '').trim();
    if (!/^[a-zA-Z0-9_-]{20,100}$/.test(id)) throw new Error('Informe um ID de planilha válido.');
    if (!request.dateRange) throw new Error('A consulta precisa do período selecionado no relatório.');
    var mode = params.tabela, fields = fields_(mode), names = request.fields.map(function (f) { return f.name; });
    var valid = new Set(fieldSpecs_(mode).map(function (s) { return s[0]; }));
    if (names.some(function (name) { return !valid.has(name); })) throw new Error('O relatório solicitou um campo desconhecido.');
    var requestedFields = fields.forIds(names);
    names = requestedFields.asArray().map(function (f) { return f.getId(); });
    var tables = readTables_(id, request.dateRange,api);
    var result = NexoAbc.calculate(tables[0], tables[1], request.dateRange.startDate, request.dateRange.endDate);
    var response = {
      schema: requestedFields.build(),
      rows: result[mode].map(function (r) { return {values: names.map(function (name) {
        var value = r[name];
        return name === 'periodo_inicio' || name === 'periodo_fim' ? value.replace(/-/g, '') : value;
      })}; }),
      filtersApplied: false
    };
    api.checkDeadline('RESULTADO_ABC');
    return response;
  } catch (error) {
    var safe = error.nexoValidation || !error.nexoDiagnostic && /^(Continuações:|Data inválida|Valor monetário|Cabeçalho|Chave obrigatória|Registros conflitantes|O início|Item sem|Versão da carga|Quantidade inválida|Valor acima|As bases|Pedido com|Selecione|Aba BI|A origem excede|Informe um ID|A consulta precisa|O relatório solicitou)/.test(String(error.message));
    console.error(JSON.stringify(NexoTables.diagnostic(error,api)));
    cc.newUserError().setText((safe?error.message+' ':'')+NexoTables.diagnosticText(error,api)).throwException();
  }
}
