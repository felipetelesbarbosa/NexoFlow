const api = new URLSearchParams(location.search).get("api") === "central" ? "central" : "hub";
const mount = document.querySelector("#swagger-ui");

async function showContract() {
  const response = await fetch("/api/central/v1/documentacao/openapi.json?api=" + api, {
    credentials: "same-origin",
    cache: "no-store",
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok || response.redirected || !response.headers.get("Content-Type")?.includes("application/json"))
    throw new Error("O contrato está indisponível.");
  SwaggerUIBundle({
    spec: await response.json(),
    domNode: mount,
    deepLinking: true,
    supportedSubmitMethods: [],
    persistAuthorization: false,
    validatorUrl: null,
    plugins: [() => ({
      components: { authorizeBtn: () => null, authorizeOperationBtn: () => null },
    })],
  });
}

showContract().catch(() => {
  mount.setAttribute("role", "alert");
  mount.textContent = "Não foi possível abrir o contrato. Confira sua sessão na Central e atualize a página.";
});
