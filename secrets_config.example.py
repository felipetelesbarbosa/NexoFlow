# ============================================================
# EXEMPLO DE CONFIGURAÇÃO
# ============================================================
# Copie este arquivo para "secrets_config.py" e preencha os
# valores reais. "secrets_config.py" NÃO deve entrar no Git.

WENI_API_TOKEN = "COLE_SEU_TOKEN_WENI_AQUI"

GOOGLE_SPREADSHEET_ID = "COLE_O_ID_DA_PLANILHA_GOOGLE_AQUI"


# ============================================================
# FARMALÍDER API
# ============================================================
FARMALIDER_API_ENABLED = True
FARMALIDER_API_TOKEN = "COLE_SEU_TOKEN_FARMALIDER_AQUI"

# False = produção
# True  = endpoints /api/Delivery/hml/...
FARMALIDER_USE_HML = False

# Webhook (futuro)
WEBHOOK_SHARED_SECRET = "TROQUE_POR_UM_SEGREDO_FORTE"

# ============================================================
# PROXY CORPORATIVO
# ============================================================
# auto = usa o proxy somente quando host:porta estiver acessível
# on   = força o proxy
# off  = nunca configura o proxy pelo projeto
PROXY_MODE = "auto"

PROXY_HOST = "10.1.15.3"
PROXY_PORT = 8020

# Na máquina pessoal, é mais seguro manter estes dois vazios e
# usar PROXY_MODE = "off".
PROXY_USER = "SEU_USUARIO_DO_PROXY"
PROXY_PASSWORD = "SUA_SENHA_DO_PROXY"

# Endereços que não devem usar o proxy.
# Formato compatível com NO_PROXY.
PROXY_BYPASS = "localhost,127.0.0.1"

# Tempo máximo, em segundos, para detectar se o proxy existe.
PROXY_DETECTION_TIMEOUT = 1.5
