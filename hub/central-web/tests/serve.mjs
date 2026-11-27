import http from "node:http";
import { readFile } from "node:fs/promises";
import { resolve, sep, extname } from "node:path";
const root = resolve("dist");
const mime = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".woff2": "font/woff2",
  ".ico": "image/x-icon",
};
http
  .createServer(async (req, res) => {
    const pathname = new URL(req.url, "http://localhost").pathname;
    // Sessão sintética padrão para os ensaios da interface; testes de papel
    // e autenticação substituem esta resposta no próprio navegador.
    if (pathname === "/api/central/v1/sessao") {
      res.writeHead(200, { "Content-Type": "application/json" })
        .end(JSON.stringify({ ambientes: ["homologacao"], hub_disponivel: true }));
      return;
    }
    const path = resolve(
      root,
      "." + (pathname === "/" ? "/index.html" : pathname),
    );
    if (!path.startsWith(root + sep)) {
      res.writeHead(404).end();
      return;
    }
    try {
      const data = await readFile(path);
      res
        .writeHead(200, {
          "Content-Type": mime[extname(path)] ?? "application/octet-stream",
        })
        .end(data);
    } catch {
      res.writeHead(404).end();
    }
  })
  .listen(18745, "127.0.0.1");
