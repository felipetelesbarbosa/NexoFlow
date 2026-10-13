"""Padronização de localidades usando somente dados fictícios e mocks."""

import unittest
from copy import deepcopy

from analytics import BI_ORDERS_COLUMNS, build_bi_order_rows, normalize_contact
from geography import canonical_geography, geography_changes, normalize_geography
from looker_bi import SCHEMAS, build_looker_tables
from tests.test_pharmacy_scope import fixture, store_fixture
from weni_update import (
    ContactUpdatePlan,
    _prepare_frozen_plan_for_apply,
    _same_value,
    _sync_contact_geography_fields,
    audit_plans,
)


class GeographyTests(unittest.TestCase):
    def test_city_typo_accents_case_and_uf_names(self):
        for city in ("belem", "BELÉM", "Belenm", "Bellem", "Anbelem"):
            self.assertEqual(canonical_geography(city, "PA", ""), ("Belém", "Pará", ""))
        for city in ("Anani", "Ananideua", "Ananindeu", "Ananimeuia"):
            self.assertEqual(canonical_geography(city, "PA", "")[0], "Ananindeua")
        self.assertEqual(
            canonical_geography("sao paulo", "sp", ""), ("São Paulo", "São Paulo", "")
        )
        self.assertEqual(
            canonical_geography("salinopolis", "para", "")[0], "Salinópolis"
        )

    def test_homonyms_wrong_uf_and_unknowns_are_preserved(self):
        self.assertEqual(
            canonical_geography("belem", "PB", ""), ("Belém", "Paraíba", "")
        )
        self.assertEqual(canonical_geography("Belém", "", "")[1], "")
        self.assertEqual(canonical_geography("Anani", "SP", "")[0], "Anani")
        self.assertEqual(
            canonical_geography("Localidade X", "Estado X", "Lugar Y"),
            ("Localidade X", "Estado X", "Lugar Y"),
        )
        self.assertEqual(canonical_geography("Manaus", "51", "")[1], "51")

    def test_neighborhood_spelling_districts_and_aliases(self):
        pairs = {
            "Tapana Icoaraci": "Tapanã",
            "Valdecaes": "Val-de-Cans",
            "Curioutinga": "Curió-Utinga",
            "Telegrafo Sem Fio": "Telégrafo",
            "São Braz": "São Brás",
            "Tenone": "Tenoné",
            "Mangueirao": "Mangueirão",
            "Bengui": "Benguí",
            "Pratinha 2 Icoaraci": "Pratinha II",
        }
        for before, after in pairs.items():
            self.assertEqual(canonical_geography("Belém", "Pará", before)[2], after)
        self.assertEqual(
            canonical_geography("Ananindeua", "PA", "Curucamba")[2], "Curuçambá"
        )
        self.assertEqual(
            canonical_geography("Ananindeua", "PA", "Levilandia")[2], "Levilândia"
        )
        self.assertEqual(
            canonical_geography("Ananindeua", "PA", "Quarenta Horas Coqueiro")[2],
            "40 Horas",
        )

    def test_subdivisions_remain_distinct_with_consistent_numerals(self):
        for before in (
            "Cidade Nova 6",
            "Cidade Nova06",
            "Cidade Nova Vi",
            "Cid Nova 6",
            "Cidade 6 Nova",
        ):
            self.assertEqual(
                canonical_geography("Ananindeua", "Pará", before)[2], "Cidade Nova VI"
            )
        self.assertNotEqual(
            canonical_geography("Ananindeua", "PA", "Cidade Nova 5")[2],
            canonical_geography("Ananindeua", "PA", "Cidade Nova 6")[2],
        )

    def test_do_not_erase_road_details_or_choose_between_neighborhoods(self):
        for value in (
            "Guama Cremacao",
            "Agulha Icoaraci Tapana",
            "Cidade Nova 5 We 64",
            "We 29 N651",
        ):
            self.assertEqual(canonical_geography("Belém", "Pará", value)[2], value)
        self.assertEqual(
            canonical_geography("Santarém", "Pará", "Cfremacao")[2], "Cfremacao"
        )

    def test_spelling_is_corrected_without_switching_a_conflicting_city(self):
        self.assertEqual(
            canonical_geography("Ananindeua", "PA", "Cabanazem"),
            ("Ananindeua", "Pará", "Cabanagem"),
        )
        self.assertEqual(
            canonical_geography("Belém", "Pará", "Levilandia"),
            ("Belém", "Pará", "Levilândia"),
        )
        self.assertEqual(
            canonical_geography("Belém", "Pará", "Icoaraci Ponta Grossa")[2],
            "Ponta Grossa",
        )

    def test_misplaced_city_requires_unambiguous_context_without_cep(self):
        self.assertEqual(canonical_geography("Pa", "Pará", "Umarizal")[0], "Belém")
        self.assertEqual(canonical_geography("Pa", "Pará", "Coqueiro")[0], "Pa")
        row = {
            "cidade": "Cidade Nova",
            "estado": "Pará",
            "bairro": "Atalaia",
            "cep": "00000000",
        }
        self.assertEqual(normalize_geography(row)["cidade"], "Cidade Nova")

    def test_normalizer_idempotent_preserves_private_and_business_values(self):
        row = {
            "cidade": "Belenm",
            "estado": "PA",
            "bairro": "Tapana Icoaraci",
            "cep": "00000000",
            "cpf": "synthetic",
            "pedido_data": "2026-10-01",
            "opt_in_lgpd": "Recusado",
        }
        before = deepcopy(row)
        clean = normalize_geography(row)
        self.assertEqual(normalize_geography(clean), clean)
        self.assertEqual(row, before)
        for key in ("cep", "cpf", "pedido_data", "opt_in_lgpd"):
            self.assertEqual(clean[key], row[key])
        self.assertEqual(normalize_geography({}), {})
        self.assertEqual(
            geography_changes({"cidade": None, "estado": "", "bairro": None}), {}
        )

    def test_wrapped_text_values_keep_existing_analytics_contract(self):
        wrapped = {
            "cidade": {"value": "Belem"},
            "estado": {"value": "PA"},
            "bairro": {"value": "Nazare"},
        }
        self.assertEqual(
            normalize_geography(wrapped),
            {"cidade": "Belém", "estado": "Pará", "bairro": "Nazaré"},
        )
        self.assertEqual(normalize_geography({"cidade": 0})["cidade"], "0")

    def test_verified_cep_can_resolve_conflict_but_mismatched_reference_cannot(self):
        row = {
            "cidade": "Cidade Nova",
            "estado": "Pará",
            "bairro": "Atalaia",
            "cep": "12345-678",
        }
        reference = {
            "localidade": "Belém",
            "uf": "PA",
            "bairro": "Guamá",
            "cep": "12345678",
        }
        clean = normalize_geography(row, postal_reference=reference)
        self.assertEqual(
            (clean["cidade"], clean["estado"], clean["bairro"]),
            ("Belém", "Pará", "Guamá"),
        )
        self.assertEqual(clean["cep"], row["cep"])
        self.assertEqual(normalize_geography(clean, postal_reference=reference), clean)
        for bad in (
            {**reference, "cep": "99999999"},
            {**reference, "erro": True},
            {**reference, "localidade": "Localidade falsa"},
        ):
            self.assertEqual(normalize_geography(row, postal_reference=bad), row)

    def test_analytics_and_bi_share_canonical_geography(self):
        order, items, base = fixture()
        base.update(cidade="Belenm", estado="PA", bairro="Tapana Icoaraci")
        normalized = normalize_contact(
            {"uuid": "synthetic-contact", "fields": base}, "2026-10-13"
        )
        self.assertEqual(normalized["cidade"], "Belém")
        tables = build_looker_tables(
            [base], [order], items, snapshot_date="2026-10-13", updated_at="2026-10-13"
        )
        public = dict(zip(SCHEMAS["BI_Publico"], tables["BI_Publico"][0], strict=True))
        self.assertEqual(public["cidade"], "Belém")
        self.assertEqual(public["estado"], "Pará")
        detail = dict(
            zip(
                BI_ORDERS_COLUMNS,
                build_bi_order_rows([base], [order], items, updated_at="2026-10-13")[0],
                strict=True,
            )
        )
        self.assertEqual(detail["bairro"], "Tapanã")

    def test_google_contact_and_history_gates(self):
        _, _, base = fixture()
        base.update(cidade="Belenm", estado="PA", bairro="Tapana Icoaraci")
        store = store_fixture()
        store.upsert_contacts([base])
        row = dict(zip(store.base.values[0], store.base.values[1], strict=True))
        self.assertEqual(row["cidade"], "Belém")
        store.append_history([base], {"synthetic-contact"})
        historical = dict(
            zip(store.history.values[0], store.history.values[1], strict=True)
        )
        self.assertEqual(historical["cidade"], "Belém")
        self.assertEqual(historical["bairro"], "Tapanã")

    def test_weni_plan_strict_case_audit_and_address_conflict(self):
        fields = {
            "cidade": "BELÉM",
            "estado": "PA",
            "bairro": "Tapana Icoaraci",
            "cep": "00000000",
        }
        plan = ContactUpdatePlan(contact_uuid="synthetic-contact")
        _sync_contact_geography_fields(plan, fields, {"cidade", "estado", "bairro"})
        self.assertEqual(plan.fields["cidade"], "Belém")
        self.assertFalse(_same_value("cidade", "BELÉM", "Belém"))
        audit_plans([plan], opt_out_group_available=True)
        changed = {**fields, "cep": "11111111"}
        ready, reason = _prepare_frozen_plan_for_apply(
            plan,
            {"uuid": "synthetic-contact", "fields": changed},
            opt_in_group_name="Opt-In",
            opt_in_group_uuid="",
            opt_out_group_name="Opt-Out",
            opt_out_group_uuid="",
        )
        self.assertIsNone(ready)
        self.assertIn("cep", reason)
        plan.fields["cidade"] = "Outra cidade"
        with self.assertRaises(RuntimeError):
            audit_plans([plan], opt_out_group_available=True)


if __name__ == "__main__":
    unittest.main()
