import { useEffect, useState } from "react";
import { BarChart3, Search } from "lucide-react";
import { previas } from "./metricas-paginas";

export type Periodo = { inicio: string; fim: string };
export type Publicacao = Periodo & { segmento: "FARMA"; fonte: "data_studio_producao"; revisao: string; versao: number };
export type Produto = { codigo: string | null; nome: string; unidades: string; receita_centavos: number };
export type RelatorioProdutos = Publicacao & {
  produtos_com_codigo: number; itens_sem_codigo: number; itens_incompletos: number;
  unidades: string; receita_centavos: number; ranking: Produto[];
};
export type Anuncio = {
  conta: string; moeda: string; fuso: string; atribuicao: string;
  anuncio: string | null; campanha: string | null;
  investimento: string | null; conversas: string | null; conversas_parciais: boolean;
  pedidos: number | null; receita_centavos: number | null; primeiras_compras: number | null;
  cpa_centavos: number | null; roas: string | null; cac_centavos: number | null; cobertura_parcial: boolean;
};
export type RelatorioAnuncios = Publicacao & { totais: Anuncio[]; anuncios: Anuncio[]; anuncios_limitados: boolean };

const numeros = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 });
const decimal = (value: unknown): value is string =>
  typeof value === "string" && /^\d+(?:\.\d+)?$/.test(value) && Number.isFinite(Number(value));

export function conferirPublicacao(data: Publicacao, periodo: Periodo) {
  if (data?.segmento !== "FARMA" || data.fonte !== "data_studio_producao" ||
      data.inicio !== periodo.inicio || data.fim !== periodo.fim ||
      !Number.isSafeInteger(data.versao) || data.versao < 1 ||
      typeof data.revisao !== "string" || !/^[\da-f-]{36}$/i.test(data.revisao)) {
    throw new Error("A fonte devolveu uma resposta incompatível.");
  }
}

export function lerProdutos(data: RelatorioProdutos) {
  if (!Array.isArray(data.ranking) || data.ranking.length > 50 || !decimal(data.unidades) ||
      ![data.produtos_com_codigo, data.itens_sem_codigo, data.itens_incompletos, data.receita_centavos].every(Number.isSafeInteger) ||
      data.ranking.some((row) => typeof row.nome !== "string" || !decimal(row.unidades) ||
        !Number.isSafeInteger(row.receita_centavos) || (row.codigo !== null && typeof row.codigo !== "string"))) {
    throw new Error("A fonte devolveu uma resposta incompatível.");
  }
  return data;
}

export function lerAnuncios(data: RelatorioAnuncios) {
  if (!Array.isArray(data.totais) || !Array.isArray(data.anuncios) ||
      data.totais.length > 50 || data.anuncios.length > 100 ||
      [...data.totais, ...data.anuncios].some((row) =>
        typeof row.conta !== "string" || !/^[A-Z]{3}$/.test(row.moeda) ||
        ![row.investimento, row.conversas, row.roas].every((value) => value === null || decimal(value)) ||
        ![row.pedidos, row.receita_centavos, row.primeiras_compras, row.cpa_centavos, row.cac_centavos]
          .every((value) => value === null || Number.isSafeInteger(value)))) {
    throw new Error("A fonte devolveu uma resposta incompatível.");
  }
  return data;
}

export function dinheiro(centavos: number, moeda = "BRL") {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: moeda }).format(centavos / 100);
}

export function Cards({ dados, titulo }: { dados: readonly { titulo: string; valor: string }[]; titulo: string }) {
  return (
    <section className="metricas-kpis" aria-label={titulo}>
      {dados.map(({ titulo: label, valor }, index) => (
        <article key={label} className={index === 0 ? "metrica-card metrica-primary" : "metrica-card"}>
          <span className="metrica-icon"><BarChart3 size={17} aria-hidden="true" /></span>
          <h2>{label}</h2>
          <p>{valor}</p>
        </article>
      ))}
    </section>
  );
}

function Tabela({ titulo, colunas, linhas = [], vazio, children }: {
  titulo: string; colunas: readonly string[]; linhas?: readonly string[][]; vazio?: string;
  children?: React.ReactNode;
}) {
  return (
    <section className="panel metricas-section metricas-detail">
      <h2>{titulo}</h2>
      {children}
      <div className="metricas-table-wrap" tabIndex={0} role="region" aria-label={titulo}>
        <table className="metricas-table metricas-report-table">
          <thead><tr>{colunas.map((label) => <th scope="col" key={label}>{label}</th>)}</tr></thead>
          <tbody>
            {linhas.map((row, index) => <tr key={index}>
              <th scope="row">{row[0]}</th>
              {row.slice(1).map((value, i) => <td key={i}>{value}</td>)}
            </tr>)}
            {linhas.length === 0 && <tr><td colSpan={colunas.length} className="metricas-table-empty">
              {vazio ?? "Aguardando validação da fonte"}
            </td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Barras({ titulo, itens, valor }: {
  titulo: string; itens: readonly { nome: string; total: number }[]; valor: (v: number) => string;
}) {
  if (!itens.length) return null;
  const maximo = Math.max(1, ...itens.map((item) => item.total));
  return (
    <section className="panel metricas-section">
      <h2>{titulo}</h2>
      <dl className="metricas-breakdown">
        {itens.map((item, index) => <div key={index}>
          <dt>{item.nome}</dt><dd>{valor(item.total)}</dd>
          <progress aria-label={item.nome} value={item.total} max={maximo} />
        </div>)}
      </dl>
    </section>
  );
}

export function Produtos({ relatorio }: { relatorio: RelatorioProdutos }) {
  const [busca, setBusca] = useState("");
  const termo = busca.trim().toLocaleLowerCase("pt-BR");
  const encontrados = relatorio.ranking.filter(({ nome, codigo }) =>
    !termo || nome.toLocaleLowerCase("pt-BR").includes(termo) || (codigo ?? "").toLowerCase().includes(termo));
  return <>
    <Cards titulo="Indicadores de produtos" dados={[
      { titulo: "Receita de produtos", valor: dinheiro(relatorio.receita_centavos) },
      { titulo: "Unidades vendidas", valor: numeros.format(Number(relatorio.unidades)) },
      { titulo: "Produtos com código", valor: numeros.format(relatorio.produtos_com_codigo) },
    ]} />
    {relatorio.itens_incompletos > 0 && <p className="metricas-empty" role="status">
      Dados parciais. {numeros.format(relatorio.itens_incompletos)} itens sem quantidade ou receita válida.
    </p>}
    {relatorio.itens_sem_codigo > 0 && <p className="metricas-unit">
      {numeros.format(relatorio.itens_sem_codigo)} itens sem código informado.
    </p>}
    <Barras titulo="5 mais vendidos por unidades"
      itens={relatorio.ranking.slice(0, 5).map((row) => ({ nome: row.nome, total: Number(row.unidades) }))}
      valor={(v) => numeros.format(v)} />
    <Tabela titulo="Ranking por unidades · até 50 produtos" colunas={["Produto", "Código", "Unidades", "Receita"]}
      linhas={encontrados.map((row) => [row.nome, row.codigo ?? "Sem código", numeros.format(Number(row.unidades)), dinheiro(row.receita_centavos)])}
      vazio={termo ? "Nenhum produto corresponde à busca no ranking." : relatorio.itens_incompletos ? "Nenhum item com quantidade e receita completas." : "Sem itens vendidos no período."}>
      <label className="metricas-search"><Search size={16} aria-hidden="true" /> Buscar no ranking
        <input value={busca} onChange={(event) => setBusca(event.target.value)} type="search" />
      </label>
    </Tabela>
  </>;
}

const chave = (row: Anuncio) => JSON.stringify([row.conta, row.moeda, row.fuso, row.atribuicao]);
const moeda = (row: Anuncio) => row.investimento === null ? "Investimento pendente" :
  dinheiro(Number(row.investimento) * 100, row.moeda);
const contagem = (value: string | number | null, vazio: string) => value === null ? vazio : numeros.format(Number(value));

export function Anuncios({ relatorio }: { relatorio: RelatorioAnuncios }) {
  const [grupo, setGrupo] = useState("");
  const totais = relatorio.totais.find((row) => chave(row) === grupo) ?? relatorio.totais[0];
  const dados = totais ? [
    { titulo: "Investimento", valor: moeda(totais) },
    { titulo: "Receita atribuída", valor: totais.receita_centavos === null ? "Receita pendente" : dinheiro(totais.receita_centavos) },
    { titulo: "Pedidos atribuídos", valor: contagem(totais.pedidos, "Pedidos pendentes") },
    { titulo: "Conversas iniciadas", valor: contagem(totais.conversas, "Conversas pendentes") },
    { titulo: "CPA", valor: totais.cpa_centavos !== null ? dinheiro(totais.cpa_centavos) : totais.pedidos === 0 ? "Sem pedido" : "Cálculo pendente" },
    { titulo: "ROAS", valor: totais.roas !== null ? numeros.format(Number(totais.roas)) + "×" : Number(totais.investimento) === 0 && totais.investimento !== null ? "Sem investimento" : "Cálculo pendente" },
    { titulo: "CAC", valor: totais.cac_centavos !== null ? dinheiro(totais.cac_centavos) : totais.primeiras_compras === 0 ? "Sem primeira compra" : "Primeira compra pendente" },
  ] : ["Investimento", "Receita atribuída", "Pedidos atribuídos", "Conversas iniciadas", "CPA", "ROAS", "CAC"]
    .map((titulo) => ({ titulo, valor: "Sem veiculação" }));
  const anuncios = totais ? relatorio.anuncios.filter((row) => chave(row) === chave(totais)) : [];
  return <>
    {relatorio.totais.length > 1 && <label className="metricas-search">Conta e configuração de anúncios
      <select value={chave(totais)} onChange={(event) => setGrupo(event.target.value)}>
        {relatorio.totais.map((row, i) => <option key={chave(row)} value={chave(row)}>
          {row.conta} · {row.moeda} · {row.fuso} · configuração {i + 1}
        </option>)}
      </select>
    </label>}
    <Cards titulo="Indicadores de anúncios" dados={dados} />
    {!totais && <p className="metricas-empty" role="status">Sem veiculação registrada no período.</p>}
    {totais && (totais.cobertura_parcial || totais.conversas_parciais) &&
      <p className="metricas-empty" role="status">Dados parciais. Os valores exibidos consideram a cobertura disponível.</p>}
    <Barras titulo="5 anúncios com maior investimento" itens={anuncios.filter((row) => row.investimento !== null)
      .slice(0, 5).map((row) => ({ nome: row.campanha ? row.campanha + " · " + row.anuncio : row.anuncio ?? "Anúncio", total: Number(row.investimento) }))}
      valor={(value) => dinheiro(value * 100, totais.moeda)} />
    <Tabela titulo="Resultados por anúncio" colunas={["Campanha", "Identificação do anúncio", "Investimento", "Conversas", "Pedidos", "Receita"]}
      linhas={anuncios.map((row) => [row.campanha ?? "Campanha não informada", row.anuncio ?? "Não informado", moeda(row),
        contagem(row.conversas, "Pendente"), contagem(row.pedidos, "Pendente"),
        row.receita_centavos === null ? "Pendente" : dinheiro(row.receita_centavos)])}
      vazio={totais ? "Sem detalhe de anúncios disponível para esta conta no recorte exibido." : "Sem veiculação registrada."}>
      {relatorio.anuncios_limitados && <p className="metricas-unit">Até 100 anúncios, ordenados por investimento.</p>}
    </Tabela>
  </>;
}

type PedidoAnuncio = {
  anuncio: string; campanha: string | null; conversa: string; emissao: string;
  vinculo: keyof typeof vinculos; receita_centavos: number;
};
type RelatorioPedidos = Publicacao & {
  encontrado: boolean; cobertura: "completa" | "parcial" | "sem_evidencia";
  limitado: boolean; pedidos: PedidoAnuncio[];
};
const vinculos = {
  direto: "Na conversa original",
  posterior: "Em até 7 dias",
  sem_vinculo_conversa: "Em até 7 dias · atendimento não confirmado",
} as const;
const dataBr = (data: string) => data.split("-").reverse().join("/");
const colunasPedidos = ["Campanha", "Identificação do anúncio", "Data da conversa", "Emissão do pedido", "Vínculo", "Receita"];

export function PedidosAnuncios({ periodo }: { periodo: Periodo }) {
  const [tipo, setTipo] = useState("campanha");
  const [codigo, setCodigo] = useState("");
  const [selecionado, setSelecionado] = useState<{ tipo: string; identificador: string }>();
  const [resultado, setResultado] = useState<{ periodo: Periodo; relatorio?: RelatorioPedidos; erro?: string }>();
  useEffect(() => {
    if (!selecionado) return;
    const stop = new AbortController();
    const timer = window.setTimeout(() => stop.abort(), 58000);
    let active = true;
    const query = new URLSearchParams({ ...periodo, ...selecionado });
    fetch("/api/central/v1/metricas/pedidos-anuncios?" + query, {
      cache: "no-store", credentials: "same-origin", redirect: "error", signal: stop.signal,
    }).then(async (response) => {
      if (!response.ok) throw new Error("Não foi possível consultar os pedidos vinculados na VPS.");
      const report: RelatorioPedidos = await response.json();
      conferirPublicacao(report, periodo);
      if (!Array.isArray(report.pedidos) || report.pedidos.length > 100 ||
          report.pedidos.some((row) => !Object.hasOwn(vinculos, row.vinculo) ||
            !Number.isSafeInteger(row.receita_centavos) || typeof row.anuncio !== "string" ||
            !/^\d{4}-\d{2}-\d{2}$/.test(row.conversa) || !/^\d{4}-\d{2}-\d{2}$/.test(row.emissao))) {
        throw new Error("A fonte devolveu pedidos em um formato incompatível.");
      }
      if (active) setResultado({ periodo, relatorio: report });
    }).catch((error) => {
      if (active) setResultado({ periodo, erro: stop.signal.aborted ? "A consulta excedeu o prazo." :
        error instanceof Error && !(error instanceof TypeError) ? error.message : "Falha ao acessar a VPS." });
    }).finally(() => window.clearTimeout(timer));
    return () => { active = false; window.clearTimeout(timer); stop.abort(); };
  }, [periodo, selecionado]);
  const atual = resultado?.periodo === periodo ? resultado : undefined;
  const relatorio = atual?.relatorio;
  const vazio = !relatorio?.encontrado ? "Identificação sem registros de anúncio no período." :
    relatorio.cobertura === "completa" ? "Sem pedido atribuído para esta identificação." : "Sem pedido comprovado na cobertura disponível.";
  return <>
    <form className="metricas-filter" onSubmit={(event) => {
      event.preventDefault();
      setResultado(undefined);
      setSelecionado({ tipo, identificador: codigo.trim() });
    }}>
      <label>Buscar por<select aria-label="Buscar por" value={tipo} onChange={(event) => setTipo(event.target.value)}>
        <option value="campanha">Campanha</option><option value="grupo">Grupo de anúncios</option><option value="anuncio">Anúncio</option>
      </select></label>
      <label>ID na Meta<input inputMode="numeric" autoComplete="off" pattern="[0-9]{1,25}"
        value={codigo} onChange={(event) => setCodigo(event.target.value)} required /></label>
      <button className="refresh"><Search size={16} aria-hidden="true" /> Buscar pedidos</button>
    </form>
    {selecionado && !atual && <p className="waiting" role="status">Buscando pedidos vinculados…</p>}
    {atual?.erro && <p className="metricas-empty" role="alert">{atual.erro}</p>}
    {relatorio && <>
      <div className="metricas-source">
        <span>{dataBr(periodo.inicio)} a {dataBr(periodo.fim)} · ID {selecionado?.identificador}</span>
        <span title={relatorio.revisao}>Revisão publicada v{relatorio.versao}</span>
        <button className="metricas-secondary metricas-export" onClick={() => window.print()}>Exportar PDF</button>
      </div>
      {relatorio.encontrado && relatorio.cobertura !== "completa" && <p className="metricas-empty" role="status">
        {relatorio.cobertura === "parcial" ? "Dados parciais da atribuição." : "Evidência de pedidos ainda não disponível."}
      </p>}
      <Tabela titulo="Pedidos atribuídos" colunas={colunasPedidos} vazio={vazio}
        linhas={relatorio.pedidos.map((row) => [row.campanha ?? "Campanha não informada", row.anuncio, dataBr(row.conversa),
          dataBr(row.emissao), vinculos[row.vinculo], dinheiro(row.receita_centavos)])}>
        {relatorio.limitado && <p className="metricas-unit">Até 100 resultados, começando pelas emissões mais recentes.</p>}
      </Tabela>
    </>}
  </>;
}

export function PreviaMetricas({ pagina, periodo }: { pagina: keyof typeof previas; periodo?: string }) {
  const config = previas[pagina];
  return <>
    <p className="metricas-empty" role="status"><strong>Em homologação.</strong> {config.pendencia}{periodo && <> <small>{periodo}</small></>}</p>
    {config.indicadores.length > 0 && <Cards titulo="Indicadores" dados={config.indicadores.map((titulo) => ({
      titulo, valor: "Pendente",
    }))} />}
    {config.secoes.map((secao) => <Tabela key={secao.titulo} titulo={secao.titulo} colunas={secao.colunas} />)}
  </>;
}
