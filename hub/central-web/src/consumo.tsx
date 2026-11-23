import { useEffect, useRef, useState } from "react";
import { Braces, ChevronRight, RefreshCw, X } from "lucide-react";
import { horaLocal } from "./resumo";
import type { Segmento } from "./resumo";

const labels = { hub: "API do Hub", weni: "Webhook Weni" };
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

function Trend({ volumes }: { volumes: Consumption["serie"] }) {
  if (!volumes.length) return null;
  const end = Date.parse(volumes.at(-1)!.hora);
  const start = Date.parse(volumes[0].hora);
  const peak = Math.max(1, ...volumes.flatMap((point) => [point.sucesso, point.erros]));
  return (
    <svg className="api-trend" viewBox="0 0 300 55" role="img"
      aria-label="Volume por hora. Verde para sucessos e vermelho para erros.">
      {volumes.map((point) => {
        const x = (Date.parse(point.hora) - start) * 280 / Math.max(3600000, end - start);
        return (
          <g key={point.hora}>
            <title>{horaLocal(point.hora)} · {point.sucesso} sucessos · {point.erros} erros</title>
            <rect x={x} y={55 - 48 * point.sucesso / peak} width="5"
              height={48 * point.sucesso / peak} className="api-success" />
            <rect x={x + 5} y={55 - 48 * point.erros / peak} width="5"
              height={48 * point.erros / peak} className="api-error" />
          </g>
        );
      })}
    </svg>
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
      <p>HTTP {item.http} · {item.duracao_ms} ms</p>
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

export function ApiConsumption({ segment }: { segment?: Segmento }) {
  const [api, setApi] = useState<API>();
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [before, setBefore] = useState<number>();
  const [data, setData] = useState<Consumption>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [detail, setDetail] = useState<RequestLog>();
  useEffect(() => {
    const stop = new AbortController();
    const timeout = setTimeout(() => stop.abort(), 15000);
    let active = true;
    setLoading(true);
    setError(false);
    setData(undefined);
    setDetail(undefined);
    const params = new URLSearchParams();
    if (segment) params.set("segmento", segment);
    if (api) params.set("api", api);
    if (before) params.set("antes", String(before));
    if (onlyErrors) params.set("so_erros", "true");
    fetch("/api/central/v1/consumo?" + params, {
      credentials: "same-origin", cache: "no-store", signal: stop.signal,
    }).then(async (response) => {
      if (!response.ok || response.redirected) throw new Error();
      const result: Consumption = await response.json();
      if (segment && result.segmento !== segment) throw new Error();
      if (active) setData(result);
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
  }, [segment, api, before, onlyErrors, refresh]);

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
        <div className="api-grid">
          {(Object.keys(labels) as API[]).map((name) => {
            const summary = data.resumo.find((item) => item.api === name);
            return (
              <section className="panel api-card" key={name}>
                <h2><Braces size={18} aria-hidden="true" /> {labels[name]}</h2>
                {summary && summary.total > 0 ? (
                  <>
                    <dl>
                      <div><dt>Sucesso HTTP</dt><dd>{percent.format(summary.sucesso / summary.total)}</dd></div>
                      <div><dt>Taxa de erro</dt><dd>{percent.format(summary.erros / summary.total)}</dd></div>
                    </dl>
                    <p>{summary.total} requisições · {summary.erros} erros · p95 de {summary.p95_ms} ms</p>
                    <Trend volumes={data.serie.filter((point) => point.api === name)} />
                  </>
                ) : <p>Nenhuma requisição registrada no período.</p>}
                <button className="refresh" aria-label={`Detalhes de ${labels[name]}`} aria-pressed={api === name}
                  onClick={() => { setApi(name); setOnlyErrors(false); setBefore(undefined); }}>
                  Detalhes <ChevronRight size={15} aria-hidden="true" />
                </button>
              </section>
            );
          })}
        </div>
      )}
      {api && data && (
        <section className="panel api-card" aria-label={`Requisições de ${labels[api]}`}>
          <h2>Requisições · {labels[api]}</h2>
          <label>
            <input type="checkbox" checked={onlyErrors} onChange={(event) => {
              setOnlyErrors(event.target.checked); setBefore(undefined);
            }} /> Somente erros
          </label>
          {data.requisicoes.length === 0 ? <p>Nenhuma requisição nesse recorte.</p> : (
            <ul className="api-request-list">
              {data.requisicoes.map((item) => (
                <li key={item.id}>
                  <button type="button" className="api-request" onClick={() => setDetail(item)}>
                    <code>{item.metodo} {item.endpoint}</code>
                    <span>HTTP {item.http} · {item.duracao_ms} ms</span>
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
      {api && detail && <RequestDetail item={detail} api={api} close={() => setDetail(undefined)} />}
    </>
  );
}
