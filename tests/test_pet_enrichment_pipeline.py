"""Perfis reais carregados em processos isolados; rede bloqueada pelo bootstrap."""

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from contact_enrichment import infer_contact_fields

ROOT = Path(__file__).resolve().parents[1]


class PetMessageEnrichmentTests(unittest.TestCase):
    def test_pet_never_calls_majority_extractors_but_preserves_age_and_lgpd(self):
        messages = [
            {
                "id": "age",
                "created_on": "2026-11-03T10:00:00Z",
                "direction": "in",
                "text": "Tenho 16 anos",
            },
            {
                "id": "q",
                "created_on": "2026-11-03T10:00:01Z",
                "direction": "out",
                "text": "Você autoriza o tratamento dos seus dados pessoais conforme a LGPD?",
            },
            {
                "id": "a",
                "created_on": "2026-11-03T10:00:02Z",
                "direction": "in",
                "text": "Sim",
            },
        ]
        with (
            patch.dict(os.environ, NEXOFLOW_PERFIL="PET"),
            patch(
                "contact_enrichment._direct_majority",
                side_effect=AssertionError("PET não calcula maioridade"),
            ),
        ):
            result = infer_contact_fields(messages, candidate_message_ids={"age", "a"})
        self.assertEqual(result["idade"].value, 16)
        self.assertEqual(result["opt_in_lgpd"].value, "Sim")
        self.assertNotIn("maior_de_18_anos", result)

    def test_pet_majority_prompt_alone_does_not_produce_evidence(self):
        messages = [
            {
                "id": "q",
                "created_on": "2026-11-03T10:00:01Z",
                "direction": "out",
                "text": "Você é maior de 18 anos?",
            },
            {
                "id": "a",
                "created_on": "2026-11-03T10:00:02Z",
                "direction": "in",
                "text": "Sim",
            },
        ]
        with patch.dict(os.environ, NEXOFLOW_PERFIL="PET"):
            self.assertEqual(
                infer_contact_fields(messages, candidate_message_ids={"a"}), {}
            )


class SegmentStartupEnrichmentTests(unittest.TestCase):
    def test_actual_profile_creation_and_optional_enrichment_contract(self):
        code = textwrap.dedent("""
            import tests
            import secrets_config
            from copy import deepcopy
            from datetime import date
            from unittest.mock import Mock
            from types import SimpleNamespace
            from runtime_profile import segment
            secrets_config.PERFIS = {
                'PET': {'SEGMENTO': 'PET', 'WENI_API_TOKEN': 'pet-synthetic', 'FARMALIDER_API_TOKEN': 'api-synthetic', 'GOOGLE_SPREADSHEET_ID': 'pet-sheet-synthetic'},
                'FARMA': {'SEGMENTO': 'FARMA', 'WENI_API_TOKEN': 'farma-synthetic', 'FARMALIDER_API_TOKEN': 'api-synthetic', 'GOOGLE_SPREADSHEET_ID': 'farma-sheet-synthetic'},
            }
            from customer_discovery import build_new_customer_plans, audit_creation
            from farmalider_customers import CustomerDirectory, enrichment
            from tests.test_farmalider_customers import customer_snapshot, CPF
            from weni_update import REQUIRED_ORDER_FIELDS, ContactUpdatePlan, _apply_customer_enrichment, audit_plans
            import weni_update
            fields = REQUIRED_ORDER_FIELDS | {'cpf', 'idade', 'genero', 'email', 'cep', 'cidade', 'estado', 'bairro', 'origem_contato'}
            if segment() == 'FARMA': fields |= {'maior_de_18_anos'}
            else: fields |= {'compra_recente'}
            for option in ('filled', 'null', 'absent', 'unavailable'):
                payload = customer_snapshot()
                payload['ultimoPedido']['segmento'] = segment()
                payload['itens'][0]['descricao'] = 'Produto pet sintético' if segment() == 'PET' else 'Produto humano sintético'
                if option == 'null':
                    payload['cliente'].update(nascimento=None, sexo=None, email=None, enderecos=None)
                elif option == 'absent':
                    for key in ('nascimento','sexo','email','enderecos'): payload['cliente'].pop(key, None)
                index = CustomerDirectory([payload], segment=segment())
                farm = SimpleNamespace(customer_directory=index, get_cliente_by_cpf=lambda cpf: index.latest_by_cpf(cpf), get_pedido=lambda oid: index.order_by_id(oid))
                available = REQUIRED_ORDER_FIELDS | {'cpf'} if option == 'unavailable' else fields
                plans, pending = build_new_customer_plans(farm, [], captured_at='2026-11-03T10:00:00-03:00', available_fields=available)
                assert not pending, (segment(), option, pending)
                assert len(plans)==1
                plan = plans[0]
                assert plan.order_validated and plan.fields['pedido_id']=='8'
                if option=='filled':
                    assert plan.fields.get('cep')=='66023170', (segment(), option, 'CEP do pedido confirmado não enriquecido')
                    assert plan.fields.get('cidade') and plan.fields.get('bairro')
                audit_creation(plan)
                audit_plans([plan], opt_out_group_available=True)
                if segment()=='PET':
                    for section in (plan.fields, plan.guards, plan.evidence): assert 'maior_de_18_anos' not in section, (option, section)
                    if '__farmalider_cadastro' in plan.guards:
                        assert 'maior_de_18_anos' not in plan.guards['__farmalider_cadastro']['contact']['fields']
                    if 'compra_recente' in available: assert 'compra_recente' in plan.fields
                elif option=='filled':
                    assert plan.fields['maior_de_18_anos']=='Sim'
                contact = {'uuid':'synthetic-existing', 'name':'Pessoa Sintética', 'fields':{'cpf':CPF}, 'urns':[]}
                update = ContactUpdatePlan(contact['uuid'])
                _apply_customer_enrichment(update, contact, farm, '2026-11-03T10:00:00-03:00', None)
                audit_plans([update], opt_out_group_available=True)
                if segment()=='PET':
                    assert 'maior_de_18_anos' not in update.fields
                    assert 'maior_de_18_anos' not in update.evidence
                elif option=='filled': assert update.fields['maior_de_18_anos']=='Sim'
            print('Perfil', segment(), 'criação e atualização auditadas em quatro cenários')
        """)
        for segment in ("PET", "FARMA"):
            with self.subTest(segment=segment):
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    cwd=ROOT,
                    env={**os.environ, "NEXOFLOW_PERFIL": segment},
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
