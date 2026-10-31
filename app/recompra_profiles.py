"""Perfis de segmento e cliente PET compartilhados pelos aplicativos."""

from dataclasses import dataclass
from pathlib import Path

from farmalider_client import (
    FarmaliderAuthError,
    FarmaliderClient,
    FarmaliderError,
    FarmaliderUnavailableError,
)
from farmalider_customers import CustomerDirectory, ExecutionReadCache
from product_scope import PHARMACY_SCOPE_VERSION


@dataclass(frozen=True)
class RecompraProfile:
    segment: str
    days: int
    brand: str

    @property
    def group(self):
        return f"Recompra {self.brand}"

    @property
    def flow(self):
        return f"{self.group} D+{self.days}"

    @property
    def policy(self):
        scope = (
            f"PRODUTOS_HUMANOS_{PHARMACY_SCOPE_VERSION}"
            if self.segment == "FARMA"
            else "BASE_PET"
        )
        return f"JANELA_0_A_{self.days}_SEM_RECUSA_{scope}_EXECUCAO_V5"

    @property
    def directory(self):
        return Path("logs") if self.segment == "FARMA" else Path("logs/PET")


def profile_for(segment="FARMA"):
    if segment == "FARMA":
        return RecompraProfile("FARMA", 25, "FarmaLíder")
    if segment == "PET":
        return RecompraProfile("PET", 30, "Pets Líder")
    raise ValueError("Perfil deve ser FARMA ou PET.")


def profile_settings(settings, segment):
    """Nunca completar PET com tokens FARMA; configuração plana permanece compatível."""
    profiles = getattr(settings, "PERFIS", {})
    if isinstance(profiles, dict) and segment in profiles:
        selected = profiles[segment]
        if (
            not isinstance(selected, dict)
            or selected.get("SEGMENTO", segment) != segment
        ):
            raise ValueError("Configuração do perfil divergente.")
        return dict(selected)
    if segment == "PET":
        raise ValueError(
            'Configure PERFIS["PET"] em secrets_config.py; não será usado o token FARMA.'
        )
    return {
        key: getattr(settings, key, None)
        for key in (
            "WENI_API_TOKEN",
            "FARMALIDER_API_TOKEN",
            "FARMALIDER_API_ENABLED",
            "FARMALIDER_USE_HML",
        )
    }


class PetRecompraClient(FarmaliderClient):
    """Consulta PET exige vínculo no cadastro PET; fallback de pedido exige segmento."""

    def prepare_customer_directory(self, *, expected_contacts=None):
        with self._directory_lock:
            if self.customer_directory is not None:
                return True
            if self._directory_attempted:
                return False
            self._directory_attempted = True
            if self._execution_cache is None:
                self._execution_cache = ExecutionReadCache()
            try:
                from task_progress import TaskProgress

                with TaskProgress(
                    "FarmaLíder: base cadastral PET",
                    1,
                    unit="consultas",
                    interval=15,
                    detail=lambda: (
                        "aguardando base completa; resposta pode demorar até 10 minutos por tentativa"
                    ),
                ) as progress:
                    self.customer_directory = CustomerDirectory(
                        self.get_clientes_segmento("PET"), segment="PET"
                    )
                    progress.advance()
            except (FarmaliderAuthError, FarmaliderUnavailableError):
                raise
            except (FarmaliderError, ValueError):
                return False
            return True

    customer_segment = "PET"

    def get_cliente_by_cpf(self, cpf):
        self.prepare_customer_directory()
        return super().get_cliente_by_cpf(cpf)

    def get_pedido(self, codigo):
        self.prepare_customer_directory()
        directory = self.customer_directory
        if directory is not None:
            snapshot = directory.order_by_id(str(codigo))
            if snapshot is not None:
                return snapshot
        return super().get_pedido(codigo)


CANCEL_EXPRESSION = '@(if(or(lower(trim(default(fields.pedido_status, ""))) = "3", lower(trim(default(fields.pedido_status, ""))) = "3.0", lower(trim(default(fields.pedido_status, ""))) = "cancelado", lower(trim(default(fields.pedido_status, ""))) = "cancelada", lower(trim(default(fields.pedido_forma_pagamento, ""))) = "0", lower(trim(default(fields.pedido_forma_pagamento, ""))) = "0.0", lower(trim(default(fields.pedido_forma_pagamento, ""))) = "_", lower(trim(default(fields.pedido_forma_pagamento, ""))) = "cancelado", lower(trim(default(fields.pedido_forma_pagamento, ""))) = "cancelada"), "CANCELADO", "CONTINUAR"))'
PET_LEGACY_REFUSAL_EXPRESSION = '@(if(or(lower(trim(default(fields.marketing_opt_in, ""))) = "recusado", lower(trim(default(fields.marketing_opt_in, ""))) = "não", lower(trim(default(fields.marketing_opt_in, ""))) = "nao", lower(trim(default(fields.marketing_opt_in, ""))) = "negado", lower(trim(default(fields.marketing_opt_in, ""))) = "inativo", lower(trim(default(fields.marketing_opt_in, ""))) = "false", lower(trim(default(fields.marketing_opt_in, ""))) = "0", lower(trim(default(fields.marketing_opt_in, ""))) = "cancelado", lower(trim(default(fields.marketing_opt_in, ""))) = "recusa", lower(trim(default(fields.marketing_opt_in, ""))) = "não autorizado", lower(trim(default(fields.marketing_opt_in, ""))) = "nao autorizado", lower(trim(default(fields.marketing_opt_in, ""))) = "nao quero receber", lower(trim(default(fields.opt_in_marketing, ""))) = "recusado", lower(trim(default(fields.opt_in_marketing, ""))) = "não", lower(trim(default(fields.opt_in_marketing, ""))) = "nao", lower(trim(default(fields.opt_in_marketing, ""))) = "negado", lower(trim(default(fields.opt_in_marketing, ""))) = "inativo", lower(trim(default(fields.opt_in_marketing, ""))) = "false", lower(trim(default(fields.opt_in_marketing, ""))) = "0", lower(trim(default(fields.opt_in_marketing, ""))) = "cancelado", lower(trim(default(fields.opt_in_marketing, ""))) = "recusa", lower(trim(default(fields.opt_in_marketing, ""))) = "não autorizado", lower(trim(default(fields.opt_in_marketing, ""))) = "nao autorizado", lower(trim(default(fields.opt_in_marketing, ""))) = "nao quero receber"), "MKT_RECUSADO", "MKT_SEM_RECUSA"))'

PET_REFUSAL_EXPRESSION = '@(if(or(lower(trim(default(fields.opt_in_marketing, ""))) = "recusado", lower(trim(default(fields.opt_in_marketing, ""))) = "não", lower(trim(default(fields.opt_in_marketing, ""))) = "nao", lower(trim(default(fields.opt_in_marketing, ""))) = "negado", lower(trim(default(fields.opt_in_marketing, ""))) = "inativo", lower(trim(default(fields.opt_in_marketing, ""))) = "false", lower(trim(default(fields.opt_in_marketing, ""))) = "0", lower(trim(default(fields.opt_in_marketing, ""))) = "cancelado", lower(trim(default(fields.opt_in_marketing, ""))) = "recusa", lower(trim(default(fields.opt_in_marketing, ""))) = "não autorizado", lower(trim(default(fields.opt_in_marketing, ""))) = "nao autorizado", lower(trim(default(fields.opt_in_marketing, ""))) = "nao quero receber"), "MKT_RECUSADO", "MKT_SEM_RECUSA"))'
