"""Servidor MCP local: seis ferramentas GET, transporte STDIO e nenhum segredo no protocolo."""

from __future__ import annotations

import sys
from contextlib import closing
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from connectors.meta_ads_mcp.client import MetaAdsClient
from connectors.meta_ads_mcp.settings import load_settings

mcp = FastMCP("NexoFlow Meta Ads - Somente Leitura")
READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


def _read(method: str, *args: Any) -> dict[str, Any]:
    # Carregar em cada chamada permite renovar o arquivo local, sem manter uma
    # sessão nem uma cópia do token no cadastro do Codex. Exceções de bibliotecas
    # podem conter URLs/headers: não as devolver pelo protocolo.
    try:
        with closing(MetaAdsClient(load_settings())) as client:
            return getattr(client, method)(*args)
    except Exception:
        raise ToolError(
            "Consulta Meta não concluída. Verifique as credenciais locais, ads_read, conta autorizada e conectividade."
        ) from None


@mcp.tool(annotations=READ_ONLY)
def contas_permitidas() -> dict[str, Any]:
    """Lista a allowlist local, sem comprovar autorização na Meta."""
    return _read("accounts")


@mcp.tool(annotations=READ_ONLY)
def detalhes_conta(conta_id: str) -> dict[str, Any]:
    """Consulta detalhes de uma conta autorizada, sem alterações."""
    return _read("account_details", conta_id)


@mcp.tool(annotations=READ_ONLY)
def campanhas(conta_id: str, limite: int = 50, paginas: int = 2) -> dict[str, Any]:
    """Lista campanhas, sem editar ou pausar."""
    return _read("campaigns", conta_id, limite, paginas)


@mcp.tool(annotations=READ_ONLY)
def conjuntos(conta_id: str, limite: int = 50, paginas: int = 2) -> dict[str, Any]:
    """Lista conjuntos, sem editar orçamento ou segmentação."""
    return _read("adsets", conta_id, limite, paginas)


@mcp.tool(annotations=READ_ONLY)
def anuncios(conta_id: str, limite: int = 50, paginas: int = 2) -> dict[str, Any]:
    """Lista anúncios, sem publicações ou alterações."""
    return _read("ads", conta_id, limite, paginas)


@mcp.tool(annotations=READ_ONLY)
def insights(
    conta_id: str,
    data_inicio: str,
    data_fim: str,
    nivel: str = "campaign",
    limite: int = 100,
    paginas: int = 3,
) -> dict[str, Any]:
    """Consulta métricas atribuídas pela Meta; não são vendas confirmadas do Delivery."""
    return _read("insights", conta_id, data_inicio, data_fim, nivel, limite, paginas)


if __name__ == "__main__":
    mcp.run(transport="stdio")
