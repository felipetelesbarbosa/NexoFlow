import { useEffect, useState } from "react";
import { Activity, ArrowDown, ArrowUp, Cpu, Database, HardDrive, RefreshCw, Server } from "lucide-react";
import { horaLocal } from "./resumo";

type Sample = [string, number];
type Metrics = Record<"cpu" | "ram" | "disco" | "entrada" | "saida" | "uptime", Sample[]>;
type VPS = {
  coletado_em: string;
  hostname: string;
  sistema: string | null;
  estado: "running" | "stopped" | "starting" | "stopping" | "unknown";
  cidade: string | null;
  pais: string | null;
  ipv4: string | null;
  plano: string | null;
  nucleos: number | null;
  ram_bytes: number | null;
  disco_bytes: number | null;
  banda_bytes: number | null;
  validade: string | null;
  renovacao_automatica: boolean | null;
  ultimo_backup_provedor: string | null;
  metricas: Metrics | null;
};
type Snapshot =
  | { estado: "disponivel" | "desatualizado"; vps: VPS }
  | { estado: "aguardando_coleta" | "indisponivel"; vps: null };

const unavailable = "Indisponível";
const digits = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const countries = new Intl.DisplayNames(["pt-BR"], { type: "region" });
const serviceStates = {
  running: "Em atividade",
  stopped: "Parada",
  starting: "Iniciando",
  stopping: "Parando",
  unknown: "Estado indisponível",
};
function bytes(value: number | null | undefined) {
  if (value == null) return unavailable;
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let scale = 0;
  while (value >= 1024 && scale < units.length - 1) {
    value /= 1024;
    scale += 1;
  }
  return digits.format(value) + " " + units[scale];
}
function duration(seconds?: number) {
  if (seconds === undefined) return unavailable;
  const hours = Math.floor(seconds / 3600);
  if (hours === 0) return digits.format(Math.floor(seconds / 60)) + " min";
  return hours >= 24
    ? `${Math.floor(hours / 24)} d ${hours % 24} h`
    : `${hours} h ${Math.floor((seconds % 3600) / 60)} min`;
}
function dateLabel(instant: string | null) {
  return instant === null ? unavailable : horaLocal(instant);
}

function usage(value: number | undefined, capacity: number | null) {
  if (value === undefined || !capacity) return bytes(value);
  return `${digits.format(value * 100 / capacity)}% · ${bytes(value)}`;
}

function Sparkline({ series, label }: { series: Sample[]; label: string }) {
  if (series.length < 2) return null;
  const max = Math.max(1, ...series.map(([, value]) => value));
  const first = Date.parse(series[0][0]);
  const span = Math.max(1, Date.parse(series.at(-1)![0]) - first);
  const points = series.map(([at, value]) =>
    `${2 + 116 * (Date.parse(at) - first) / span},${27 - 23 * value / max}`
  ).join(" ");
  return (
    <svg className="infra-chart" viewBox="0 0 120 30" role="img" aria-label={label}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

function Metric({
  title,
  icon: Icon,
  series = [],
  format,
  context,
}: {
  title: string;
  icon: typeof Cpu;
  series?: Sample[];
  format: (number: number | undefined) => string;
  context?: string;
}) {
  const latest = series.at(-1);
  return (
    <article className="panel infra-metric">
      <h2><Icon size={18} aria-hidden="true" /> {title}</h2>
      <div className="infra-metric-reading">
        <strong>{format(latest?.[1])}</strong>
        <Sparkline series={series} label={`Histórico de ${title.toLowerCase()} nas últimas 24 horas`} />
      </div>
      {context && <p>{context}</p>}
      <small>{latest ? `Amostra de ${horaLocal(latest[0])}` : "Sem amostra nas últimas 24 horas"}</small>
    </article>
  );
}

function Details({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <section className="panel infra-details">
      <h2>{title}</h2>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt><dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function Infrastructure() {
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const stop = new AbortController();
    const timeout = setTimeout(() => stop.abort(), 15000);
    let active = true;
    fetch("/api/central/v1/infraestrutura", {
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: stop.signal,
    })
      .then(async (response) => {
        if (response.status === 401 || response.status === 403 || response.redirected)
          throw new Error("Confira sua sessão de acesso à Central.");
        if (!response.ok || !response.headers.get("Content-Type")?.includes("application/json"))
          throw new Error("A consulta de infraestrutura está indisponível.");
        const data: Snapshot = await response.json();
        if (!["disponivel", "desatualizado", "aguardando_coleta", "indisponivel"].includes(data?.estado))
          throw new Error("A Central recebeu um estado de infraestrutura desconhecido.");
        if (active) setSnapshot(data);
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error && reason.name !== "AbortError"
          ? reason.message : "A consulta de infraestrutura excedeu o prazo.");
      })
      .finally(() => {
        clearTimeout(timeout);
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      clearTimeout(timeout);
      stop.abort();
    };
  }, [attempt]);

  const vps = snapshot?.vps;
  const metrics = vps?.metricas;
  return (
    <>
      <div className="title-row">
        <div><h1>Infraestrutura</h1><p className="updated">Visão geral da VPS</p></div>
        <button className="refresh" disabled={loading} onClick={() => {
          setLoading(true);
          setError("");
          setSnapshot(undefined);
          setAttempt((value) => value + 1);
        }}>
          <RefreshCw size={16} aria-hidden="true" /> Atualizar
        </button>
      </div>
      {loading && <p className="waiting" role="status">Consultando infraestrutura…</p>}
      {error && <p className="error-panel" role="alert">{error}</p>}
      {snapshot?.estado === "aguardando_coleta" && (
        <p className="panel infra-notice" role="status">Aguardando a primeira coleta da VPS.</p>
      )}
      {snapshot?.estado === "indisponivel" && (
        <p className="error-panel" role="alert">Dados da VPS indisponíveis.</p>
      )}
      {vps && (
        <>
          <section className="panel infra-server" aria-label="Estado da VPS">
            <Server size={25} aria-hidden="true" />
            <div>
              <h2>{vps.hostname}</h2>
              <p>{[vps.sistema, vps.plano].filter(Boolean).join(" · ")}</p>
            </div>
            <div className="infra-status">
              <strong>{serviceStates[vps.estado]}</strong>
              <small>Coleta de {horaLocal(vps.coletado_em)} · Belém</small>
            </div>
          </section>
          {snapshot?.estado === "desatualizado" && (
            <p className="panel infra-notice" role="status">Coleta atrasada. Exibindo os últimos dados disponíveis.</p>
          )}
          <div className="infra-grid">
            <Metric title="Uso da CPU" icon={Cpu} series={metrics?.cpu}
              format={(n) => n === undefined ? unavailable : digits.format(n) + "%"} />
            <Metric title="Uso de memória" icon={Activity} series={metrics?.ram} format={(n) => usage(n, vps.ram_bytes)}
              context={vps.ram_bytes ? `Capacidade de ${bytes(vps.ram_bytes)}` : undefined} />
            <Metric title="Uso do disco" icon={HardDrive} series={metrics?.disco} format={(n) => usage(n, vps.disco_bytes)}
              context={vps.disco_bytes ? `Capacidade de ${bytes(vps.disco_bytes)}` : undefined} />
            <Metric title="Tráfego de entrada" icon={ArrowDown} series={metrics?.entrada} format={bytes} />
            <Metric title="Tráfego de saída" icon={ArrowUp} series={metrics?.saida} format={bytes} />
            <Metric title="Tempo em atividade" icon={Server} series={metrics?.uptime} format={duration} />
          </div>
          <div className="infra-details-grid">
            <Details title="Detalhes da VPS" rows={[
              ["Localização", [vps.cidade, vps.pais && countries.of(vps.pais)].filter(Boolean).join(" · ") || unavailable],
              ["Sistema operacional", vps.sistema ?? unavailable],
              ["IPv4", vps.ipv4 ?? unavailable],
            ]} />
            <Details title="Plano e capacidade" rows={[
              ["Plano", vps.plano ?? unavailable],
              ["Validade", dateLabel(vps.validade)],
              ["Renovação automática", vps.renovacao_automatica === null ? unavailable : vps.renovacao_automatica ? "Ativa" : "Desativada"],
              ["Núcleos da CPU", vps.nucleos === null ? unavailable : digits.format(vps.nucleos)],
              ["Memória", bytes(vps.ram_bytes)],
              ["Disco", bytes(vps.disco_bytes)],
              ["Cota de banda", bytes(vps.banda_bytes)],
            ]} />
          </div>
          <section className="panel infra-details">
            <h2><Database size={18} aria-hidden="true" /> Backup da VPS</h2>
            <dl><div><dt>Último backup listado pela Hostinger</dt><dd>{dateLabel(vps.ultimo_backup_provedor)}</dd></div></dl>
          </section>
        </>
      )}
    </>
  );
}
