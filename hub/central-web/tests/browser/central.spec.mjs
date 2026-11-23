import { expect, test } from "@playwright/test";
const now = new Date().toISOString();
const summary = {
  segmento: "FARMA",
  ambiente: "homologacao",
  metricas: { habilitado: false },
  integracoes: { hub: "pronto", processamento: "homologacao" },
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
