import { expect, test } from "@playwright/test";
const now = new Date().toISOString();
const summary = {
  segmento: "FARMA",
  ambiente: "homologacao",
  metricas: { habilitado: false },
  integracoes: { hub: "pronto", processamento: "homologacao" },
  operacao: {
    worker_estado: "sinal_atrasado",
    worker_ultimo_ciclo_em: now,
    fila_prontas: 1,
    fila_em_espera: 2,
    fila_leases_expirados: 1,
    fila_espera_segundos: 120,
    ultima_conclusao_em: null,
  },
  tarefas: [
    {
      id: "6129c5f2-3e58-4c36-9bc4-cb6916c77269",
      estado: "falhou",
      criado_em: now,
      atualizado_em: now,
    },
  ],
  eventos: [
    { tipo: "atendimento_transferido", ocorrido_em: now, recebido_em: now },
  ],
};

test("Central mostra as etapas do Noturno e onde a execução parou", async ({ page }) => {
  await page.route("**/api/central/v1/resumo", (route) =>
    route.fulfill({ json: {
      ...summary,
      tarefas: [{
        ...summary.tarefas[0],
        tipo: "noturno",
        estado: "revisao_necessaria",
        etapas: [
          { etapa: "atualizacao_weni", estado: "concluida" },
          { etapa: "analytics", estado: "concluida" },
          { etapa: "publicacao", estado: "revisao_necessaria" },
          { etapa: "recompra", estado: "pendente" },
        ],
      }],
    } }),
  );
  await page.goto("/");
  await expect(page.getByText("Noturno · 6129c5f2")).toBeVisible();
  await page.getByRole("button", { name: /Detalhes da execução/ }).click();
  const stages = page.getByRole("region", { name: "Etapas do Noturno" });
  await expect(stages).toBeVisible();
  await expect(stages).toContainText("Publicação PostgreSQL");
  await expect(stages).toContainText("Revisão necessária");
  await expect(stages).toContainText("Recompra");
  await expect(stages).toContainText("Pendente");
});

test("documentação abre o Swagger em outra aba no celular e no PC", async ({ page, context }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await context.route("**/swagger.html?*", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: {
      ...response.headers(),
      "Content-Security-Policy": "default-src 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'none'",
    } });
  });
  await page.route("**/api/central/v1/resumo", (route) => route.fulfill({ json: summary }));
  await context.route("**/api/central/v1/documentacao/openapi.json?*", (route) => {
    const isCentral = new URL(route.request().url()).searchParams.get("api") === "central";
    return route.fulfill({ json: {
      openapi: "3.1.0",
      info: { title: isCentral ? "API da Central" : "API do Hub", version: "0.1.0" },
      paths: {
        [isCentral ? "/api/central/v1/resumo" : "/tarefas"]: {
          get: {
            tags: [isCentral ? "Operação" : "Execuções"],
            operationId: isCentral ? "resumo" : "tarefas",
            summary: isCentral ? "Consultar tarefas e eventos" : "Listar execuções do segmento",
            security: [{ Token: [] }],
            responses: { 200: { description: "Sucesso" } },
          },
        },
      },
      components: { securitySchemes: { Token: { type: "http", scheme: "bearer" } } },
    } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Abrir menu" }).click();
  await page.getByRole("link", { name: "Documentação", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Documentação da API" })).toBeVisible();
  await expect(page.getByText("Authorization: Bearer SEU_TOKEN")).toBeVisible();
  await page.getByRole("textbox", { name: "Buscar rotas da API" }).fill("xyz");
  await expect(page.getByText("Nenhuma rota encontrada.")).toBeVisible();
  await page.getByRole("button", { name: "API da Central" }).click();
  await expect(page.getByText("Consultar tarefas e eventos")).toBeVisible();
  await expect(page.getByText("Entre com sua conta individual", { exact: false })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  const originalUrl = page.url();
  const [swagger] = await Promise.all([
    page.waitForEvent("popup", { timeout: 5000 }),
    page.getByRole("link", { name: "Abrir Swagger" }).click(),
  ]);
  await expect(swagger).toHaveURL(/swagger\.html\?api=central$/);
  await expect(swagger.locator("#swagger-ui")).toContainText("Consultar tarefas e eventos");
  await swagger.locator(".opblock-summary").click();
  await expect(swagger.getByRole("button", { name: "Try it out" })).toHaveCount(0);
  await expect(swagger.getByRole("button", { name: /authorize/i })).toHaveCount(0);
  await expect(page).toHaveURL(originalUrl);
  await expect(page.getByRole("heading", { name: "Documentação da API" })).toBeVisible();
  await expect(page.getByRole("button", { name: "API da Central" })).toHaveAttribute("aria-pressed", "true");
  await swagger.close();

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.getByRole("button", { name: "API do Hub" }).click();
  await expect(page.getByText("Listar execuções do segmento")).toBeVisible();
  const [hubSwagger] = await Promise.all([
    page.waitForEvent("popup", { timeout: 5000 }),
    page.getByRole("link", { name: "Abrir Swagger" }).click(),
  ]);
  await expect(hubSwagger).toHaveURL(/swagger\.html\?api=hub$/);
  await expect(hubSwagger.locator("#swagger-ui")).toContainText("Listar execuções do segmento");
  await expect(page).toHaveURL(originalUrl);
  await expect(page.getByRole("heading", { name: "Documentação da API" })).toBeVisible();
});

test("navegar, filtrar e atualizar com revogação de acesso", async ({
  page,
}) => {
  let allowed = true;
  await page.route("**/api/central/v1/resumo", (route) =>
    allowed ? route.fulfill({ json: summary }) : route.fulfill({ status: 403 }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "NexoFlow Métricas" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: /Detalhes da execução/ }).click();
  await expect(page.getByRole("dialog")).toContainText(summary.tarefas[0].id);
  await page.keyboard.press("Escape");
  await page.getByRole("link", { name: "Execuções", exact: true }).click();
  await page.getByLabel("Estado da execução").selectOption("concluida");
  await expect(page.getByText("Nenhuma execução na seleção.")).toBeVisible();
  await page.getByRole("link", { name: "Eventos Weni", exact: true }).click();
  await expect(
    page.getByRole("cell", { name: "atendimento_transferido" }),
  ).toBeVisible();
  allowed = false;
  await page.getByRole("button", { name: "Atualizar", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("permissão de leitura");
  await expect(
    page.getByRole("cell", { name: "atendimento_transferido" }),
  ).toHaveCount(0);
});
test("celular, vazio e falha de leitura têm estados distintos", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 800 });
  let available = true;
  await page.route("**/api/central/v1/resumo", (r) =>
    available
      ? r.fulfill({ json: { ...summary, tarefas: [], eventos: [] } })
      : r.fulfill({ status: 503 }),
  );
  await page.goto("/");
  await expect(page.getByText("Nenhuma execução na seleção.")).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(375);
  await page.getByRole("button", { name: "Abrir menu" }).click();
  await page.getByRole("link", { name: "Eventos Weni", exact: true }).click();
  await expect(page.getByText("Nenhum evento na seleção.")).toBeVisible();
  available = false;
  await page.getByRole("button", { name: "Atualizar", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("indisponível");
  await expect(page.getByText("Nenhum evento na seleção.")).toHaveCount(0);
});

test("tema inicial claro, preferência escura aplicada antes da API e navegação lateral no desktop", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "dark" });
  let themeAtRequest;
  await page.route("**/api/central/v1/resumo", async (route) => {
    themeAtRequest = await page.locator("html").getAttribute("data-tema");
    await route.fulfill({ json: summary });
  });
  await page.goto("/");
  const theme = page.getByRole("button", { name: "Tema escuro" });
  await expect(
    page.getByRole("button", { name: /Detalhes da execução/ }),
  ).toBeVisible();
  expect(themeAtRequest).toBe("claro");
  await expect(theme).toHaveAttribute("aria-pressed", "false");
  await theme.click();
  await expect(theme).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(
    page.getByRole("button", { name: /Detalhes da execução/ }),
  ).toBeVisible();
  expect(themeAtRequest).toBe("grafite");
  await expect(theme).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Recolher navegação" }).click();
  await expect(
    page.getByRole("button", { name: "Expandir navegação" }),
  ).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("link", { name: "Execuções", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Execuções", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Expandir navegação" }).click();
  await expect(
    page.getByRole("button", { name: "Recolher navegação" }),
  ).toHaveAttribute("aria-expanded", "true");
});

for (const width of [320, 375]) {
  for (const dark of [false, true]) {
    test(`execução, filtros e retorno em ${width}px no tema ${dark ? "grafite" : "claro"}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 700 });
      await page.route("**/api/central/v1/resumo", (r) =>
        r.fulfill({ json: summary }),
      );
      await page.goto("/");
      if (dark) await page.getByRole("button", { name: "Tema escuro" }).click();
      const operation = page.getByRole("region", { name: "Processamento do Hub" });
      await expect(operation).toContainText("Sinal atrasado");
      await expect(operation).toContainText("Maior espera entre as prontas 120 s");
      await expect(operation).toContainText("Nenhuma conclusão registrada");
      const fits = async () =>
        expect(
          await page.evaluate(() =>
            Math.max(
              document.documentElement.scrollWidth,
              ...Array.from(document.querySelectorAll(".scroll"), (el) =>
                el.scrollWidth > el.clientWidth
                  ? document.documentElement.clientWidth + 1
                  : 0,
              ),
            ),
          ),
        ).toBeLessThanOrEqual(width);
      await page.getByText("Ver valores por dia", { exact: true }).click();
      await fits();
      await page.getByRole("button", { name: "Abrir menu" }).click();
      await expect(
        page.getByRole("button", { name: "NexoFlow Métricas" }),
      ).toBeDisabled();
      await page.getByRole("link", { name: "Execuções", exact: true }).click();
      await page.getByLabel("Estado da execução").selectOption("concluida");
      await expect(
        page.getByText("Nenhuma execução na seleção."),
      ).toBeVisible();
      await page.getByLabel("Estado da execução").selectOption("falhou");
      await page.getByRole("searchbox").fill("6129c5f2");
      const open = page.getByRole("button", { name: /Detalhes da execução/ });
      await expect(page.locator("td .status")).toHaveText("Falhou");
      await fits();
      await open.click();
      await expect(page.getByRole("dialog")).toContainText(
        summary.tarefas[0].id,
      );
      await fits();
      await page.getByRole("button", { name: "Fechar detalhes" }).click();
      await expect(open).toBeFocused();
      await page.getByRole("button", { name: "Abrir menu" }).click();
      await page
        .getByRole("link", { name: "Eventos Weni", exact: true })
        .click();
      await expect(
        page.getByRole("cell", { name: /atendimento_transferido/ }),
      ).toBeVisible();
      await fits();
      await page.getByRole("button", { name: "Abrir menu" }).click();
      await page
        .getByRole("link", { name: "Visão geral", exact: true })
        .click();
      await expect(
        page.getByRole("heading", { name: "Visão geral" }),
      ).toBeVisible();
    });
  }
}

test("trocar segmentos autorizados limpa dados e descarta respostas superadas; revogação recarrega permissões", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 700 });
  let releaseSlowPet;
  const slowPet = new Promise((resolve) => {
    releaseSlowPet = resolve;
  });
  let attempts = 0;
  let revoked = false;
  const petId = "1d7570de-46bb-41eb-bded-d02622ad6aab";
  await page.route("**/api/central/v1/resumo*", async (route) => {
    const segment = new URL(route.request().url()).searchParams.get("segmento");
    if (revoked && segment) return route.fulfill({ status: 403 });
    if (segment === "PET") {
      if (++attempts === 1) await slowPet;
      return route.fulfill({
        json: {
          ...summary,
          segmento: "PET",
          segmentos_autorizados: ["FARMA", "PET"],
          tarefas: [{ ...summary.tarefas[0], id: petId }],
        },
      });
    }
    return route.fulfill({
      json: {
        ...summary,
        segmentos_autorizados: revoked ? ["FARMA"] : ["FARMA", "PET"],
      },
    });
  });
  await page.goto("/");
  const picker = page.getByLabel("Segmento da Central");
  const farma = page.getByRole("button", {
    name: "Detalhes da execução " + summary.tarefas[0].id,
  });
  const pet = page.getByRole("button", {
    name: "Detalhes da execução " + petId,
  });
  await expect(farma).toBeVisible();
  await picker.selectOption("PET");
  await expect(page.getByRole("status")).toBeVisible();
  await expect(farma).toHaveCount(0);
  await picker.selectOption("FARMA");
  await expect(farma).toBeVisible();
  releaseSlowPet();
  await expect(pet).toHaveCount(0);
  await picker.selectOption("PET");
  await expect(pet).toBeVisible();
  await expect(farma).toHaveCount(0);
  await expect(picker).toHaveValue("PET");
  revoked = true;
  await page.getByRole("button", { name: "Atualizar", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("permissão");
  await expect(pet).toHaveCount(0);
  await expect(picker).toHaveCount(0);
  await page.getByRole("button", { name: "Atualizar", exact: true }).click();
  await expect(farma).toBeVisible();
  await expect(page.getByLabel("Segmento FARMA")).toBeVisible();
  await expect(picker).toHaveCount(0);
});

test("infraestrutura em uma aba própria e uma coleta atrasada no celular", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 760 });
  await page.route("**/api/central/v1/resumo", (r) => r.fulfill({ json: summary }));
  let collected = false;
  await page.route("**/api/central/v1/infraestrutura", (r) => r.fulfill({
    json: collected ? {
      estado: "desatualizado",
      vps: {
        coletado_em: now, hostname: "vps.example.test", sistema: "Ubuntu",
        estado: "running", cidade: "Campinas", pais: "BR", ipv4: "192.0.2.1",
        plano: "KVM 4", nucleos: 4, ram_bytes: 16 * 1024 ** 3,
        disco_bytes: 200 * 1024 ** 3, banda_bytes: null,
        validade: null, renovacao_automatica: null, ultimo_backup_provedor: null,
        metricas: { cpu: [[now, 0]], ram: [], disco: [], entrada: [], saida: [], uptime: [] },
      },
    } : { estado: "aguardando_coleta", vps: null },
  }));
  await page.goto("/");
  await page.getByRole("button", { name: "Abrir menu" }).click();
  await page.getByRole("link", { name: "Infraestrutura" }).click();
  await expect(page.getByRole("heading", { name: "Infraestrutura" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Aguardando a primeira coleta");
  await expect(page.getByLabel("Período")).toHaveCount(0);
  collected = true;
  await page.getByRole("button", { name: "Atualizar", exact: true }).click();
  await expect(page.getByText("Coleta atrasada", { exact: false })).toBeVisible();
  await expect(page.getByText("0%", { exact: true })).toBeVisible();
  await expect(page.getByText("Sem amostra nas últimas 24 horas").first()).toBeVisible();
  await page.getByRole("button", { name: "Tema escuro" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-tema", "grafite");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

test("consumo de APIs abre histórico, detalhes e log textual no celular", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 760 });
  await page.route("**/api/central/v1/resumo", (r) => r.fulfill({ json: summary }));
  await page.route("**/api/central/v1/consumo*", (r) => {
    const api = new URL(r.request().url()).searchParams.get("api");
    return r.fulfill({
      json: {
        segmento: "FARMA",
        resumo: [{ api: "hub", total: 4, sucesso: 3, erros: 1, p95_ms: 22 }],
        serie: [{ api: "hub", hora: new Date(Math.floor(Date.parse(now) / 3600000) * 3600000).toISOString(), sucesso: 3, erros: 1 }],
        requisicoes: api === "hub" ? [{
          id: 100, ocorrido_em: now, metodo: "POST", endpoint: "/tarefas",
          http: 409, duracao_ms: 22, corpo: { origem: "teste" },
          erro: "IDEMPOTENCIA_CONFLITANTE",
        }] : [],
        proximo: null,
      },
    });
  });
  await page.goto("/#consumo");
  await expect(page.getByText("75%", { exact: true })).toBeVisible();
  await expect(page.getByText("25%", { exact: true })).toBeVisible();
  const coverage = page.getByRole("region", { name: "Integrações sem telemetria na Central" });
  await expect(coverage.getByText("FarmaLíder", { exact: true })).toBeVisible();
  await expect(coverage.getByText("Weni Flows", { exact: true })).toBeVisible();
  await page.getByText("Ver números por hora").click();
  await expect(page.getByRole("columnheader", { name: "Hora (Belém)" })).toBeVisible();
  await expect(page.getByText("Nenhuma requisição registrada no período.")).toBeVisible();
  await page.getByRole("button", { name: "Detalhes de API do Hub" }).click();
  await expect(page.getByRole("region", { name: "Requisições de API do Hub" })).toBeFocused();
  await page.getByLabel("Somente erros").check();
  await page.getByRole("button", { name: /POST \/tarefas/ }).click();
  const detail = page.getByRole("dialog");
  await expect(detail).toContainText("IDEMPOTENCIA_CONFLITANTE");
  await expect(detail).toContainText("A mesma chave foi usada com dados diferentes.");
  await expect(detail).toContainText("Campos técnicos do corpo");
  await detail.getByText("Log textual").click();
  await expect(detail.getByText(/"requisicao": 100/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  await page.keyboard.press("Escape");
  await expect(detail).toHaveCount(0);
});

test("troca de ambiente exibe apenas resultados e segmentos do destino", async ({ page }) => {
  await page.route("**/api/central/v1/sessao", (route) =>
    route.fulfill({ json: { ambientes: ["homologacao", "producao"] } }),
  );
  await page.route("**/api/central/v1/resumo*", (route) => {
    const production = new URL(route.request().url()).searchParams.get("ambiente") === "producao";
    return route.fulfill({ json: production ? {
      ...summary,
      segmento: "PET",
      segmentos_autorizados: ["PET"],
      ambiente: "producao",
      integracoes: { hub: "pronto", processamento: "producao" },
      tarefas: [],
      eventos: [],
    } : summary });
  });
  await page.goto("/");
  const environment = page.getByRole("combobox", { name: "Ambiente da Central" });
  await expect(environment).toHaveValue("homologacao");
  await expect(page.getByRole("button", { name: /Detalhes da execução/ })).toBeVisible();
  await environment.selectOption("producao");
  await expect(page.getByLabel("Segmento PET", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Detalhes da execução/ })).toHaveCount(0);
  await environment.selectOption("homologacao");
  await expect(page.getByLabel("Segmento FARMA", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Detalhes da execução/ })).toBeVisible();
});

test("Minha Conta salva o nome e encaminha a segurança ao provedor", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 });
  let name = "Felipe";
  await page.route("**/api/central/v1/minha-conta", (route) => {
    if (route.request().method() === "PUT") {
      const change = route.request().postDataJSON();
      name = change.nome;
      return route.fulfill({ json: { nome: name } });
    }
    return route.fulfill({ json: {
      nome: name,
      email: "operador@example.invalid",
      nome_editavel: true,
      mfa_url: "https://ensaio.cloudflareaccess.com/AddMfaDevice",
    } });
  });
  await page.goto("/#conta");
  const field = page.getByRole("textbox", { name: "Nome de exibição" });
  await expect(field).toHaveValue("Felipe");
  await field.fill("Felipe Silva");
  await page.getByRole("button", { name: "Salvar nome" }).click();
  await expect(page.getByText("Nome salvo.")).toBeVisible();
  await page.reload();
  await expect(field).toHaveValue("Felipe Silva");
  await expect(page.getByText("operador@example.invalid")).toBeVisible();
  await expect(page.getByRole("link", { name: /Alterar e-mail ou senha/ })).toHaveAttribute("href", "https://dash.cloudflare.com/profile");
  await expect(page.getByRole("link", { name: /Configurar um dispositivo/ })).toHaveAttribute("href", "https://ensaio.cloudflareaccess.com/AddMfaDevice");
  await expect(page.getByRole("option", { name: "Produção indisponível" })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

test("só o Super Admin vê o cadastro de convites e o atalho para autorização na Cloudflare", async ({ page }) => {
  let admin = false;
  let papel = "admin";
  let conviteEnviado;
  let papelAlterado;
  await page.route("**/api/central/v1/sessao", (route) =>
    route.fulfill({ json: { ambientes: ["homologacao"], gerencia_usuarios: admin, metricas_farma: true, papel: admin ? "super_admin" : "admin" } }),
  );
  await page.route("**/api/central/v1/usuarios", (route) =>
    route.fulfill({ json: { usuarios: [{ id: "super", email: "super@example.invalid", segmentos: ["FARMA"], super_admin: true, papel: "super_admin" }, { id: "leitor", email: "leitor@example.invalid", segmentos: ["FARMA"], super_admin: false, papel }], convites: ["pendente", "aceito", "expirado", "cancelado"].map((estado) => ({
      id: estado, email: estado + "@example.invalid", segmentos: ["FARMA"], estado, expira_em: 1800000000,
    })) } }),
  );
  await page.route("**/api/central/v1/convites", (route) => {
    conviteEnviado = route.request().postDataJSON();
    return route.fulfill({ status: 201, json: { codigo: "c".repeat(43) } });
  });
  await page.route("**/api/central/v1/usuarios/papel", (route) => {
    papelAlterado = route.request().postDataJSON();
    papel = papelAlterado.papel;
    return route.fulfill({ status: 204 });
  });
  await page.goto("/#usuarios");
  await expect(page.getByText("Área exclusiva do Super Admin.")).toBeVisible();
  await expect(page.getByRole("link", { name: /Autorizar convidados no Cloudflare Access/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Gerenciar Usuários", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "NexoFlow Métricas", exact: true })).toHaveCount(1);
  admin = true;
  await page.reload();
  await expect(page.getByRole("region", { name: "Autorizar na Cloudflare" })).toBeVisible();
  await expect(page.getByText("Central | Convidados OTP", { exact: true })).toBeVisible();
  const link = page.getByRole("link", { name: /Autorizar convidados no Cloudflare Access/ });
  await expect(link).toHaveAttribute("href", "https://dash.cloudflare.com/3d28f3cbcbb2f27849194e412022d510/one/access-controls/policies/53c46c33-5075-41fe-a475-77be7ab3be6a/edit");
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(page.getByRole("link", { name: "Autorizar admins no Cloudflare Access" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Autorizar admins com MFA" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Autorizar convidados com MFA" })).toBeVisible();
  const tornarConvidado = page.getByRole("button", { name: "Tornar Convidado", exact: true });
  const tornarMetricas = page.getByRole("button", { name: "Tornar Convidado Métricas", exact: true });
  const tornarAdmin = page.getByRole("button", { name: "Tornar Admin", exact: true });
  await expect(page.getByRole("listitem").filter({ hasText: "Você · Super Admin" }).getByRole("button")).toHaveCount(0);
  await expect(tornarConvidado).toBeVisible();
  await expect(tornarMetricas).toBeVisible();
  await expect(tornarAdmin).toBeVisible();
  await expect(tornarConvidado).toBeEnabled();
  await expect(tornarAdmin).toBeDisabled();
  expect(await tornarAdmin.getAttribute("aria-pressed")).toBe("true");
  page.once("dialog", (dialog) => dialog.accept());
  await tornarConvidado.click();
  await expect(tornarConvidado).toBeDisabled();
  await expect(tornarAdmin).toBeEnabled();
  expect(papelAlterado).toEqual({ id: "leitor", papel: "convidado" });
  await page.setViewportSize({ width: 320, height: 740 });
  await expect(tornarConvidado).toBeVisible();
  await expect(tornarAdmin).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  page.once("dialog", (dialog) => dialog.accept());
  await tornarAdmin.click();
  await expect(tornarConvidado).toBeEnabled();
  await expect(tornarAdmin).toBeDisabled();
  expect(papelAlterado).toEqual({ id: "leitor", papel: "admin" });
  page.once("dialog", (dialog) => dialog.accept());
  await tornarMetricas.click();
  await expect(tornarMetricas).toBeDisabled();
  await expect(tornarConvidado).toBeEnabled();
  await expect(tornarAdmin).toBeEnabled();
  expect(papelAlterado).toEqual({ id: "leitor", papel: "convidado_metricas" });
  await expect(page.getByRole("button", { name: "Pendentes (1)" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Cancelar convite" })).toBeVisible();
  await page.getByRole("button", { name: "Aceitos (1)" }).click();
  await expect(page.getByText("aceito@example.invalid", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancelar convite" })).toHaveCount(0);
  await page.getByRole("button", { name: "Cancelados (2)" }).click();
  await expect(page.getByText("Expirado · FARMA", { exact: true })).toBeVisible();
  await expect(page.getByText("Cancelado · FARMA", { exact: true })).toBeVisible();
  await page.getByLabel("E-mail do convidado").fill("convidado@example.invalid");
  await page.getByLabel("Papel do usuário").selectOption("admin");
  await page.getByLabel("FARMA", { exact: true }).check();
  await page.getByRole("button", { name: "Criar convite" }).click();
  await expect(page.getByLabel(/Link de uso único/)).toHaveValue(
    "https://central.nexoflowhub.com.br/#convite/" + "c".repeat(43),
  );
  expect(conviteEnviado).toEqual({ email: "convidado@example.invalid", segmentos: ["FARMA"], papel: "admin" });
  await page.getByLabel("E-mail do convidado").fill("metricas@example.invalid");
  await page.getByLabel("PET", { exact: true }).check();
  await page.getByLabel("Papel do usuário").selectOption("convidado_metricas");
  await expect(page.getByLabel("FARMA", { exact: true })).toBeChecked();
  await expect(page.getByLabel("PET", { exact: true })).not.toBeChecked();
  await expect(page.getByLabel("PET", { exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Criar convite" }).click();
  await expect(page.getByLabel(/Link de uso único/)).toHaveValue(
    "https://central.nexoflowhub.com.br/#convite/" + "c".repeat(43),
  );
  expect(conviteEnviado).toEqual({ email: "metricas@example.invalid", segmentos: ["FARMA"], papel: "convidado_metricas" });
  await page.goto("/#convite/" + "c".repeat(43));
  await expect(page.getByRole("button", { name: "Aceitar convite" })).toBeVisible();
  await expect(link).toHaveCount(0);
});

test("Vendas FARMA abre em outra aba, mostra os indicadores e imprime no celular", async ({ page: central, context }) => {
  await central.setViewportSize({ width: 320, height: 740 });
  await context.route("**/api/central/v1/sessao", (route) => route.fulfill({
    json: { ambientes: ["homologacao"], metricas_farma: true },
  }));
  await context.route("**/api/central/v1/resumo", (route) => route.fulfill({ json: summary }));
  await context.route("**/api/central/v1/metricas/vendas?*", (route) => {
    const params = new URL(route.request().url()).searchParams;
    const inicio = params.get("inicio"), fim = params.get("fim");
    const empty = inicio === "2025-01-01";
    const totals = {
      pedidos: empty ? 0 : 2,
      produtos_centavos: empty ? 0 : 10100,
      frete_centavos: empty ? 0 : 350,
      faturamento_centavos: empty ? 0 : 10450,
    };
    return route.fulfill({ json: {
      inicio, fim, segmento: "FARMA", fonte: "data_studio_producao",
      revisao: "f3f4cbfd-eb3d-4c37-973c-b17190c3fe27", versao: 61,
      totais: totals, dias: empty ? [] : [{ data: inicio, ...totals }],
    } });
  });
  await central.goto("/#geral");
  await central.getByRole("button", { name: "Tema escuro" }).click();
  await central.getByRole("button", { name: "Abrir menu" }).click();
  const [page] = await Promise.all([
    central.waitForEvent("popup", { timeout: 5000 }),
    central.getByRole("link", { name: "NexoFlow Métricas", exact: true }).click(),
  ]);
  await page.setViewportSize({ width: 320, height: 740 });
  await expect(central).toHaveURL(/#geral$/);
  await expect(page).toHaveURL(/#metricas$/);
  await expect(page).toHaveTitle("Vendas · NexoFlow Métricas");
  await expect(page.locator("html")).toHaveAttribute("data-tema", "grafite");
  await expect(page.getByRole("navigation", { name: "Navegação principal" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Vendas" })).toHaveAttribute("aria-current", "page");
  const back = page.getByRole("link", { name: "Voltar à Central" });
  await expect(back).toBeVisible();
  const kpis = page.getByRole("region", { name: "Indicadores de vendas" });
  await expect(kpis).toContainText("104,50");
  await expect(page.getByText("Revisão publicada v61")).toBeVisible();
  await expect(page.getByRole("img", { name: /Faturamento em reais por dia/ })).toBeVisible();
  await page.getByRole("button", { name: "Pedidos", exact: true }).click();
  await expect(page.getByRole("img", { name: /Pedidos válidos por dia/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  await page.evaluate(() => { window.print = () => document.body.classList.add("print-invoked"); });
  await page.getByRole("button", { name: "Exportar PDF" }).click();
  await expect(page.locator("body")).toHaveClass(/print-invoked/);
  await page.emulateMedia({ media: "print" });
  await expect(page.getByRole("button", { name: "Aplicar período" })).toBeHidden();
  await expect(page.getByRole("navigation")).toBeHidden();
  await expect(back).toBeHidden();
  await expect(page.locator(".metricas-print-name")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Vendas por dia" })).toBeVisible();
  const pdf = await page.pdf({ preferCSSPageSize: true, printBackground: true });
  expect(pdf.toString("utf8", 0, 5)).toBe("%PDF-");
  expect(pdf.byteLength).toBeGreaterThan(15000);
  // A one-row report must not create an empty cover page.
  expect(pdf.toString("latin1").match(/\/Type\s*\/Page\b/g) ?? []).toHaveLength(1);
  await expect(page.locator("html")).toHaveCSS("page", "relatorio-vendas");
  await expect(page.locator(".metricas-table")).toHaveCSS("table-layout", "fixed");
  await page.emulateMedia({ media: "screen" });
  await page.getByLabel("Início", { exact: true }).fill("2026-11-01");
  await page.getByLabel("Fim", { exact: true }).fill("2026-11-03");
  await page.getByRole("button", { name: "Aplicar período" }).click();
  await expect(page.getByText(/Dias sem registro ficam sem ponto/)).toBeVisible();
  await page.getByLabel("Início", { exact: true }).fill("2025-01-01");
  await page.getByLabel("Fim", { exact: true }).fill("2025-01-02");
  await page.getByRole("button", { name: "Aplicar período" }).click();
  await expect(page.getByText("Sem vendas registradas na revisão para este período.")).toBeVisible();
  await expect(kpis).toContainText("0,00");
  await back.click();
  await expect(page).toHaveURL(/#geral$/);
  await expect(page.getByRole("heading", { name: "Visão geral" })).toBeVisible();
});

test("Vendas FARMA não consulta dados quando a sessão não tem permissão", async ({ page }) => {
  await page.route("**/api/central/v1/sessao", (route) => route.fulfill({
    json: { ambientes: ["homologacao"] },
  }));
  let accesses = 0;
  page.on("request", (request) => {
    if (request.url().includes("/metricas/vendas?")) accesses++;
  });
  await page.goto("/#metricas");
  await expect(page.getByText("NexoFlow Métricas indisponível para esta conta.")).toBeVisible();
  expect(accesses).toBe(0);
});

test("convidado exclusivo do Métricas entra direto em Vendas sem consultar nem exibir o Hub", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 740 });
  await page.route("**/api/central/v1/sessao", (route) => route.fulfill({
    json: {
      ambientes: ["homologacao"], papel: "convidado_metricas",
      hub_disponivel: false, metricas_farma: true, gerencia_usuarios: false,
    },
  }));
  await page.route("**/api/central/v1/metricas/vendas?*", (route) => {
    const params = new URL(route.request().url()).searchParams;
    return route.fulfill({ json: {
      inicio: params.get("inicio"), fim: params.get("fim"), segmento: "FARMA",
      fonte: "data_studio_producao", revisao: "f3f4cbfd-eb3d-4c37-973c-b17190c3fe27",
      versao: 15, totais: { pedidos: 0, produtos_centavos: 0, frete_centavos: 0, faturamento_centavos: 0 },
      dias: [],
    } });
  });
  const hubCalls = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/central/v1/") && !["/api/central/v1/sessao", "/api/central/v1/metricas/vendas"].includes(path)) hubCalls.push(path);
  });
  await page.goto("/");
  await expect(page).toHaveURL(/#metricas$/);
  await expect(page.getByRole("region", { name: "Indicadores de vendas" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Voltar à Central" })).toHaveCount(0);
  await expect(page.getByRole("navigation", { name: "Navegação principal" })).toHaveCount(0);
  for (const path of ["usuarios", "infraestrutura", "documentacao", "execucoes", "conta"]) {
    await page.goto("/#" + path);
    await expect(page).toHaveURL(/#metricas$/);
    await expect(page.getByRole("link", { name: "Vendas", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Gerenciar Usuários" })).toHaveCount(0);
  }
  expect(hubCalls).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

test("falha da sessão não abre a navegação nem consulta dados do Hub", async ({ page }) => {
  await page.route("**/api/central/v1/sessao", (route) => route.fulfill({ status: 403 }));
  const hubCalls = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/central/v1/") && path !== "/api/central/v1/sessao") hubCalls.push(path);
  });
  await page.goto("/#infraestrutura");
  await expect(page.getByRole("alert")).toContainText("Não foi possível confirmar sua autorização");
  await expect(page.getByRole("navigation", { name: "Navegação principal" })).toHaveCount(0);
  expect(hubCalls).toEqual([]);
});
