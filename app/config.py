from __future__ import annotations

import os
from pathlib import Path
from typing import Final

BASE_DIR: Final = Path(__file__).resolve().parents[1]
CREDENTIALS_DIR: Final = BASE_DIR / "credentials"
LOG_DIR: Final = BASE_DIR / "logs"

WENI_CONTACTS_API_URL: Final = "https://flows.weni.ai/api/v2/contacts.json"
WENI_MESSAGES_API_URL: Final = "https://flows.weni.ai/api/v2/messages.json"
WENI_CONTACT_ACTIONS_API_URL: Final = (
    "https://flows.weni.ai/api/v2/contact_actions.json"
)
WENI_GROUPS_API_URL: Final = "https://flows.weni.ai/api/v2/groups.json"
WENI_FIELDS_API_URL: Final = "https://flows.weni.ai/api/v2/fields.json"
# Compatibilidade com módulos antigos.
WENI_API_URL: Final = WENI_CONTACTS_API_URL
GOOGLE_CREDENTIALS_FILE: Final = CREDENTIALS_DIR / "google_credentials.json"

PAGE_LIMIT: Final = 100
# Agrupamento de exibição; não altera paginação nem tamanho de chamadas à API.
WENI_PROGRESS_BATCH_SIZE: Final = 1000
WENI_PROGRESS_INTERVAL_SECONDS: Final = 15.0
REQUEST_TIMEOUT_SECONDS: Final = 60
SYNC_OVERLAP_MINUTES: Final = 5
MAX_RETRIES: Final = 4

# Atualização automática de campos na Weni
WENI_UPDATE_OVERLAP_MINUTES: Final = 10
WENI_UPDATE_CONTEXT_LOOKBACK_HOURS: Final = 24
WENI_UPDATE_INITIAL_LOOKBACK_DAYS: Final = 90
WENI_UPDATE_OPT_IN_GROUP: Final = "Opt-In LGPD"
WENI_UPDATE_OPT_OUT_GROUP: Final = "Opt-Out LGPD"
WENI_UPDATE_STATE_FILE: Final = LOG_DIR / "weni_update_state.json"
WENI_UPDATE_AUDIT_FILE: Final = LOG_DIR / "weni_update_audit.jsonl"
WENI_UPDATE_LOG_FILE: Final = LOG_DIR / "nexoflow_update_weni.log"

SHEET_BASE_CONTATOS: Final = "Base_Contatos"
SHEET_HISTORICO: Final = "Historico_Alteracoes"
SHEET_METRICAS: Final = "Metricas_Diarias"
SHEET_EVENTOS: Final = "Eventos_Anuncios"
SHEET_CAMPANHAS_META: Final = "Campanhas_Meta"
SHEET_CONTROLE: Final = "Controle"
SHEET_PEDIDOS: Final = "Pedidos_FarmaLider"
SHEET_ITENS_PEDIDOS: Final = "Itens_Pedidos_FarmaLider"
SHEET_METRICAS_VENDAS: Final = "Metricas_Vendas"
SHEET_BI_RESUMO_DIARIO: Final = "BI_Resumo_Diario"
SHEET_BI_CANAIS: Final = "BI_Canais"
SHEET_BI_CONVERSAO: Final = "BI_Conversao"
SHEET_BI_VENDAS: Final = "BI_Vendas"
SHEET_BI_ADS: Final = "BI_Ads"
SHEET_BI_PEDIDOS: Final = "BI_Pedidos"
SHEET_BI_STATUS: Final = "BI_Status"

TIPO_PRIMEIRO_ANUNCIO: Final = "Primeiro anúncio que trouxe o cliente"
TIPO_ULTIMO_ANUNCIO: Final = "Anúncio mais recente que trouxe o cliente"

LOG_FILE: Final = LOG_DIR / "nexoflow.log"

# FarmaLíder
# Com proxy corporativo: URL interna, sem porta 3200.
# Sem proxy: URL externa, com porta 3200.
FARMALIDER_API_BASE_URL_PROXY: Final = "https://api.farmalider.net.br/farmalider"
FARMALIDER_API_BASE_URL_EXTERNAL: Final = (
    "https://api.farmalider.net.br:3200/farmalider"
)
FARMALIDER_REQUEST_TIMEOUT_SECONDS: Final = 60
FARMALIDER_MAX_RETRIES: Final = 4

# Concorrência controlada da FarmaLíder.
# O delay é GLOBAL entre inícios de requisição, mesmo com vários workers.
FARMALIDER_REQUEST_DELAY_SECONDS: Final = 0.01
FARMALIDER_MAX_WORKERS: Final = 4
FARMALIDER_PARALLEL_MIN_CPFS: Final = 20
FARMALIDER_BATCH_SIZE: Final = 500
FARMALIDER_429_COOLDOWN_SECONDS: Final = 5.0
FARMALIDER_MAX_ADAPTIVE_DELAY_SECONDS: Final = 0.20
FARMALIDER_5XX_COOLDOWN_SECONDS: Final = 5.0
FARMALIDER_RECOVERY_MAX_DELAY_SECONDS: Final = 1.0
FARMALIDER_RECOVERY_SERIAL_SUCCESSES: Final = 6
FARMALIDER_RECOVERY_PARALLEL_SUCCESSES: Final = 12
FARMALIDER_CIRCUIT_MIN_5XX: Final = 12
FARMALIDER_CIRCUIT_MIN_DISTINCT_QUERIES: Final = 3
FARMALIDER_BATCH_ERROR_ABORT_RATE: Final = 0.20
FARMALIDER_BATCH_ERROR_ABORT_MIN_ERRORS: Final = 20
FARMALIDER_SLOW_REQUEST_SECONDS: Final = 2.0

# Google Sheets
# Timeout/retry protege leituras contra indisponibilidade temporária e evita espera indefinida.
GOOGLE_SHEETS_CONNECT_TIMEOUT_SECONDS: Final = 10
GOOGLE_SHEETS_READ_TIMEOUT_SECONDS: Final = 60
GOOGLE_SHEETS_READ_MAX_RETRIES: Final = 6

# Cadência segura de escrita para cargas grandes.
GOOGLE_SHEETS_WRITE_DELAY_SECONDS: Final = 1.10
GOOGLE_SHEETS_WRITE_MAX_RETRIES: Final = 6
GOOGLE_SHEETS_UPDATE_BATCH_SIZE: Final = 1500
GOOGLE_SHEETS_APPEND_BATCH_SIZE: Final = 2000
# Limite conservador por payload. O Google recomenda manter requisições em torno
# de até 2 MB; usamos 1,5 MB para deixar margem para JSON/overhead HTTP.
GOOGLE_SHEETS_MAX_BATCH_PAYLOAD_BYTES: Final = 1_500_000
GOOGLE_SHEETS_PROGRESS_EVERY_RECORDS: Final = 5000

# Cache de validação FarmaLíder usado somente no Analytics incremental.
# Carga completa sempre revalida para servir como reconciliação integral.
FARMALIDER_CACHE_CONFIRMED_HOURS: Final = 24
FARMALIDER_CACHE_NOT_FOUND_HOURS: Final = 1


def farmalider_api_base_url() -> str:
    """Retorna a URL correta da FarmaLíder para a rede atual."""
    proxy_state = os.getenv("WENI_PROXY_ACTIVE", "").strip()

    if proxy_state == "1":
        return FARMALIDER_API_BASE_URL_PROXY
    if proxy_state == "0":
        return FARMALIDER_API_BASE_URL_EXTERNAL

    # Fallback para execução direta fora dos wrappers do projeto.
    no_proxy = os.getenv("NO_PROXY", os.getenv("no_proxy", "")).strip()
    has_proxy = any(
        os.getenv(name)
        for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
    )

    if has_proxy and no_proxy != "*":
        return FARMALIDER_API_BASE_URL_PROXY

    return FARMALIDER_API_BASE_URL_EXTERNAL
