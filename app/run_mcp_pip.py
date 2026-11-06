"""Instala somente dependências MCP, com a rota NexoFlow e saída sanitizada."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from network_diagnostics import NetworkFailure, classify_network_failure

ROOT = Path(__file__).resolve().parents[1]
REPORT = Path("logs/meta_ads_mcp_dependencias.json")


@dataclass
class PipAttempt:
    numero: int
    codigo_saida: int | None
    categoria: str
    http: int | None = None
    repetivel: bool = False
    mensagem: str = ""
    ultima_etapa_reportada: str = "indeterminada"


@dataclass
class DependencyReport:
    """Somente valores controlados: nunca saída, comando, URL ou ambiente bruto."""

    schema_version: int = 1
    componente: str = "Meta Ads MCP — dependências"
    perfil: str = "FARMA"
    status: str = "em_andamento"
    preflight_https: str = "nao_executado"
    rota: str = "nao_configurada"
    categoria_rede: str | None = None
    http_rede: int | None = None
    mensagem_rede: str | None = None
    atualizado_em: str = ""
    limite_tentativas: int = 3
    tentativas: list[PipAttempt] = field(default_factory=list)

    def save(self) -> None:
        self.atualizado_em = datetime.now(UTC).isoformat()
        temporary: Path | None = None
        try:
            target = ROOT / REPORT
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=target.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump(asdict(self), stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except OSError:
            print(
                "[AVISO] DIAGNOSTICO_MCP_GRAVACAO: não foi possível salvar o diagnóstico; confira o resultado da instalação no console.",
                flush=True,
            )
        finally:
            if temporary:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


def pip_stage(output: str) -> str:
    """Última etapa reconhecida, não uma afirmação sobre a causa da falha."""
    stages = (
        ("collecting ", "resolucao"),
        ("downloading ", "download"),
        ("building wheel for ", "compilacao"),
        ("installing collected packages", "instalacao"),
    )
    text = output.lower()
    positions = [(text.rfind(marker), stage) for marker, stage in stages]
    position, stage = max(positions)
    return stage if position >= 0 else "indeterminada"


def pip_failure(output: str) -> NetworkFailure:
    """Inspeciona mensagens localmente; nunca devolve linhas/URLs do pip."""
    import requests

    text = output.lower()
    connect = re.search(r"tunnel connection failed:\s*(\d{3})\b", text)
    if connect or re.search(r"\b407\s+proxy authentication", text):
        code = connect[1] if connect else "407"
        failure = classify_network_failure(
            requests.exceptions.ProxyError(OSError(f"Tunnel connection failed: {code}"))
        )
        if 400 <= int(code) < 500 and int(code) != 429:
            return replace(failure, retryable=False)
        return failure
    if "certificate verify failed" in text or "certificate_verify_failed" in text:
        return classify_network_failure(requests.exceptions.SSLError())
    if re.search(r"timed out|\b(?:connect|read)?timeout(?:error)?\b\s*[:(]", text):
        return classify_network_failure(requests.exceptions.Timeout())
    http = re.search(
        r"\b(?:http error|http(?:/[\d.]+)?)\s*[:=]?\s*([45]\d{2})\b|\b([45]\d{2})\s+(?:client|server) error\b",
        text,
    )
    if http:
        status = int(http[1] or http[2])
        if status == 407:
            return classify_network_failure(
                requests.exceptions.ProxyError(OSError("Tunnel connection failed: 407"))
            )
        return NetworkFailure(
            "PIP_HTTP",
            "Uma requisição do pip foi recusada pelo índice, download ou intermediário.",
            "O preflight do índice não comprova acesso aos arquivos; confira o código HTTP e a política de acesso com a TI.",
            status == 429 or status >= 500,
            status,
        )
    conditions = (
        (
            "no module named pip" in text,
            "PIP_AUSENTE",
            "O Python MCP não encontrou o módulo pip.",
            "Confira a criação do ambiente virtual MCP.",
        ),
        (
            "requires a different python" in text,
            "PIP_PYTHON",
            "O pip informou incompatibilidade de versão Python.",
            "Confira o Python 3.14 exigido pelo conector e seus requisitos.",
        ),
        (
            "resolutionimpossible" in text or "conflicting dependencies" in text,
            "PIP_CONFLITO_DEPENDENCIAS",
            "O pip informou um conflito entre dependências.",
            "Confira os requisitos e o ambiente MCP; não altere versões sem validar.",
        ),
        (
            "[winerror 32]" in text or "[winerror 33]" in text,
            "PIP_ARQUIVO_EM_USO",
            "O pip informou que um arquivo está em uso.",
            "Encerre os processos MCP e confira o arquivo bloqueado localmente.",
        ),
        (
            "permission denied" in text
            or "[winerror 5]" in text
            or "[errno 13]" in text,
            "PIP_PERMISSAO",
            "O pip informou acesso negado a um arquivo ou diretório.",
            "Confira permissões e os eventos de segurança no Windows; o diagnóstico não identifica quem bloqueou o acesso.",
        ),
        (
            "no space left on device" in text or "[winerror 112]" in text,
            "PIP_ESPACO",
            "O pip informou falta de espaço em disco.",
            "Confira espaço disponível no destino e na pasta temporária.",
        ),
        (
            "failed building wheel" in text
            or "failed to build installable wheels" in text,
            "PIP_COMPILACAO",
            "O pip não conseguiu construir uma dependência.",
            "Confira compatibilidade e disponibilidade de wheels para o Python instalado.",
        ),
        (
            "no matching distribution" in text,
            "PIP_CANDIDATO",
            "O pip não selecionou uma distribuição compatível.",
            "Isso não comprova ausência do pacote; confira acesso ao índice, versão Python e requisitos.",
        ),
    )
    for matches, category, detail, action in conditions:
        if matches:
            return NetworkFailure(category, detail, action, False)
    return NetworkFailure(
        "PIP_INSTALACAO",
        "O pip não concluiu a instalação MCP.",
        "Confira acesso ao índice, requisitos e dependências; falha de acesso não comprova ausência de uma versão.",
        False,
    )


def network_setup_failure(error: Exception) -> NetworkFailure:
    """Traduz códigos de preflight conhecidos sem propagar mensagens privadas."""
    text = str(error)
    code = re.match(r"^(PROXY_CONNECT_|REDE_PIP_HTTP_)([45]\d{2})(?::|$)", text)
    if code:
        prefix = (
            "Tunnel connection failed:" if code[1] == "PROXY_CONNECT_" else "HTTP error"
        )
        return pip_failure(f"{prefix} {code[2]}")
    if text.startswith(("TLS_CERTIFICADO:", "TLS_INDICE:")):
        return NetworkFailure(
            "TLS_CERTIFICADO",
            "A configuração TLS ou o certificado aprovado não pôde ser validado.",
            "Confira o índice HTTPS e a CA aprovada; mantenha TLS ativo.",
            False,
        )
    for category, detail, action in (
        (
            "PROXY_INDISPONIVEL",
            "O proxy selecionado não respondeu à sondagem de conexão.",
            "Confira disponibilidade e configuração com a TI; não foi usada rota direta alternativa.",
        ),
        (
            "REDE_AMBIGUA",
            "A rota de rede ainda precisa ser confirmada.",
            "Escolha a rede autorizada no Setup ou na sessão NexoFlow antes de repetir o auxiliar.",
        ),
        (
            "REDE_PIP_INDISPONIVEL",
            "A verificação HTTPS do índice não foi concluída.",
            "Confira a rota e a disponibilidade do índice com a TI.",
        ),
    ):
        if text.startswith(f"{category}:"):
            return NetworkFailure(category, detail, action, False)
    return NetworkFailure(
        "CONFIGURACAO_REDE_MCP",
        "A preparação da rede MCP não foi concluída.",
        "Confira secrets_config.py, perfil, seleção de rede e CA aprovada; nenhum pip foi iniciado.",
        False,
    )


def dependency_environment() -> dict[str, str]:
    from proxy_config import configure_proxy

    # Falha de configuração não autoriza fallback direto. A configuração é
    # importada somente depois da seleção de perfil pelo ponto de entrada.
    status = configure_proxy()
    print(
        f"[INFO] Rede MCP: rota={'proxy' if status.active else 'direta explícita/sem proxy configurado'}; "
        f"credenciais={'configuradas' if status.has_credentials else 'ausentes'}; HTTPS ainda não comprovado.",
        flush=True,
    )
    from pip_network import pip_environment, preflight

    env = pip_environment(status.active)
    preflight(env)
    return env


def install(python: Path, *, run=subprocess.run, sleep=time.sleep) -> int:
    profile = os.environ.get("NEXOFLOW_PERFIL", "FARMA")
    report = DependencyReport(
        perfil=profile if profile in {"FARMA", "PET"} else "FARMA"
    )
    report.save()
    try:
        env = dependency_environment()
    except Exception as exc:
        failure = network_setup_failure(exc)
        print(f"[ERRO] {failure.summary}", flush=True)
        report.status = "falha"
        report.preflight_https = "nao_aprovado"
        report.categoria_rede = failure.category
        report.http_rede = failure.status
        report.mensagem_rede = failure.summary
        report.save()
        print(f"[INFO] Diagnóstico sanitizado: {REPORT.as_posix()}", flush=True)
        return 2
    report.rota = (
        "proxy" if env.get("PIP_PROXY") or env.get("HTTPS_PROXY") else "direta"
    )
    report.preflight_https = "aprovado"
    report.save()
    command = [
        str(python),
        "-m",
        "pip",
        "--disable-pip-version-check",
        "install",
        "--no-input",
        "--retries",
        "0",
        "--timeout",
        "45",
        "-r",
        str(ROOT / "connectors/meta_ads_mcp/requirements.txt"),
    ]
    for attempt in range(1, 4):
        print(f"[INFO] Dependências MCP: tentativa {attempt}/3.", flush=True)
        exit_code = None
        stage = "indeterminada"
        try:
            result = run(
                command,
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )
            exit_code = result.returncode
            if result.returncode == 0:
                report.tentativas.append(PipAttempt(attempt, 0, "OK"))
                report.status = "sucesso"
                report.save()
                print(
                    "[OK] Dependências MCP instaladas; validação offline será executada."
                )
                return 0
            output = result.stdout or ""
            failure = pip_failure(output)
            stage = pip_stage(output)
        except subprocess.TimeoutExpired:
            failure = NetworkFailure(
                "TIMEOUT",
                "O pip excedeu o prazo de instalação.",
                "Confira a rota e o índice.",
                True,
            )
        except OSError:
            failure = NetworkFailure(
                "PIP_EXECUCAO",
                "Não foi possível iniciar o pip MCP.",
                "Confira o ambiente Python instalado.",
                False,
            )
        print(f"[ERRO] {failure.summary}", flush=True)
        report.tentativas.append(
            PipAttempt(
                attempt,
                exit_code,
                failure.category,
                failure.status,
                failure.retryable,
                failure.summary,
                stage,
            )
        )
        if not failure.retryable or attempt == 3:
            report.status = "falha"
            report.save()
            print(f"[INFO] Diagnóstico sanitizado: {REPORT.as_posix()}", flush=True)
            return 1
        report.save()
        sleep(2 ** (attempt - 1))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dependências MCP com rede NexoFlow; sem Codex."
    )
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument(
        "--perfil",
        choices=["FARMA", "PET"],
        default=os.environ.get("NEXOFLOW_PERFIL", "FARMA"),
    )
    args = parser.parse_args()
    os.environ["NEXOFLOW_PERFIL"] = args.perfil
    expected = ROOT / "connectors/meta_ads_mcp/.venv/Scripts/python.exe"
    if args.python.resolve() != expected.resolve() or not expected.is_file():
        print("[ERRO] Interpretador MCP ausente ou fora da instalação esperada.")
        return 2
    return install(expected)


if __name__ == "__main__":
    raise SystemExit(main())
