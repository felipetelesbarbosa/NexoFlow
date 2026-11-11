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
    var api = options.api, hash = options.hash, started = Number.isFinite(options.startedAt) ? options.startedAt : Date.now(), consumed = 0, scanned = 0;
    var idPattern = /^[a-zA-Z0-9_-]{20,100}$/;
    var history = ['Historico_Pedidos','Historico_Itens','BI_LTV_Clientes','BI_Cobertura_Historica','BI_Historico_Resumo'];
    if (!idPattern.test(hub) || !titles.length || titles.some(function (t) { return options.schemas ? !Object.prototype.hasOwnProperty.call(options.schemas,t) : !/^BI_[A-Za-z0-9_]+$/.test(t); })) fail('origem inválida.');
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
    if (options.onManifest) options.onManifest(hash(stable(initial)));
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
    function origin(id, role) {
      if (!initial) return;
      var c = maps.config.principal, known = id === c.roots[role] || (maps.arquivo[id] && maps.arquivo[id].role === role);
      if (!known) fail('arquivo não pertence ao dashboard.');
      var tags = (meta(id).developerMetadata || []).filter(function (m) { return m.metadataKey === 'nexoflow_continuation_origin_v1'; });
      if (tags.length !== 1 || tags[0].visibility !== 'DOCUMENT' || !tags[0].location || tags[0].location.spreadsheet !== true) fail('origem não comprovada.');
      var tag;
      try { tag = JSON.parse(tags[0].metadataValue); } catch (_) { fail('origem inválida.'); }
      if (tag.hub !== hub || tag.segment !== c.segment || tag.role !== role) fail('segmento do arquivo divergente.');
    }
    origin(hub, 'dashboard');
    if (options.schemaOnly === true) {
      if (!initial || !options.schemas || !['FARMA','PET'].includes(options.segment)) fail('vinculação exige manifesto, registro e segmento.');
      var roots=maps.config.principal.roots, roles=['dashboard','operacao','historico'];
      if (roles.some(function(role){return !idPattern.test(roots[role]||'');}) || new Set(roles.map(function(role){return roots[role];})).size!==3) fail('três origens distintas são obrigatórias.');
      roles.forEach(function(role){origin(roots[role],role);});
      // Somente cabeçalhos do registro autorizado. Não consultar linhas de fatos,
      // exigir READY ou alegar que uma fonte vazia já foi conciliada.
      var definitions=titles.map(function(title){return [options.schemas[title].map(function(spec){return spec[0];})];});
      delete metadata[hub];
      if (stable(indexValues()) !== stable(initial)) fail('a carga mudou durante a vinculação; tente novamente.');
      return definitions;
    }
    // Uma raiz legada registrada durante o planejamento ainda não foi publicada
    // pelo gerenciador. Sua conferência não fabrica estado READY no manifesto.
    var bootstrapRead = false;
    function legacyWriterFree() {
      var locks = (meta(hub).developerMetadata || []).filter(function(m) { return m.metadataKey==='nexoflow_continuation_writer_v1' || m.metadataId===191126102; });
      if (!locks.length) return;
      if (locks.length!==1) fail('trava do gravador remoto inconsistente.');
      var lock=locks[0], value;
      try { value=JSON.parse(lock.metadataValue); } catch (_) { fail('trava do gravador remoto inválida.'); }
      if (lock.metadataId!==191126102 || lock.metadataKey!=='nexoflow_continuation_writer_v1' || lock.visibility!=='DOCUMENT' || !lock.location || lock.location.spreadsheet!==true || !value || !/^[a-f0-9]{32}$/.test(value.owner || '') || typeof value.expires!=='number' || !Number.isFinite(value.expires)) fail('trava do gravador remoto inválida.');
      if (Date.now()/1000<=value.expires+60) fail('gravador ativo ou em recuperação; aguarde antes de conferir o legado.');
    }
    var physical = new Set();
    var result = titles.map(function (title) {
      var historical = history.includes(title), role = title.startsWith('Historico_') ? 'historico' : 'dashboard', keys = new Set();
      if (historical && (!initial || (maps.config.principal.history_publication && maps.config.principal.history_publication.state !== 'READY'))) fail('histórico em publicação; nenhum total parcial foi retornado.');
      var state = maps.estado[title], registered = Object.keys(maps.parte).map(function (k) {
        var p = maps.parte[k];
        if (k !== p.title + '#' + p.number) fail('chave de parte divergente.');
        return p;
      }).filter(function (p) { return p.title === title; }).sort(function (a, b) { return a.number - b.number; });
      var bootstrap = !!(initial && options.schemas && titles.length===1 && title==='BI_Itens' && !state && registered.length===1 && registered[0].number===0 && registered[0].book_id===hub && registered[0].width===options.schemas[title].length && /^[a-f0-9]{64}$/.test(registered[0].schema || '') && !Object.keys(maps.criacao).some(function(key) { return key.startsWith(title+'#') || maps.criacao[key].title===title; }));
      if (bootstrap) { legacyWriterFree(); bootstrapRead=true; }
      if (state && state.state !== 'READY') fail('tabela em atualização. Aguarde a carga terminar.');
      if (registered.length && !bootstrap && (!state || state.state !== 'READY' || !Array.isArray(state.parts) || state.parts.length !== registered.length)) fail('tabela em atualização ou sem confirmação. Aguarde a carga terminar.');
      if (historical && !registered.length) fail('tabela histórica sem partes confirmadas.');
      if (!registered.length) {
        var sheet = (meta(hub).sheets || []).find(function (s) { return s.properties.title === title; });
        if (!sheet) fail('aba BI obrigatória ausente.');
        registered = [{title: title, number: 0, book_id: hub, sheet_id: sheet.properties.sheetId}];
      }
      var combined = [], schema = null;
      registered.forEach(function (p, number) {
        if (p.number !== number || !idPattern.test(p.book_id)) fail('sequência de partes incompleta.');
        origin(p.book_id, role);
        var key = p.book_id + ':' + p.sheet_id;
        if (physical.has(key)) fail('aba vinculada mais de uma vez.');
        physical.add(key);
        var sheet = (meta(p.book_id).sheets || []).find(function (s) { return s.properties.sheetId === p.sheet_id && s.properties.title === title; });
        if (!sheet) fail('parte removida ou renomeada.');
        var width = p.width || options.widths[title], end = letter(width);
        if (!width || width > 300) fail('largura de tabela inválida.');
        var header = api.values(p.book_id, "'" + title + "'!A1:" + end + '1')[0];
        if (!header || header.length !== width || (p.schema && hash(stable(header)) !== p.schema) || (schema && stable(header) !== stable(schema))) fail('cabeçalho divergente entre partes.');
        if (options.schemas && stable(header) !== stable(options.schemas[title].map(function (s) { return s[0]; }))) fail('schema não corresponde ao registro autorizado.');
        if (!schema) { schema = header; combined.push(header); }
        var count = state && state.parts.find(function (r) { return r.number === number; });
        if (state && (!count || !Number.isInteger(count.rows) || count.rows < 0)) fail('contagem de linhas inválida.');
        var rows = count ? count.rows : Math.max(0, sheet.properties.gridProperties.rowCount - 1), actual = 0;
        if (rows > sheet.properties.gridProperties.rowCount - 1) fail('parte incompleta.');
        for (var start = 2; start <= sheet.properties.gridProperties.rowCount; start += 4000) {
          if (Date.now() - started > 240000) fail('tempo de consulta excedido; reduza o volume da fonte.');
          var data = api.values(p.book_id, "'" + title + "'!A" + start + ':' + end + Math.min(sheet.properties.gridProperties.rowCount, start + 3999));
          data.forEach(function (row) {
            if (!row.some(function (v) { return v !== '' && v !== null; })) return;
            if (row.length > width) fail('linha maior que o cabeçalho.');
            actual++;
            if (++scanned > 1000000) fail('consulta acima de um milhão de linhas lidas; use as tabelas de resumo ou uma fonte de maior capacidade. Nenhum resultado parcial foi retornado.');
            row = row.concat(Array(width - row.length).fill(''));
            if (bootstrap) {
              var itemKey=row[header.indexOf('item_chave')];
              if (typeof itemKey!=='string' || !itemKey || keys.has(itemKey)) fail('chave de item legada ausente ou duplicada.');
              keys.add(itemKey);
              options.schemas[title].forEach(function(spec,i) {
                var value=row[i]; if (value==='' || value===null) return;
                if (spec[1]==='number' && (typeof value!=='number' || !Number.isFinite(value))) fail('medida legada sem tipo numérico.');
                if (spec[1]==='text' && typeof value!=='string') fail('identificador legado sem tipo texto.');
                if (spec[1]==='date' && options.date) options.date(value);
              });
            }
            if (historical) {
              var keyIndex=header.indexOf('chave'), segIndex=header.indexOf('segmento');
              if (keyIndex<0 || typeof row[keyIndex]!=='string' || !row[keyIndex] || keys.has(row[keyIndex])) fail('chave histórica ausente ou duplicada entre partes.');
              keys.add(row[keyIndex]);
              if (row[segIndex]!==maps.config.principal.segment) fail('linha histórica de outro segmento.');
              if (!options.schemas) fail('registro de schema histórico obrigatório.');
              options.schemas[title].forEach(function (s,i) {
                var v=row[i]; if (v==='' || v===null) return;
                if (s[1]==='number' && (typeof v!=='number' || !Number.isFinite(v))) fail('medida histórica sem tipo numérico.');
                if (s[1]==='text' && typeof v!=='string') fail('identificador histórico sem tipo texto.');
                if (s[1]==='date' && options.date) options.date(v);
              });
              if (row[header.indexOf('vigente')]!=='Sim') return;
            }
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
    if (bootstrapRead) legacyWriterFree();
    if (options.onManifest) options.onManifest(hash(stable(initial)));
    return result;
  }
  return {read: read, stable: stable};
})();
if (typeof module !== 'undefined') module.exports = NexoTables;
