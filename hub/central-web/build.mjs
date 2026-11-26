import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { basename } from "node:path";
import { build } from "esbuild";

await rm("dist", { recursive: true, force: true });
await mkdir("dist/assets", { recursive: true });
const { metafile } = await build({
  entryPoints: ["src/app.tsx"],
  bundle: true,
  format: "esm",
  jsx: "automatic",
  minify: true,
  metafile: true,
  outdir: "dist/assets",
  entryNames: "[name]-[hash]",
  assetNames: "[name]-[hash]",
  loader: { ".woff2": "file" },
  target: "es2022",
  define: { "process.env.NODE_ENV": '"production"' },
});
const output = Object.entries(metafile.outputs).find(
  ([, m]) => m.entryPoint === "src/app.tsx",
);
if (!output?.[1].cssBundle) throw new Error("Assets da Central incompletos");
const html = (await readFile("index.html", "utf8")).replace(
  "<!-- assets -->",
  `<link rel="stylesheet" href="/assets/${basename(output[1].cssBundle)}"><script type="module" src="/assets/${basename(output[0])}"></script>`,
);
await writeFile("dist/index.html", html);
await cp("public", "dist", { recursive: true });
for (const asset of ["swagger-ui-bundle.js", "swagger-ui.css"]) {
  await cp("node_modules/swagger-ui-dist/" + asset, "dist/assets/" + asset);
}
const notices = [];
for (const name of ["react", "react-dom", "scheduler", "lucide-react", "@fontsource-variable/inter", "swagger-ui-dist"]) {
  notices.push(name + "\n" + (await readFile("node_modules/" + name + "/LICENSE", "utf8")));
}
for (const notice of ["NOTICE", "swagger-ui-bundle.js.LICENSE.txt"]) {
  notices.push(await readFile("node_modules/swagger-ui-dist/" + notice, "utf8"));
}
await writeFile("dist/licenses.txt", notices.join("\n\n"));
