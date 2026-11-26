import { useEffect, useState } from "react";
import { ArrowUpRight, BookOpen, Search } from "lucide-react";

type Api = "hub" | "central";
type Route = {
  method: string;
  path: string;
  id: string;
  name: string;
  group: string;
};

const definitions = {
  hub: {
    label: "API do Hub",
    authentication: "Use o token do segmento para executar e consultar tarefas. O webhook Weni FARMA usa uma credencial própria.",
  },
  central: {
    label: "API da Central",
    authentication: "Entre com sua conta individual no Cloudflare Access. A Central aplica as permissões do usuário para FARMA e PET.",
  },
};

function routesFrom(value: unknown): Route[] {
  if (!value || typeof value !== "object" || !("paths" in value) ||
      !value.paths || typeof value.paths !== "object") {
    throw new Error("O contrato da API está indisponível.");
  }
  const routes: Route[] = [];
  for (const [path, methods] of Object.entries(value.paths)) {
    if (!methods || typeof methods !== "object") continue;
    for (const [method, raw] of Object.entries(methods)) {
      if (!["get", "post"].includes(method) || !raw || typeof raw !== "object") continue;
      const { summary, operationId, tags } = raw as {
        summary?: unknown; operationId?: unknown; tags?: unknown;
      };
      const group: unknown = Array.isArray(tags) ? tags[0] : undefined;
      if (typeof summary !== "string" || typeof operationId !== "string" ||
          typeof group !== "string") continue;
      routes.push({
        method: method.toUpperCase(), path, id: operationId, name: summary, group,
      });
    }
  }
  return routes;
}

export function Documentation() {
  const [api, setApi] = useState<Api>("hub");
  const [search, setSearch] = useState("");
  const [routes, setRoutes] = useState<Route[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const schema = "/api/central/v1/documentacao/openapi.json?api=" + api;
  const swagger = "/swagger.html?api=" + api;

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 15000);
    let current = true;
    fetch(schema, { signal: controller.signal, cache: "no-store", credentials: "same-origin" })
      .then(async (response) => {
        if (response.status === 401 || response.redirected)
          throw new Error("Entre novamente na Central para consultar a documentação.");
        if (response.status === 403)
          throw new Error("Sua conta não tem acesso à documentação da Central.");
        if (!response.ok || !response.headers.get("Content-Type")?.includes("application/json"))
          throw new Error("A documentação da API está indisponível.");
        return routesFrom(await response.json());
      })
      .then((value) => { if (current) setRoutes(value); })
      .catch((reason: unknown) => {
        if (!current) return;
        setError(controller.signal.aborted ? "A documentação não respondeu a tempo."
          : reason instanceof Error && !(reason instanceof TypeError) ? reason.message
          : "A documentação da API está indisponível.");
      })
      .finally(() => window.clearTimeout(timer));
    return () => {
      current = false;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [schema, attempt]);

  const term = search.trim().toLocaleLowerCase("pt-BR");
  const groups = new Map<string, Route[]>();
  for (const route of routes ?? []) {
    if ([route.name, route.path, route.method, route.group].some((text) =>
      text.toLocaleLowerCase("pt-BR").includes(term))) {
      const group = groups.get(route.group);
      if (group) group.push(route);
      else groups.set(route.group, [route]);
    }
  }

  return (
    <section aria-labelledby="docs-title">
      <div className="title-row">
        <div><h1 id="docs-title">Documentação da API</h1>
          <p className="updated">Rotas, autenticação e exemplos do NexoFlow Hub.</p></div>
        <div className="docs-links">
          <a className="docs-action" href={swagger}><BookOpen size={16} /> Abrir Swagger</a>
          <a href={schema}>OpenAPI (JSON) <ArrowUpRight size={14} /></a>
        </div>
      </div>
      <div className="docs-tabs" aria-label="APIs disponíveis">
        {(Object.keys(definitions) as Api[]).map((key) => (
          <button key={key} type="button" aria-pressed={api === key} onClick={() => {
            if (key === api) return;
            setRoutes(null);
            setError("");
            setSearch("");
            setApi(key);
          }}>{definitions[key].label}</button>
        ))}
      </div>
      <div className="docs-access">
        <h2>Autenticação</h2>
        <p>{definitions[api].authentication}</p>
        {api === "hub" && <>
          <p><code>Authorization: Bearer SEU_TOKEN</code></p>
          <p>A rota interna <code>GET /saude</code> responde sem token para o monitoramento.</p>
        </>}
      </div>
      <label className="docs-search">
        <Search size={16} aria-hidden="true" />
        <input value={search} onChange={(event) => setSearch(event.target.value)}
          placeholder="Buscar por rota, método ou assunto" aria-label="Buscar rotas da API" />
      </label>
      {error ? <div role="alert" className="docs-access">
        <p>{error}</p>
        <button type="button" onClick={() => { setError(""); setAttempt(attempt + 1); }}>
          Tentar novamente
        </button>
      </div> : routes === null ? <p role="status">Carregando rotas…</p>
        : groups.size === 0 ? <p role="status">Nenhuma rota encontrada.</p>
        : Array.from(groups, ([name, entries]) => (
          <section className="docs-group" key={name}>
            <h2>{name}</h2>
            <ul>{entries.map((route) => (
              <li key={route.id}>
                <a href={swagger + "#/" + encodeURIComponent(route.group) + "/" + encodeURIComponent(route.id)}>
                  <span className={"docs-method " + route.method.toLowerCase()}>{route.method}</span>
                  <span><strong>{route.name}</strong><code>{route.path}</code></span>
                  <ArrowUpRight size={16} aria-hidden="true" />
                </a>
              </li>
            ))}</ul>
          </section>
        ))}
    </section>
  );
}
