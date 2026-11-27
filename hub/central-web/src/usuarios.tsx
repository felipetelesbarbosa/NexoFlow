import { useEffect, useState } from "react";
import { horaLocal, isSegmento } from "./resumo";
import type { Segmento } from "./resumo";

const api = "/api/central/v1";
const centralOficial = "https://central.nexoflowhub.com.br";
const accessApps = "https://dash.cloudflare.com/3d28f3cbcbb2f27849194e412022d510/one/access-controls/policies/53c46c33-5075-41fe-a475-77be7ab3be6a/edit";
const accessAdminOtp = "https://dash.cloudflare.com/3d28f3cbcbb2f27849194e412022d510/one/access-controls/policies/ae3938e9-9ed6-48fa-b376-5528bf0791b4/edit";
const accessAdminMfa = "https://dash.cloudflare.com/3d28f3cbcbb2f27849194e412022d510/one/access-controls/policies/17c00832-aa4b-423d-9d24-ca6cbe9c4233/edit";
const accessGuestMfa = "https://dash.cloudflare.com/3d28f3cbcbb2f27849194e412022d510/one/access-controls/policies/42c4c9d2-cad1-4788-be7c-fb342a62aa63/edit";
type Papel = "convidado" | "admin";
type Usuario = { id: string; email: string | null; segmentos: Segmento[]; super_admin: boolean; papel?: Papel | "super_admin" };
type Convite = { id: string; email: string; segmentos: Segmento[]; expira_em: number; estado: keyof typeof estados; papel?: Papel };
const papeis = { super_admin: "Super Admin", admin: "Admin", convidado: "Convidado" };
type Acessos = { usuarios: Usuario[]; convites: Convite[] };
const estados = {
  pendente: "Pendente",
  aceito: "Aceito",
  expirado: "Expirado",
  cancelado: "Cancelado",
};
const abas = ["Pendentes", "Aceitos", "Cancelados"] as const;
const abaPorEstado = {
  pendente: "Pendentes", aceito: "Aceitos", cancelado: "Cancelados", expirado: "Cancelados",
} as const;
const mensagens: Record<string, string> = {
  EMAIL_JA_TEM_ACESSO: "Esse e-mail já tem acesso à Central.",
  CONVITE_JA_PENDENTE: "Já existe um convite pendente para esse e-mail. Cancele o anterior para gerar outro.",
  CONVITE_INVALIDO_OU_INDISPONIVEL: "Este convite expirou, já foi utilizado ou foi enviado para outro e-mail.",
  OPERADOR_JA_TEM_ACESSO: "Sua conta já tem acesso à Central.",
  PAPEL_SUPER_ADMIN_IMUTAVEL: "O papel do Super Admin não pode ser alterado aqui.",
  OPERADOR_NAO_ENCONTRADO: "A pessoa não tem um acesso ativo à Central.",
};
const segmentOptions: Segmento[] = ["FARMA", "PET"];

async function consultar(path: string, body?: object, signal?: AbortSignal) {
  const response = await fetch(api + path, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal,
    ...(body && {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  });
  if (response.status === 204) return;
  const data = await response.json();
  if (!response.ok) {
    throw new Error(mensagens[data.detail] ?? "Não foi possível concluir a solicitação.");
  }
  return data;
}

export function GerenciarUsuarios() {
  const [aba, setAba] = useState<(typeof abas)[number]>("Pendentes");
  const [acessos, setAcessos] = useState<Acessos>();
  const [email, setEmail] = useState("");
  const [segmentos, setSegmentos] = useState<Segmento[]>([]);
  const [papel, setPapel] = useState<Papel>("convidado");
  const [link, setLink] = useState("");
  const [aviso, setAviso] = useState("");
  const [erro, setErro] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    consultar("/usuarios", undefined, controller.signal)
      .then(setAcessos)
      .catch(() => {
        if (!controller.signal.aborted) setErro("Não foi possível consultar os acessos.");
      });
    return () => controller.abort();
  }, []);

  async function alterar(path: string, body: object, feedback: string) {
    setErro("");
    setAviso("");
    setBusy(true);
    try {
      const result = await consultar(path, body);
      if (path === "/convites" && /^[A-Za-z0-9_-]{43}$/.test(result?.codigo)) {
        setLink(centralOficial + "/#convite/" + result.codigo);
        setEmail("");
        setSegmentos([]);
        setPapel("convidado");
      } else {
        setLink("");
      }
      setAviso(feedback);
      setAcessos(await consultar("/usuarios"));
    } catch (reason) {
      setErro(reason instanceof Error ? reason.message : "Não foi possível concluir a solicitação.");
    } finally {
      setBusy(false);
    }
  }

  const grupos = { Pendentes: [] as Convite[], Aceitos: [] as Convite[], Cancelados: [] as Convite[] };
  for (const convite of acessos?.convites ?? []) grupos[abaPorEstado[convite.estado]].push(convite);

  return (
    <>
      <div className="title-row">
        <div><h1>Gerenciar Usuários</h1><p className="updated">Super Admin · Central de Operações</p></div>
      </div>
      {erro && <p role="alert">{erro}</p>}
      {aviso && <p role="status">{aviso}</p>}
      <div className="account-grid">
        <section className="panel account-panel" aria-labelledby="convidar">
          <h2 id="convidar">Convidar para homologação</h2>
          <p>Escolha o papel e os segmentos que a pessoa poderá consultar.</p>
          <form onSubmit={(event) => {
            event.preventDefault();
            if (!busy && email.trim() && segmentos.length) void alterar("/convites", { email, segmentos, papel }, "Convite criado.");
          }}>
            <label htmlFor="email-convite">E-mail do convidado</label>
            <input id="email-convite" type="email" required maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} />
            <label htmlFor="papel-convite">Papel do usuário</label>
            <select id="papel-convite" value={papel} onChange={(event) => setPapel(event.target.value === "admin" ? "admin" : "convidado")}>
              <option value="convidado">Convidado · Hub</option>
              <option value="admin">Admin · Hub e Métricas</option>
            </select>
            <small>Gerenciar Usuários é exclusivo do Super Admin. Métricas respeita os segmentos autorizados.</small>
            <fieldset className="invite-segments">
              <legend>Segmentos permitidos</legend>
              {segmentOptions.map((segmento) => (
                <label key={segmento}>
                  <input type="checkbox" value={segmento} checked={segmentos.includes(segmento)}
                    onChange={(event) => {
                      const value = event.target.value;
                      if (isSegmento(value)) setSegmentos(event.target.checked
                        ? [...segmentos, value] : segmentos.filter((item) => item !== value));
                    }} /> {segmento}
                </label>
              ))}
            </fieldset>
            <button className="refresh" disabled={busy || !acessos || !email.trim() || !segmentos.length}>Criar convite</button>
          </form>
          {link && <>
            <label htmlFor="link-convite">Link de uso único · válido por 7 dias</label>
            <input id="link-convite" readOnly value={link} onFocus={(event) => event.target.select()} />
            <button className="plain" onClick={() => {
              const selecionarLink = () => {
                const campo = document.getElementById("link-convite");
                if (campo instanceof HTMLInputElement) {
                  campo.focus();
                  campo.select();
                }
                setAviso("Link selecionado. Pressione Ctrl+C para copiar.");
              };
              if (!navigator.clipboard) { selecionarLink(); return; }
              navigator.clipboard.writeText(link).then(
                () => setAviso("Link copiado."),
                selecionarLink,
              );
            }}>Copiar convite</button>
          </>}
        </section>
        <section className="panel account-panel" aria-labelledby="usuarios-ativos">
          <h2 id="usuarios-ativos">Usuários com acesso</h2>
          <ul className="access-list">
            {acessos?.usuarios.map((user) => (
              <li key={user.id}>
                <strong>{user.super_admin ? "Você · Super Admin" : user.email ?? "Usuário já cadastrado"}</strong>
                <span>{user.segmentos.join(" · ")}</span>
                {!user.super_admin && <small>{papeis[user.papel ?? "convidado"]}</small>}
                {!user.email && !user.super_admin && <small>Identidade Access {user.id}</small>}
                {!user.super_admin && user.papel && <button className="plain" disabled={busy} onClick={() => {
                  const proximo = user.papel === "admin" ? "convidado" : "admin";
                  if (window.confirm(`Alterar o papel desta pessoa para ${papeis[proximo]}? Confira as políticas correspondentes no Cloudflare Access.`)) {
                    void alterar("/usuarios/papel", { id: user.id, papel: proximo }, "Papel atualizado. Confira as políticas no Cloudflare Access.");
                  }
                }}>{user.papel === "admin" ? "Tornar Convidado" : "Tornar Admin"}</button>}
                {!user.super_admin && <button className="plain" disabled={busy} onClick={() => {
                  if (window.confirm("Revogar o acesso desta pessoa à Central de Operações?")) {
                    void alterar("/usuarios/revogar", { id: user.id }, "Acesso revogado.");
                  }
                }}>Revogar acesso</button>}
              </li>
            ))}
          </ul>
        </section>
      </div>
      <section className="panel account-panel invite-history" aria-labelledby="autorizar-cloudflare">
        <h2 id="autorizar-cloudflare">Autorizar na Cloudflare</h2>
        <p>Adicione o e-mail à política correspondente ao papel. OTP permite o código por e-mail; MFA permite o login Cloudflare com autenticação adicional para identidades elegíveis.</p>
        <p><strong>Central | Convidados OTP</strong></p>
        <a href={accessApps} target="_blank" rel="noopener noreferrer">Autorizar convidados no Cloudflare Access</a>
        <p><a href={accessGuestMfa} target="_blank" rel="noopener noreferrer">Autorizar convidados com MFA</a></p>
        <p><strong>Central | Admins OTP</strong></p>
        <a href={accessAdminOtp} target="_blank" rel="noopener noreferrer">Autorizar admins no Cloudflare Access</a>
        <p><a href={accessAdminMfa} target="_blank" rel="noopener noreferrer">Autorizar admins com MFA</a></p>
      </section>
      <section className="panel account-panel invite-history" aria-labelledby="convites-lista">
        <h2 id="convites-lista">Convites</h2>
        <div className="docs-tabs" role="group" aria-label="Filtrar convites por situação">
          {abas.map((categoria) => (
            <button key={categoria} type="button" aria-pressed={aba === categoria}
              onClick={() => setAba(categoria)}>
              {categoria}{acessos && ` (${grupos[categoria].length})`}
            </button>
          ))}
        </div>
        {acessos && grupos[aba].length === 0 && <p>Nenhum convite nesta aba.</p>}
        <ul className="access-list" aria-label={aba}>
          {grupos[aba].map((invite) => (
            <li key={invite.id}>
              <strong>{invite.email}</strong>
              <span>{estados[invite.estado]} · {invite.segmentos.join(" · ")}</span>
              <small>{papeis[invite.papel ?? "convidado"]}</small>
              {invite.estado === "pendente" && <>
                <small>Válido até {horaLocal(new Date(invite.expira_em * 1000))} · Belém</small>
                <button className="plain" disabled={busy} onClick={() => {
                  if (window.confirm("Cancelar este convite?")) {
                    void alterar("/convites/cancelar", { id: invite.id }, "Convite cancelado.");
                  }
                }}>Cancelar convite</button>
              </>}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

export function AceitarConvite() {
  const [erro, setErro] = useState("");
  const [busy, setBusy] = useState(false);
  const codigo = window.location.hash.slice("#convite/".length);
  const valido = /^[A-Za-z0-9_-]{43}$/.test(codigo);
  return (
    <main className="invitation-page">
      <section className="panel account-panel">
        <h1>Convite para a Central de Operações</h1>
        <p>Use a conta Cloudflare com o e-mail que recebeu o convite.</p>
        {erro && <p role="alert">{erro}</p>}
        {!valido && <p role="alert">Abra o link completo que recebeu.</p>}
        <button className="refresh" disabled={busy || !valido} onClick={async () => {
          setErro("");
          setBusy(true);
          try {
            await consultar("/convites/aceitar", { codigo });
            window.location.replace("/");
          } catch (reason) {
            setErro(reason instanceof Error ? reason.message : "Não foi possível aceitar o convite.");
            setBusy(false);
          }
        }}>{busy ? "Confirmando…" : "Aceitar convite"}</button>
      </section>
    </main>
  );
}
