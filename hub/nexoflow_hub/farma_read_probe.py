"""Diagnóstico FARMA somente leitura; nenhum dado pessoal sai do processo."""

from __future__ import annotations

import os
import re

from order_history import HistoryQuery, page_envelope

from .real_read_transport import ReadOnlySession, private_token, require_scope

EXTERNAL = "https://api.farmalider.net.br:3200/farmalider"
PREFIX = "/farmalider/api/Delivery/"


def inspect_sources(client, start, end, *, limit=10, directory=False):
    """Amostra delimitada; não representa cobertura histórica integral."""
    result = {
        "segmento": "FARMA",
        "periodo": [start, end],
        "escritas": 0,
        "publicacoes": 0,
        "fontes": {},
    }
    sources = result["fontes"]
    query = HistoryQuery("FARMA", start, end, limit)
    rows, total, pages = page_envelope(client.get_pedidos_history(query, 1), query, 1)
    if any(str(row["capa"].get("segmento", "")).upper() != "FARMA" for row in rows):
        raise ValueError("HISTORICO_SEGMENTO_DIVERGENTE")
    sources["historico"] = {
        "estado": "amostra_validada",
        "linhas": len(rows),
        "total_informado": total,
        "paginas_informadas": pages,
        "cobertura_integral": False,
    }
    if rows:
        expected = rows[0]["capa"]["id"]
        order = client.get_pedido(expected)
        if not isinstance(order, dict) or not isinstance(order.get("capa"), dict):
            raise ValueError("PEDIDO_INDISPONIVEL")
        if (
            order.get("_nexoflow_invalid_segment")
            or str(order["capa"].get("segmento", "")).upper() != "FARMA"
            or str(order["capa"].get("id")) != str(expected)
        ):
            raise ValueError("PEDIDO_SEGMENTO_OU_ID_DIVERGENTE")
        items = order.get("itens")
        if not isinstance(items, list):
            raise ValueError("ITENS_INDISPONIVEIS")
        if any(
            not isinstance(item, dict) or str(item.get("codPedido")) != str(expected)
            for item in items
        ):
            raise ValueError("ITENS_PEDIDO_DIVERGENTE")
        sources["pedido"] = {"estado": "amostra_validada"}
        sources["itens"] = {
            "estado": "amostra_validada" if items else "pendente_sem_itens_na_amostra",
            "linhas": len(items),
        }
    else:
        for source in ("pedido", "itens"):
            sources[source] = {"estado": "pendente_sem_pedido_na_amostra"}
    # Esta rota não é paginada. Exige habilitação explícita e orçamento de
    # memória/tempo verificado pelo operador antes do primeiro ensaio.
    sources["cadastros"] = {"estado": "pendente_validacao_diretorio"}
    if directory:
        from farmalider_customers import CustomerDirectory

        directory_data = client.get_clientes_segmento("FARMA")
        if not isinstance(directory_data, list):
            raise ValueError("DIRETORIO_INVALIDO")
        valid = CustomerDirectory(directory_data, segment="FARMA")
        if not directory_data or not valid.by_id:
            raise ValueError("DIRETORIO_SEM_CADASTRO_VALIDADO")
        sources["cadastros"] = {
            "estado": "parcial"
            if valid.skipped or valid.conflicted_ids
            else "amostra_validada",
            "recebidos": len(directory_data),
            "cadastros_validos": len(valid.by_id),
            "descartados": valid.skipped,
            "conflitos": len(valid.conflicted_ids),
            "segmento_evidencia": "rota_FARMA_e_validacao_compartilhada",
        }
    result.update(
        estado="amostra_validada"
        if all(s["estado"] == "amostra_validada" for s in sources.values())
        else "parcial",
        fonte="FarmaliderClient",
        sintetico=False,
        cobertura_integral=False,
    )
    return result


def run_from_worker(start, end):
    """Reutiliza cliente Windows, fixando a rota externa sem fallback corporativo."""
    require_scope()
    token = private_token("HUB_FARMALIDER_TOKEN_FILE")
    from farmalider_client import FarmaliderClient

    class FarmaliderExternal(FarmaliderClient):
        def _new_session(self):
            session = ReadOnlySession(
                host="api.farmalider.net.br",
                port=3200,
                path_allowed=lambda p: (
                    p in {PREFIX + "clientes/FARMA", PREFIX + "pedidos/farma"}
                    or re.fullmatch(re.escape(PREFIX) + r"pedido/[0-9]{1,10}", p)
                    is not None
                ),
                proxy_var="HUB_SOURCE_PROXY_URL",
                proxy_expected="http://farma-fontes-egress:3128",
            )
            session.headers.update({"Accept": "application/json"})
            return session

        def _request_route(self, path):
            return EXTERNAL + path, {}

        def _refresh_network_route(self, *, reason, attempt=1):
            return False

    client = FarmaliderExternal(token)
    try:
        if client.base_url != EXTERNAL or client.customer_segment != "FARMA":
            raise ValueError("ROTA_EXTERNA_FARMA_OBRIGATORIA")
        return inspect_sources(
            client,
            start,
            end,
            directory=os.environ.get("HUB_FARMALIDER_DIRECTORY_PROBE") == "true",
        )
    finally:
        client.close()
