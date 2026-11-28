import type { Ambiente } from "./resumo";
import { useEffect, useRef, useState } from "react";
import {
  Activity, Braces, ChevronRight, CircleAlert, CircleCheck,
  Radio, RefreshCw, Waypoints, X,
} from "lucide-react";
import { horaLocal } from "./resumo";
import type { Segmento } from "./resumo";

const labels = { hub: "API do Hub", weni: "Webhook Weni" };
const monitored = {
  hub: { description: "Execuções e consultas do Hub", icon: Braces },
  weni: { description: "Eventos enviados pela Weni ao Hub", icon: Radio },
};
const awaiting = [
  { name: "FarmaLíder", description: "Consultas de clientes, pedidos, itens e histórico por segmento", origin: "Windows" },
  { name: "Weni Flows", description: "Consultas e atualizações de contatos, campos e grupos. Também fornece eventos e mensagens.", origin: "Windows" },
  { name: "PostgreSQL · Publicador", description: "Leitura de tabelas, envio de lotes e confirmação de revisões", origin: "Windows → VPS" },
  { name: "PostgreSQL · Leitor", description: "Consultas de relatórios à API da VPS", origin: "Relatórios → VPS" },
  { name: "Meta Ads", description: "Anúncios, campanhas e Insights nos perfis com a integração habilitada", origin: "Windows · quando habilitada" },
  { name: "Weni Insights e Chats", description: "Totais de conversas no Insights e leitura de atendimentos no Chats quando essas rotinas estão configuradas", origin: "Windows · sob configuração" },
  { name: "Google Sheets e Drive", description: "Integrações legadas, exportações e rotinas de migração", origin: "Windows · quando selecionado" },
];
const errorDescriptions: Record<string, string> = {
  SEGMENTO_NAO_AUTORIZADO: "A credencial desta chamada não tinha acesso ao segmento solicitado.",
  TAREFA_NAO_ENCONTRADA: "A execução não foi localizada no segmento autorizado.",
  IDEMPOTENCIA_CONFLITANTE: "A mesma chave foi usada com dados diferentes.",
  EVENTO_CONFLITANTE: "O identificador do evento já estava registrado com dados diferentes.",
  PARAMETROS_HISTORICO_INVALIDOS: "Um ou mais parâmetros do histórico não passaram na validação.",
  REQUISICAO_INVALIDA: "O formato da requisição não passou na validação.",
  SERVICO_INDISPONIVEL: "O Hub encontrou uma falha interna ao atender a chamada.",
};
type API = keyof typeof labels;
type RequestLog = {
  id: number;
  ocorrido_em: string;
  metodo: string;
  endpoint: string;
  http: number;
  duracao_ms: number;
  corpo: Record<string, string | number> | null;
  erro: string | null;
};
type Volume = { sucesso: number; erros: number };
type Consumption = {
  segmento: Segmento;
  resumo: (Volume & { api: API; total: number; p95_ms: number })[];
  serie: (Volume & { api: API; hora: string })[];
  requisicoes: RequestLog[];
  proximo: number | null;
};

const percent = new Intl.NumberFormat("pt-BR", {
  style: "percent", maximumFractionDigits: 2,
});

const integer = new Intl.NumberFormat("pt-BR");
const clock = new Intl.DateTimeFormat("pt-BR", {
  hour: "2-digit", minute: "2-digit", timeZone: "America/Belem",
});
const HOUR_MS = 3600000;

function Trend({ volumes, asOf }: { volumes: Consumption["serie"]; asOf: number }) {
  if (!volumes.length) return null;
  const lastHour = Math.floor(asOf / HOUR_MS) * HOUR_MS;
  const firstHour = lastHour - 24 * HOUR_MS;
  const peak = Math.max(1, ...volumes.map((point) => point.sucesso + point.erros));
  const countsByHour = new Map(volumes.map((point) => [Date.parse(point.hora), point]));
  return (
    <figure className="api-figure">
      <figcaption>
        <strong>Requisições por hora</strong>
        <span className="api-legend"><i className="api-dot-success" /> 2xx <i className="api-dot-error" /> Erros</span>
      </figcaption>
      <svg className="api-trend" viewBox="0 0 300 72" role="img"
        aria-label="Requisições por hora. As barras empilham respostas 2xx e erros. A tabela abaixo mostra os valores.">
        {[12, 36, 60].map((y) => (
          <line key={y} x1="0" x2="300" y1={y} y2={y} className="api-chart-grid" />
        ))}
        {Array.from({ length: 25 }, (_, i) => {
          const hour = firstHour + i * HOUR_MS;
          const point = countsByHour.get(hour);
          if (!point) return null;
          const x = i * 12 + 2;
          const success = 48 * point.sucesso / peak;
          const errors = 48 * point.erros / peak;
          return (
            <g key={hour}>
              <title>{horaLocal(point.hora)} · {point.sucesso} respostas 2xx · {point.erros} erros</title>
              <rect x={x} y={60 - success} width="8" height={success} className="api-success" />
              <rect x={x} y={60 - success - errors} width="8" height={errors} className="api-error" />
            </g>
          );
        })}
      </svg>
      <div className="api-axis">
        <span>Início · {clock.format(asOf - 24 * HOUR_MS)}</span>
        <span>Consulta · {clock.format(asOf)}</span>
      </div>
      <details className="api-hourly">
        <summary>Ver números por hora</summary>
        <table>
          <thead><tr><th scope="col">Hora (Belém)</th><th scope="col">HTTP 2xx</th><th scope="col">Erros</th></tr></thead>
          <tbody>{volumes.map((point) => <tr key={point.hora}><td>{horaLocal(point.hora)}</td><td>{point.sucesso}</td><td>{point.erros}</td></tr>)}</tbody>
        </table>
      </details>
    </figure>
  );
}

function Status({ status }: { status: number }) {
  const success = status >= 200 && status <= 299;
  return (
    <span className={"api-status " + (success ? "api-ok" : "api-failed")}>
      {success ? <CircleCheck size={14} aria-hidden="true" /> : <CircleAlert size={14} aria-hidden="true" />}
      HTTP {status}
    </span>
  );
}

function Overview({ summaries }: { summaries: Consumption["resumo"] }) {
  const totals = summaries.reduce((sum, row) => ({
    total: sum.total + row.total, success: sum.success + row.sucesso, errors: sum.errors + row.erros,
  }), { total: 0, success: 0, errors: 0 });
  const stats = [
    { label: "Requisições registradas", value: totals.total, icon: Activity, tone: "total" },
    { label: "Respostas HTTP 2xx", value: totals.success, icon: CircleCheck, tone: "good" },
    { label: "Respostas com erro", value: totals.errors, icon: CircleAlert, tone: "bad" },
  ];
  return (
    <div className="api-overview" aria-label="Totais das últimas 24 horas">
      {stats.map(({ label, value, icon: Icon, tone }) => (
        <div className={`panel api-stat api-stat-${tone}`} key={label}>
          <span className="api-stat-icon"><Icon size={18} aria-hidden="true" /></span>
          <div><span>{label}</span><strong>{integer.format(value)}</strong></div>
        </div>
      ))}
    </div>
  );
}

function RequestDetail({ item, api, close }: { item: RequestLog; api: API; close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => dialog.current?.showModal(), []);
  const response = { status: item.http, codigo_erro: item.erro };
  const log = JSON.stringify({
    requisicao: item.id,
    api: labels[api],
    ocorrido_em: item.ocorrido_em,
    metodo: item.metodo,
    endpoint: item.endpoint,
    duracao_ms: item.duracao_ms,
    corpo: item.corpo,
    resposta: response,
  }, null, 2);
  const [copied, setCopied] = useState("");
  return (
    <dialog className="drawer" ref={dialog} aria-labelledby="request-title" onClose={close}>
      <div className="section-head">
        <h2 id="request-title">Requisição {item.id}</h2>
        <button className="plain" onClick={() => dialog.current?.close()} aria-label="Fechar requisição"><X size={20} /></button>
      </div>
      <p>{labels[api]} · {horaLocal(item.ocorrido_em)} · Belém</p>
      <p className="api-endpoint"><code>{item.metodo} {item.endpoint}</code></p>
      <div className="api-result-line">
        <Status status={item.http} /> <span>{integer.format(item.duracao_ms)} ms</span>
      </div>
      {item.erro && errorDescriptions[item.erro] && (
        <p className="api-error-explanation">{errorDescriptions[item.erro]}</p>
      )}
      <h3>Campos técnicos do corpo</h3>
      <pre className="api-log">{item.corpo ? JSON.stringify(item.corpo, null, 2) : "Sem campos registrados"}</pre>
      <h3>Resposta técnica</h3>
      <pre className="api-log">{JSON.stringify(response, null, 2)}</pre>
      <details><summary>Log textual</summary><pre className="api-log">{log}</pre></details>
      <button className="refresh" onClick={() => {
        if (!navigator.clipboard) {
          setCopied("Abra o log textual e selecione o texto para copiar.");
          return;
        }
        navigator.clipboard.writeText(log).then(
          () => setCopied("Log copiado."),
          () => setCopied("Abra o log textual e selecione o texto para copiar."),
        );
      }}>Copiar log</button>
      {copied && <p role="status">{copied}</p>}
    </dialog>
  );
}

export function ApiConsumption({ segment, ambiente }: { segment?: Segmento; ambiente: Ambiente }) {
  const [api, setApi] = useState<API>();
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [before, setBefore] = useState<number>();
  const [snapshot, setSnapshot] = useState<{ data: Consumption; readAt: number; selection: string }>();
  const detailsSection = useRef<HTMLElement>(null);
  const openDetails = useRef(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [detail, setDetail] = useState<RequestLog>();
  const selection = JSON.stringify([ambiente, segment, api, before, onlyErrors, refresh]);
  const currentSnapshot = snapshot?.selection === selection ? snapshot : undefined;
  const data = currentSnapshot?.data;
  useEffect(() => {
    const stop = new AbortController();
    const timeout = setTimeout(() => stop.abort(), 15000);
    let active = true;
    setLoading(true);
    setError(false);
    setSnapshot(undefined);
    setDetail(undefined);
    const params = new URLSearchParams();
    if (ambiente === "producao") params.set("ambiente", ambiente);
    if (segment) params.set("segmento", segment);
    if (api) params.set("api", api);
    if (before) params.set("antes", String(before));
    if (onlyErrors) params.set("so_erros", "true");
    fetch("/api/central/v1/consumo?" + params, {
      credentials: "same-origin", cache: "no-store", signal: stop.signal,
    }).then(async (response) => {
      if (!response.ok || response.redirected) throw new Error();
      const result: Consumption & { ambiente?: Ambiente } = await response.json();
      if ((result.ambiente ?? "homologacao") !== ambiente) throw new Error();
      if (segment && result.segmento !== segment) throw new Error();
      if (active) setSnapshot({ data: result, readAt: Date.now(), selection });
    }).catch(() => {
      if (active) setError(true);
    }).finally(() => {
      clearTimeout(timeout);
      if (active) setLoading(false);
    });
    return () => {
      active = false;
      clearTimeout(timeout);
      stop.abort();
    };
  }, [ambiente, segment, api, before, onlyErrors, selection]);

  useEffect(() => {
    if (api && data && openDetails.current) {
      openDetails.current = false;
      detailsSection.current?.focus();
    }
  }, [api, data]);

  return (
    <>
      <div className="title-row">
        <div>
          <h1>Consumo de APIs</h1>
          <p className="updated">Tráfego recebido pelo Hub nas últimas 24 horas{data ? ` · ${data.segmento}` : ""}</p>
        </div>
        <button className="refresh" onClick={() => { setBefore(undefined); setRefresh((value) => value + 1); }}>
          <RefreshCw size={16} aria-hidden="true" /> Atualizar
        </button>
      </div>
      {loading && <p className="waiting" role="status">Consultando requisições…</p>}
      {error && <p className="error-panel" role="alert">Consulta de APIs indisponível. Confira seu acesso ou atualize o painel.</p>}
      {data && (
        <>
        <Overview summaries={data.resumo} />
        <div className="api-section-heading">
          <h2>APIs monitoradas</h2>
          <span>Taxas calculadas sobre as chamadas registradas</span>
        </div>
        <div className="api-grid">
          {(Object.keys(labels) as API[]).map((name) => {
            const summary = data.resumo.find((item) => item.api === name);
            const source = monitored[name];
            const Icon = source.icon;
            return (
              <section className={`panel api-card api-service ${api === name ? "api-service-current" : ""}`} key={name}>
                <div className="api-service-heading">
                  <span className="api-service-icon"><Icon size={20} aria-hidden="true" /></span>
                  <div><h3>{labels[name]}</h3><p>{source.description}</p></div>
                </div>
                {summary && summary.total > 0 ? (
                  <>
                    <dl>
                      <div><dt>Sucesso HTTP</dt><dd>{percent.format(summary.sucesso / summary.total)}</dd></div>
                      <div><dt>Taxa de erro</dt><dd>{percent.format(summary.erros / summary.total)}</dd></div>
                    </dl>
                    <p className="api-p95"><strong>{integer.format(summary.total)}</strong> requisições · 95% responderam em até <strong className="api-duration">{integer.format(summary.p95_ms)} ms</strong></p>
                    <Trend volumes={data.serie.filter((point) => point.api === name)} asOf={currentSnapshot!.readAt} />
                  </>
                ) : <p className="api-empty">Nenhuma requisição registrada no período.</p>}
                <button className="refresh" aria-label={`Detalhes de ${labels[name]}`} aria-pressed={api === name}
                  onClick={() => {
                    if (api === name && !onlyErrors && !before) {
                      detailsSection.current?.focus();
                    } else {
                      openDetails.current = true;
                      setApi(name);
                      setOnlyErrors(false);
                      setBefore(undefined);
                    }
                  }}>
                  Detalhes <ChevronRight size={15} aria-hidden="true" />
                </button>
              </section>
            );
          })}
        </div>
        </>
      )}
      {api && data && (
        <section className="panel api-card" ref={detailsSection} tabIndex={-1}
          aria-label={`Requisições de ${labels[api]}`}>
          <div className="api-section-heading">
          <h2>Requisições · {labels[api]}</h2>
          <label className="api-error-filter">
            <input type="checkbox" checked={onlyErrors} onChange={(event) => {
              setOnlyErrors(event.target.checked); setBefore(undefined);
            }} /> Somente erros
          </label>
          </div>
          {data.requisicoes.length === 0 ? <p>Nenhuma requisição nesse recorte.</p> : (
            <ul className="api-request-list">
              {data.requisicoes.map((item) => (
                <li key={item.id}>
                  <button type="button" className="api-request" onClick={() => setDetail(item)}>
                    <code>{item.metodo} {item.endpoint}</code>
                    <span className="api-result-line"><Status status={item.http} /> {integer.format(item.duracao_ms)} ms</span>
                    <small>{horaLocal(item.ocorrido_em)} · Belém</small>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="api-pages">
            {before && <button className="refresh" onClick={() => setBefore(undefined)}>Mais recentes</button>}
            {data.proximo && <button className="refresh" onClick={() => setBefore(data.proximo!)}>Página seguinte</button>}
          </div>
        </section>
      )}
      <section className="panel api-card api-coverage" aria-labelledby="api-coverage-title">
        <h2 id="api-coverage-title">Integrações sem telemetria na Central</h2>
        <ul>{awaiting.map(({ name, description, origin }) => (
          <li key={name}>
            <Waypoints size={17} aria-hidden="true" />
            <div><strong>{name}</strong><p>{description}</p></div>
            <span>{origin}</span>
          </li>
        ))}</ul>
        <p>O coletor da VPS fica em <a href="#infraestrutura">Infraestrutura</a>.</p>
      </section>
      {api && detail && <RequestDetail item={detail} api={api} close={() => setDetail(undefined)} />}
    </>
  );
}
