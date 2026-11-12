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

# Produção em todos os perfis. Flag antiga mantida por compatibilidade.
FARMALIDER_USE_HML = False
# Listagem cadastral FARMA: auto para cargas a partir de 500 contatos.
FARMALIDER_CUSTOMER_DIRECTORY_MODE = "auto"
FARMALIDER_CUSTOMER_DIRECTORY_MIN_CONTACTS = 500

# Histórico incremental e suas cinco fontes: habilitar após validar destinos/fontes.
FARMALIDER_HISTORY_ENABLED = False
FARMALIDER_HISTORY_SHEETS_ENABLED = False
FARMALIDER_HISTORY_PAGE_LIMIT = 500
FARMALIDER_HISTORY_MAX_PAGES = 100

# Webhook (futuro)
WEBHOOK_SHARED_SECRET = "TROQUE_POR_UM_SEGREDO_FORTE"

# ============================================================
# PROXY CORPORATIVO
# ============================================================
# auto = usa o proxy somente quando host:porta estiver acessível
# on   = força o proxy
# off  = nunca configura o proxy pelo projeto
PROXY_MODE = "auto"
# Habilitar somente com autorização da TI para alternar automaticamente à rota direta.
PROXY_ALLOW_DIRECT_FALLBACK = False

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


# Perfis dos aplicativos: escolha FARMA ou PET ao abrir o executável.
# Se PERFIS já existir no arquivo local, atualize esse dicionário em vez de duplicá-lo.
PERFIS = {
    "FARMA": {
        "SEGMENTO": "FARMA",
        "WENI_API_TOKEN": WENI_API_TOKEN,
        "GOOGLE_SPREADSHEET_ID": GOOGLE_SPREADSHEET_ID,
        "GOOGLE_OPERATIONS_SPREADSHEET_ID": "",
        "GOOGLE_HISTORY_SPREADSHEET_ID": "",
        "FARMALIDER_API_ENABLED": FARMALIDER_API_ENABLED,
        "FARMALIDER_API_TOKEN": FARMALIDER_API_TOKEN,
        "FARMALIDER_USE_HML": FARMALIDER_USE_HML,
    },
    "PET": {
        "SEGMENTO": "PET",
        "GOOGLE_SPREADSHEET_ID": "",
        "GOOGLE_OPERATIONS_SPREADSHEET_ID": "",
        "GOOGLE_HISTORY_SPREADSHEET_ID": "",
        "WENI_API_TOKEN": "",
        "FARMALIDER_API_ENABLED": True,
        "FARMALIDER_API_TOKEN": "",
        "FARMALIDER_USE_HML": False,
        "FARMALIDER_HISTORY_ENABLED": False,
        "FARMALIDER_HISTORY_SHEETS_ENABLED": False,
        # Ative após configurar o fluxo e o evento D+30 usando pedido_data.
        "RECOMPRA_ENABLED": False,
    },
}

# Publicação BI_Itens FARMA via API privada (não é conexão PostgreSQL direta).
# Manter sheets até homologar API/Access. PET não participa desta integração.
PERFIS["FARMA"].update({
    "BI_ITENS_DESTINO": "sheets",  # depois: postgres
    "BI_ITENS_POSTGRES_MODO": "simular",  # depois da conferência: aplicar
    "BI_ITENS_POSTGRES_CREDENTIALS_FILE": "credentials/bi_itens_farma_publicador.json",
})
