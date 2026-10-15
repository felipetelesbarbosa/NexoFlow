from __future__ import annotations

import sys
from urllib.parse import urlsplit

import requests
from config import (
    FARMALIDER_BATCH_SIZE,
    FARMALIDER_MAX_ADAPTIVE_DELAY_SECONDS,
    FARMALIDER_MAX_WORKERS,
    FARMALIDER_REQUEST_DELAY_SECONDS,
    GOOGLE_CREDENTIALS_FILE,
    WENI_CONTACTS_API_URL,
)
from farmalider_client import FarmaliderClient, FarmaliderError
from google_sheets import GoogleSheetsStore
from network_diagnostics import classify_network_failure
from project_paths import load_private_settings
from weni_client import WeniClient, WeniError

secrets = load_private_settings()


def safe_failure(error: Exception) -> str:
    if isinstance(error, requests.RequestException):
        return classify_network_failure(error).summary
    if isinstance(error, (WeniError, FarmaliderError)):
        return str(error)
    return f"Falha do tipo {type(error).__name__}; consulte o diagnóstico local."


def ok(text: str) -> None:
    print(f"[OK] {text}")


def warn(text: str) -> None:
    print(f"[AVISO] {text}")


def fail(text: str) -> None:
    print(f"[ERRO] {text}")


def main() -> int:
    errors = 0
    farm_auth_unconfirmed = False
    print("=== Diagnóstico NexoFlow ===\n")
    print(
        "[INFO] Proxy TCP acessível não comprova autenticação nem acesso a cada serviço HTTPS."
    )
    print(
        "[INFO] TLS permanece validado; o diagnóstico não muda automaticamente a rota de rede.\n"
    )

    weni_token = str(getattr(secrets, "WENI_API_TOKEN", "")).strip()
    spreadsheet_id = str(getattr(secrets, "GOOGLE_SPREADSHEET_ID", "")).strip()
    farm_token = str(getattr(secrets, "FARMALIDER_API_TOKEN", "")).strip()
    farm_enabled = bool(getattr(secrets, "FARMALIDER_API_ENABLED", True))
    farm_hml = bool(getattr(secrets, "FARMALIDER_USE_HML", False))

    if weni_token and weni_token != "COLE_SEU_TOKEN_WENI_AQUI":
        ok("Token da Weni preenchido no secrets_config.py")
    else:
        fail("Token da Weni ainda não foi preenchido")
        errors += 1

    if GOOGLE_CREDENTIALS_FILE.exists():
        ok(f"Credencial Google encontrada: {GOOGLE_CREDENTIALS_FILE}")
    else:
        fail("Arquivo credentials/google_credentials.json não encontrado")
        errors += 1

    if spreadsheet_id and spreadsheet_id != "COLE_O_ID_DA_PLANILHA_GOOGLE_AQUI":
        ok("ID da planilha Google preenchido")
    else:
        fail("ID da planilha Google ainda não foi preenchido")
        errors += 1

    if farm_enabled:
        if farm_token and farm_token != "COLE_SEU_TOKEN_FARMALIDER_AQUI":
            ok("Token da FarmaLíder preenchido (QueryString)")
            ok(
                "Intervalo global mínimo FarmaLíder: "
                f"{int(FARMALIDER_REQUEST_DELAY_SECONDS * 1000)} ms"
            )
            ok(
                "Concorrência FarmaLíder: "
                f"{FARMALIDER_MAX_WORKERS} workers | "
                f"lotes de até {FARMALIDER_BATCH_SIZE} CPFs"
            )
            ok(
                "Throttle adaptativo FarmaLíder: até "
                f"{int(FARMALIDER_MAX_ADAPTIVE_DELAY_SECONDS * 1000)} ms "
                "após HTTP 429"
            )
        else:
            warn(
                "Token da FarmaLíder não preenchido. Weni/Google funcionarão, "
                "mas sem validação de CPF/pedido."
            )
    else:
        warn("Integração FarmaLíder está desabilitada")

    if errors:
        print("\nCorrija os itens obrigatórios acima antes de testar as conexões.")
        return 1

    print("\nTestando Weni...")
    proxies = requests.utils.get_environ_proxies(WENI_CONTACTS_API_URL)
    route = "proxy" if proxies.get("https") or proxies.get("all") else "direta"
    print(
        f"[INFO] Destino: {urlsplit(WENI_CONTACTS_API_URL).hostname} | conexão: {route}"
    )
    client = WeniClient(weni_token)
    try:
        result = client.test_connection()
        ok(
            "Conexão com Weni funcionando "
            f"(amostra retornada: {result['sample_count']})"
        )
    except Exception as exc:
        fail(f"Falha na Weni: {safe_failure(exc)}")
        errors += 1
    finally:
        client.close()

    if farm_enabled and farm_token:
        print("\nTestando FarmaLíder API...")
        farm = FarmaliderClient(farm_token, use_hml=farm_hml)
        try:
            result = farm.test_connection()
            if result["status_code"] in {400, 404}:
                farm_auth_unconfirmed = True
                warn(
                    "FarmaLíder respondeu ao teste com CPF fictício "
                    f"({result['environment']}, HTTP {result['status_code']}). "
                    "Rede acessível; autenticação não confirmada por este teste."
                )
            else:
                ok(
                    f"FarmaLíder respondeu ao teste ({result['environment']}, HTTP {result['status_code']})."
                )
            ok(f"URL selecionada FarmaLíder: {result['base_url']}")
        except Exception as exc:
            fail(f"Falha na FarmaLíder API: {safe_failure(exc)}")
            errors += 1
        finally:
            farm.close()

    print("\nTestando Google Sheets...")
    try:
        GoogleSheetsStore(spreadsheet_id, validate_structure=True)
        ok("Conexão com Google Sheets funcionando e estrutura completa validada")
    except Exception as exc:
        fail(f"Falha no Google Sheets: {safe_failure(exc)}")
        errors += 1

    print()
    if errors:
        print(f"Diagnóstico concluído com {errors} erro(s).")
        return 1

    if farm_auth_unconfirmed:
        warn(
            "Conexões testadas; autenticação FarmaLíder ainda precisa ser confirmada em uma consulta real."
        )
    else:
        print("Tudo certo. O projeto está pronto para sincronizar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
