import { Fragment, useEffect, useLayoutEffect, useId, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type { ComponentType } from "react";
import {
  Activity,
  ArrowDownWideNarrow,
  ArrowRight,
  BookOpen,
  Braces,
  CalendarDays,
  ChartNoAxesColumn,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  Clock3,
  FlaskConical,
  Inbox,
  Layers,
  LayoutDashboard,
  ListChecks,
  LockKeyhole,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
  Search,
  Server,
  SlidersHorizontal,
  Sun,
  UserRound,
  UsersRound,
  Waypoints,
  Webhook,
  X,
} from "lucide-react";
import {
  ambientes,
  isAmbiente,
  ativos,
  atencao,
  estados,
  etapasNoturno,
  estadosWorker,
  horaLocal,
  janela,
  lerResumo,
  isSegmento,
} from "./resumo";
import type { Ambiente, Estado, Evento, Resumo, Segmento, Tarefa } from "./resumo";
import { ApiConsumption } from "./consumo";
import { Infrastructure } from "./infraestrutura";
import { AceitarConvite, GerenciarUsuarios } from "./usuarios";
import { MinhaConta } from "./minha-conta";
import { Documentation } from "./documentacao";
import "./style.css";

const pages = {
  geral: { nome: "Visão geral", icone: LayoutDashboard },
  execucoes: { nome: "Execuções", icone: ListChecks },
  eventos: { nome: "Eventos Weni", icone: Webhook },
  consumo: { nome: "Consumo de APIs", icone: Braces },
  infraestrutura: { nome: "Infraestrutura", icone: Server },
  documentacao: { nome: "Documentação", icone: BookOpen },
  conta: { nome: "Minha Conta", icone: UserRound },
  usuarios: { nome: "Gerenciar Usuários", icone: UsersRound },
  convite: { nome: "Convite", icone: UsersRound },
} as const;
type Page = keyof typeof pages;
type Slice = ReturnType<typeof janela>;
const digits = new Intl.NumberFormat("pt-BR");
function pageFromHash(): Page {
  const slug = window.location.hash.slice(1);
  if (slug.startsWith("convite/")) return "convite";
  return Object.hasOwn(pages, slug) ? (slug as Page) : "geral";
}

async function consultar(signal: AbortSignal, ambiente: Ambiente, segmento?: Segmento) {
  const path = "/api/central/v1/resumo";
  const params = new URLSearchParams();
  if (ambiente === "producao") params.set("ambiente", ambiente);
  if (segmento) params.set("segmento", segmento);
  const response = await fetch(
    params.size ? path + "?" + params : path,
    {
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal,
    },
  );
  if (response.status === 401 || response.redirected)
    throw new Error(
      "Abra a Central pelo endereço autenticado do Cloudflare Access e entre novamente.",
    );
  if (response.status === 403)
    throw new Error(
      "Sua identidade não tem permissão de leitura da Central. Consulte o administrador do Hub.",
    );
  if (!response.ok)
    throw new Error(
      "A API da Central está indisponível. Tente atualizar a consulta.",
    );
  if (!response.headers.get("Content-Type")?.includes("application/json"))
    throw new Error(
      "A autenticação ou a rota da Central precisa ser conferida.",
    );
  const data = lerResumo(await response.json());
  if (data.ambiente !== ambiente)
    throw new Error("A API retornou outro ambiente. Atualize a consulta.");
  if (segmento && data.segmento !== segmento)
    throw new Error("A API retornou outro segmento. Atualize a consulta.");
  return data;
}

function App() {
  const [dark, setDark] = useState(
    () => document.documentElement.dataset.tema === "grafite",
  );
  useLayoutEffect(() => {
    document.documentElement.dataset.tema = dark ? "grafite" : "claro";
  }, [dark]);
  function toggleTheme() {
    setDark(!dark);
    try {
      localStorage.setItem("nexoflow.central.tema", dark ? "claro" : "grafite");
    } catch {
      // Se storage estiver bloqueado, a escolha vale até o fim da sessão.
    }
  }
  const [page, setPage] = useState(pageFromHash);
  const [compact, setCompact] = useState(false);
  const [menu, setMenu] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [disponiveis, setDisponiveis] = useState<Ambiente[]>(["homologacao"]);
  const [resumo, setResumo] = useState<Resumo>();
  const [fetched, setFetched] = useState<Date>();
  const [busy, setBusy] = useState(true);
  const [erro, setErro] = useState("");
  const [request, setRequest] = useState<{ id: number; ambiente: Ambiente; segmento?: Segmento }>({
    id: 0, ambiente: "homologacao",
  });
  const [scopes, setScopes] = useState<Segmento[]>([]);
  const currentRequest = useRef(0);
  function reload(segmento?: Segmento, ambiente = request.ambiente) {
    const id = ++currentRequest.current;
    setResumo(undefined);
    setFetched(undefined);
    setErro("");
    setDetail(null);
    setBusy(true);
    setRequest({ id, segmento, ambiente });
  }
  const [dias, setDias] = useState(7);
  const [detail, setDetail] = useState<Tarefa | null>(null);
  const main = useRef<HTMLElement>(null);
  const openMenuButton = useRef<HTMLButtonElement>(null);
  const closeMenuButton = useRef<HTMLButtonElement>(null);
  const closeMenu = () => {
    setMenu(false);
    requestAnimationFrame(() => openMenuButton.current?.focus());
  };
  useEffect(() => {
    if (!menu) return;
    closeMenuButton.current?.focus();
    const dismiss = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeMenu();
    };
    const wide = window.matchMedia("(min-width: 851px)");
    const onWide = () => {
      if (wide.matches) setMenu(false);
    };
    wide.addEventListener("change", onWide);
    window.addEventListener("keydown", dismiss);
    return () => {
      wide.removeEventListener("change", onWide);
      window.removeEventListener("keydown", dismiss);
    };
  }, [menu]);

  useEffect(() => {
    const go = () => {
      setPage(pageFromHash());
      setMenu(false);
      main.current?.focus();
    };
    window.addEventListener("hashchange", go);
    return () => window.removeEventListener("hashchange", go);
  }, []);
  useEffect(() => {
    const stop = new AbortController();
    fetch("/api/central/v1/sessao", {
      credentials: "same-origin",
      cache: "no-store",
      signal: stop.signal,
    }).then(async (response) => {
      if (!response.ok || response.redirected) return;
      const { ambientes: enabled, gerencia_usuarios: admin } = await response.json();
      if (!stop.signal.aborted) {
        setIsAdmin(admin === true);
        if (Array.isArray(enabled) && enabled.includes("producao")) {
          setDisponiveis(["homologacao", "producao"]);
        }
      }
    }).catch(() => {
      // Homologação continua disponível mesmo se a consulta à sessão falhar.
    });
    return () => stop.abort();
  }, []);
  const needsSummary = page !== "documentacao" && page !== "conta" && page !== "usuarios" && page !== "convite";
  useEffect(() => {
    if (!needsSummary) return;
    const stop = new AbortController();
    let active = true;
    const timer = setTimeout(() => stop.abort(), 20000);
    setBusy(true);
    setErro("");
    setDetail(null);
    setResumo(undefined);
    setFetched(undefined);
    consultar(stop.signal, request.ambiente, request.segmento)
      .then((data) => {
        if (active && request.id === currentRequest.current) {
          setScopes(data.segmentos_autorizados);
          setResumo(data);
          setFetched(new Date());
        }
      })
      .catch((reason) => {
        if (!active || request.id !== currentRequest.current) return;
        setScopes([]);
        setErro(
          stop.signal.aborted
            ? "A consulta excedeu o prazo. Tente atualizar novamente."
            : reason instanceof Error && !(reason instanceof TypeError)
              ? reason.message
              : "Não foi possível conectar à Central. Confira o acesso e tente novamente.",
        );
      })
      .finally(() => {
        clearTimeout(timer);
        if (active && request.id === currentRequest.current) setBusy(false);
      });
    return () => {
      active = false;
      clearTimeout(timer);
      stop.abort();
    };
  }, [request, needsSummary]);

  const data = resumo && fetched ? janela(resumo, dias, fetched) : null;
  const view = pages[page];
  if (page === "convite") return <AceitarConvite />;
  return (
    <div className={`shell ${compact ? "compact" : ""}`}>
      <a
        className="skip"
        href="#conteudo"
        onClick={(e) => {
          e.preventDefault();
          main.current?.focus();
        }}
      >
        Ir para o conteúdo
      </a>
      <aside id="navegacao" className={`sidebar ${menu ? "opened" : ""}`}>
        <div className="brand">
          <img src="/nexoflow.ico" alt="" width="36" height="36" />
          <span>
            NexoFlow <b>Hub</b>
          </span>
          <button
            className="mobile plain"
            ref={closeMenuButton}
            onClick={closeMenu}
            aria-label="Fechar menu"
          >
            <X />
          </button>
        </div>
        <nav aria-label="Navegação principal">
          <div className="navlabel">Operação</div>
          {(Object.keys(pages) as Page[])
            .filter((key) => key !== "convite" && (key !== "usuarios" || isAdmin))
            .map((key) => {
            const p = pages[key],
              Icon = p.icone;
            return (
              <a
                key={key}
                href={"#" + key}
                onClick={() => {
                  setMenu(false);
                  main.current?.focus();
                }}
                className={key === page ? "current" : ""}
                aria-label={p.nome}
                title={p.nome}
                aria-current={key === page ? "page" : undefined}
              >
                <Icon size={19} />
                <span>{p.nome}</span>
              </a>
            );
          })}
          <div className="navlabel products">Produtos</div>
          <button
            className="disabled-product"
            disabled
            title="NexoFlow Métricas desabilitado"
          >
            <ChartNoAxesColumn size={19} />
            <span>NexoFlow Métricas</span>
            <LockKeyhole size={13} className="end" />
          </button>
        </nav>
        <div className="aside-bottom">
          <span className="homolog">
            <FlaskConical size={16} />
            <span>{ambientes[request.ambiente]}</span>
          </span>
          <button
            className="collapse plain"
            onClick={() => setCompact((v) => !v)}
            title={compact ? "Expandir navegação" : "Recolher navegação"}
            aria-expanded={!compact}
            aria-controls="navegacao"
            aria-label={compact ? "Expandir navegação" : "Recolher navegação"}
          >
            {compact ? (
              <PanelLeftOpen size={18} />
            ) : (
              <PanelLeftClose size={18} />
            )}
          </button>
        </div>
      </aside>
      {menu && (
        <button
          className="scrim"
          onClick={closeMenu}
          aria-label="Fechar navegação"
        />
      )}
      <div className="workspace" inert={menu}>
        <header>
          <button
            className="mobile plain"
            ref={openMenuButton}
            aria-controls="navegacao"
            aria-label="Abrir menu"
            aria-expanded={menu}
            onClick={() => setMenu(!menu)}
          >
            <Menu size={22} />
          </button>
          <span className="crumb">Central de Operações</span>
          <ChevronRight size={14} />
          <strong>{view.nome}</strong>
          <div className="header-right">
            <select
              className="segment-picker environment-picker"
              aria-label="Ambiente da Central"
              value={request.ambiente}
              onChange={(event) => {
                const value = event.target.value;
                if (isAmbiente(value) && disponiveis.includes(value)) {
                  setScopes([]);
                  reload(undefined, value);
                }
              }}
            >
              <option value="homologacao">Homologação</option>
              <option value="producao" disabled={!disponiveis.includes("producao")}>
                {disponiveis.includes("producao") ? "Produção" : "Produção indisponível"}
              </option>
            </select>
            {page !== "infraestrutura" && page !== "documentacao" && page !== "conta" && page !== "usuarios" && <>
            <Layers size={15} />
            <span>Segmento</span>
            {scopes.length > 1 ? (
              <select
                className="segment-picker"
                aria-label="Segmento da Central"
                value={resumo?.segmento ?? request.segmento}
                onChange={(event) => {
                  const value = event.target.value;
                  if (isSegmento(value) && scopes.includes(value))
                    reload(value);
                }}
              >
                {scopes.map((segmento) => (
                  <option key={segmento}>{segmento}</option>
                ))}
              </select>
            ) : (
              <strong
                aria-label={
                  resumo
                    ? "Segmento " + resumo.segmento
                    : "Segmento indisponível"
                }
              >
                {resumo?.segmento ?? "—"}
              </strong>
            )}
            </>}
            <button
              className="plain theme-toggle"
              aria-label="Tema escuro"
              aria-pressed={dark}
              title={dark ? "Usar tema claro" : "Usar tema grafite"}
              onClick={toggleTheme}
            >
              {dark ? <Sun size={18} /> : <Moon size={18} />}
            </button>
          </div>
        </header>
        <main id="conteudo" tabIndex={-1} ref={main}>
          {page === "usuarios" ? (isAdmin ? <GerenciarUsuarios /> : <p>Área exclusiva do Super Admin.</p>) : page === "conta" ? <MinhaConta /> : page === "documentacao" ? <Documentation /> : page === "infraestrutura" ? <Infrastructure /> : page === "consumo" ? (
            <ApiConsumption key={request.ambiente + ":" + (request.segmento ?? "inicial")} ambiente={request.ambiente} segment={request.segmento} />
          ) : <>
          <div className="title-row">
            <div>
              <h1>{page === "geral" ? "Visão geral" : view.nome}</h1>
              <p className="updated">
                {fetched
                  ? "Atualizado em " + horaLocal(fetched) + " · Belém"
                  : "Central de Operações do NexoFlow Hub"}
              </p>
            </div>
            <div className="actions">
              <label className="select-label">
                <CalendarDays size={16} />
                <select
                  aria-label="Período"
                  value={dias}
                  onChange={(e) => setDias(Number(e.target.value))}
                >
                  <option value={1}>Hoje</option>
                  <option value={7}>Últimos 7 dias</option>
                  <option value={30}>Últimos 30 dias</option>
                </select>
              </label>
              <button
                className="refresh"
                onClick={() => reload(erro ? undefined : request.segmento)}
                disabled={busy}
              >
                <RefreshCw size={16} className={busy ? "spin" : ""} />
                {busy ? "Atualizando" : "Atualizar"}
              </button>
            </div>
          </div>
          {erro && (
            <div className="error-panel" role="alert">
              <CircleAlert size={24} />
              <div>
                <h2>Consulta indisponível</h2>
                <p>{erro}</p>
              </div>
            </div>
          )}
          {busy && (
            <div className="waiting" role="status">
              <RefreshCw className="spin" size={20} /> Consultando a API do Hub…
            </div>
          )}
          {!busy && data && page === "geral" && (
            <>
              <div className="cards">
                <Stat
                  label="Execuções"
                  value={data.tarefas.length}
                  Icon={Layers}
                  tint="blue"
                />
                <Stat
                  label="Em andamento ou fila"
                  value={data.tarefas.filter((t) => ativos(t.estado)).length}
                  Icon={Activity}
                  tint="teal"
                />
                <Stat
                  label="Exigem atenção"
                  value={data.tarefas.filter((t) => atencao(t.estado)).length}
                  Icon={CircleAlert}
                  tint="amber"
                />
                <Stat
                  label="Eventos Weni"
                  value={data.eventos.length}
                  Icon={Webhook}
                  tint="violet"
                />
              </div>
              <OperationPanel value={resumo?.operacao} />
              <div className="charts">
                <ActivityChart data={data} />
                <StatePanel rows={data.tarefas} />
              </div>
              <section className="panel table-panel">
                <Heading title="Execuções recentes" link="execucoes" />
                <Tasks rows={data.tarefas.slice(0, 5)} onOpen={setDetail} />
              </section>
            </>
          )}
          {!busy && data && page === "execucoes" && (
            <TaskBrowser key={dias} rows={data.tarefas} onOpen={setDetail} />
          )}
          {!busy && data && page === "eventos" && (
            <EventBrowser key={dias} rows={data.eventos} />
          )}
          {!busy && data && (
            <p className="coverage">
              Até 50 execuções e 50 eventos recentes. Filtros aplicados a essa
              amostra, no horário de Belém.
            </p>
          )}
          </>}
        </main>
      </div>
      {detail && (
        <TaskDetail
          value={data?.tarefas.find((task) => task.id === detail.id) ?? detail}
          close={() => setDetail(null)}
        />
      )}
    </div>
  );
}

function OperationPanel({ value }: { value: Resumo["operacao"] }) {
  return (
    <section className="panel operation-panel" aria-labelledby="operation-title">
      <h2 id="operation-title">Processamento do Hub</h2>
      {value ? (
        <dl>
          <div>
            <dt>Worker</dt>
            <dd>{estadosWorker[value.worker_estado]}</dd>
            {value.worker_ultimo_ciclo_em && (
              <dd className="operation-detail">
                Último ciclo em {horaLocal(value.worker_ultimo_ciclo_em)}
              </dd>
            )}
          </div>
          <div>
            <dt>Fila do segmento</dt>
            <dd>
              {digits.format(value.fila_prontas)} prontas ·{" "}
              {digits.format(value.fila_em_espera)} aguardando horário
            </dd>
            {value.fila_espera_segundos !== null && (
              <dd className="operation-detail">
                Maior espera entre as prontas{" "}
                {digits.format(value.fila_espera_segundos)} s
              </dd>
            )}
            {value.fila_leases_expirados > 0 && (
              <dd className="operation-detail">
                {digits.format(value.fila_leases_expirados)} com prazo de execução expirado
              </dd>
            )}
          </div>
          <div>
            <dt>Última execução concluída</dt>
            <dd>
              {value.ultima_conclusao_em
                ? horaLocal(value.ultima_conclusao_em)
                : "Nenhuma conclusão registrada"}
            </dd>
          </div>
        </dl>
      ) : (
        <p>Dados operacionais indisponíveis.</p>
      )}
    </section>
  );
}

function Stat({
  label,
  value,
  Icon,
  tint,
}: {
  label: string;
  value: number;
  Icon: ComponentType<{ size: number }>;
  tint: string;
}) {
  return (
    <div className="stat">
      <span className={"glyph " + tint}>
        <Icon size={18} />
      </span>
      <div>
        <span className="stat-label">{label}</span>
        <strong>{digits.format(value)}</strong>
      </div>
    </div>
  );
}
function Heading({ title, link }: { title: string; link?: Page }) {
  return (
    <div className="section-head">
      <h2>{title}</h2>
      {link && (
        <a href={"#" + link}>
          Ver todas <ArrowRight size={15} />
        </a>
      )}
    </div>
  );
}
function ActivityChart({ data }: { data: Slice }) {
  const id = useId();
  const max = Math.max(1, ...data.serie.flatMap((x) => [x.tarefas, x.eventos]));
  const last = data.serie.length - 1;
  return (
    <section className="panel chart-panel">
      <Heading title="Atividade por dia" />
      <div className="legend">
        <span>
          <i className="blue-dot" />
          Execuções criadas
        </span>
        <span>
          <i className="violet-dot" />
          Eventos recebidos
        </span>
      </div>
      <div className="chart-box">
        <div className="axis">
          <span>{digits.format(max)}</span>
          <span>0</span>
        </div>
        <svg
          viewBox="0 0 560 120"
          preserveAspectRatio="none"
          aria-labelledby={id}
          role="img"
        >
          <title id={id}>
            Atividade diária no período. Valores disponíveis em Ver valores por
            dia.
          </title>
          {[8, 58, 108].map((y) => (
            <line
              key={y}
              x1={0}
              x2={560}
              y1={y}
              y2={y}
              stroke="var(--chart-grid)"
              strokeDasharray="3 5"
            />
          ))}
          {data.serie.map((v, i) => {
            const cell = 560 / data.serie.length,
              w = Math.min(11, cell * 0.32),
              x = (i + 0.5) * cell;
            return (
              <g key={v.dia}>
                <title>
                  {v.dia}: {v.tarefas} execuções, {v.eventos} eventos
                </title>
                {[v.tarefas, v.eventos].map((n, j) => (
                  <rect
                    key={j}
                    x={j ? x + 1 : x - w - 1}
                    y={108 - (100 * n) / max}
                    height={(100 * n) / max}
                    width={w}
                    rx={2}
                    fill={j ? "var(--plot-event)" : "var(--plot-task)"}
                  />
                ))}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="x-axis">
        {[...new Set([0, Math.floor(last / 2), last])].map((i) => (
          <span key={i}>
            {data.serie[i].dia.slice(8)}/{data.serie[i].dia.slice(5, 7)}
          </span>
        ))}
      </div>
      <details className="chart-details">
        <summary>Ver valores por dia</summary>
        <table>
          <thead>
            <tr>
              <th>Dia</th>
              <th>Execuções</th>
              <th>Eventos</th>
            </tr>
          </thead>
          <tbody>
            {data.serie.map((d) => (
              <tr key={d.dia}>
                <td>{d.dia.split("-").reverse().join("/")}</td>
                <td>{d.tarefas}</td>
                <td>{d.eventos}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}
function StatePanel({ rows }: { rows: Tarefa[] }) {
  const sections = [
    {
      label: "Concluídas",
      n: rows.filter((x) => x.estado === "concluida").length,
      cls: "teal",
      Icon: CircleCheck,
    },
    {
      label: "Em andamento ou fila",
      n: rows.filter((x) => ativos(x.estado)).length,
      cls: "blue",
      Icon: Clock3,
    },
    {
      label: "Exigem atenção",
      n: rows.filter((x) => atencao(x.estado)).length,
      cls: "amber",
      Icon: CircleAlert,
    },
  ];
  return (
    <section className="panel state-panel">
      <Heading title="Situação das execuções" />
      <div className="states">
        {sections.map(({ label, n, cls, Icon }) => (
          <div key={label}>
            <div>
              <span className={cls}>
                <Icon size={15} />
              </span>
              {label}
              <b>{digits.format(n)}</b>
            </div>
            <progress
              className={cls}
              max={Math.max(1, rows.length)}
              value={n}
              aria-label={label}
            />
          </div>
        ))}
      </div>
    </section>
  );
}
function Empty({ children }: { children: string }) {
  return (
    <div className="empty">
      <Inbox size={21} />
      <span>{children}</span>
    </div>
  );
}
function Status({ value }: { value: Estado }) {
  const Icon = ativos(value) ? Clock3 : atencao(value) ? CircleAlert : Check;
  return (
    <span
      className={
        "status " + (ativos(value) ? "blue" : atencao(value) ? "amber" : "teal")
      }
    >
      <Icon size={13} />
      {estados[value]}
    </span>
  );
}
function Tasks({
  rows,
  onOpen,
}: {
  rows: Tarefa[];
  onOpen: (t: Tarefa) => void;
}) {
  if (!rows.length) return <Empty>Nenhuma execução na seleção.</Empty>;
  return (
    <div className="scroll">
      <table>
        <thead>
          <tr>
            <th>Execução</th>
            <th>Estado</th>
            <th>Criada em</th>
            <th>Atualizada em</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id}>
              <td data-label="Execução">
                <button
                  className="id"
                  onClick={() => onOpen(t)}
                  aria-label={"Detalhes da execução " + t.id}
                >
                  {t.tipo === "noturno" ? "Noturno · " : ""}
                  {t.id.slice(0, 8)}
                  <ChevronRight size={13} />
                </button>
              </td>
              <td data-label="Estado">
                <Status value={t.estado} />
              </td>
              <td data-label="Criada em">{horaLocal(t.criado_em)}</td>
              <td data-label="Atualizada em">{horaLocal(t.atualizado_em)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function TaskDetail({ value, close }: { value: Tarefa; close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      className="drawer"
      ref={dialog}
      aria-labelledby="detail-title"
      onClose={close}
    >
      <div className="section-head">
        <h2 id="detail-title">Detalhes da execução</h2>
        <button
          className="plain"
          onClick={() => dialog.current?.close()}
          aria-label="Fechar detalhes"
        >
          <X size={20} />
        </button>
      </div>
      <dl>
        <dt>Identificador</dt>
        <dd className="mono">{value.id}</dd>
        <dt>Estado</dt>
        <dd>
          <Status value={value.estado} />
        </dd>
        <dt>Criada em · Belém</dt>
        <dd>{horaLocal(value.criado_em)}</dd>
        <dt>Atualizada em · Belém</dt>
        <dd>{horaLocal(value.atualizado_em)}</dd>
      </dl>
      {value.etapas && (
        <section aria-label="Etapas do Noturno">
          <h3>Etapas do Noturno</h3>
          <dl>
            {value.etapas.map(({ etapa, estado }) => (
              <Fragment key={etapa}>
                <dt>{etapasNoturno[etapa]}</dt>
                <dd>
                  <Status value={estado} />
                </dd>
              </Fragment>
            ))}
          </dl>
        </section>
      )}
    </dialog>
  );
}
function SearchBox({
  label,
  value,
  set,
}: {
  label: string;
  value: string;
  set: (s: string) => void;
}) {
  return (
    <label className="search">
      <Search size={15} />
      <input
        type="search"
        aria-label={label}
        placeholder={label}
        value={value}
        onChange={(e) => set(e.target.value)}
      />
    </label>
  );
}
function Pager({
  current,
  count,
  set,
}: {
  current: number;
  count: number;
  set: (n: number) => void;
}) {
  const total = Math.max(1, Math.ceil(count / 10));
  return (
    <div className="pager">
      <span>{digits.format(count)} registros na seleção</span>
      <button
        className="plain"
        onClick={() => set(current - 1)}
        disabled={!current}
        aria-label="Página anterior"
      >
        <ChevronLeft size={17} />
      </button>
      {current + 1} / {total}
      <button
        className="plain"
        onClick={() => set(current + 1)}
        disabled={current + 1 >= total}
        aria-label="Próxima página"
      >
        <ChevronRight size={17} />
      </button>
    </div>
  );
}
function TaskBrowser({
  rows,
  onOpen,
}: {
  rows: Tarefa[];
  onOpen: (t: Tarefa) => void;
}) {
  const [q, setQ] = useState(""),
    [estado, setEstado] = useState(""),
    [page, setPage] = useState(0),
    [desc, setDesc] = useState(true);
  const filtered = rows.filter(
    (t) =>
      (!estado || t.estado === estado) &&
      t.id.toLowerCase().includes(q.trim().toLowerCase()),
  );
  if (!desc) filtered.reverse();
  return (
    <section className="panel table-panel">
      <div className="tools">
        <SearchBox
          label="Buscar por ID"
          value={q}
          set={(v) => {
            setQ(v);
            setPage(0);
          }}
        />
        <label className="select-label">
          <SlidersHorizontal size={15} />
          <select
            aria-label="Estado da execução"
            value={estado}
            onChange={(e) => {
              setEstado(e.target.value);
              setPage(0);
            }}
          >
            <option value="">Todos os estados</option>
            {Object.entries(estados).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button
          className="sort"
          onClick={() => {
            setDesc(!desc);
            setPage(0);
          }}
        >
          <ArrowDownWideNarrow size={15} />
          {desc ? "Mais recentes" : "Mais antigas"}
        </button>
      </div>
      <Tasks rows={filtered.slice(page * 10, page * 10 + 10)} onOpen={onOpen} />
      <Pager current={page} count={filtered.length} set={setPage} />
    </section>
  );
}
function EventBrowser({ rows }: { rows: Evento[] }) {
  const [q, setQ] = useState(""),
    [page, setPage] = useState(0),
    [desc, setDesc] = useState(true);
  const filtered = rows.filter((e) =>
    e.tipo.toLowerCase().includes(q.trim().toLowerCase()),
  );
  if (!desc) filtered.reverse();
  return (
    <section className="panel table-panel">
      <div className="tools">
        <SearchBox
          label="Buscar tipo de evento"
          value={q}
          set={(v) => {
            setQ(v);
            setPage(0);
          }}
        />
        <button
          className="sort"
          onClick={() => {
            setDesc(!desc);
            setPage(0);
          }}
        >
          <ArrowDownWideNarrow size={15} />
          {desc ? "Mais recentes" : "Mais antigos"}
        </button>
      </div>
      {filtered.length ? (
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>Tipo de evento</th>
                <th>Ocorreu em</th>
                <th>Recebido em</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(page * 10, page * 10 + 10).map((e, i) => (
                <tr key={i}>
                  <td data-label="Tipo de evento">
                    <span className="event-name">
                      <Waypoints size={15} />
                      {e.tipo}
                    </span>
                  </td>
                  <td data-label="Ocorreu em">{horaLocal(e.ocorrido_em)}</td>
                  <td data-label="Recebido em">{horaLocal(e.recebido_em)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty>Nenhum evento na seleção.</Empty>
      )}
      <Pager current={page} count={filtered.length} set={setPage} />
    </section>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
