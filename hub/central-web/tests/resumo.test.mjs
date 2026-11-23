import test from "node:test";
import assert from "node:assert/strict";
import {
  lerResumo,
  janela,
  horaLocal,
  ativos,
  atencao,
} from "../src/resumo.ts";

const sample = {
  segmento: "FARMA",
  ambiente: "homologacao",
  metricas: { habilitado: false },
  integracoes: { hub: "pronto", processamento: "homologacao" },
  tarefas: [],
  eventos: [],
};

test("vazio confirmado fica vazio e resposta inválida é recusada", () => {
  assert.equal(lerResumo(sample).eventos.length, 0);
  for (const fields of [
    { eventos: null },
    { metricas: { habilitado: true } },
    { ambiente: "producao" },
    { tarefas: [{}] },
  ]) {
    assert.throws(() => lerResumo({ ...sample, ...fields }));
  }
});
test("datas inclusivas usam ocorrência de criação e de recebimento em Belém", () => {
  const tarefa = (t) => ({
    id: t,
    estado: "concluida",
    criado_em: t,
    atualizado_em: t,
  });
  const dados = lerResumo({
    ...sample,
    tarefas: [
      "2026-11-20T02:59:59Z",
      "2026-11-20T03:00:00Z",
      "2026-11-21T02:59:59Z",
    ].map(tarefa),
    eventos: [
      {
        tipo: "transferencia",
        ocorrido_em: "2026-11-19T14:00:00Z",
        recebido_em: "2026-11-20T14:00:00Z",
      },
    ],
  });
  const s = janela(dados, 1, new Date("2026-11-21T02:59:59Z"));
  assert.deepEqual(s.serie, [{ dia: "2026-11-20", tarefas: 2, eventos: 1 }]);
  assert.equal(s.tarefas[0].id, "2026-11-21T02:59:59Z");
  assert.match(horaLocal(s.tarefas[0].id), /^20\/11\/26 23:59:59$/);
});
test("falhas e revisões exigem atenção; trabalho pendente entra na fila", () => {
  assert.equal(ativos("pendente"), true);
  assert.equal(ativos("falhou"), false);
  assert.equal(atencao("revisao_necessaria"), true);
  assert.equal(atencao("parcial"), true);
});

test("a lista de segmentos pertence à resposta e à identidade atual", () => {
  assert.deepEqual(lerResumo(sample).segmentos_autorizados, ["FARMA"]);
  assert.deepEqual(
    lerResumo({ ...sample, segmentos_autorizados: ["FARMA", "PET"] })
      .segmentos_autorizados,
    ["FARMA", "PET"],
  );
  for (const scopes of [
    [],
    ["PET"],
    ["FARMA", "FARMA"],
    ["FARMA", "OUTRO"],
    null,
  ]) {
    assert.throws(() =>
      lerResumo({ ...sample, segmentos_autorizados: scopes }),
    );
  }
});
