from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from farmalider_client import FarmaliderClient
from runtime_profile import scoped_path
from versioning import CURRENT_VERSION as VERSION
from weni_client import WeniClient

BASE_DIR = Path(__file__).resolve().parents[1]

LOG_DIR = BASE_DIR / scoped_path("logs")


def _line(char: str = "=", width: int = 58) -> str:
    return char * width


def _title(text: str) -> None:
    print(_line())
    print(text)
    print(_line())


def _safe_text(value: Any, *, max_len: int = 110) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        text = "sim" if value else "não"
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _load_secrets() -> Any:
    path = BASE_DIR / "secrets_config.py"
    if not path.exists():
        raise RuntimeError(
            "secrets_config.py não foi encontrado em C:\\NexoFlow. "
            "Execute o Setup/configuração antes de consultar APIs."
        )
    spec = importlib.util.spec_from_file_location("nexoflow_terminal_secrets", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Não foi possível carregar secrets_config.py.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from runtime_profile import select_settings

    return select_settings(module)


def _prepare_network() -> str:
    from proxy_config import configure_proxy

    status = configure_proxy()
    return status.safe_summary


def _make_weni_client() -> WeniClient:
    secrets = _load_secrets()
    token = str(getattr(secrets, "WENI_API_TOKEN", "") or "").strip()
    if not token or "COLE_SEU_TOKEN" in token:
        raise RuntimeError("Token Weni não está configurado em secrets_config.py.")
    _prepare_network()
    return WeniClient(token)


def _make_farmalider_client() -> FarmaliderClient:
    secrets = _load_secrets()
    enabled = bool(getattr(secrets, "FARMALIDER_API_ENABLED", True))
    if not enabled:
        raise RuntimeError("FarmaLíder API está desativada em secrets_config.py.")
    token = str(getattr(secrets, "FARMALIDER_API_TOKEN", "") or "").strip()
    if not token or "COLE_SEU_TOKEN" in token:
        raise RuntimeError(
            "Token FarmaLíder não está configurado em secrets_config.py."
        )
    use_hml = bool(getattr(secrets, "FARMALIDER_USE_HML", False))
    _prepare_network()
    return FarmaliderClient(token, use_hml=use_hml)


def _write_json(payload: Any, path_text: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        path = BASE_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] JSON salvo em: {path}")
    return path


def _json_or_save(payload: Any, args: argparse.Namespace) -> bool:
    saved = getattr(args, "salvar", None)
    if saved:
        _write_json(payload, saved)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return True
    return False


def _field(fields: dict[str, Any], key: str) -> Any:
    value = fields.get(key)
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _print_kv(label: str, value: Any) -> None:
    text = _safe_text(value)
    if text:
        print(f"{label:.<25} {text}")


def _show_weni_contact(contact: dict[str, Any]) -> None:
    fields = contact.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    urns = contact.get("urns")
    if not isinstance(urns, list):
        urns = []
    _title("Weni - Contato")
    _print_kv("UUID", contact.get("uuid"))
    _print_kv("Nome Weni", contact.get("name"))
    _print_kv("URNs nativas", "; ".join(str(x) for x in urns))
    _print_kv("URN principal", _field(fields, "contact_urn"))
    _print_kv("WhatsApp", _field(fields, "contact_urn_whatsapp"))
    _print_kv("Instagram", _field(fields, "contact_urn_instagram"))
    _print_kv("Facebook/Messenger", _field(fields, "contact_urn_facebook"))
    _print_kv("Canal principal", _field(fields, "contact_canal_principal"))
    _print_kv("CPF", _field(fields, "cpf"))
    _print_kv("Idade", _field(fields, "idade"))
    _print_kv("Maior de 18", _field(fields, "maior_de_18_anos"))
    _print_kv("LGPD", _field(fields, "opt_in_lgpd"))
    _print_kv("Última compra", _field(fields, "ultima_compra"))
    _print_kv("Criado em", contact.get("created_on"))
    _print_kv("Modificado em", contact.get("modified_on"))
    print()
    print("Dica: use --json para ver a resposta completa da Weni.")


def _show_messages(messages: list[dict[str, Any]]) -> None:
    _title(f"Weni - Mensagens ({len(messages)})")
    if not messages:
        print("Nenhuma mensagem encontrada.")
        return
    for item in messages:
        direction = str(item.get("direction") or "").lower()
        side = "CLIENTE" if direction in {"in", "incoming", "inbound"} else "SAÍDA"
        created = _safe_text(item.get("created_on"), max_len=30)
        text = _safe_text(
            item.get("text") or item.get("msg") or item.get("type"), max_len=140
        )
        print(f"{created} | {side:<7} | {text}")


def _show_simple_records(
    title: str, records: Iterable[dict[str, Any]], keys: list[str]
) -> None:
    records = list(records)
    _title(f"{title} ({len(records)})")
    if not records:
        print("Nenhum registro encontrado.")
        return
    for index, record in enumerate(records, start=1):
        values = []
        for key in keys:
            value = record.get(key)
            if value not in (None, "", []):
                values.append(f"{key}={_safe_text(value, max_len=70)}")
        print(f"{index:>3}. " + " | ".join(values))


def _show_farmalider_payload(
    title: str, payload: dict[str, Any] | list[dict[str, Any]] | None
) -> None:
    _title(title)
    if payload is None:
        print("Nenhum registro encontrado.")
        return
    if isinstance(payload, list):
        print(
            f"Clientes retornados: {len(payload)}. Nenhum cliente selecionado automaticamente."
        )
        print("Use --json para comparar os dados com o contato da Weni.")
        return
    scalar_items: list[tuple[str, Any]] = []
    nested: list[str] = []
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            nested.append(key)
        else:
            scalar_items.append((str(key), value))
    for key, value in scalar_items[:35]:
        _print_kv(key, value)
    if nested:
        print()
        print("Estruturas adicionais: " + ", ".join(nested))
    print()
    print("Dica: use --json para visualizar a resposta completa da API.")


def _normalize_cpf(raw: str) -> str:
    cpf = re.sub(r"\D", "", raw or "")
    if not cpf:
        raise RuntimeError("Informe os dígitos do CPF cadastrado, mesmo que inválido.")
    return cpf


def _run_windows_target(filename: str) -> int:
    path = BASE_DIR / filename
    if not path.exists():
        raise RuntimeError(f"Arquivo não encontrado: {path}")
    if os.name == "nt":
        if path.suffix.lower() in {".bat", ".cmd"}:
            completed = subprocess.run(
                ["cmd.exe", "/d", "/c", str(path)],
                cwd=BASE_DIR,
                check=False,
                env={**os.environ, "NEXOFLOW_LAUNCHER": "1"},
            )
        else:
            completed = subprocess.run([str(path)], cwd=BASE_DIR, check=False)
        return int(completed.returncode)
    raise RuntimeError("Este comando operacional só pode ser executado no Windows.")


def _tail_lines(path: Path, lines: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        data = handle.readlines()
    return [line.rstrip("\r\n") for line in data[-max(1, lines) :]]


def _follow_file(path: Path, lines: int) -> int:
    if not path.exists():
        print(f"[ERRO] Log ainda não existe: {path}")
        return 1
    for line in _tail_lines(path, lines):
        print(line)
    print("\n[Acompanhando ao vivo. Pressione Ctrl+C para sair.]\n")
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(0, os.SEEK_END)
            while True:
                line = handle.readline()
                if line:
                    print(line.rstrip("\r\n"))
                else:
                    time.sleep(0.4)
    except KeyboardInterrupt:
        print("\nAcompanhamento encerrado.")
        return 0


def _log_path(kind: str) -> Path:
    normalized = kind.lower()
    if normalized in {"weni", "update", "atualizacao"}:
        return LOG_DIR / "nexoflow_update_weni.log"
    if normalized in {"analytics", "analitico"}:
        return LOG_DIR / "nexoflow.log"
    raise RuntimeError("Log desconhecido. Use 'weni' ou 'analytics'.")


def _print_commands() -> None:
    _title(f"NexoFlow Terminal {VERSION} - Comandos")
    print("GERAL")
    print("  nexo                         Abre o menu simples")
    print("  nexo ajuda                   Lista todos os comandos")
    print("  nexo status                  Mostra ambiente e testa as APIs")
    print("  nexo status --local          Mostra somente o estado local")
    print("  nexo diagnostico             Executa check-up + teste de conexões")
    print("  nexo versao                  Mostra a versão")
    print()
    print("WENI")
    print("  nexo weni testar             Testa acessos sem gravar")
    print("  nexo weni dry-run            Simula alterações sem gravar")
    print("  nexo weni atualizar          Atualização incremental segura")
    print("  nexo weni carga-completa     Carga completa com revisão humana")
    print("  nexo weni recompra auditoria|dry-run|aplicar  Recompra D+25 com revisão")
    print("  nexo weni planilhas          Atualiza a Weni a partir dos exports XLSX")
    print()
    print("ANALYTICS")
    print("  nexo analytics               Executa o NexoFlow Analytics")
    print(
        "  nexo looker --inicio AAAA-MM-DD --fim AAAA-MM-DD  Recalcula KPIs para o Data Studio"
    )
    print(
        "  nexo analytics planilhas     Consulta os exports e atualiza o Google Sheets"
    )
    print()
    print("CONSULTAS WENI - SOMENTE LEITURA")
    print("  nexo api weni status")
    print("  nexo api weni contato --uuid <UUID>")
    print('  nexo api weni contato --urn "whatsapp:5591..."')
    print("  nexo api weni mensagens --uuid <UUID> --limite 10")
    print("  nexo api weni grupos")
    print('  nexo api weni grupos --nome "Opt-In LGPD"')
    print("  nexo api weni campos")
    print("  nexo api weni campos --chave cpf")
    print()
    print("CONSULTAS FARMALÍDER - SOMENTE LEITURA")
    print("  nexo api farmalider status")
    print("  nexo api farmalider cliente --cpf 12345678900")
    print("  nexo api farmalider pedido 123456")
    print()
    print("LOGS")
    print("  nexo logs weni              Últimas 50 linhas")
    print("  nexo logs weni --linhas 100")
    print("  nexo logs weni --seguir     Acompanha o log ao vivo")
    print("  nexo logs analytics")
    print()
    print("Nas consultas de API, use --json para resposta completa ou")
    print("--salvar arquivo.json para gravar a resposta sem expor tokens.")
    print()
    print('Documentação completa: "docs/README TERMINAL.md"')


def _status(local_only: bool) -> int:
    _title(f"NexoFlow {VERSION} - Status")
    print(f"Pasta.................... {BASE_DIR}")
    print(f"Python................... {sys.version.split()[0]}")
    print(
        f"Ambiente virtual......... {'OK' if (BASE_DIR / '.venv').exists() else 'não encontrado'}"
    )
    try:
        proxy = _prepare_network()
    except Exception as exc:
        proxy = f"ERRO: {exc}"
    print(f"Proxy.................... {proxy}")

    state_path = LOG_DIR / "weni_update_state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            last = (
                state.get("last_success_utc")
                or state.get("last_successful_sync_started_at")
                or "não informado"
            )
            pending = state.get("pending_conflict_uuids") or []
            print(f"Último checkpoint Weni... {_safe_text(last)}")
            print(
                f"Conflitos pendentes...... {len(pending) if isinstance(pending, list) else 0}"
            )
        except Exception:
            print("Checkpoint Weni........... arquivo presente, mas não pôde ser lido")
    else:
        print("Checkpoint Weni........... ainda não criado")

    if local_only:
        return 0

    print()
    print("Conexões:")
    try:
        client = _make_weni_client()
        try:
            client.test_connection()
            print("  Weni.................... OK")
        finally:
            client.close()
    except Exception as exc:
        print(f"  Weni.................... ERRO: {_safe_text(exc)}")

    try:
        client = _make_farmalider_client()
        try:
            result = client.test_connection()
            code = result.get("status_code")
            env = result.get("environment")
            print(f"  FarmaLíder.............. OK ({env}, HTTP {code})")
        finally:
            client.close()
    except Exception as exc:
        print(f"  FarmaLíder.............. ERRO: {_safe_text(exc)}")
    return 0


def _doctor() -> int:
    _title("NexoFlow - Diagnóstico")
    print("1/2 Check-up do projeto")
    code = _run_windows_target("comandos/check-up.bat")
    if code != 0:
        return code
    print("\n2/2 Teste de conexões do NexoFlow Weni")
    return _run_windows_target("comandos/testar_update_weni.bat")


def _api_weni(args: argparse.Namespace) -> int:
    client = _make_weni_client()
    try:
        action = args.weni_action
        if action == "status":
            payload = client.test_connection()
            if not _json_or_save(payload, args):
                _title("Weni - Status")
                print("Conexão.................. OK")
                print(f"Amostra retornada........ {payload.get('sample_count', 0)}")
            return 0

        if action == "contato":
            contact = client.get_contact(uuid=args.uuid, urn=args.urn)
            payload: Any = contact if contact is not None else {}
            if _json_or_save(payload, args):
                return 0
            if contact is None:
                print("Contato não encontrado.")
                return 2
            _show_weni_contact(contact)
            return 0

        if action == "mensagens":
            messages = client.list_messages(
                contact=args.uuid,
                urn=args.urn,
                limit=args.limite,
            )
            messages = sorted(
                messages,
                key=lambda item: str(item.get("created_on") or ""),
                reverse=True,
            )[: args.limite]
            if _json_or_save(messages, args):
                return 0
            _show_messages(messages)
            return 0

        if action == "grupos":
            groups = client.list_groups(name=args.nome)
            if _json_or_save(groups, args):
                return 0
            _show_simple_records("Weni - Grupos", groups, ["name", "uuid", "count"])
            return 0

        if action == "campos":
            fields = client.list_fields(key=args.chave)
            if _json_or_save(fields, args):
                return 0
            _show_simple_records("Weni - Campos", fields, ["key", "name", "value_type"])
            return 0

        raise RuntimeError("Consulta Weni desconhecida.")
    finally:
        client.close()


def _api_farmalider(args: argparse.Namespace) -> int:
    from logging_config import configure_logging

    configure_logging()
    client = _make_farmalider_client()
    try:
        action = args.farma_action
        if action == "status":
            payload = client.test_connection()
            if not _json_or_save(payload, args):
                _title("FarmaLíder API - Status")
                print("Conexão.................. OK")
                print(f"Ambiente................. {payload.get('environment')}")
                print(f"HTTP..................... {payload.get('status_code')}")
                print(f"URL base................. {payload.get('base_url')}")
                print("Autenticação............. QueryString (token oculto)")
            return 0

        if action == "cliente":
            cpf = _normalize_cpf(args.cpf)
            payload = client.get_cliente_by_cpf(cpf)
            if _json_or_save(payload or {}, args):
                return 0
            _show_farmalider_payload("FarmaLíder - Cliente", payload)
            return 0 if payload is not None else 2

        if action == "pedido":
            codigo = str(args.codigo).strip()
            if not codigo:
                raise RuntimeError("Código do pedido não informado.")
            payload = client.get_pedido(codigo)
            if _json_or_save(payload or {}, args):
                return 0
            _show_farmalider_payload("FarmaLíder - Pedido", payload)
            return 0 if payload is not None else 2

        raise RuntimeError("Consulta FarmaLíder desconhecida.")
    finally:
        client.close()


def _menu() -> int:
    while True:
        _title(f"NexoFlow Terminal {VERSION}")
        print("1. Ver status")
        print("2. Rodar diagnóstico")
        print("3. Testar Weni/FarmaLíder")
        print("4. Dry-run Weni")
        print("5. Atualizar Weni")
        print("6. Carga completa Weni")
        print("7. Executar Analytics")
        print("8. Ver log Weni")
        print("9. Listar todos os comandos")
        print("0. Sair")
        choice = input("\nEscolha uma opção: ").strip()
        try:
            if choice == "0":
                return 0
            if choice == "1":
                _status(False)
            elif choice == "2":
                _doctor()
            elif choice == "3":
                _run_windows_target("comandos/testar_update_weni.bat")
            elif choice == "4":
                _run_windows_target("comandos/atualizar_weni_dry_run.bat")
            elif choice == "5":
                _run_windows_target("comandos/atualizar_weni.bat")
            elif choice == "6":
                _run_windows_target("comandos/atualizar_weni_carga_completa.bat")
            elif choice == "7":
                _run_windows_target("NexoFlow Analytics.exe")
            elif choice == "8":
                for line in _tail_lines(_log_path("weni"), 50):
                    print(line)
            elif choice == "9":
                _print_commands()
            else:
                print("Opção inválida.")
        except Exception as exc:
            print(f"[ERRO] {_safe_text(exc, max_len=220)}")
        input("\nPressione ENTER para voltar ao menu...")
        print()


def _add_output_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        "--raw",
        dest="json",
        action="store_true",
        help="mostra a resposta JSON completa",
    )
    parser.add_argument(
        "--salvar",
        metavar="ARQUIVO",
        help="salva a resposta JSON em um arquivo",
    )


def build_parser() -> argparse.ArgumentParser:
    from config import FARMALIDER_MAX_WORKERS

    parser = argparse.ArgumentParser(
        prog="nexo",
        add_help=True,
        description="Comandos amigáveis do NexoFlow Terminal.",
        epilog='Use "nexo ajuda" para ver exemplos práticos.',
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser(
        "ajuda", aliases=["help", "comandos"], help="lista todos os comandos"
    )
    sub.add_parser("versao", aliases=["version"], help="mostra a versão do NexoFlow")

    status = sub.add_parser("status", help="mostra status local e conexões")
    status.add_argument("--local", action="store_true", help="não consulta APIs")

    sub.add_parser(
        "diagnostico", aliases=["doctor", "check"], help="check-up e conexões"
    )
    analytics = sub.add_parser("analytics", help="executa o NexoFlow Analytics")
    analytics.add_argument(
        "analytics_op",
        nargs="?",
        choices=["planilhas"],
        help="carga pelos exports de conversas e contatos",
    )

    looker = sub.add_parser(
        "looker", help="recalcula os KPIs do Data Studio usando o histórico do Google Sheets"
    )
    looker.add_argument("--inicio", help="Início do período, AAAA-MM-DD")
    looker.add_argument("--fim", help="Fim do período, AAAA-MM-DD")

    weni = sub.add_parser("weni", help="rotinas seguras de atualização da Weni")
    weni_sub = weni.add_subparsers(dest="weni_op")
    weni_sub.add_parser(
        "testar", aliases=["teste", "test"], help="testa acessos sem gravar"
    )
    weni_sub.add_parser(
        "dry-run", aliases=["simular"], help="simula alterações sem gravar"
    )
    weni_sub.add_parser(
        "atualizar", aliases=["update"], help="atualização incremental segura"
    )
    weni_sub.add_parser(
        "carga-completa", aliases=["full"], help="carga completa com revisão humana"
    )
    recompra = weni_sub.add_parser(
        "recompra", help="auditoria, simulação e aplicação revisada da recompra D+25"
    )
    recompra.add_argument(
        "recompra_op", choices=["auditoria", "dry-run", "aplicar", "atualizar"]
    )
    recompra.add_argument(
        "--revisao", default=str(scoped_path("logs/recompra_review.json"))
    )
    recompra.add_argument("--contato", help="UUID de um contato para a simulação")
    recompra.add_argument("--full", action="store_true")
    recompra.add_argument(
        "--workers",
        type=int,
        choices=range(1, FARMALIDER_MAX_WORKERS + 1),
        help=f"consultas FarmaLíder simultâneas no dry-run (padrão: {FARMALIDER_MAX_WORKERS})",
    )
    weni_sub.add_parser(
        "planilhas",
        help="carga de pedidos a partir dos exports XLSX, com revisão humana",
    )

    logs = sub.add_parser("logs", help="consulta logs do NexoFlow")
    logs.add_argument("tipo", nargs="?", default="weni", choices=["weni", "analytics"])
    logs.add_argument(
        "--linhas", type=int, default=50, help="quantidade de linhas (padrão: 50)"
    )
    logs.add_argument(
        "--seguir", "--follow", action="store_true", help="acompanha o log ao vivo"
    )

    api = sub.add_parser("api", help="consultas GET amigáveis e somente leitura")
    api_sub = api.add_subparsers(dest="api_target")

    api_weni = api_sub.add_parser("weni", help="consultas de leitura na Weni")
    api_weni_sub = api_weni.add_subparsers(dest="weni_action")
    p = api_weni_sub.add_parser("status", help="testa leitura da Weni")
    _add_output_flags(p)
    p = api_weni_sub.add_parser("contato", help="consulta um contato por UUID ou URN")
    ident = p.add_mutually_exclusive_group(required=True)
    ident.add_argument("--uuid")
    ident.add_argument("--urn")
    _add_output_flags(p)
    p = api_weni_sub.add_parser("mensagens", help="consulta mensagens de um contato")
    ident = p.add_mutually_exclusive_group(required=True)
    ident.add_argument("--uuid")
    ident.add_argument("--urn")
    p.add_argument(
        "--limite", type=int, default=10, choices=range(1, 101), metavar="1-100"
    )
    _add_output_flags(p)
    p = api_weni_sub.add_parser("grupos", help="lista grupos da Weni")
    p.add_argument("--nome")
    _add_output_flags(p)
    p = api_weni_sub.add_parser("campos", help="lista campos da Weni")
    p.add_argument("--chave", help="ex.: cpf, contact_urn")
    _add_output_flags(p)

    api_farma = api_sub.add_parser(
        "farmalider", aliases=["farma"], help="consultas GET na FarmaLíder"
    )
    api_farma_sub = api_farma.add_subparsers(dest="farma_action")
    p = api_farma_sub.add_parser("status", help="testa a API FarmaLíder")
    _add_output_flags(p)
    p = api_farma_sub.add_parser("cliente", help="consulta cliente pelo CPF")
    p.add_argument("--cpf", required=True)
    _add_output_flags(p)
    p = api_farma_sub.add_parser("pedido", help="consulta pedido pelo código")
    p.add_argument("codigo")
    _add_output_flags(p)

    return parser


def run(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if not args_list:
        return _menu()

    parser = build_parser()
    args = parser.parse_args(args_list)

    try:
        if args.command in {"ajuda", "help", "comandos"}:
            _print_commands()
            return 0
        if args.command in {"versao", "version"}:
            print(f"NexoFlow {VERSION}")
            return 0
        if args.command == "status":
            return _status(args.local)
        if args.command in {"diagnostico", "doctor", "check"}:
            return _doctor()
        if args.command == "analytics":
            return _run_windows_target(
                "comandos/executar_analytics_planilhas.bat"
                if args.analytics_op == "planilhas"
                else "NexoFlow Analytics.exe"
            )
        if args.command == "looker":
            from run_looker import run as looker_run

            arguments = []
            if args.inicio:
                arguments += ["--inicio", args.inicio]
            if args.fim:
                arguments += ["--fim", args.fim]
            return looker_run(arguments)
        if args.command == "weni":
            if args.weni_op == "recompra":
                if args.recompra_op == "atualizar":
                    return _run_windows_target("comandos/atualizar_recompra.bat")
                from run_recompra import main as recompra_main

                arguments = [
                    {
                        "auditoria": "--check-only",
                        "dry-run": "--dry-run",
                        "aplicar": "--apply",
                    }[args.recompra_op]
                ]
                arguments += [
                    "--require-review"
                    if args.recompra_op == "aplicar"
                    else "--review-out",
                    args.revisao,
                ]
                if args.contato:
                    arguments += ["--contact", args.contato]
                if args.full:
                    arguments.append("--full")
                if args.workers is not None:
                    arguments += ["--workers", str(args.workers)]
                return recompra_main(arguments)
            mapping = {
                "testar": "comandos/testar_update_weni.bat",
                "teste": "comandos/testar_update_weni.bat",
                "test": "comandos/testar_update_weni.bat",
                "dry-run": "comandos/atualizar_weni_dry_run.bat",
                "simular": "comandos/atualizar_weni_dry_run.bat",
                "atualizar": "comandos/atualizar_weni.bat",
                "update": "comandos/atualizar_weni.bat",
                "carga-completa": "comandos/atualizar_weni_carga_completa.bat",
                "full": "comandos/atualizar_weni_carga_completa.bat",
                "planilhas": "comandos/atualizar_weni_planilhas.bat",
            }
            if args.weni_op not in mapping:
                parser.parse_args(["weni", "-h"])
            return _run_windows_target(mapping[args.weni_op])
        if args.command == "logs":
            path = _log_path(args.tipo)
            if args.seguir:
                return _follow_file(path, args.linhas)
            _title(f"Log {args.tipo} - últimas {args.linhas} linhas")
            lines = _tail_lines(path, args.linhas)
            if not lines:
                print(f"Log ainda não existe: {path}")
                return 2
            print("\n".join(lines))
            return 0
        if args.command == "api":
            if args.api_target == "weni" and args.weni_action:
                return _api_weni(args)
            if args.api_target in {"farmalider", "farma"} and args.farma_action:
                return _api_farmalider(args)
            print('Use "nexo ajuda" para ver as consultas disponíveis.')
            return 2

        _print_commands()
        return 0
    except KeyboardInterrupt:
        print("\nOperação cancelada pelo usuário.")
        return 130
    except Exception as exc:
        print(f"[ERRO] {_safe_text(exc, max_len=300)}", file=sys.stderr)
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
