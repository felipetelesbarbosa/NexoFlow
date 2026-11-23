const test = require('node:test');
const assert = require('node:assert/strict');

const table = 'Produtos_Mais_Vendidos';
const configParams = {segmento: 'FARMA', ambiente: 'homologacao', tabela: table};
const dateRange = {startDate: '2026-11-09', endDate: '2026-11-09'};
const item = {
  periodo_inicio: dateRange.startDate, produto_codigo: '001', produto_nome: 'Nome de exibição',
  quantidade: '2.25', receita_item: '10.04', participacao_acumulada: '0.1657',
  registros: '4', produtos_distintos_periodo: '2', posicao_receita_top5: '1', posicao_unidades_top5: '1'
};
function request(fields, dimensionsFilters = []) {
  return {configParams, dateRange, fields: fields.map(name => ({name})), dimensionsFilters};
}
function includes(values, operator = 'IN_LIST') {
  return {fieldName: 'produto_nome', type: 'INCLUDE', operator, values};
}

module.exports = function registerProductTests({fixture, result, assertFarmaError}) {
  test('Produtos mais vendidos fornece uma fonte de período FARMA com moeda, percentuais e agregações', () => {
    const f = fixture();
    const fields = f.ctx.dsFields_(table).build();
    const expected = {
      periodo_inicio: ['dimension','date'], produto_codigo: ['dimension','text'],
      produto_nome: ['dimension','text'], quantidade: ['metric','number','sum'],
      receita_item: ['metric','currency_brl','sum'], participacao_acumulada: ['metric','percent','max'],
      registros: ['metric','number','sum'], produtos_distintos_periodo: ['metric','number','max'],
      posicao_receita_top5: ['metric','number','max'], posicao_unidades_top5: ['metric','number','max']
    };
    assert.equal(f.ctx.NexoDSSchemas[table].period, 'periodo_inicio');
    assert.equal(fields.length, Object.keys(expected).length);
    for (const field of fields) {
      const values = [field.role, field.type];
      if (field.aggregation) values.push(field.aggregation);
      assert.deepEqual(values, expected[field.id]);
    }
    const pet = {...request(['registros']), configParams: {...configParams, segmento: 'PET'}};
    assert.throws(() => f.ctx.getData(pet), /DS_TABELA_NAO_AUTORIZADA/);
    assert.equal(f.calls.length, 0);
  });

  test('Sete componentes leem as projeções corretas e a resposta segue a ordem de campos do SDK', () => {
    const charts = [
      ['ranking', ['produto_nome','produto_codigo','receita_item','quantidade']],
      ['unidades', ['produto_nome','produto_codigo','quantidade','posicao_unidades_top5']],
      ['receita', ['participacao_acumulada','posicao_receita_top5','produto_codigo','receita_item']],
      ['resumo', ['produtos_distintos_periodo']], ['resumo', ['receita_item']], ['resumo', ['quantidade']],
      ['nomes', ['produto_nome','registros']]
    ];
    for (const [mode, projected] of charts) {
      const f = fixture(payload => {
        assert.equal(payload.mode, mode);
        assert.equal(payload.start, dateRange.startDate);
        assert.equal(payload.end, dateRange.endDate);
        assert.equal(payload.names, null);
        assert.deepEqual(new Set(payload.fields), new Set([...projected, 'periodo_inicio']));
        return result(payload, [payload.fields.map(field => item[field])]);
      });
      const response = f.ctx.getData(request([...projected, 'periodo_inicio']));
      assert.equal(response.rows.length, 1);
      assert.equal(f.calls.length, 1);
      assert.ok(f.calls[0].url.endsWith('/v1/produtos'));
      assert.equal(response.filtersApplied, false);
      for (const [i, field] of response.schema.entries()) {
        const expected = field.type === 'text' ? item[field.name]
          : field.type === 'date' ? '20261109' : Number(item[field.name]);
        assert.equal(response.rows[0].values[i], expected);
      }
    }
    const f = fixture(payload => {
      assert.equal(payload.mode, 'receita');
      return result(payload, [['001',null]]);
    });
    const share = f.ctx.getData(request(['produto_codigo','participacao_acumulada']));
    assert.deepEqual(Array.from(share.rows[0].values), ['001',null]);
  });

  test('Filtro de nome precede cartões e Top 5, respeita OR e AND e remove o campo forFilterOnly', () => {
    const groups = [
      [includes(['Água','x']), includes([' Óleo '],'EQUALS')],
      [includes([' Óleo ','Água','Água'])]
    ];
    for (const [fields, mode] of [
      [['receita_item'], 'resumo'], [['produto_codigo','posicao_unidades_top5'], 'unidades']
    ]) {
      const f = fixture(payload => {
        assert.deepEqual(payload.names.sort(), [' Óleo ','Água']);
        assert.equal(payload.mode, mode);
        assert.ok(!payload.fields.includes('produto_nome'));
        return result(payload, [payload.fields.map(field => item[field])]);
      });
      const req = request(fields, groups);
      req.fields.push({name:'produto_nome', forFilterOnly:true});
      const response = f.ctx.getData(req);
      assert.equal(response.filtersApplied, true);
      assert.equal(response.schema.length, fields.length);
    }
    for (const filters of [[[includes([])]], [[includes(['A'])],[includes(['B'])]]]) {
      const f = fixture(payload => {
        assert.deepEqual(payload.names, []);
        return result(payload, [[0]]);
      });
      const response = f.ctx.getData(request(['receita_item'], filters));
      assert.equal(response.rows[0].values[0], 0);
      assert.equal(response.filtersApplied, true);
    }
  });

  test('Filtros e projeções não representáveis falham antes de consultar o leitor', () => {
    const f = fixture();
    for (const filters of [
      [[{...includes(['A']), type:'EXCLUDE'}]], [[includes(['A'], 'REGEXP_PARTIAL_MATCH')]],
      [[{...includes(['A']), fieldName:'produto_codigo'}]], [[includes(['A','B'],'EQUALS')]],
      [[includes(Array(101).fill('X'))]], [[includes(['ab\0cd'])]], [[includes([13])]],
      [Array(17).fill(includes(['A']))], [[]]
    ]) {
      assertFarmaError(f, request(['quantidade'], filters), /DS_FILTRO_/);
    }
    for (const fields of [
      ['posicao_receita_top5','posicao_unidades_top5'], ['produto_nome','receita_item'],
      ['produtos_distintos_periodo','produto_codigo'], ['item_chave'], [], ['produto_nome','produto_nome']
    ]) {
      assertFarmaError(f, request(fields), /DS_CAMPOS_NAO_AUTORIZADOS/);
    }
    const strayFilter = request(['registros']);
    strayFilter.fields.push({name:'produto_nome', forFilterOnly:true});
    assertFarmaError(f, strayFilter, /DS_FILTRO_AGREGACAO_NAO_SUPORTADO/);
    assert.equal(f.calls.length, 0);
  });

  test('Amostra multigrão confirma o destino sem varrer dados; período normal exige datas reais', () => {
    const f = fixture();
    const fields = Array.from(f.ctx.NexoDSSchemas[table].columns);
    const req = {...request(fields), scriptParams:{sampleExtraction:true}};
    for (const range of [undefined, dateRange]) {
      const sample = f.ctx.getData({...req, dateRange:range});
      assert.equal(sample.rows.length, 0);
      assert.equal(sample.schema.length, fields.length);
    }
    assert.ok(f.calls.every(call => call.url.endsWith('/v1/destino')));
    const normal = request(['quantidade']);
    assertFarmaError(f, {...normal, dateRange:{}}, /DS_PERIODO_OBRIGATORIO/);
    for (const [startDate,endDate] of [
      ['2026-02-29','2026-03-01'], ['2026-11-09','2026-11-08'], ['0000-01-01','0000-01-02']
    ]) {
      assertFarmaError(f, {...normal, dateRange:{startDate,endDate}}, /DS_PERIODO_INVALIDO/);
    }
    assert.equal(f.calls.length, 2);
  });

  test('Período vazio, limites, versão, destino, campos e valores preservam respostas inteiras', () => {
    for (const [fields, rows] of [
      [['quantidade'], [[0]]], [['produto_codigo'], []], [['produto_nome','registros'], []]
    ]) {
      const f = fixture(p => result(p, rows));
      assert.equal(f.ctx.getData(request(fields)).rows.length, rows.length);
    }
    for (const [fields, rows, error] of [
      [['quantidade'], [], /DS_RESPOSTA_INCOMPLETA/], [['quantidade'], [[1],[1]], /DS_RESPOSTA_INCOMPLETA/],
      [['posicao_receita_top5'], [[1],[2],[3],[4],[5],[6]], /DS_RESPOSTA_INCOMPLETA/],
      [['posicao_unidades_top5'], [[2]], /DS_RESPOSTA_INCOMPLETA/],
      [['produto_codigo'], Array(50001).fill(['01']), /DS_RESPOSTA_INCOMPLETA/],
      [['receita_item'], [[null]], /DS_NUMERO_INVALIDO/], [['quantidade'], [['']], /DS_NUMERO_INVALIDO/],
      [['quantidade'], [['Infinity']], /DS_NUMERO_INVALIDO/], [['quantidade'], [[false]], /DS_NUMERO_INVALIDO/],
      [['registros'], [['1.2']], /DS_NUMERO_INVALIDO/], [['produto_codigo'], [[1]], /DS_SCHEMA_DIVERGENTE/],
      [['quantidade'], [[1,2]], /DS_SCHEMA_DIVERGENTE/], [['quantidade'], ['1'], /DS_SCHEMA_DIVERGENTE/],
      [['periodo_inicio'], [['2026-11-10']], /DS_DATA_INVALIDA/]
    ]) {
      assertFarmaError(fixture(p => result(p,rows)), request(fields), error);
    }
    for (const override of [
      {complete:false}, {version:0}, {version:'1'}, {protocol:'outro'}, {fields:[]},
      {schema_hash:'outro'}, {environment:'producao'}, {target:'nexoflow_datastudio_homologacao.pet'}
    ]) {
      const f = fixture(p => ({body:{...result(p,[[1]]).body,...override}}));
      assertFarmaError(f, request(['registros']), /DS_(RESPOSTA_INCOMPLETA|CONTRATO_DESTINO_DIVERGENTE)/);
    }
    for (const error of ['DS_PRODUTOS_BASE_INVALIDA','DS_REVISAO_ALTERADA']) {
      const f = fixture(() => ({status:409,body:{error,detail:'texto privado'}}));
      assertFarmaError(f, request(['receita_item']), new RegExp(error));
      assert.ok(!f.logs.join().includes('texto privado'));
    }
    let elapsed = 0;
    const late = fixture(p => { elapsed = 45001; return result(p,[[0]]); });
    late.ctx.Date = class extends Date { static now() { return elapsed; } };
    assertFarmaError(late, request(['receita_item']), /DS_PRAZO_CONSULTA/);
    const trace = JSON.parse(late.infos.at(-1));
    assert.deepEqual([trace.diagnostico, trace.modo, trace.inicio, trace.fim],
      ['produtos_farma', 'resumo', dateRange.startDate, dateRange.endDate]);
    assert.equal(trace.duracao_ms, 45001);
    assert.equal(trace.concluida, false);
    assert.equal(trace.versao, null);
    assert.equal(trace.linhas, null);
  });
};
