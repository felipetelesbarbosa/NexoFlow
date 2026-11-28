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
export const etapasNoturno = {
  atualizacao_weni: "Atualização Weni",
  analytics: "Analytics",
  publicacao: "Publicação PostgreSQL",
  recompra: "Recompra",
  analytics_final: "Analytics após Recompra",
} as const;
export const motivosNoturno = {
  RESERVA_FARMA: "Reserva FARMA: retirada do grupo Opt-Out LGPD adiada para a próxima carga.",
  COBERTURA_PARCIAL: "Anúncios: cobertura incompleta; verificar na próxima carga.",
  RESPOSTA_INCERTA: "Publicação sem confirmação: conferir a revisão e o recibo antes de repetir.",
  FONTE_ESSENCIAL_INCOMPLETA: "Fonte essencial incompleta: conferir a cobertura antes de publicar.",
} as const;
export const fontesNoturno = {
  weni: "Weni",
  farmalider: "FarmaLíder",
  meta: "Meta Ads",
} as const;
export const estadosFonte = {
  amostra_validada: "Amostra validada",
  validada: "Cobertura validada",
  parcial: "Parcial",
  pendente: "Pendente",
  nao_executada: "Não executada",
} as const;
export const motivosFonte = {
  CREDENCIAL_NAO_PROVISIONADA: "Credencial não provisionada",
  SAIDA_PRIVADA_NAO_CONFIGURADA: "Saída privada não configurada",
  ESCOPO_FARMA_HML_OBRIGATORIO: "Escopo de homologação não confirmado",
  LEITURA_NAO_CONFIRMADA: "Leitura não confirmada",
  CREDENCIAL_INVALIDA: "Credencial inválida",
  CONTEXTO_INCOMPLETO: "Contexto incompleto",
  LIMITE_AMOSTRA_EXCEDIDO: "Limite de coleta excedido",
  ESTADO_PRIVADO_AUSENTE: "Estado privado não provisionado",
  RESERVAS_NAO_CONFIRMADAS: "Reservas não confirmadas",
} as const;
export const etapasReplay = {
  validacao: "Validação da referência",
  weni: "Update Weni",
  recompra: "Recompra D+25",
  analytics: "Analytics",
  conferido: "Comparação encerrada",
} as const;
export const motivosReplay = {
  ESTADO_PRIVADO_AUSENTE: "Referência privada não provisionada",
  ESCOPO_FARMA_HML_OBRIGATORIO: "Escopo de homologação não confirmado",
  REFERENCIA_DIVERGENTE: "Referência ou checkpoint divergente",
  LIMITE_REFERENCIA_EXCEDIDO: "Limite de referência excedido",
  ESCRITA_O_REDE_BLOQUEADA: "Operação externa bloqueada",
} as const;
export const contagensReplay = {
  contatos: "Contatos existentes", planos: "Planos", campos: "Campos",
  grupos: "Ações de grupo", identicos: "Decisões idênticas",
  divergentes: "Divergências", inclusoes: "Inclusões", remocoes: "Remoções",
  trocas: "Trocas", sem_acao: "Sem ação de grupo", reservados: "Reservados",
  novos_pendentes: "Novos cadastros pendentes",
} as const;
export type EvidenciaReplay = {
  modo: "referencia_congelada";
  etapa: keyof typeof etapasReplay;
  etapa_pendente: keyof typeof etapasReplay | null;
  motivo: keyof typeof motivosReplay | null;
  ultimo_lote: number; lotes_total: number;
  retomada: boolean; paridade: boolean; revisao: "v15";
  contagens: Partial<Record<keyof typeof contagensReplay,number>>;
  weni_final?: Partial<Record<keyof typeof contagensReplay,number>>;
  recompra_final?: Partial<Record<keyof typeof contagensReplay,number>>;
};
export type EvidenciaNoturno = { modo: "sintetico" } | EvidenciaReplay | {
  modo: "leitura_real_amostral" | "planejamento_real";
  primeira_etapa_pendente: keyof typeof etapasNoturno | null;
  planejamento_motivo?: keyof typeof motivosFonte | null;
  planos?: { etapa: keyof typeof etapasNoturno; estado: "planejado" | "parcial" | "pendente" | "nao_executada" }[];
  fontes: {
    nome: keyof typeof fontesNoturno;
    estado: keyof typeof estadosFonte;
    origem: "real" | "nao_confirmada";
    cobertura_integral: boolean;
    motivo: keyof typeof motivosFonte | null;
  }[];
};
export type Tarefa = {
  id: string;
  estado: Estado;
  criado_em: string;
  atualizado_em: string;
  tipo?: string;
  motivos?: (keyof typeof motivosNoturno)[];
  evidencia?: EvidenciaNoturno;
  etapas?: { etapa: keyof typeof etapasNoturno; estado: Estado }[];
};
export type Evento = { tipo: string; ocorrido_em: string; recebido_em: string };
export type Segmento = "FARMA" | "PET";
export const isSegmento = (value: unknown): value is Segmento =>
  value === "FARMA" || value === "PET";
export const estadosWorker = {
  ativo: "Sinal recente",
  sinal_atrasado: "Sinal atrasado",
  sem_sinal: "Aguardando primeiro sinal",
} as const;
type Operacao = {
  worker_estado: keyof typeof estadosWorker;
  worker_ultimo_ciclo_em: string | null;
  fila_prontas: number;
  fila_em_espera: number;
  fila_leases_expirados: number;
  fila_espera_segundos: number | null;
  ultima_conclusao_em: string | null;
};
export const ambientes = {
  homologacao: "Homologação",
  producao: "Produção",
} as const;
export type Ambiente = keyof typeof ambientes;
export const isAmbiente = (value: unknown): value is Ambiente =>
  typeof value === "string" && Object.hasOwn(ambientes, value);

export type Resumo = {
  segmento: Segmento;
  segmentos_autorizados: Segmento[];
  ambiente: Ambiente;
  metricas: { habilitado: boolean };
  tarefas: Tarefa[];
  integracoes: { hub: "pronto"; processamento: Ambiente };
  eventos: Evento[];
  operacao?: Operacao | null;
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

function contagem(x: unknown): x is number {
  return typeof x === "number" && Number.isSafeInteger(x) && x >= 0;
}

function operacaoValida(x: unknown): boolean {
  if (x === undefined || x === null) return true;
  return (
    registro(x) &&
    typeof x.worker_estado === "string" &&
    Object.hasOwn(estadosWorker, x.worker_estado) &&
    (x.worker_estado === "sem_sinal"
      ? x.worker_ultimo_ciclo_em === null
      : instante(x.worker_ultimo_ciclo_em)) &&
    contagem(x.fila_prontas) &&
    contagem(x.fila_em_espera) &&
    contagem(x.fila_leases_expirados) &&
    (x.fila_prontas === 0
      ? x.fila_espera_segundos === null
      : contagem(x.fila_espera_segundos)) &&
    (x.ultima_conclusao_em === null || instante(x.ultima_conclusao_em))
  );
}

function evidenciaValida(x: unknown): boolean {
  if (x === undefined) return true;
  if (!registro(x)) return false;
  if (x.modo === "sintetico") return true;
  if (x.modo === "referencia_congelada") {
    return typeof x.etapa === "string" && Object.hasOwn(etapasReplay,x.etapa) &&
      (x.etapa_pendente === null || (typeof x.etapa_pendente === "string" && Object.hasOwn(etapasReplay,x.etapa_pendente))) &&
      (x.motivo === null || (typeof x.motivo === "string" && Object.hasOwn(motivosReplay,x.motivo))) &&
      contagem(x.ultimo_lote) && contagem(x.lotes_total) && x.ultimo_lote <= x.lotes_total &&
      typeof x.retomada === "boolean" && typeof x.paridade === "boolean" &&
      x.revisao === "v15" && registro(x.contagens) &&
      Object.entries(x.contagens).every(([k,v]) => Object.hasOwn(contagensReplay,k) && contagem(v)) &&
      [x.weni_final,x.recompra_final].every(r => r === undefined || (registro(r) &&
        Object.entries(r).every(([k,v]) => Object.hasOwn(contagensReplay,k) && contagem(v))));
  }
  return (x.modo === "leitura_real_amostral" || x.modo === "planejamento_real") &&
    (x.primeira_etapa_pendente === null || (
      typeof x.primeira_etapa_pendente === "string" &&
      Object.hasOwn(etapasNoturno, x.primeira_etapa_pendente))) &&
    (x.planejamento_motivo === undefined || x.planejamento_motivo === null ||
       (typeof x.planejamento_motivo === "string" && Object.hasOwn(motivosFonte, x.planejamento_motivo))) &&
    (x.planos === undefined || (Array.isArray(x.planos) && x.planos.length === 5 &&
      new Set(x.planos.map(p => registro(p) ? p.etapa : null)).size === 5 &&
      x.planos.every((p: unknown) => registro(p) && typeof p.etapa === "string" &&
        Object.hasOwn(etapasNoturno, p.etapa) &&
        ["planejado", "parcial", "pendente", "nao_executada"].includes(String(p.estado))))) &&
    Array.isArray(x.fontes) && x.fontes.length === 3 &&
    new Set(x.fontes.map(f => registro(f) ? f.nome : null)).size === 3 &&
    x.fontes.every((f: unknown) =>
      registro(f) && typeof f.nome === "string" && Object.hasOwn(fontesNoturno, f.nome) &&
      typeof f.estado === "string" && Object.hasOwn(estadosFonte, f.estado) &&
      (f.origem === "real" || f.origem === "nao_confirmada") &&
      typeof f.cobertura_integral === "boolean" &&
      (f.motivo === null || (typeof f.motivo === "string" && Object.hasOwn(motivosFonte, f.motivo))));
}

export function lerResumo(x: unknown): Resumo {
  const ok =
    registro(x) &&
    isSegmento(x.segmento) &&
    isAmbiente(x.ambiente) &&
    registro(x.metricas) &&
    typeof x.metricas.habilitado === "boolean" &&
    registro(x.integracoes) &&
    x.integracoes.hub === "pronto" &&
    x.integracoes.processamento === x.ambiente &&
    operacaoValida(x.operacao) &&
    Array.isArray(x.tarefas) &&
    x.tarefas.every(
      (t: unknown) =>
        registro(t) &&
        typeof t.id === "string" &&
        t.id.length > 0 &&
        typeof t.estado === "string" &&
        Object.hasOwn(estados, t.estado) &&
        instante(t.criado_em) &&
        instante(t.atualizado_em) &&
        evidenciaValida(t.evidencia) &&
        (t.motivos === undefined || (Array.isArray(t.motivos) && t.motivos.every((m: unknown) => typeof m === "string" && Object.hasOwn(motivosNoturno, m)))) &&
        (t.etapas === undefined ||
          (Array.isArray(t.etapas) &&
            t.etapas.every(
              (stage: unknown) =>
                registro(stage) &&
                typeof stage.etapa === "string" &&
                Object.hasOwn(etapasNoturno, stage.etapa) &&
                typeof stage.estado === "string" &&
                Object.hasOwn(estados, stage.estado),
            ))),
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
