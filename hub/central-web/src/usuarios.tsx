import { useEffect, useState } from "react";
import { horaLocal, isSegmento } from "./resumo";
import type { Segmento } from "./resumo";

const api = "/api/central/v1";
const accessApps = "https://one.dash.cloudflare.com/?to=/:account/access/apps";
type Usuario = { id: string; email: string | null; segmentos: Segmento[]; super_admin: boolean };
type Convite = { id: string; email: string; segmentos: Segmento[]; expira_em: number; estado: keyof typeof estados };
type Acessos = { usuarios: Usuario[]; convites: Convite[] };
const estados = {
  pendente: "Pendente",
  aceito: "Aceito",
  expirado: "Expirado",
  cancelado: "Cancelado",
};
const mensagens: Record<string, string> = {
  EMAIL_JA_TEM_ACESSO: "Esse e-mail já tem acesso à Central.",
  CONVITE_JA_PENDENTE: "Já existe um convite pendente para esse e-mail. Cancele o anterior para gerar outro.",
  CONVITE_INVALIDO_OU_INDISPONIVEL: "Este convite expirou, já foi utilizado ou foi enviado para outro e-mail.",
  OPERADOR_JA_TEM_ACESSO: "Sua conta já tem acesso à Central.",
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
  const [acessos, setAcessos] = useState<Acessos>();
  const [email, setEmail] = useState("");
  const [segmentos, setSegmentos] = useState<Segmento[]>([]);
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
        setLink(window.location.origin + "/#convite/" + result.codigo);
        setEmail("");
        setSegmentos([]);
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
          <p>Escolha os segmentos que o convidado poderá consultar.</p>
          <form onSubmit={(event) => {
            event.preventDefault();
            if (!busy && email.trim() && segmentos.length) void alterar("/convites", { email, segmentos }, "Convite criado.");
          }}>
            <label htmlFor="email-convite">E-mail do convidado</label>
            <input id="email-convite" type="email" required maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} />
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
              if (!navigator.clipboard) { setAviso("Selecione o endereço acima para copiar."); return; }
              navigator.clipboard.writeText(link).then(
                () => setAviso("Link copiado."),
                () => setAviso("Selecione o endereço acima para copiar."),
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
                {!user.email && !user.super_admin && <small>Identidade Access {user.id}</small>}
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
        <p>Abra a aplicação <strong>NexoFlow Central de Operações HML</strong> e inclua na política de acesso o mesmo e-mail do convite.</p>
        <a href={accessApps} target="_blank" rel="noopener noreferrer">Abrir aplicações no Cloudflare Access</a>
      </section>
      <section className="panel account-panel invite-history" aria-labelledby="convites-lista">
        <h2 id="convites-lista">Convites recentes</h2>
        {acessos?.convites.length === 0 && <p>Nenhum convite criado.</p>}
        <ul className="access-list">
          {acessos?.convites.map((invite) => (
            <li key={invite.id}>
              <strong>{invite.email}</strong>
              <span>{estados[invite.estado]} · {invite.segmentos.join(" · ")}</span>
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
