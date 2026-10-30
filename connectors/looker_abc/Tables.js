/* Leitor somente leitura das partes BI, compartilhado com o conector ABC. */
var NexoTables = (function () {
  'use strict';
  function fail(message) { throw new Error('Continuações: ' + message); }
  function stable(value) {
    if (Array.isArray(value)) return '[' + value.map(stable).join(',') + ']';
    if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(function (key) { return JSON.stringify(key) + ':' + stable(value[key]); }).join(',') + '}';
    return JSON.stringify(value);
  }
  function letter(n) { var text = ''; while (n > 0) { n--; text = String.fromCharCode(65 + n % 26) + text; n = Math.floor(n / 26); } return text; }
  function read(hub, titles, options) {
    var api = options.api, hash = options.hash, started = Date.now(), consumed = 0, scanned = 0;
    var idPattern = /^[a-zA-Z0-9_-]{20,100}$/;
    if (!idPattern.test(hub) || !titles.length || titles.some(function (t) { return !/^BI_[A-Za-z0-9_]+$/.test(t); })) fail('origem inválida.');
    var metadata = {}, initial = indexValues();
    function meta(id) {
      if (!metadata[id]) metadata[id] = api.meta(id);
      return metadata[id];
    }
    function indexValues() {
      var root = meta(hub), found = (root.sheets || []).some(function (s) { return s.properties.title === 'NexoFlow_Continuidade'; });
      return found ? api.values(hub, "'NexoFlow_Continuidade'!A1:C10000") : null;
    }
    if (!initial && !options.legacy) fail('configure primeiro o armazenamento no NexoFlow.');
    var maps = {config: {}, arquivo: {}, parte: {}, estado: {}, criacao: {}};
    if (initial) {
      if (stable(initial[0]) !== stable(['tipo', 'chave', 'valor']) || initial.length >= 10000) fail('índice inválido ou acima do limite.');
      initial.slice(1).forEach(function (r) {
        if (!r.length || !r.some(function (v) { return v !== ''; })) return;
        if (r.length !== 3 || !Object.prototype.hasOwnProperty.call(maps, r[0]) || Object.prototype.hasOwnProperty.call(maps[r[0]], r[1])) fail('registro inválido no índice.');
        var data;
        try { data = JSON.parse(r[2]); } catch (_) { fail('JSON inválido no índice.'); }
        if (!data || typeof data !== 'object' || Array.isArray(data)) fail('registro incompleto.');
        maps[r[0]][r[1]] = data;
      });
      var c = maps.config.principal;
      if (Object.keys(maps.config).length !== 1 || !c || c.format !== 1 || c.hub !== hub || c.enabled !== true || !['FARMA', 'PET'].includes(c.segment) || (options.segment && c.segment !== options.segment) || !c.roots || c.roots.dashboard !== hub) fail('perfil ou dashboard divergente.');
      Object.keys(maps.arquivo).forEach(function (id) {
        var info = maps.arquivo[id];
        if (!idPattern.test(id) || !c.roots[info.role] || !Number.isInteger(info.number) || info.number < 1 || info.source !== c.roots[info.role]) fail('arquivo fora do perfil.');
      });
    }
    function origin(id) {
      if (!initial) return;
      var c = maps.config.principal, known = id === hub || (maps.arquivo[id] && maps.arquivo[id].role === 'dashboard');
      if (!known) fail('arquivo não pertence ao dashboard.');
      var tags = (meta(id).developerMetadata || []).filter(function (m) { return m.metadataKey === 'nexoflow_continuation_origin_v1'; });
      if (tags.length !== 1 || tags[0].visibility !== 'DOCUMENT' || !tags[0].location || tags[0].location.spreadsheet !== true) fail('origem não comprovada.');
      var tag;
      try { tag = JSON.parse(tags[0].metadataValue); } catch (_) { fail('origem inválida.'); }
      if (tag.hub !== hub || tag.segment !== c.segment || tag.role !== 'dashboard') fail('segmento do arquivo divergente.');
    }
    origin(hub);
    var physical = new Set();
    var result = titles.map(function (title) {
      var state = maps.estado[title], registered = Object.keys(maps.parte).map(function (k) {
        var p = maps.parte[k];
        if (k !== p.title + '#' + p.number) fail('chave de parte divergente.');
        return p;
      }).filter(function (p) { return p.title === title; }).sort(function (a, b) { return a.number - b.number; });
      if (state && state.state !== 'READY') fail('tabela em atualização. Aguarde a carga terminar.');
      if (registered.length && (!state || state.state !== 'READY' || !Array.isArray(state.parts) || state.parts.length !== registered.length)) fail('tabela em atualização ou sem confirmação. Aguarde a carga terminar.');
      if (!registered.length) {
        var sheet = (meta(hub).sheets || []).find(function (s) { return s.properties.title === title; });
        if (!sheet) fail('aba BI obrigatória ausente.');
        registered = [{title: title, number: 0, book_id: hub, sheet_id: sheet.properties.sheetId}];
      }
      var combined = [], schema = null;
      registered.forEach(function (p, number) {
        if (p.number !== number || !idPattern.test(p.book_id)) fail('sequência de partes incompleta.');
        origin(p.book_id);
        var key = p.book_id + ':' + p.sheet_id;
        if (physical.has(key)) fail('aba vinculada mais de uma vez.');
        physical.add(key);
        var sheet = (meta(p.book_id).sheets || []).find(function (s) { return s.properties.sheetId === p.sheet_id && s.properties.title === title; });
        if (!sheet) fail('parte removida ou renomeada.');
        var width = p.width || options.widths[title], end = letter(width);
        if (!width || width > 300) fail('largura de tabela inválida.');
        var header = api.values(p.book_id, "'" + title + "'!A1:" + end + '1')[0];
        if (!header || header.length !== width || (p.schema && hash(stable(header)) !== p.schema) || (schema && stable(header) !== stable(schema))) fail('cabeçalho divergente entre partes.');
        if (!schema) { schema = header; combined.push(header); }
        var count = state && state.parts.find(function (r) { return r.number === number; });
        if (state && (!count || !Number.isInteger(count.rows) || count.rows < 0)) fail('contagem de linhas inválida.');
        var rows = count ? count.rows : Math.max(0, sheet.properties.gridProperties.rowCount - 1), actual = 0;
        if (rows > sheet.properties.gridProperties.rowCount - 1) fail('parte incompleta.');
        for (var start = 2; start <= rows + 1; start += 4000) {
          if (Date.now() - started > 240000) fail('tempo de consulta excedido; reduza o volume da fonte.');
          var data = api.values(p.book_id, "'" + title + "'!A" + start + ':' + end + Math.min(rows + 1, start + 3999));
          data.forEach(function (row) {
            if (!row.some(function (v) { return v !== '' && v !== null; })) return;
            if (row.length > width) fail('linha maior que o cabeçalho.');
            actual++;
            if (++scanned > 1000000) fail('consulta acima de um milhão de linhas lidas; use as tabelas de resumo ou uma fonte de maior capacidade. Nenhum resultado parcial foi retornado.');
            row = row.concat(Array(width - row.length).fill(''));
            if (options.accept && !options.accept(title, header, row)) return;
            if (++consumed > 200000) fail('resultado acima de 200 mil linhas; reduza o período ou use as tabelas de resumo. Nenhum resultado parcial foi retornado.');
            combined.push(row);
          });
        }
        if (count && actual !== count.rows) fail('quantidade de linhas diverge da carga confirmada.');
      });
      return combined;
    });
    if (Date.now() - started > 240000) fail('tempo de consulta excedido; reduza o volume da fonte.');
    delete metadata[hub];
    if (stable(indexValues()) !== stable(initial)) fail('a carga mudou durante a leitura; tente novamente.');
    return result;
  }
  return {read: read, stable: stable};
})();
if (typeof module !== 'undefined') module.exports = NexoTables;
