from __future__ import annotations

import sys

import secrets_config as secrets
from config import (
    FARMALIDER_BATCH_SIZE,
    FARMALIDER_MAX_ADAPTIVE_DELAY_SECONDS,
    FARMALIDER_MAX_WORKERS,
    FARMALIDER_REQUEST_DELAY_SECONDS,
    GOOGLE_CREDENTIALS_FILE,
)
from farmalider_client import FarmaliderClient
from google_sheets import GoogleSheetsStore
from weni_client import WeniClient


def ok(text: str) -> None:
    print(f"[OK] {text}")


def warn(text: str) -> None:
    print(f"[AVISO] {text}")


def fail(text: str) -> None:
    print(f"[ERRO] {text}")


def main() -> int:
    errors = 0
    print("=== Diagnóstico NexoFlow ===\n")

    weni_token = str(getattr(secrets, "WENI_API_TOKEN", "")).strip()
    spreadsheet_id = str(
        getattr(secrets, "GOOGLE_SPREADSHEET_ID", "")
    ).strip()
    farm_token = str(
        getattr(secrets, "FARMALIDER_API_TOKEN", "")
    ).strip()
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
    client = WeniClient(weni_token)
    try:
        result = client.test_connection()
        ok(
            "Conexão com Weni funcionando "
            f"(amostra retornada: {result['sample_count']})"
        )
    except Exception as exc:
        fail(f"Falha na Weni: {exc}")
        errors += 1
    finally:
        client.close()

    if farm_enabled and farm_token:
        print("\nTestando FarmaLíder API...")
        farm = FarmaliderClient(farm_token, use_hml=farm_hml)
        try:
            result = farm.test_connection()
            ok(
                "FarmaLíder API acessível "
                f"({result['environment']}, HTTP {result['status_code']}; "
                "token não foi explicitamente rejeitado)"
            )
            ok(f"URL selecionada FarmaLíder: {result['base_url']}")
        except Exception as exc:
            fail(f"Falha na FarmaLíder API: {exc}")
            errors += 1
        finally:
            farm.close()

    print("\nTestando Google Sheets...")
    try:
        GoogleSheetsStore(spreadsheet_id, validate_structure=True)
        ok("Conexão com Google Sheets funcionando e estrutura completa validada")
    except Exception as exc:
        fail(f"Falha no Google Sheets: {exc}")
        errors += 1

    print()
    if errors:
        print(f"Diagnóstico concluído com {errors} erro(s).")
        return 1

    print("Tudo certo. O projeto está pronto para sincronizar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
