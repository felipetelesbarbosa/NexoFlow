"""Adaptador interno sintético; regras puras compartilhadas com o Windows.

Não é um novo contrato da API FarmaLíder e não consulta fontes externas.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from ad_attribution import extract_meta_ads_attribution
from business_recompra import DAYS
from pedido_utils import (
    BUSINESS_TIMEZONE,
)

from .contracts import SCENARIOS

SEGMENTS = DAYS


class ContractPending(Exception):
    pass


class RealWriteBlocked(Exception):
    pass


class ExternalConnector:
    """Porta futura: nenhuma implementação de HTTP ou publicação nesta etapa."""

    def read(self, *_args, **_kwargs):
        raise ContractPending("CONTRATO_NAO_HABILITADO")

    def write(self, *_args, **_kwargs):
        raise RealWriteBlocked("ESCRITA_REAL_BLOQUEADA")


CONNECTORS = {
    name: ExternalConnector()
    for name in (
        "FarmaLider",
        "PetsLider",
        "Weni",
        "MetaAds",
        "GoogleAds",
        "GoogleSheets",
        "DataStudio",
        "HistoricoPedidos",
    )
}


def evaluate(segment, scenario):
    """Fixtures geram evidências; decisões usam o núcleo normalizado."""
    from .orders import Item, OrderEvidence, evaluate_order

    if scenario not in SCENARIOS:
        raise ValueError("CENARIO_NAO_HABILITADO")

    purchase = datetime(2026, 1, 1, 12, tzinfo=BUSINESS_TIMEZONE)
    now = purchase + timedelta(days=SEGMENTS[segment], hours=-1)
    if scenario == "compra_recente":
        purchase = now - timedelta(days=1)
    if scenario == "retroativo":
        purchase = now - timedelta(days=SEGMENTS[segment] + 1)
    evidence = OrderEvidence(
        segment=None
        if scenario == "segmento_desconhecido"
        else ("OUTRO" if scenario == "segmento_divergente" else segment),
        confirmed=True,
        order_id="fixture-order",
        customer_id="fixture-client",
        owner_id="outro" if scenario == "identidade_divergente" else "fixture-client",
        cpf="52998224725",
        contact_cpf="52998224725",
        customer_name="Cliente Sintético",
        contact_name="Cliente Sintético",
        customer_phone="",
        contact_phone="",
        date=purchase,
        status=3 if scenario == "cancelado" else 2,
        payment=0 if scenario == "pagamento_cancelado" else 5,
        freight=Decimal("10.00"),
        billed=Decimal("110.00"),
        items=None
        if scenario == "dados_incompletos"
        else (
            ()
            if scenario == "itens_vazios"
            else (
                Item(
                    "fixture-product",
                    "Produto sintético",
                    Decimal(1),
                    Decimal("100.00"),
                ),
                Item(
                    "0",
                    "",
                    Decimal(1),
                    Decimal("9.00")
                    if scenario == "frete_divergente"
                    else Decimal("10.00"),
                ),
            )
        ),
        refusal_fields={"opt_in_marketing": "Não" if scenario == "recusa" else ""},
        opt_out=scenario == "optout",
    )
    result = evaluate_order(
        None if scenario == "sem_pedido" else evidence, segment, now
    )
    result["anuncio_identificado"] = (
        extract_meta_ads_attribution(
            {
                "id": "fixture-msg",
                "created_on": now.isoformat(),
                "urn": "whatsapp:5500000000000",
                "direction": "in",
                "referral": {
                    "source_type": "ad",
                    "source_id": "fixture-ad",
                    "ctwa_clid": "fixture-click",
                },
            }
        )
        is not None
    )
    return result
