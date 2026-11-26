import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";

const contaUrl = "/api/central/v1/minha-conta";
const cloudflarePerfil = "https://dash.cloudflare.com/profile";

type Conta = {
  nome: string;
  email: string;
  nome_editavel: boolean;
  mfa_url: string;
};

export function MinhaConta() {
  const [conta, setConta] = useState<Conta>();
  const [nome, setNome] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");
  const [salvo, setSalvo] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch(contaUrl, { cache: "no-store", credentials: "same-origin", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok || response.redirected) throw new Error();
        const data: Conta = await response.json();
        if (typeof data.nome !== "string" || typeof data.email !== "string" ||
            typeof data.nome_editavel !== "boolean" ||
            !/^https:\/\/[a-z0-9-]+\.cloudflareaccess\.com\/AddMfaDevice$/.test(data.mfa_url)) throw new Error();
        if (!controller.signal.aborted) {
          setConta(data);
          setNome(data.nome);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setErro("Não foi possível consultar sua conta.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setCarregando(false);
      });
    return () => controller.abort();
  }, []);

  async function salvar() {
    setSalvando(true);
    setErro("");
    setSalvo(false);
    try {
      const response = await fetch(contaUrl, {
        method: "PUT",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nome: nome.trim() }),
      });
      if (!response.ok || response.redirected) throw new Error();
      const data = await response.json();
      if (typeof data.nome !== "string") throw new Error();
      setNome(data.nome);
      setConta((current) => current && { ...current, nome: data.nome });
      setSalvo(true);
    } catch {
      setErro("Não foi possível salvar seu nome. Tente novamente.");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <>
      <div className="title-row"><h1>Minha Conta</h1></div>
      {carregando && <p role="status">Consultando sua conta…</p>}
      {erro && <p role="alert">{erro}</p>}
      {conta && (
        <div className="account-grid">
          <section className="panel account-panel" aria-labelledby="conta-perfil">
            <h2 id="conta-perfil">Perfil</h2>
            <form onSubmit={(event) => {
              event.preventDefault();
              if (!salvando && conta.nome_editavel && nome.trim() && nome.trim() !== conta.nome) void salvar();
            }}>
              <label htmlFor="nome-conta">Nome de exibição</label>
              <input id="nome-conta" autoComplete="name" maxLength={80} required value={nome}
                disabled={salvando || !conta.nome_editavel}
                onChange={(event) => { setNome(event.target.value); setSalvo(false); }} />
              <button className="refresh" disabled={salvando || !conta.nome_editavel || !nome.trim() || nome.trim() === conta.nome}>
                {salvando ? "Salvando…" : "Salvar nome"}
              </button>
              {salvo && <p role="status">Nome salvo.</p>}
            </form>
            <dl>
              <dt>E-mail de login</dt>
              <dd>{conta.email}</dd>
            </dl>
          </section>
          <section className="panel account-panel" aria-labelledby="conta-seguranca">
            <h2 id="conta-seguranca"><ShieldCheck size={18} /> Segurança</h2>
            <p>Altere seu e-mail e sua senha na conta Cloudflare. Se mudar o e-mail, o administrador da Central pode precisar autorizar o novo endereço.</p>
            <a href={cloudflarePerfil} target="_blank" rel="noopener noreferrer">Alterar e-mail ou senha na Cloudflare</a>
            <p>Cadastre um aplicativo autenticador, uma chave de segurança ou a biometria do seu dispositivo.</p>
            <a href={conta.mfa_url} target="_blank" rel="noopener noreferrer">Configurar um dispositivo de MFA</a>
          </section>
        </div>
      )}
    </>
  );
}
