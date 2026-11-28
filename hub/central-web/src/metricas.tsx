import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, Banknote, CalendarDays, Package, Printer, ShoppingBag, Truck } from "lucide-react";
import { dataLocal } from "./resumo";
import { paginasMetricas, previas } from "./metricas-paginas";
import type { PaginaMetricas } from "./metricas-paginas";
import { Anuncios, PedidosAnuncios, PreviaMetricas, Produtos, conferirPublicacao, lerAnuncios, lerProdutos } from "./metricas-relatorios";
import type { RelatorioAnuncios, RelatorioProdutos } from "./metricas-relatorios";
import "./metricas.css";

type Totais = {
  pedidos: number;
  produtos_centavos: number;
  frete_centavos: number;
  faturamento_centavos: number;
};
type Dia = Totais & { data: string };
type Periodo = { inicio: string; fim: string };
type Vendas = Periodo & {
  segmento: "FARMA";
  fonte: "data_studio_producao";
  revisao: string;
  versao: number;
  totais: Totais;
  dias: Dia[];
};
type Indicador = "faturamento_centavos" | "pedidos";

const numeros = new Intl.NumberFormat("pt-BR");
const reais = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const abreviado = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
const percentual = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 1 });
const dinheiro = (centavos: number) => reais.format(centavos / 100);
const dataBr = (data: string) => data.split("-").reverse().join("/");
const umDia = 86400000;

function lerVendas(data: Vendas, periodo: Periodo) {
  const valido = (row: Totais) =>
    Number.isSafeInteger(row?.pedidos) && row.pedidos >= 0 &&
    Number.isSafeInteger(row.produtos_centavos) && Number.isSafeInteger(row.frete_centavos) &&
    Number.isSafeInteger(row.faturamento_centavos) &&
    row.produtos_centavos + row.frete_centavos === row.faturamento_centavos;
  if (data?.segmento !== "FARMA" || data.fonte !== "data_studio_producao" ||
      data.inicio !== periodo.inicio || data.fim !== periodo.fim ||
      typeof data.revisao !== "string" || !/^[\da-f-]{36}$/i.test(data.revisao) ||
      !Number.isSafeInteger(data.versao) || data.versao < 1 ||
      !valido(data.totais) || !Array.isArray(data.dias) || data.dias.length > 366 ||
      data.dias.some((dia, i) => !valido(dia) || !/^\d{4}-\d{2}-\d{2}$/.test(dia.data) ||
        dia.data < data.inicio || dia.data > data.fim || (i > 0 && data.dias[i - 1].data >= dia.data))) {
    throw new Error("A fonte devolveu uma resposta incompatível.");
  }
  return data;
}

function serie(report: Vendas, indicador: Indicador) {
  const dias = new Map(report.dias.map((dia) => [dia.data, dia[indicador]]));
  const pontos = [];
  for (let instante = Date.parse(report.inicio); instante <= Date.parse(report.fim); instante += umDia) {
    const data = new Date(instante).toISOString().slice(0, 10);
    const total = dias.get(data);
    pontos.push({ data, total: total === undefined ? null : indicador === "pedidos" ? total : total / 100 });
  }
  return pontos;
}

function GraficoVendas({ report, indicador }: { report: Vendas; indicador: Indicador }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const node = canvas.current;
    const ctx = node?.getContext("2d");
    if (!node || !ctx) return;
    const pontos = serie(report, indicador);
    const grupos: { index: number; total: number }[][] = [];
    let anterior = -2;
    pontos.forEach(({ total }, index) => {
      if (total === null) return;
      if (index !== anterior + 1) grupos.push([]);
      grupos[grupos.length - 1].push({ index, total });
      anterior = index;
    });
    const valores = grupos.flatMap((grupo) => grupo.map(({ total }) => total));
    function draw() {
      if (!node || !ctx) return;
      const { width, height } = node.getBoundingClientRect();
      if (!width || !height) return;
      const scale = Math.min(window.devicePixelRatio || 1, 3);
      node.width = Math.round(width * scale);
      node.height = Math.round(height * scale);
      ctx.scale(scale, scale);
      const vars = getComputedStyle(node);
      const printing = window.matchMedia("print").matches;
      const ink = printing ? "#344253" : vars.getPropertyValue("--muted").trim();
      const grid = printing ? "#cbd4df" : vars.getPropertyValue("--chart-grid").trim();
      const accent = printing ? "#0051fa" : vars.getPropertyValue("--accent").trim();
      const left = 50, right = width - 15, top = 16, bottom = height - 30;
      const min = Math.min(0, ...valores);
      const max = Math.max(1, ...valores);
      const x = (index: number) => left + (right - left) *
        (pontos.length === 1 ? 0.5 : index / (pontos.length - 1));
      const y = (value: number) => bottom - (bottom - top) * (value - min) / (max - min);
      ctx.font = "11px Inter, sans-serif";
      ctx.fillStyle = ink;
      ctx.strokeStyle = grid;
      ctx.textAlign = "right";
      for (let i = 0; i <= 4; i++) {
        const total = min + (max - min) * i / 4;
        const pos = y(total);
        ctx.beginPath();
        ctx.moveTo(left, pos);
        ctx.lineTo(right, pos);
        ctx.stroke();
        if (indicador !== "pedidos" || max - min >= 4 || Number.isInteger(total)) {
          ctx.fillText(abreviado.format(total), left - 8, pos + 4);
        }
      }
      const markers = [...new Set([0, Math.floor((pontos.length - 1) / 2), pontos.length - 1])];
      markers.forEach((index, i) => {
        if (pontos.length > 1 && width < 350 && i !== 0 && i !== markers.length - 1) return;
        ctx.textAlign = pontos.length === 1 ? "center" : i === 0 ? "left" : i === markers.length - 1 ? "right" : "center";
        ctx.fillText(dataBr(pontos[index].data).slice(0, 5), x(index), height - 9);
      });
      for (const grupo of grupos) {
        ctx.fillStyle = accent;
        if (grupo.length === 1) {
          const [{ index, total }] = grupo;
          ctx.beginPath();
          ctx.arc(x(index), y(total), 3.5, 0, 2 * Math.PI);
          ctx.fill();
          continue;
        }
        ctx.beginPath();
        for (const [position, { index, total }] of grupo.entries()) {
          if (position === 0) ctx.moveTo(x(index), y(total));
          else ctx.lineTo(x(index), y(total));
        }
        ctx.strokeStyle = accent;
        ctx.lineWidth = 2.2;
        ctx.lineJoin = "round";
        ctx.stroke();
        ctx.lineTo(x(grupo[grupo.length - 1].index), y(0));
        ctx.lineTo(x(grupo[0].index), y(0));
        ctx.closePath();
        ctx.globalAlpha = 0.10;
        ctx.fill();
        ctx.globalAlpha = 1;
      }
    }
    const resize = new ResizeObserver(draw);
    resize.observe(node);
    const theme = new MutationObserver(draw);
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["data-tema"] });
    window.addEventListener("beforeprint", draw);
    window.addEventListener("afterprint", draw);
    draw();
    return () => {
      resize.disconnect();
      theme.disconnect();
      window.removeEventListener("beforeprint", draw);
      window.removeEventListener("afterprint", draw);
    };
  }, [report, indicador]);

  return (
    <canvas ref={canvas} className="metricas-chart" role="img"
      aria-label={indicador === "pedidos"
        ? "Pedidos válidos por dia. Os valores estão na tabela de vendas por dia."
        : "Faturamento em reais por dia. Os valores estão na tabela de vendas por dia."} />
  );
}

export function Metricas({ pagina }: { pagina: PaginaMetricas }) {
  const [filtros, setFiltros] = useState<Periodo>(() => {
    const hoje = dataLocal(new Date());
    return { inicio: hoje.slice(0, 7) + "-01", fim: hoje };
  });
  const [consulta, setConsulta] = useState<Periodo>(filtros);
  const [carregado, setCarregado] = useState<
    { destino: "vendas"; dados: Vendas } |
    { destino: "produtos"; dados: RelatorioProdutos } |
    { destino: "anuncios"; dados: RelatorioAnuncios }
  >();
  const destino = pagina === "resumo" || pagina === "vendas" ? "vendas"
    : pagina === "produtos" || pagina === "anuncios" ? pagina : null;
  const atual = carregado?.destino === destino &&
    carregado.dados.inicio === consulta.inicio && carregado.dados.fim === consulta.fim ? carregado : undefined;
  const vendas = atual?.destino === "vendas" ? atual.dados : undefined;
  const [indicador, setIndicador] = useState<Indicador>("faturamento_centavos");
  const [busy, setBusy] = useState(true);
  const [falha, setFalha] = useState<{ destino: string; periodo: Periodo; texto: string }>();
  const [filtroErro, setFiltroErro] = useState("");
  useEffect(() => {
    if (destino === null) return;
    const controller = new AbortController();
    let active = true;
    const timer = setTimeout(() => controller.abort(), 58000);
    setBusy(true);
    setFalha(undefined);
    setCarregado(undefined);
    fetch("/api/central/v1/metricas/" + destino + "?" + new URLSearchParams(consulta), {
      credentials: "same-origin", cache: "no-store", redirect: "error", signal: controller.signal,
    }).then(async (response) => {
      if (response.status === 403) throw new Error("Sua conta não tem acesso a este relatório FARMA.");
      if (!response.ok) throw new Error("Não foi possível consultar a fonte na VPS. Tente novamente.");
      const report = await response.json();
      conferirPublicacao(report, consulta);
      if (!active) return;
      if (destino === "produtos") setCarregado({ destino, dados: lerProdutos(report) });
      else if (destino === "anuncios") setCarregado({ destino, dados: lerAnuncios(report) });
      else setCarregado({ destino, dados: lerVendas(report, consulta) });
    }).catch((reason) => {
      if (active) setFalha({ destino, periodo: consulta,
        texto: controller.signal.aborted ? "A consulta à VPS excedeu o prazo." :
          reason instanceof Error && !(reason instanceof TypeError) ? reason.message : "Não foi possível consultar a VPS.",
      });
    }).finally(() => {
      clearTimeout(timer);
      if (active) setBusy(false);
    });
    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [consulta, destino]);
  const erro = falha?.destino === destino && falha.periodo === consulta ? falha.texto : "";
  const previa = Object.hasOwn(previas, pagina) ? pagina as keyof typeof previas : null;
  const carregando = destino !== null && (busy || (!atual && !erro));

  const totals = vendas?.totais;
  const kpis = totals && [
    { title: "Faturamento", value: dinheiro(totals.faturamento_centavos), icon: Banknote, primary: true },
    { title: "Pedidos válidos", value: numeros.format(totals.pedidos), icon: ShoppingBag },
    { title: "Receita de produtos", value: dinheiro(totals.produtos_centavos), icon: Package },
    ...(pagina === "resumo" ? [
      { title: "Ticket médio", value: totals.pedidos ? dinheiro(Math.round(totals.faturamento_centavos / totals.pedidos)) : "Sem pedidos", icon: Truck },
    ] : [{ title: "Frete", value: dinheiro(totals.frete_centavos), icon: Truck }]),
  ];
  return (
    <div className="metricas">
      <header className="metricas-heading">
        <div>
          <p className="metricas-kicker"><span className="metricas-print-name">NexoFlow Métricas</span><span>FARMA</span></p>
          <h1>{paginasMetricas[pagina]}</h1>
          <p>{previa ? previas[previa].escopo : "Homologação · Dados reais da VPS"}</p>
        </div>
        {destino && <div className="metricas-export">
          <button className="metricas-secondary" disabled={!atual || carregando} onClick={() => window.print()}>
            <Printer size={16} aria-hidden="true" /> Imprimir
          </button>
          <button className="refresh" title="Abra a impressão e selecione Salvar como PDF" disabled={!atual || carregando}
            onClick={() => window.print()}>
            Exportar PDF <ArrowUpRight size={16} aria-hidden="true" />
          </button>
        </div>}
      </header>
      {pagina !== "base" && <form className="metricas-filter" onSubmit={(event) => {
        event.preventDefault();
        const intervalo = Date.parse(filtros.fim) - Date.parse(filtros.inicio);
        if (!Number.isFinite(intervalo) || intervalo < 0 || intervalo >= 366 * umDia) {
          setFiltroErro("Escolha um período de até 366 dias, com início anterior ou igual ao fim.");
          return;
        }
        setFiltroErro("");
        setConsulta({ ...filtros });
      }}>
        <CalendarDays size={18} aria-hidden="true" />
        <label>Início<input type="date" value={filtros.inicio} required
          onChange={(event) => setFiltros({ ...filtros, inicio: event.target.value })} /></label>
        <label>Fim<input type="date" value={filtros.fim} required
          onChange={(event) => setFiltros({ ...filtros, fim: event.target.value })} /></label>
        <button className="refresh" disabled={carregando}>Aplicar período</button>
      </form>}
      {filtroErro && <p role="alert">{filtroErro}</p>}
      {carregando && <p className="waiting" role="status">Consultando a publicação na VPS…</p>}
      {erro && <div className="error-panel" role="alert"><div><h2>Falha ao carregar o relatório</h2><p>{erro}</p></div></div>}
      {atual && <div className="metricas-source">
        <span>{dataBr(atual.dados.inicio)} a {dataBr(atual.dados.fim)} · Belém</span>
        <span title={atual.dados.revisao}>Revisão publicada v{atual.dados.versao}</span>
      </div>}
      {previa && <PreviaMetricas key={previa} pagina={previa} periodo={pagina === "base" ? undefined :
        dataBr(consulta.inicio) + " a " + dataBr(consulta.fim)} />}
      {pagina === "pedidos-dos-anuncios" && <PedidosAnuncios periodo={consulta} />}
      {atual?.destino === "produtos" && <Produtos relatorio={atual.dados} />}
      {atual?.destino === "anuncios" && <Anuncios relatorio={atual.dados} />}
      {vendas && totals && kpis && (
        <>
          <section className="metricas-kpis" aria-label="Indicadores de vendas">
            {kpis.map(({ title, value, icon: Icon, primary }) => (
              <article key={title} className={primary ? "metrica-card metrica-primary" : "metrica-card"}>
                <span className="metrica-icon"><Icon size={17} aria-hidden="true" /></span>
                <h2>{title}</h2>
                <p>{value}</p>
              </article>
            ))}
          </section>
          {totals.pedidos === 0 && (
            <p className="metricas-empty" role="status">Sem vendas registradas na revisão para este período.</p>
          )}
          {vendas.dias.length > 0 && (
            <div className="metricas-graphs">
              <section className="panel metricas-section" aria-labelledby="metricas-evolucao">
                <div className="metricas-graph-head">
                  <h2 id="metricas-evolucao">Evolução diária</h2>
                  <div className="metricas-graph-controls" role="group" aria-label="Indicador do gráfico">
                    <button className="metricas-secondary" aria-pressed={indicador === "faturamento_centavos"}
                      onClick={() => setIndicador("faturamento_centavos")}>Faturamento</button>
                    <button className="metricas-secondary" aria-pressed={indicador === "pedidos"}
                      onClick={() => setIndicador("pedidos")}>Pedidos</button>
                  </div>
                </div>
                <p className="metricas-unit">
                  {indicador === "pedidos" ? "Pedidos válidos" : "Faturamento em reais"}
                  {vendas.dias.length < 1 + (Date.parse(vendas.fim) - Date.parse(vendas.inicio)) / umDia
                    && " · Dias sem registro ficam sem ponto"}
                </p>
                <GraficoVendas report={vendas} indicador={indicador} />
              </section>
              <section className="panel metricas-section" aria-labelledby="metricas-composicao">
                <h2 id="metricas-composicao">Composição do faturamento</h2>
                <dl className="metricas-breakdown">
                  {[{ name: "Produtos", value: totals.produtos_centavos }, { name: "Frete", value: totals.frete_centavos }]
                    .map(({ name, value }) => {
                      const share = totals.faturamento_centavos > 0 && value >= 0 && value <= totals.faturamento_centavos
                        ? value / totals.faturamento_centavos : null;
                      return <div key={name}>
                        <dt>{name}</dt><dd>{dinheiro(value)}</dd>
                        {share !== null && <>
                          <progress aria-label={"Participação de " + name.toLowerCase()} value={share} max={1} />
                          <small>{percentual.format(share)} do faturamento</small>
                        </>}
                      </div>;
                    })}
                </dl>
              </section>
            </div>
          )}
          {pagina === "vendas" && vendas.dias.length > 0 && (
            <section className="panel metricas-section metricas-detail" aria-labelledby="metricas-dias">
              <h2 id="metricas-dias">Vendas por dia</h2>
              <div className="metricas-table-wrap" tabIndex={0} role="region" aria-labelledby="metricas-dias">
                <table className="metricas-table">
                  <thead><tr><th scope="col">Data</th><th scope="col">Pedidos</th><th scope="col">Produtos</th>
                    <th scope="col">Frete</th><th scope="col">Faturamento</th></tr></thead>
                  <tbody>{vendas.dias.map((dia) => (
                    <tr key={dia.data}><th scope="row">{dataBr(dia.data)}</th><td>{numeros.format(dia.pedidos)}</td>
                      <td>{dinheiro(dia.produtos_centavos)}</td><td>{dinheiro(dia.frete_centavos)}</td>
                      <td>{dinheiro(dia.faturamento_centavos)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </section>
          )}

        </>
      )}
      {atual && <p className="metricas-foot">Fonte PostgreSQL da VPS · FARMA · Revisão {atual.dados.revisao}</p>}
    </div>
  );
}
