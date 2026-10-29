"""Cada perfil é exercitado em processo novo, com credenciais e APIs sintéticas."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOT = """
import tests
import secrets_config as settings
settings.PERFIS = {
 'FARMA': {'SEGMENTO':'FARMA', 'WENI_API_TOKEN':'WENI_FARMA_TEST', 'FARMALIDER_API_TOKEN':'API_TEST', 'GOOGLE_SPREADSHEET_ID':'D_FARMA', 'GOOGLE_OPERATIONS_SPREADSHEET_ID':'O_FARMA', 'GOOGLE_HISTORY_SPREADSHEET_ID':'H_FARMA'},
 'PET': {'SEGMENTO':'PET', 'WENI_API_TOKEN':'WENI_PET_TEST', 'FARMALIDER_API_TOKEN':'API_TEST', 'GOOGLE_SPREADSHEET_ID':'D_PET', 'GOOGLE_OPERATIONS_SPREADSHEET_ID':'O_PET', 'GOOGLE_HISTORY_SPREADSHEET_ID':'H_PET'}
}
"""


class RuntimeProfileTests(unittest.TestCase):
    def invoke(self, profile, code):
        result = subprocess.run(
            [sys.executable, "-c", BOOT + code],
            cwd=ROOT,
            env={**os.environ, "NEXOFLOW_PERFIL": profile},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=40,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result.stdout

    def test_both_profiles_route_credentials_paths_and_order_scope(self):
        for profile in ("FARMA", "PET"):
            with self.subTest(profile=profile):
                data = json.loads(
                    self.invoke(
                        profile,
                        """
import json
from project_paths import load_private_settings
from runtime_profile import scoped_path, last_purchase_field
from config import LOG_DIR
from product_scope import pharmacy_items
from farmalider_client import FarmaliderClient
from recompra_profiles import PetRecompraClient
s=load_private_settings(); farm=FarmaliderClient('API_TEST')
print(json.dumps({'token':s.WENI_API_TOKEN, 'sheet':s.GOOGLE_SPREADSHEET_ID,
 'log':str(LOG_DIR).replace(chr(92),'/'), 'import':str(scoped_path('importacoes')).replace(chr(92),'/'),
 'field':last_purchase_field(), 'retained':len(pharmacy_items([{'produto_nome':'Ração para cães'}])), 'pet_client':isinstance(farm,PetRecompraClient)}))
farm.close()
""",
                    )
                )
                self.assertEqual(data["token"], "WENI_" + profile + "_TEST")
                self.assertEqual(data["sheet"], "D_" + profile)
                self.assertEqual(data["pet_client"], profile == "PET")
                self.assertEqual(data["retained"], int(profile == "PET"))
                self.assertEqual(
                    data["field"],
                    "compra_recente" if profile == "PET" else "ultima_compra",
                )
                self.assertEqual(data["log"].endswith("/logs/PET"), profile == "PET")
                self.assertEqual(
                    data["import"],
                    "importacoes/PET" if profile == "PET" else "importacoes",
                )

    def test_pet_blocks_wrong_sheet_map_before_external_writes(self):
        self.invoke(
            "PET",
            """
from runtime_profile import validate_sheet_destinations
validate_sheet_destinations('D_PET','O_PET','H_PET')
for ids in [('D_PET','O_FARMA','H_PET'),('D_FARMA','O_PET','H_PET')]:
 try: validate_sheet_destinations(*ids)
 except ValueError: pass
 else: raise AssertionError('Mistura de planilhas aceita')
""",
        )

    def test_pet_token_wrong_org_is_blocked_before_contact_request(self):
        self.invoke(
            "PET",
            """
from unittest.mock import Mock
from weni_client import WeniClient, WeniError
c=WeniClient('PET_TEST'); response=Mock(); response.status_code=200; response.json.return_value={'name':'Delivery FarmaLíder'}
c.session.request=Mock(return_value=response)
try: list(c.iter_contacts())
except WeniError: pass
else: raise AssertionError('Projeto errado aceito')
assert c.session.request.call_count==1
assert c.session.request.call_args.args[1].endswith('/org.json')
c.close()
""",
        )

    def test_pet_weni_purchase_preserves_pet_and_uses_compra_recente(self):
        self.invoke(
            "PET",
            """
from tests.test_recompra import fixture, NOW
from weni_update import ContactUpdatePlan, _apply_purchase_candidate, _set_field_if_changed, audit_plans, UpdateStats, write_review_snapshot, load_review_snapshot, PlanAuditError
from analytics import normalize_contact
from pathlib import Path
from tempfile import TemporaryDirectory
c,o,items=fixture(2); items[0]['produto_nome']='Ração para cães'
p=ContactUpdatePlan(c['uuid'])
assert _apply_purchase_candidate(p,c,farm_client=None,captured_at=NOW.isoformat(),resolved_order=(o,items))
assert 'compra_recente' in p.fields and 'ultima_compra' not in p.fields
assert not p.order_has_animal_products
_set_field_if_changed(p,{},'maior_de_18_anos','Sim')
assert 'maior_de_18_anos' not in p.fields
_set_field_if_changed(p,{},'opt_in_lgpd','recusado')
assert p.fields['opt_in_lgpd']=='Não'
c['fields'].update(compra_recente='2026-10-07T10:00:00', opt_in_marketing='Não')
row=normalize_contact(c,NOW.isoformat())
assert row['ultima_compra']==c['fields']['compra_recente']
with TemporaryDirectory() as temp:
 import json
 path=Path(temp)/'r.json'
 path.write_text(json.dumps({'schema_version':1,'segment':'FARMA'}))
 try: load_review_snapshot(full=False,json_path=path)
 except PlanAuditError: pass
 else: raise AssertionError('Revisão FARMA aceita no PET')
""",
        )

    def test_pet_analytics_writes_pet_orders_and_items_idempotently(self):
        self.invoke(
            "PET",
            "\nfrom tests.test_pharmacy_scope import fixture,store_fixture\nfrom pharmacy_scope import filter_pharmacy_order\norder,items,_=fixture(pet_only=True)\nfiltered,retained=filter_pharmacy_order(order,items)\nassert filtered is not None and retained==items\nstore=store_fixture()\nr,i=store.upsert_pharmacy_orders([order],items)\nassert len(r.final_records)==1 and len(i.final_records)==1\nassert 'Ração' in i.final_records[0]['produto_nome']\nr2,i2=store.upsert_pharmacy_orders([order],items)\nassert len(r2.final_records)==1 and len(i2.final_records)==1\n",
        )

    def test_pet_planilhas_real_resolution_review_and_apply(self):
        self.invoke(
            "PET",
            "\nfrom tests.test_delivery_tickets import DeliveryTicketsTests, contact\nfrom delivery_tickets import write_delivery_review,apply_delivery_review\nfrom pathlib import Path\nfrom tempfile import TemporaryDirectory\nfrom unittest.mock import Mock\nfrom weni_update import REQUIRED_ORDER_FIELDS\ncase=DeliveryTicketsTests()\nplans,delivery=case.reconcile()\ndelivery['target']='weni'\nassert plans and plans[0].purchase_confirmed\nwith TemporaryDirectory() as temp:\n path=Path(temp)/'review.json';write_delivery_review(plans,delivery,path)\n import json\n assert json.loads(path.read_text())['segment']=='PET'\n w=Mock();live=contact();w.get_contact.side_effect=lambda **kwargs:live\n w.list_fields.return_value=[{'key':key,'value_type':'text'} for key in REQUIRED_ORDER_FIELDS]\n w.update_contact_fields.side_effect=lambda uid,fields:live['fields'].update(fields)\n result=apply_delivery_review(path,w,target='weni')\n assert result['contacts_accepted']==1 and result['conflicts']==0\n assert w.update_contact_fields.call_count==1\n",
        )

    def test_pet_directory_outage_stays_pending_without_reloading_base_per_contact(
        self,
    ):
        self.invoke(
            "PET",
            """
from unittest.mock import patch
from farmalider_client import FarmaliderClient,FarmaliderError
farm=FarmaliderClient('API_TEST')
with patch.object(farm,'get_clientes_segmento',side_effect=FarmaliderError('Timeout sintético')) as load:
 for cpf in ('52998224725','11111111111'):
  try: farm.get_cliente_by_cpf(cpf)
  except FarmaliderError: pass
  else: raise AssertionError('Ausência de base tratada como cadastro válido')
 assert load.call_count==1
 farm.reset_execution_reads()
 try: farm.get_cliente_by_cpf('52998224725')
 except FarmaliderError: pass
 assert load.call_count==2
farm.close()
""",
        )

    def test_pet_noturno_keeps_profile_specific_report_and_failure_code(self):
        self.invoke(
            "PET",
            "\nfrom tempfile import TemporaryDirectory\nfrom pathlib import Path\nfrom run_noturno import execute\nwith TemporaryDirectory() as temp:\n root=Path(temp)\n def fail(arguments,**kwargs):return 3\n assert execute(root,runner=fail)==3\n assert len(list((root/'logs'/'PET'/'noturno').glob('*/resultado.json')))==1\n assert not (root/'logs'/'noturno').exists()\n",
        )
