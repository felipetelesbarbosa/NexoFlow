export const paginasMetricas = {
  resumo: "Resumo",
  vendas: "Vendas",
  clientes: "Meus clientes",
  "pedidos-por-cliente": "Pedidos por cliente",
  produtos: "Produtos mais vendidos",
  abc: "Curva ABC",
  anuncios: "Anúncios",
  "pedidos-dos-anuncios": "Pedidos dos Anúncios",
  base: "Base de clientes",
} as const;

export type PaginaMetricas = keyof typeof paginasMetricas;

export function enderecoMetricas(pagina: PaginaMetricas) {
  return pagina === "vendas" ? "/#metricas" : "/#metricas/" + pagina;
}

export function paginaMetricasDoHash(hash: string): PaginaMetricas {
  const slug = hash.slice("#metricas/".length);
  return hash.startsWith("#metricas/") && Object.hasOwn(paginasMetricas, slug)
    ? slug as PaginaMetricas : "vendas";
}

type Previa = {
  escopo: string;
  pendencia: string;
  indicadores: readonly string[];
  secoes: readonly { titulo: string; colunas: readonly string[] }[];
};

export const previas = {
  clientes: {
    escopo: "Clientes e compras no período",
    pendencia: "Compradores e receita por cliente aguardam conferência.",
    indicadores: ["Clientes que compraram", "Receita média por cliente", "Pedidos por cliente", "LTV parcial"],
    secoes: [
      { titulo: "Clientes de destaque", colunas: ["Cliente", "Receita"] },
      { titulo: "Quem comprou no período", colunas: ["Cliente", "Pedidos", "Receita", "Ticket médio", "Última compra"] },
    ],
  },
  "pedidos-por-cliente": {
    escopo: "Pedidos emitidos no período",
    pendencia: "Vínculo dos itens e acesso por cliente aguardam conferência.",
    indicadores: [],
    secoes: [
      { titulo: "Clientes de destaque", colunas: ["Cliente", "Pedidos", "Receita"] },
      { titulo: "Pedidos e produtos por cliente", colunas: ["Cliente", "Emissão", "Pedido", "Produto", "Quantidade", "Valor do item"] },
    ],
  },
  abc: {
    escopo: "Participação na receita de produtos no período",
    pendencia: "Classes e produtos comprados juntos aguardam conferência.",
    indicadores: ["Classe A", "Classe B", "Classe C", "Participação dos 5 primeiros"],
    secoes: [
      { titulo: "Participação por classe", colunas: ["Classe", "Produtos", "Receita", "Participação"] },
      { titulo: "Classificação de produtos", colunas: ["Produto", "Código", "Receita", "Participação acumulada", "Classe"] },
      { titulo: "Produtos comprados juntos", colunas: ["Produto", "Comprado junto com", "Pedidos"] },
    ],
  },
  base: {
    escopo: "Todo o histórico de clientes",
    pendencia: "Cadastro e compras de todo o histórico aguardam conferência.",
    indicadores: ["Contatos cadastrados", "Com compra", "Sem compra", "Receita histórica"],
    secoes: [
      { titulo: "Base de clientes", colunas: ["Cliente", "Pedidos", "Receita histórica", "Última compra"] },
      { titulo: "Canais e localidades", colunas: ["Canal", "Localidade", "Contatos"] },
      { titulo: "Idade na base", colunas: ["Faixa etária", "Contatos"] },
    ],
  },
} as const satisfies Partial<Record<PaginaMetricas, Previa>>;
