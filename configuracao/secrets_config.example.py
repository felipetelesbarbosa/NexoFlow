# ============================================================
# EXEMPLO DE CONFIGURAÇÃO
# ============================================================
# Copie este arquivo para "secrets_config.py" e preencha os
# valores reais. "secrets_config.py" NÃO deve entrar no Git.

WENI_API_TOKEN = "COLE_SEU_TOKEN_WENI_AQUI"

# Weni Chats: token de integração do projeto Delivery FarmaLíder (Bearer).
# Consulte a origem HTTPS da API usada pelo seu Chats; não reutilize o token de Flows.
WENI_CHATS_API_BASE_URL = ""
WENI_CHATS_API_TOKEN = ""
# Campo estruturado do ticket que contém o ID oficial do pedido, quando disponível.
WENI_CHATS_ORDER_ID_FIELD = ""  # Somente um campo comprovadamente específico do ticket.

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

# Exemplo fictício: substitua pelo endereço autorizado da sua rede.
PROXY_HOST = "proxy.exemplo.invalid"
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

# Recompra integrada aos launchers Weni, após a carga normal e revisão própria.
# Habilite somente após corrigir as pendências de campos/campanha e auditar.
RECOMPRA_ENABLED = False
