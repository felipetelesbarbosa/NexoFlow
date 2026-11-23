export const estados = {
  pendente: "Pendente",
  executando: "Executando",
  aguardando: "Aguardando",
  concluida: "Concluída",
  parcial: "Parcial",
  falhou: "Falhou",
  revisao_necessaria: "Revisão necessária",
} as const;

export type Estado = keyof typeof estados;
export type Tarefa = {
  id: string;
  estado: Estado;
  criado_em: string;
  atualizado_em: string;
};
export type Evento = { tipo: string; ocorrido_em: string; recebido_em: string };
export type Segmento = "FARMA" | "PET";
export const isSegmento = (value: unknown): value is Segmento =>
  value === "FARMA" || value === "PET";
export type Resumo = {
  segmento: Segmento;
  segmentos_autorizados: Segmento[];
  ambiente: "homologacao";
  metricas: { habilitado: false };
  tarefas: Tarefa[];
  integracoes: { hub: "pronto"; processamento: "homologacao" };
  eventos: Evento[];
};

export const fuso = "America/Belem";
const dia = new Intl.DateTimeFormat("sv-SE", {
  timeZone: fuso,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const momento = new Intl.DateTimeFormat("pt-BR", {
  timeZone: fuso,
  day: "2-digit",
  month: "2-digit",
  year: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});
export const dataLocal = (s: string | Date) => dia.format(new Date(s));
export const horaLocal = (s: string | Date) =>
  momento.format(new Date(s)).replace(",", "");

function registro(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

function instante(x: unknown): x is string {
  return (
    typeof x === "string" &&
    /T.*(Z|[+-]\d{2}:\d{2})$/.test(x) &&
    Number.isFinite(Date.parse(x))
  );
}

export function lerResumo(x: unknown): Resumo {
  const ok =
    registro(x) &&
    isSegmento(x.segmento) &&
    x.ambiente === "homologacao" &&
    registro(x.metricas) &&
    x.metricas.habilitado === false &&
    registro(x.integracoes) &&
    x.integracoes.hub === "pronto" &&
    x.integracoes.processamento === "homologacao" &&
    Array.isArray(x.tarefas) &&
    x.tarefas.every(
      (t: unknown) =>
        registro(t) &&
        typeof t.id === "string" &&
        t.id.length > 0 &&
        typeof t.estado === "string" &&
        Object.hasOwn(estados, t.estado) &&
        instante(t.criado_em) &&
        instante(t.atualizado_em),
    ) &&
    Array.isArray(x.eventos) &&
    x.eventos.every(
      (e: unknown) =>
        registro(e) &&
        typeof e.tipo === "string" &&
        e.tipo.length > 0 &&
        instante(e.ocorrido_em) &&
        instante(e.recebido_em),
    );
  if (!ok || !isSegmento(x.segmento))
    throw new Error("Resposta incompatível com a versão da Central.");
  const scopes = Object.hasOwn(x, "segmentos_autorizados")
    ? x.segmentos_autorizados
    : [x.segmento];
  if (
    !Array.isArray(scopes) ||
    !scopes.every(isSegmento) ||
    new Set(scopes).size !== scopes.length ||
    !scopes.includes(x.segmento)
  )
    throw new Error("Segmentos incompatíveis com a resposta da Central.");
  return { ...(x as Resumo), segmentos_autorizados: scopes };
}

export const ativos = (estado: Estado) =>
  ["pendente", "executando", "aguardando"].includes(estado);
export const atencao = (estado: Estado) =>
  ["parcial", "falhou", "revisao_necessaria"].includes(estado);

export function janela(s: Resumo, dias: number, agora: Date) {
  const final = dataLocal(agora);
  const marcos = Array.from({ length: dias }, (_, i) =>
    new Date(Date.parse(final + "T12:00:00Z") - (dias - i - 1) * 86400000)
      .toISOString()
      .slice(0, 10),
  );
  const dentro = (instante: string) => {
    const dia = dataLocal(instante);
    return dia >= marcos[0] && dia <= final;
  };
  const tarefas = s.tarefas
    .filter((t) => dentro(t.criado_em))
    .sort((a, b) => Date.parse(b.criado_em) - Date.parse(a.criado_em));
  const eventos = s.eventos
    .filter((e) => dentro(e.recebido_em))
    .sort((a, b) => Date.parse(b.recebido_em) - Date.parse(a.recebido_em));
  const serie = marcos.map((dia) => ({
    dia,
    tarefas: tarefas.filter((t) => dataLocal(t.criado_em) === dia).length,
    eventos: eventos.filter((e) => dataLocal(e.recebido_em) === dia).length,
  }));
  return { tarefas, eventos, serie };
}
