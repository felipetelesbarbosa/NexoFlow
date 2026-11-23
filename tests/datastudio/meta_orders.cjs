const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const folder = path.join(__dirname, '../../connectors/datastudio_api');
const source = 'Pedidos_Atribuiveis_Meta';

function sdkFields() {
  const fields = [];
  function add() {
    const field = {
      setId(id) { this.id = id; return this; },
      setName() { return this; },
      setType(type) { this.type = type; return this; },
      setAggregation() { return this; }
    };
    fields.push(field);
    return field;
  }
  return {
    newDimension: add,
    newMetric: add,
    build: () => fields,
    forIds: ids => ({
      build: () => fields.filter(f => ids.includes(f.id)).map(f => ({name:f.id, type:f.type}))
    })
  };
}

function contact(id, purchase = '2026-11-09T10:00:00-03:00', ad = '2026-11-06T10:00:00-03:00', origin = 'Meta Ads') {
  return {pedido_id:id, pedido_data:purchase, primeiro_anuncio_data:ad, primeiro_anuncio_origem:origin};
}

function order(id, amount = '130.90', valid = '1') {
  return {
    pedido_id:id, venda_valida:valid, data:'2026-11-09', cliente:'Pessoa sintética',
    cliente_chave:'c-sintetica', pedido_produtos:'Itens de teste', pedido_faturamento_total:amount
  };
}

function request(names = ['pedido_id'], filters = []) {
  return {
    configParams: {segmento:'FARMA', ambiente:'homologacao', tabela:source},
    // Período da coorte no lado de contatos da mesclagem. A tabela de cabeçalhos
    // à direita ainda deve encontrar compras posteriores, como a de 09/11.
    dateRange: {startDate:'2026-11-06', endDate:'2026-11-06'},
    fields: names.map(name => ({name})),
    dimensionsFilters: filters
  };
}

function fixture(contacts, orders, intercept) {
  const calls = [], logs = [];
  let now = 0;
  class Clock extends Date { static now() { return now; } }
  const cc = {
    getFields: sdkFields,
    FieldType: {TEXT:'text', NUMBER:'number', YEAR_MONTH_DAY:'date', CURRENCY_BRL:'BRL'},
    AggregationType: {SUM:'sum', MAX:'max'},
    newUserError: () => ({setText: message => ({throwException() { throw Error(message); }})})
  };
  const conf = {protocol:'nexoflow_datastudio_1', environment:'homologacao', segment:'FARMA',
    endpoint:'https://reader.example.invalid', api_token:'synthetic', access_client_id:'synthetic', access_client_secret:'synthetic'};
  const ctx = {
    Date: Clock, DataStudioApp: {createCommunityConnector: () => cc}, console: {error: value => logs.push(JSON.parse(value).codigo)},
    PropertiesService: {getScriptProperties: () => ({getProperty: () => JSON.stringify(conf)})},
    Utilities: {newBlob: v => ({getBytes:() => Buffer.from(v)}), sleep(ms) { now += ms; }},
    UrlFetchApp: {fetch(url, options) {
      assert.equal(url, 'https://reader.example.invalid/v1/consulta');
      const p = JSON.parse(options.payload);
      calls.push(p);
      assert.ok(['Base_Contatos', 'BI_Pedidos'].includes(p.table));
      assert.equal(p.start, '');
      assert.equal(p.end, '');
      const records = p.table === 'Base_Contatos' ? contacts : orders;
      const filtered = records.filter(row => p.filters.every(f => f.values.includes(row[f.field])));
      const body = {
        protocol:conf.protocol, target:'nexoflow_datastudio_homologacao.farma', segment:conf.segment,
        environment:conf.environment, schema_hash:ctx.NexoDSSchemaHash, version:2,
        fields:p.fields, complete:true, rows:filtered.map(row => p.fields.map(f => row[f] ?? null))
      };
      const reply = intercept?.({p, calls, body, advance: ms => { now += ms; }}) || {};
      return {getResponseCode: () => reply.status ?? 200, getContentText: () => JSON.stringify(reply.body ?? body)};
    }}
  };
  vm.createContext(ctx);
  for (const name of ['Schemas.js','AbcCore.js','Code.js']) vm.runInContext(fs.readFileSync(path.join(folder, name),'utf8'),ctx);
  return {ctx, calls, logs, run: r => ctx.getData(r)};
}

function assertFarmaError(f, req, code) {
  const before = f.logs.length;
  assert.throws(() => f.run(req), e => /Falha ao carregar os dados|A consulta demorou|O período selecionado/.test(e.message) && !e.message.includes('DS_'));
  assert.equal(f.logs.length, before + 1);
  assert.match(f.logs.at(-1), code);
}

function records(result) {
  return Array.from(result.rows, row => Object.fromEntries(
    Array.from(result.schema, (field, i) => [field.name, row.values[i]])
  ));
}

function ordersRequested(calls) {
  return calls.filter(c => c.table === 'BI_Pedidos').flatMap(c => {
    const ids = c.filters.find(f => f.field === 'pedido_id').values;
    assert.ok(ids.length > 0 && ids.length <= 100);
    return ids;
  });
}

test('Meta usa o primeiro anúncio e instantes reais para buscar os cabeçalhos elegíveis uma vez', () => {
  const contacts = [
    contact('00012'), contact('00012'), contact('excluido-pelo-status'), contact('outra-origem', undefined, undefined, 'orgânico'),
    contact('anterior', '2026-11-06T13:00:00.001098Z', '2026-11-06T10:00:00.001099-03:00'),
    contact('igual','2026-11-06T13:00:00Z'),
    contact('sem-data', null), contact(null)
  ];
  const f = fixture(contacts, [order('00012'), order('excluido-pelo-status','9.00','0'), order('igual','10.99'),
    order('outra-origem'), order('anterior'), order('sem-data')]);
  const result = f.run(request(['data','pedido_faturamento_total','pedido_id']));
  assert.deepEqual(f.calls[0].filters, [{field:'primeiro_anuncio_origem',values:['Meta Ads']}]);
  assert.deepEqual([...f.calls[0].fields].sort(), ['pedido_data','pedido_id','primeiro_anuncio_data']);
  assert.deepEqual(ordersRequested(f.calls).sort(), ['00012','excluido-pelo-status','igual'].sort());
  assert.deepEqual(records(result).sort((a,b) => a.pedido_id.localeCompare(b.pedido_id)), [
    {data:'20261109', pedido_faturamento_total:130.90, pedido_id:'00012'},
    {data:'20261109', pedido_faturamento_total:10.99, pedido_id:'igual'}
  ]);
  assert.equal(result.schema.find(f => f.name === 'pedido_faturamento_total').type, 'BRL');
  assert.equal(f.ctx.NexoDSSchemas[source].period, null);
});

test('Meta com datas ausentes ou sem compra devolve vazio; data inválida não autoriza a associação', () => {
  const empty = fixture([contact(null), contact('ausencia', null)], []);
  assert.deepEqual(records(empty.run(request())), []);
  assert.deepEqual(ordersRequested(empty.calls), []);
  const bad = fixture([contact('invalido','2026-02-30T15:00:00-03:00')], []);
  assertFarmaError(bad, request(), /DS_DATA_INVALIDA/);
});

test('Meta respeita interseções dos filtros de pedido; filtros de outro campo ficam completos para o Looker', () => {
  const idFilter = values => ({fieldName:'pedido_id', type:'INCLUDE', operator:'IN_LIST', values});
  const f = fixture([contact('001'),contact('002')], [order('001'),order('002','99.99')]);
  const selected = request(['pedido_faturamento_total'], [[idFilter(['001','002'])],[idFilter(['002','003'])]]);
  selected.fields.push({name:'pedido_id', forFilterOnly:true});
  const result = f.run(selected);
  assert.equal(result.filtersApplied, true);
  assert.deepEqual(records(result), [{pedido_faturamento_total:99.99}]);
  assert.deepEqual(ordersRequested(f.calls), ['002']);
  const all = fixture([contact('001'),contact('002')], [order('001'),order('002','99.99')]);
  const mixed = request(['pedido_id'], [[idFilter(['001'])],[{fieldName:'cliente',type:'INCLUDE',operator:'CONTAINS',values:['Pessoa']}]]);
  mixed.fields.push({name:'cliente',forFilterOnly:true});
  const fallback = all.run(mixed);
  assert.equal(fallback.filtersApplied, false);
  assert.deepEqual(records(fallback), [
    {pedido_id:'001', cliente:'Pessoa sintética'}, {pedido_id:'002',cliente:'Pessoa sintética'}
  ]);
});

test('Meta mantém os lotes de IDs dentro do contrato e não entrega mistura de revisões', () => {
  const contacts = Array.from({length:205}, (_,i) => contact(String(i).padStart(4,'0')));
  const orders = contacts.map(c => order(c.pedido_id));
  const ok = fixture(contacts, orders);
  assert.equal(records(ok.run(request())).length, 205);
  assert.deepEqual(ordersRequested(ok.calls).sort(), contacts.map(c => c.pedido_id));
  const changed = fixture(contacts, orders, ({p,body,calls}) => {
    if (p.table === 'BI_Pedidos' && calls.filter(c => c.table === 'BI_Pedidos').length >= 2) body.version = calls.length;
  });
  assertFarmaError(changed, request(), /^DS_[A-Z0-9_]+$/);
});

test('Meta recusa duplicidade de cabeçalho, resposta parcial ou cabeçalho não solicitado', () => {
  const duplicated = fixture([contact('001')], [order('001'),order('001')]);
  assertFarmaError(duplicated, request(), /^DS_[A-Z0-9_]+$/);
  for (const change of ['partial','other-key']) {
    const bad = fixture([contact('001')], [order('001')], ({p,body}) => {
      if (p.table === 'BI_Pedidos') {
        if (change === 'partial') body.complete = false;
        else body.rows[0][p.fields.indexOf('pedido_id')] = 'pedido-inesperado';
      }
    });
    assertFarmaError(bad, request(), /^DS_[A-Z0-9_]+$/);
  }
});

test('Meta conserva a retentativa de falhas transitórias e o prazo total da operação', () => {
  let attempts = 0;
  const recovered = fixture([contact('001')],[order('001')], ({p}) => {
    if (p.table === 'BI_Pedidos' && ++attempts === 1) return {status:503,body:{}};
  });
  assert.deepEqual(records(recovered.run(request())), [{pedido_id:'001'}]);
  assert.equal(attempts, 2);
  const late = fixture([contact('001')],[order('001')], ({p,advance}) => {
    if (p.table === 'BI_Pedidos') advance(60_000);
  });
  assertFarmaError(late, request(), /^DS_[A-Z0-9_]+$/);
});

test('Meta propaga o limite do leitor; um retorno parcial jamais vira conjunto vazio válido', () => {
  const limited = fixture([contact('001')],[order('001')], ({p}) => {
    if (p.table === 'BI_Pedidos') return {status:409,body:{error:'DS_CONSULTA_EXCEDE_LIMITE_USE_RESUMO_OU_PERIODO'}};
  });
  assertFarmaError(limited, request(), /DS_CONSULTA_EXCEDE_LIMITE/);
});

test('Meta restringe a fonte ao segmento FARMA antes de consultar o leitor', () => {
  const f = fixture([], []);
  const pet = request();
  pet.configParams.segmento = 'PET';
  assert.throws(() => f.run(pet), /DS_CONFIGURACAO_INVALIDA/);
  assert.equal(f.calls.length, 0);
});

test('Meta conta bytes UTF-8 no conjunto de lotes antes de devolver o resultado', () => {
  const contacts = Array.from({length:180}, (_, i) => contact(String(i)));
  const headers = contacts.map(row => order(row.pedido_id));
  const req = request(['pedido_id','pedido_produtos']);
  for (const char of ['a', 'á']) {
    const description = char.repeat(21000);
    for (const header of headers) header.pedido_produtos = description;
    const f = fixture(contacts, headers, ({p, body}) => {
      if (p.table === 'BI_Pedidos') assert.ok(Buffer.byteLength(JSON.stringify(body)) < 7000000);
    });
    if (char === 'a') assert.equal(f.run(req).rows.length, 180);
    else assertFarmaError(f, req, /DS_RESPOSTA_EXCEDE_LIMITE/);
    assert.equal(f.calls.filter(p => p.table === 'BI_Pedidos').length, 2);
  }
});

test('Mesclagem sintética preserva as quatro janelas de novembro e o intervalo de janeiro a novembro', () => {
  function visitor(id, adDay, purchaseDay, origin) {
    const timestamp = day => '2026-11-' + day + 'T10:00:00-03:00';
    return contact(id, purchaseDay ? timestamp(purchaseDay) : null, timestamp(adDay), origin);
  }
  const contacts = [
    visitor('A','02','02'), visitor('B','04','04'), visitor('C','06','09'),
    visitor('antes','06','05'), visitor(null,'06',null),
    ...Array.from({length:34}, () => visitor(null,'03',null)),
    contact('agosto', '2026-08-10T09:00:00-03:00', '2026-08-07T22:00:00-03:00'),
    visitor('outra origem','16','17','Outros')
  ];
  const headers = [order('A','90.80'), order('B','100.99'), order('C','130.90'), order('antes','400.00'),
    {...order('agosto','50.35'), data:'2026-08-10'}, order('outra origem','999.00')];
  const windows = [
    ['2026-11-01','2026-11-17',39,3,32269], ['2026-11-01','2026-11-15',39,3,32269],
    ['2026-11-06','2026-11-06',3,1,13090], ['2026-11-16','2026-11-17',0,0,0],
    ['2026-01-01','2026-11-15',40,4,37304]
  ];
  for (const [startDate, endDate, count, matched, cents] of windows) {
    const req = request(['pedido_id','pedido_faturamento_total']);
    req.dateRange = {startDate, endDate};
    const f = fixture(contacts, headers);
    const right = new Map(records(f.run(req)).map(row => [row.pedido_id, row.pedido_faturamento_total]));
    assert.equal(right.size, 4);
    const cohort = contacts.filter(row => {
      const day = row.primeiro_anuncio_data.slice(0, 10);
      return row.primeiro_anuncio_origem === 'Meta Ads' && day >= req.dateRange.startDate && day <= req.dateRange.endDate;
    });
    const amounts = cohort.map(row => right.get(row.pedido_id)).filter(value => value != null);
    assert.equal(cohort.length, count);
    assert.equal(amounts.length, matched);
    assert.equal(amounts.reduce((total, value) => total + Math.round(value * 100), 0), cents);
  }
});

const leftSource = 'Contatos_Atribuicao_Meta';

function visitor(uuid, pedido, when, firstAd, origin = 'Meta Ads') {
  return {
    ...contact(pedido, when, firstAd, origin),
    contact_uuid: uuid,
    primeiro_anuncio_id: 'anuncio-' + uuid
  };
}

function leftRequest(day, names = ['contact_uuid', 'coorte_primeiro_anuncio', 'pedido_apos_anuncio']) {
  const req = request(names);
  req.configParams.tabela = leftSource;
  req.dateRange = {startDate: day, endDate: day};
  return req;
}

test('Fontes Meta comparam instantes por contato e filtram pelo dia do anúncio em Belém', () => {
  const people = [
    visitor('a', '0017', '07/11/26 00:00:01', '2026-11-07T02:59:59Z'),
    // O mesmo ID já é elegível em a. Para b a compra ocorreu 90 minutos antes do anúncio.
    visitor('b', '0017', '2026-11-07T01:00:00Z', '2026-11-06T23:30:00-03:00'),
    visitor('c', null, null, '2026-11-06T18:00:00+02:00'),
    visitor('d', '0018', '2026-11-06T15:00:00', '06-11-2026 14:59'),
    // O cabeçalho deve ser acessível à direita. A coorte pertence a 05/11.
    visitor('e', '0019', '2026-11-06T03:00:01Z', '2026-11-06T02:59:59Z'),
    visitor('f', '0020', '2026-11-06T16:13:01.123445Z', '2026-11-06T13:13:01.123446-03:00'),
    visitor('g', '0021', '2026-11-06T14:00:00Z', '2026-11-06T13:00:00Z', 'Orgânico')
  ];
  const headers = [
    order('0017', '130.90'), order('0018', '15.05'), order('0019', '9.10'),
    order('0020', '950.00'), order('0021', '900.00')
  ];
  const f = fixture(people, headers);
  const req = leftRequest('2026-11-06', [
    'contact_uuid', 'primeiro_anuncio_id', 'primeiro_anuncio_origem',
    'primeiro_anuncio_data', 'pedido_id', 'pedido_data', 'coorte_primeiro_anuncio', 'pedido_apos_anuncio'
  ]);
  const result = f.run(req);
  assert.equal(result.schema.find(field => field.name === 'coorte_primeiro_anuncio').type, 'date');
  assert.equal(result.schema.find(field => field.name === 'pedido_apos_anuncio').type, 'text');
  const left = records(result).sort((a, b) => a.contact_uuid.localeCompare(b.contact_uuid));
  assert.deepEqual(left.map(row => [row.contact_uuid, row.coorte_primeiro_anuncio, row.pedido_apos_anuncio]), [
    ['a', '20261106', '0017'], ['b', '20261106', null], ['c', '20261106', null],
    ['d', '20261106', '0018'], ['f', '20261106', null]
  ]);
  for (const row of left) {
    const raw = people.find(person => person.contact_uuid === row.contact_uuid);
    for (const field of ['primeiro_anuncio_id', 'primeiro_anuncio_origem', 'primeiro_anuncio_data', 'pedido_id', 'pedido_data']) {
      assert.equal(row[field], raw[field]);
    }
  }
  const right = new Map(records(f.run(request(['pedido_id', 'pedido_faturamento_total'])))
    .map(row => [row.pedido_id, row.pedido_faturamento_total]));
  assert.deepEqual([...right.keys()].sort(), ['0017', '0018', '0019']);
  const amounts = left.map(row => right.get(row.pedido_apos_anuncio)).filter(value => value !== undefined);
  assert.equal(amounts.length, 2);
  assert.equal(amounts.reduce((sum, value) => sum + Math.round(value * 100), 0), 14595);
});

test('Fontes Meta respeitam o século de anos Weni e a hora repetida histórica de Belém', () => {
  const examples = [
    {uuid: 'y68', firstAd: '01/01/68 00:00', purchase: '2068-01-01T03:00:01Z', day: '2068-01-01'},
    {uuid: 'y69', firstAd: '01-01-69 00:00:00', purchase: '1969-01-01T03:00:01Z', day: '1969-01-01'},
    // As 23h50 locais ainda eram UTC-02 na primeira ocorrência. Às 23h10 UTC-03 já se passaram 20 min.
    {uuid: 'hora-repetida', firstAd: '14/03/86 23:50', purchase: '1986-03-14T23:10:00-03:00', day: '1986-03-14'}
  ];
  for (const {uuid, firstAd, purchase, day} of examples) {
    const f = fixture([visitor(uuid, uuid, purchase, firstAd)], [order(uuid)]);
    const left = records(f.run(leftRequest(day)));
    assert.deepEqual(left, [{
      contact_uuid: uuid, coorte_primeiro_anuncio: day.replaceAll('-', ''), pedido_apos_anuncio: uuid
    }], uuid);
    assert.deepEqual(records(f.run(request(['pedido_id']))), [{pedido_id: uuid}], uuid);
  }
});

test('Fontes Meta rejeitam data Weni não vazia impossível mesmo ao lado de um pedido válido', () => {
  const people = [
    visitor('valido', '01', '01/05/26 12:01', '01/05/26 12:00'),
    visitor('invalido', '02', '31/04/26 12:01', '01/05/26 12:00')
  ];
  const headers = [order('01'), order('02')];
  for (const req of [leftRequest('2026-05-01'), request(['pedido_id'])]) {
    const f = fixture(people, headers);
    assertFarmaError(f, req, /DS_DATA_INVALIDA/);
  }
});
