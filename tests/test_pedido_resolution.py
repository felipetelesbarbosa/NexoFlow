"""Synthetic fixtures only: no customer API payloads or network requests."""
import json
import unittest
from unittest.mock import Mock

from analytics import build_sales_metrics, parse_ultimo_pedido
from farmalider_integration import (
    apply_pedido_api_confirmation,
    cliente_link_status,
    resolve_contact_order,
)
from farmalider_client import FarmaliderAuthError, FarmaliderError
from pedido_utils import (
    business_order_datetime,
    farmalider_order_status_name,
    is_order_cancelled,
    is_order_completed,
    serialize_pedido_products,
)


CAPTURED_AT = "2026-10-06T18:00:00Z"
SYNTHETIC_CPF = "52998224725"


def cliente_payload():
    return {
        "cliente": {"id": 99, "cpf": SYNTHETIC_CPF, "nome": "Cliente sintético"},
        "ultimoPedido": {"id": 123, "codCliente": 99},
    }


def pedido_payload():
    return {
        "capa": {
            "id": 123, "codCliente": 99, "emissao": "2026-10-06T10:30:00",
            "cancelamento": None, "status": 1, "frete": "9.99",
        },
        "itens": [{
            "codPedido": 123, "codProduto": "9001", "quantidade": 1,
            "valor": "38.90", "total": "38.90",
        }],
    }


def raw_order():
    return json.dumps({
        "pedido_id": "123", "data_hora": "2026-10-06T10:30:00",
        "valor_total_compra": "48.89",
        "produtos": [{
            "codigo": "9001", "nome": "Produto sintético",
            "quantidade": 1, "valor_unitario": "38.90", "valor_total": "38.90",
        }],
    })


def contact(*, raw=None, cpf=SYNTHETIC_CPF):
    fields = {}
    if cpf is not None:
        fields["cpf"] = cpf
    if raw is not None:
        fields["ultimo_pedido"] = raw
    return {"uuid": "synthetic-contact", "fields": fields}


def client(cliente=None, pedido=None):
    api = Mock()
    api.get_cliente_by_cpf.return_value = cliente_payload() if cliente is None else cliente
    api.get_pedido.return_value = pedido_payload() if pedido is None else pedido
    return api


def confirm_weni_fixture(raw, *, pedido=None, captured_at=CAPTURED_AT):
    """Exercise API reconciliation directly, outside the priority resolver."""
    order, items = parse_ultimo_pedido(contact(raw=raw), captured_at=captured_at)
    return apply_pedido_api_confirmation(
        order, items, pedido_payload() if pedido is None else pedido,
        linked_cliente_id="99", confirmed_at=captured_at,
    )


def structured_snapshot_contact(order, items):
    candidate = contact()
    candidate["fields"].update({
        "pedido_id": order["pedido_id"], "pedido_data": order["data_hora"],
        "pedido_valor": order["valor_total_compra"], "pedido_quantidade_itens": order["quantidade_itens"],
        "pedido_produtos": serialize_pedido_products(order, items),
    })
    return candidate


class PedidoResolutionTests(unittest.TestCase):
    def test_cliente_envelope_and_legacy_validate_same_identity(self):
        envelope = cliente_payload()
        expected = ("CPF_CONFIRMADO", "99", "Cliente sintético")
        self.assertEqual(cliente_link_status(SYNTHETIC_CPF, envelope), expected)
        self.assertEqual(cliente_link_status(SYNTHETIC_CPF, envelope["cliente"]), expected)

    def test_cliente_requires_present_matching_cpf_and_positive_id(self):
        for key, value in (("cpf", None), ("cpf", "16899535009"), ("id", True), ("id", 99.0), ("id", "0")):
            with self.subTest(key=key, value=value):
                payload = cliente_payload()
                payload["cliente"][key] = value
                self.assertNotEqual(cliente_link_status(SYNTHETIC_CPF, payload)[0], "CPF_CONFIRMADO")

    def test_cliente_integer_cpf_recovers_a_leading_zero(self):
        self.assertEqual(
            cliente_link_status("01234567890", {"id": 99, "cpf": 1234567890, "nome": "Cliente sintético"})[0],
            "CPF_CONFIRMADO",
        )

    def test_cpf_fallback_uses_api_items_and_includes_explicit_freight(self):
        api = client()
        order, items = resolve_contact_order(contact(), farm_client=api, captured_at=CAPTURED_AT)
        self.assertEqual(order["status_confirmacao"], "CONFIRMADO_API")
        self.assertEqual(order["status_validacao"], "OK")
        self.assertEqual(order["origem_pedido"], "FARMALIDER_CLIENTE_ULTIMO_PEDIDO")
        self.assertEqual(order["valor_total_compra"], "48.89")
        self.assertEqual(order["valor_total_api_itens"], "38.90")
        self.assertEqual(order["farmalider_frete"], "9.99")
        self.assertEqual(order["valor_origem"], "SOMA_ITENS_MAIS_FRETE_API")
        self.assertEqual(order["quantidade_itens"], "1")
        self.assertEqual(items[0]["produto_codigo"], "9001")
        self.assertEqual(items[0]["produto_nome"], "")
        self.assertEqual(order["data_hora"], "2026-10-06T10:30:00-03:00")
        api.get_cliente_by_cpf.assert_called_once_with(SYNTHETIC_CPF)
        api.get_pedido.assert_called_once_with("123")

    def test_cached_cliente_response_avoids_duplicate_cpf_request(self):
        api = client()
        order, _ = resolve_contact_order(
            contact(), farm_client=api, captured_at=CAPTURED_AT,
            linked_cliente_id="99", cliente_response=cliente_payload(),
        )
        self.assertEqual(order["status_confirmacao"], "CONFIRMADO_API")
        api.get_cliente_by_cpf.assert_not_called()

    def test_malformed_weni_does_not_fall_back_to_another_order(self):
        api = client()
        order, items = resolve_contact_order(contact(raw="{not-json"), farm_client=api, captured_at=CAPTURED_AT)
        self.assertEqual(order["status_validacao"], "ERRO")
        self.assertEqual(order["ultimo_pedido_raw"], "{not-json")
        self.assertEqual(items, [])
        api.get_cliente_by_cpf.assert_not_called()
        api.get_pedido.assert_not_called()

    def test_nonempty_weni_without_official_id_does_not_query_latest_order(self):
        payload = json.loads(raw_order())
        del payload["pedido_id"]
        api = client()
        raw = json.dumps(payload)
        order, items = resolve_contact_order(contact(raw=raw), farm_client=api, captured_at=CAPTURED_AT)
        self.assertEqual(order["pedido_id"], "")
        self.assertEqual(order["ultimo_pedido_raw"], raw)
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")
        api.get_cliente_by_cpf.assert_not_called()
        api.get_pedido.assert_not_called()

    def test_empty_or_null_weni_uses_cpf_then_official_latest_order(self):
        missing = object()
        for raw in (missing, None, "", " \t\n ", "null", " null ",
                    {"value": None}, {"value": " \t "}, {"value": "null"}):
            with self.subTest(raw=raw if raw is not missing else "missing"):
                candidate = contact()
                if raw is not missing:
                    candidate["fields"]["ultimo_pedido"] = raw
                api = client()
                order, _ = resolve_contact_order(candidate, farm_client=api, captured_at=CAPTURED_AT)
                self.assertEqual(order["origem_pedido"], "FARMALIDER_CLIENTE_ULTIMO_PEDIDO")
                self.assertEqual(order["pedido_id"], "123")
                self.assertEqual(order["status_confirmacao"], "CONFIRMADO_API")
                api.get_cliente_by_cpf.assert_called_once_with(SYNTHETIC_CPF)
                api.get_pedido.assert_called_once_with("123")

    def test_empty_raw_uses_latest_api_order_instead_of_another_structured_snapshot(self):
        snapshot = json.loads(raw_order())
        snapshot.update(
            pedido_id="124", data_hora="2026-10-05T10:30:00",
            status_confirmacao="CANCELADO_API", farmalider_status_pedido=3,
            farmalider_status_pedido_nome="Cancelado", origem_pedido="WENI_PEDIDO_FIELDS",
        )
        snapshot["produtos"][0]["nome"] = "Nome antigo de outro pedido"
        candidate = contact(raw="")
        candidate["fields"].update({
            "pedido_id": "124", "pedido_data": snapshot["data_hora"],
            "pedido_valor": snapshot["valor_total_compra"], "pedido_quantidade_itens": "1",
            "pedido_produtos": json.dumps(snapshot),
        })
        api = client()
        order, items = resolve_contact_order(candidate, farm_client=api, captured_at=CAPTURED_AT)
        self.assertEqual(order["pedido_id"], "123")
        self.assertEqual(order["origem_pedido"], "FARMALIDER_CLIENTE_ULTIMO_PEDIDO")
        self.assertEqual(order["status_confirmacao"], "CONFIRMADO_API")
        self.assertEqual(order["farmalider_status_pedido"], "1")
        self.assertEqual(order["data_hora"], "2026-10-06T10:30:00-03:00")
        self.assertFalse(is_order_cancelled(order))
        self.assertEqual(items[0]["produto_codigo"], "9001")
        self.assertEqual(items[0]["produto_nome"], "")
        api.get_cliente_by_cpf.assert_called_once_with(SYNTHETIC_CPF)
        api.get_pedido.assert_called_once_with("123")

    def test_wrapped_nonempty_weni_remains_the_priority_order(self):
        api = client()
        order, _ = resolve_contact_order(
            contact(raw={"value": "{not-json"}), farm_client=api, captured_at=CAPTURED_AT,
        )
        self.assertEqual(order["status_validacao"], "ERRO")
        self.assertEqual(order["ultimo_pedido_raw"], "{not-json")
        api.get_cliente_by_cpf.assert_not_called()
        api.get_pedido.assert_not_called()

    def test_structured_newer_order_does_not_replace_priority_raw_order(self):
        candidate = contact(raw=raw_order())
        snapshot = json.loads(raw_order())
        snapshot.update(
            pedido_id="124", data_hora="2026-10-06T11:30:00",
            status_confirmacao="CONFIRMADO_API", farmalider_status_pedido=2,
        )
        snapshot["produtos"][0]["nome"] = "Produto de outro pedido"
        candidate["fields"].update({
            "pedido_id": snapshot["pedido_id"], "pedido_data": snapshot["data_hora"],
            "pedido_valor": snapshot["valor_total_compra"], "pedido_quantidade_itens": "1",
            "pedido_produtos": json.dumps(snapshot),
        })
        order, items = parse_ultimo_pedido(candidate, captured_at=CAPTURED_AT)
        self.assertEqual(order["pedido_id"], "123")
        self.assertEqual(order["ultimo_pedido_raw"], raw_order())
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")

    def test_structured_snapshot_does_not_hide_invalid_priority_raw(self):
        candidate = contact(raw="{not-json")
        snapshot = json.loads(raw_order())
        snapshot.update(status_confirmacao="CONFIRMADO_API", farmalider_status_pedido=2)
        candidate["fields"].update({
            "pedido_id": "123", "pedido_data": snapshot["data_hora"],
            "pedido_valor": snapshot["valor_total_compra"], "pedido_quantidade_itens": "1",
            "pedido_produtos": json.dumps(snapshot),
        })
        api = client()
        order, items = resolve_contact_order(candidate, farm_client=api, captured_at=CAPTURED_AT)
        self.assertEqual(order["status_validacao"], "ERRO")
        self.assertEqual(order["ultimo_pedido_raw"], "{not-json")
        self.assertEqual(items, [])
        api.get_cliente_by_cpf.assert_not_called()
        api.get_pedido.assert_not_called()

    def test_structured_snapshot_does_not_supply_missing_identity_for_priority_raw(self):
        original = json.loads(raw_order())
        del original["pedido_id"]
        raw = json.dumps(original)
        candidate = contact(raw=raw)
        snapshot = json.loads(raw_order())
        snapshot.update(status_confirmacao="CONFIRMADO_API", farmalider_status_pedido=2)
        candidate["fields"].update({
            "pedido_id": "123", "pedido_data": snapshot["data_hora"],
            "pedido_valor": snapshot["valor_total_compra"], "pedido_quantidade_itens": "1",
            "pedido_produtos": json.dumps(snapshot),
        })
        api = client()
        order, items = resolve_contact_order(candidate, farm_client=api, captured_at=CAPTURED_AT)
        self.assertEqual(order["pedido_id"], "")
        self.assertEqual(order["ultimo_pedido_raw"], raw)
        self.assertEqual(order["status_confirmacao"], "NAO_CONFIRMADO_SEM_PEDIDO_ID")
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")
        api.get_cliente_by_cpf.assert_not_called()
        api.get_pedido.assert_not_called()

    def test_matching_snapshot_can_retain_cancellation_protection_for_priority_order(self):
        candidate = contact(raw=raw_order())
        snapshot = json.loads(raw_order())
        snapshot.update(
            status_confirmacao="CANCELADO_API", farmalider_status_pedido=3,
            farmalider_status_pedido_nome="Cancelado",
        )
        candidate["fields"].update({
            "pedido_id": "123", "pedido_data": snapshot["data_hora"],
            "pedido_valor": snapshot["valor_total_compra"], "pedido_quantidade_itens": "1",
            "pedido_produtos": json.dumps(snapshot),
        })
        order, items = parse_ultimo_pedido(candidate, captured_at=CAPTURED_AT)
        self.assertEqual(order["pedido_id"], "123")
        self.assertEqual(order["ultimo_pedido_raw"], raw_order())
        self.assertTrue(is_order_cancelled(order))
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")

    def test_path_one_uses_weni_without_any_api_requests(self):
        for raw in (raw_order(), {"value": raw_order()}):
            with self.subTest(wrapped=isinstance(raw, dict)):
                api = client()
                order, items = resolve_contact_order(contact(raw=raw), farm_client=api, captured_at=CAPTURED_AT)
                self.assertEqual(order["status_confirmacao"], "NAO_CONFIRMADO_API")
                self.assertEqual(order["origem_pedido"], "WENI_ULTIMO_PEDIDO")
                self.assertEqual(order["pedido_id"], "123")
                self.assertEqual(order["valor_total_compra"], "48.89")
                self.assertEqual(items[0]["produto_nome"], "Produto sintético")
                api.get_cliente_by_cpf.assert_not_called()
                api.get_pedido.assert_not_called()

    def test_api_reconciliation_preserves_weni_name_only_with_matching_code(self):
        order, items = confirm_weni_fixture(raw_order())
        self.assertEqual(order["status_confirmacao"], "CONFIRMADO_API")
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")
        self.assertEqual(order["origem_pedido"], "WENI_ULTIMO_PEDIDO+FARMALIDER_API")

    def test_text_in_codproduto_is_the_official_name_without_an_invented_code(self):
        pedido = pedido_payload()
        pedido["itens"][0]["codProduto"] = "  Produto Novo 750 mg  "
        order, items = resolve_contact_order(contact(), farm_client=client(pedido=pedido), captured_at=CAPTURED_AT)
        self.assertEqual(order["status_validacao"], "OK")
        self.assertEqual(items[0]["produto_nome"], "Produto Novo 750 mg")
        self.assertEqual(items[0]["produto_codigo"], "")
        self.assertEqual(items[0]["quantidade"], "1")
        self.assertEqual(items[0]["valor_unitario"], "38.90")
        self.assertEqual(items[0]["valor_total"], "38.90")
        product = json.loads(serialize_pedido_products(order, items))["produtos"][0]
        self.assertEqual(product["nome"], "Produto Novo 750 mg")
        self.assertIsNone(product["codigo"])

    def test_official_name_replaces_stale_weni_name(self):
        pedido = pedido_payload()
        pedido["itens"][0]["codProduto"] = "Descrição Atualizada"
        _, items = confirm_weni_fixture(raw_order(), pedido=pedido)
        self.assertEqual(items[0]["produto_nome"], "Descrição Atualizada")
        self.assertEqual(items[0]["produto_codigo"], "")

    def test_single_word_and_alphanumeric_product_names_follow_the_new_contract(self):
        for name in ("Paracetamol", "B12", "Produto-500mg"):
            with self.subTest(name=name):
                pedido = pedido_payload()
                pedido["itens"][0]["codProduto"] = name
                _, items = resolve_contact_order(contact(), farm_client=client(pedido=pedido), captured_at=CAPTURED_AT)
                self.assertEqual(items[0]["produto_nome"], name)
                self.assertEqual(items[0]["produto_codigo"], "")

    def test_numeric_codproduto_remains_a_legacy_code(self):
        for code in (9001, "9001", " 9001 ", "009001"):
            with self.subTest(code=code):
                pedido = pedido_payload()
                pedido["itens"][0]["codProduto"] = code
                _, items = resolve_contact_order(contact(), farm_client=client(pedido=pedido), captured_at=CAPTURED_AT)
                self.assertEqual(items[0]["produto_codigo"], str(code).strip())
                self.assertEqual(items[0]["produto_nome"], "")

    def test_legacy_numeric_code_with_explicit_name_preserves_both(self):
        for field in ("nome", "descricao"):
            with self.subTest(field=field):
                pedido = pedido_payload()
                pedido["itens"][0].update(codProduto=9001, **{field: "Produto com nome"})
                _, items = confirm_weni_fixture(raw_order(), pedido=pedido)
                self.assertEqual(items[0]["produto_nome"], "Produto com nome")
                self.assertEqual(items[0]["produto_codigo"], "9001")

    def test_invalid_product_name_types_do_not_become_descriptions(self):
        for field in ("codProduto", "nome", "descricao"):
            for value in (True, False, [], {"nome": "Texto"}, 9001.5):
                with self.subTest(field=field, value=value):
                    pedido = pedido_payload()
                    pedido["itens"][0][field] = value
                    order, _ = resolve_contact_order(contact(), farm_client=client(pedido=pedido), captured_at=CAPTURED_AT)
                    self.assertEqual(order["status_validacao"], "ERRO")

    def test_empty_product_name_without_any_identity_is_rejected(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                pedido = pedido_payload()
                pedido["itens"][0]["codProduto"] = value
                order, _ = resolve_contact_order(contact(), farm_client=client(pedido=pedido), captured_at=CAPTURED_AT)
                self.assertEqual(order["status_validacao"], "ERRO")

    def test_new_name_snapshot_is_stable_when_resolved_again(self):
        pedido = pedido_payload()
        pedido["itens"][0]["codProduto"] = "Produto Novo 750 mg"
        candidate = contact()
        api = client(pedido=pedido)
        order, items = resolve_contact_order(candidate, farm_client=api, captured_at=CAPTURED_AT)
        serialized = serialize_pedido_products(order, items)
        candidate["fields"].update({
            "pedido_id": order["pedido_id"], "pedido_data": order["data_hora"],
            "pedido_valor": order["valor_total_compra"], "pedido_quantidade_itens": order["quantidade_itens"],
            "pedido_produtos": serialized,
        })
        repeated, repeated_items = resolve_contact_order(candidate, farm_client=api, captured_at="2026-10-07T18:00:00Z")
        self.assertEqual(serialize_pedido_products(repeated, repeated_items), serialized)
        self.assertEqual(repeated_items[0]["item_chave"], items[0]["item_chave"])

    def test_raw_without_api_is_auditable_but_never_api_confirmed(self):
        payload = json.loads(raw_order())
        payload["status_confirmacao"] = "CONFIRMADO_API"
        order, items = resolve_contact_order(contact(raw=json.dumps(payload)), farm_client=None, captured_at=CAPTURED_AT)
        self.assertEqual(order["status_confirmacao"], "NAO_CONFIRMADO_API")
        self.assertEqual(order["valor_origem"], "WENI")
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")

    def test_weni_client_hint_without_cpf_cannot_confirm_a_purchase(self):
        candidate = contact(raw=raw_order(), cpf=None)
        candidate["fields"]["id_do_cliente"] = "99"
        api = client()
        order, _ = resolve_contact_order(candidate, farm_client=api, captured_at=CAPTURED_AT, linked_cliente_id="99")
        self.assertEqual(order["status_confirmacao"], "NAO_CONFIRMADO_API")
        api.get_cliente_by_cpf.assert_not_called()
        api.get_pedido.assert_not_called()

    def test_cancelled_order_remains_auditable_but_not_a_sale(self):
        pedido = pedido_payload()
        pedido["capa"]["cancelamento"] = "2026-10-06T11:00:00"
        order, items = resolve_contact_order(contact(), farm_client=client(pedido=pedido), captured_at=CAPTURED_AT)
        self.assertEqual(order["status_confirmacao"], "CANCELADO_API")
        self.assertEqual(order["status_validacao"], "OK")
        self.assertEqual(order["valor_total_compra"], "48.89")
        self.assertTrue(is_order_cancelled(order))
        self.assertEqual(build_sales_metrics([order], items), [])

    def test_documented_cancelled_code_is_cancelled_without_a_timestamp(self):
        pedido = pedido_payload()
        pedido["capa"]["status"] = 3
        order, items = resolve_contact_order(contact(), farm_client=client(pedido=pedido), captured_at=CAPTURED_AT)
        self.assertEqual(order["farmalider_status_pedido"], "3")
        self.assertEqual(order["farmalider_status_pedido_nome"], "Cancelado")
        self.assertEqual(order["farmalider_cancelamento"], "")
        self.assertEqual(order["status_confirmacao"], "CANCELADO_API")
        self.assertEqual(build_sales_metrics([order], items), [])
        snapshot = json.loads(serialize_pedido_products(order, items))
        self.assertEqual(snapshot["farmalider_status_pedido_nome"], "Cancelado")

    def test_documented_status_names_and_unknown_codes(self):
        expected = {
            0: "Em processamento", 1: "Em trânsito", 2: "Concluído",
            3: "Cancelado", 4: "Pronto para rota",
        }
        for value, name in expected.items():
            with self.subTest(value=value):
                self.assertEqual(farmalider_order_status_name(value), name)
                self.assertEqual(farmalider_order_status_name(str(value)), name)
        for value in (None, True, False, 3.0, float("nan"), float("inf"), -1, 5, 9, "3.0", "Cancelado", [], {}, "1" * 5000):
            with self.subTest(value_type=type(value).__name__):
                self.assertEqual(farmalider_order_status_name(value), "")

    def test_unknown_status_preserves_code_without_an_invented_name(self):
        pedido = pedido_payload()
        pedido["capa"]["status"] = 9
        order, _ = resolve_contact_order(contact(), farm_client=client(pedido=pedido), captured_at=CAPTURED_AT)
        self.assertEqual(order["farmalider_status_pedido"], "9")
        self.assertEqual(order["farmalider_status_pedido_nome"], "")
        self.assertFalse(is_order_cancelled(order))

    def test_only_documented_completed_code_is_a_completed_purchase(self):
        for value in (2, "2", "02"):
            self.assertTrue(is_order_completed({"farmalider_status_pedido": value}))
        for value in (None, "", 0, 1, 3, 4, 9, "0", "1", "3", "4", "9", True, False, 2.0, float("nan"), float("inf")):
            with self.subTest(value_type=type(value).__name__, value=value):
                self.assertFalse(is_order_completed({"farmalider_status_pedido": value, "status_confirmacao": "CONFIRMADO_API"}))

    def test_completed_code_is_overridden_by_cancellation_evidence(self):
        self.assertFalse(is_order_completed({"farmalider_status_pedido": 2, "farmalider_cancelamento": "2026-10-06T11:00:00"}))
        self.assertFalse(is_order_completed({"farmalider_status_pedido": 2, "status_confirmacao": "CANCELADO_API"}))
        self.assertTrue(is_order_completed({"farmalider_status_pedido": 2, "farmalider_cancelamento": "false"}))

    def test_completed_enum_text_in_status_field_is_supported(self):
        for value in ("Concluído", "concluido", " CONCLUÍDO "):
            self.assertTrue(is_order_completed({"farmalider_status_pedido": value}))
        for value in ("Pedido concluído", "Concluído parcialmente", "Pronto para rota"):
            self.assertFalse(is_order_completed({"farmalider_status_pedido": value}))

    def test_completed_display_name_cannot_override_a_conflicting_code(self):
        for value in (0, 1, 3, 4, 9, None, ""):
            self.assertFalse(is_order_completed({"farmalider_status_pedido": value, "farmalider_status_pedido_nome": "Concluído"}))

    def test_fresh_active_api_does_not_inherit_old_cancelled_confirmation(self):
        cancelled = pedido_payload()
        cancelled["capa"]["cancelamento"] = "2026-10-06T11:00:00"
        old_order, old_items = resolve_contact_order(contact(), farm_client=client(pedido=cancelled), captured_at=CAPTURED_AT)
        canonical_contact = structured_snapshot_contact(old_order, old_items)
        order, _ = resolve_contact_order(canonical_contact, farm_client=client(), captured_at=CAPTURED_AT)
        self.assertEqual(order["status_confirmacao"], "CONFIRMADO_API")
        self.assertFalse(is_order_cancelled(order))

    def test_cancelled_snapshot_without_api_retains_cancel_audit_without_confirmation(self):
        cancelled = pedido_payload()
        cancelled["capa"]["cancelamento"] = "2026-10-06T11:00:00"
        old_order, old_items = resolve_contact_order(contact(), farm_client=client(pedido=cancelled), captured_at=CAPTURED_AT)
        canonical_contact = contact(raw=serialize_pedido_products(old_order, old_items))
        order, _ = resolve_contact_order(canonical_contact, farm_client=None, captured_at=CAPTURED_AT)
        self.assertEqual(order["status_confirmacao"], "NAO_CONFIRMADO_API")
        self.assertTrue(is_order_cancelled(order))

    def test_missing_freight_is_partial_and_excluded_from_sales(self):
        pedido = pedido_payload()
        del pedido["capa"]["frete"]
        order, items = resolve_contact_order(contact(), farm_client=client(pedido=pedido), captured_at=CAPTURED_AT)
        self.assertEqual(order["valor_total_compra"], "38.90")
        self.assertEqual(order["valor_origem"], "SOMA_ITENS_API")
        self.assertEqual(order["status_validacao"], "ATENCAO_TOTAL_PARCIAL")
        self.assertEqual(build_sales_metrics([order], items), [])

    def test_explicit_total_precedes_items_plus_freight(self):
        pedido = pedido_payload()
        pedido["capa"]["valorTotal"] = "50.00"
        order, _ = resolve_contact_order(contact(), farm_client=client(pedido=pedido), captured_at=CAPTURED_AT)
        self.assertEqual(order["valor_total_compra"], "50.00")
        self.assertEqual(order["valor_origem"], "TOTAL_GERAL_API")
        self.assertEqual(order["total_api"], "50.00")

    def test_weni_api_value_difference_is_preserved_in_audit(self):
        payload = json.loads(raw_order())
        payload["valor_total_compra"] = "38.90"
        order, _ = confirm_weni_fixture(json.dumps(payload))
        self.assertEqual(order["valor_total_compra"], "48.89")
        self.assertEqual(order["valor_total_weni"], "38.90")
        self.assertEqual(order["diferenca_total_weni_api"], "-9.99")
        self.assertEqual(order["status_validacao"], "ATENÇÃO_TOTAL_DIVERGENTE")

    def test_api_rerun_preserves_original_weni_difference_and_json(self):
        payload = json.loads(raw_order())
        payload["valor_total_compra"] = "38.90"
        order, items = confirm_weni_fixture(json.dumps(payload))
        old_serialized = serialize_pedido_products(order, items)
        current, current_items = confirm_weni_fixture(old_serialized, captured_at="2026-10-07T18:00:00Z")
        self.assertEqual(current["valor_total_weni"], "38.90")
        self.assertEqual(current["diferenca_total_weni_api"], "-9.99")
        self.assertEqual(serialize_pedido_products(current, current_items), old_serialized)

    def test_invalid_cpf_does_not_call_any_api(self):
        api = client()
        order, _ = resolve_contact_order(contact(cpf="11111111111"), farm_client=api, captured_at=CAPTURED_AT)
        self.assertEqual(order["status_validacao"], "ERRO")
        api.get_cliente_by_cpf.assert_not_called()
        api.get_pedido.assert_not_called()

    def test_cpf_and_cached_link_disagreement_does_not_query_order(self):
        api = client()
        order, _ = resolve_contact_order(contact(), farm_client=api, linked_cliente_id="100", captured_at=CAPTURED_AT)
        self.assertEqual(order["status_confirmacao"], "CLIENTE_ID_DIVERGENTE_API")
        api.get_pedido.assert_not_called()

    def test_mismatched_cliente_cpf_does_not_query_order(self):
        cliente = cliente_payload()
        cliente["cliente"]["cpf"] = "16899535009"
        api = client(cliente=cliente)
        order, _ = resolve_contact_order(contact(), farm_client=api, captured_at=CAPTURED_AT)
        self.assertEqual(order["status_confirmacao"], "CPF_DIVERGENTE_API")
        api.get_pedido.assert_not_called()

    def test_missing_latest_order_produces_diagnostic(self):
        cliente = cliente_payload()
        del cliente["ultimoPedido"]
        api = client(cliente=cliente)
        order, _ = resolve_contact_order(contact(), farm_client=api, captured_at=CAPTURED_AT)
        self.assertEqual(order["status_confirmacao"], "ULTIMO_PEDIDO_NAO_INFORMADO_API")
        api.get_pedido.assert_not_called()

    def test_not_found_order_produces_diagnostic(self):
        api = client()
        api.get_pedido.return_value = None
        order, _ = resolve_contact_order(contact(), farm_client=api, captured_at=CAPTURED_AT)
        self.assertEqual(order["status_confirmacao"], "PEDIDO_NAO_ENCONTRADO_API")
        self.assertEqual(order["status_validacao"], "ERRO")

    def test_client_api_failure_preserves_diagnostic_without_contact_data_in_error(self):
        api = client()
        api.get_cliente_by_cpf.side_effect = FarmaliderError("Synthetic API failure")
        order, _ = resolve_contact_order(contact(), farm_client=api, captured_at=CAPTURED_AT)
        self.assertEqual(order["status_confirmacao"], "ERRO_API")
        self.assertEqual(order["ultimo_pedido_raw"], "")
        self.assertNotIn(SYNTHETIC_CPF, order["farmalider_erro"])

    def test_order_api_failure_preserves_diagnostic(self):
        api = client()
        api.get_pedido.side_effect = FarmaliderError("Synthetic API failure")
        order, _ = resolve_contact_order(contact(), farm_client=api, captured_at=CAPTURED_AT)
        self.assertEqual(order["status_confirmacao"], "ERRO_API")
        self.assertEqual(order["status_validacao"], "ERRO")

    def test_authentication_failure_propagates_to_stop_the_batch(self):
        api = client()
        api.get_cliente_by_cpf.side_effect = FarmaliderAuthError("Synthetic auth failure")
        with self.assertRaises(FarmaliderAuthError):
            resolve_contact_order(contact(), farm_client=api, captured_at=CAPTURED_AT)

    def test_required_ids_reject_missing_float_bool_and_other_owner(self):
        for key, value in (("id", None), ("id", True), ("id", 123.0), ("id", "0"), ("id", 124), ("codCliente", None), ("codCliente", True), ("codCliente", 100)):
            with self.subTest(key=key, value=value):
                pedido = pedido_payload()
                pedido["capa"][key] = value
                order, _ = resolve_contact_order(contact(), farm_client=client(pedido=pedido), captured_at=CAPTURED_AT)
                self.assertEqual(order["status_validacao"], "ERRO")

    def test_item_order_identity_cannot_differ(self):
        pedido = pedido_payload()
        pedido["itens"][0]["codPedido"] = 124
        order, _ = resolve_contact_order(contact(), farm_client=client(pedido=pedido), captured_at=CAPTURED_AT)
        self.assertEqual(order["status_confirmacao"], "ITEM_PEDIDO_DIVERGENTE_API")

    def test_invalid_financial_items_cannot_become_zero_sales(self):
        for key, value in (("quantidade", 0), ("quantidade", -1), ("quantidade", True), ("quantidade", "NaN"), ("valor", "Infinity"), ("valor", -1), ("total", None)):
            with self.subTest(key=key, value=value):
                pedido = pedido_payload()
                pedido["itens"][0][key] = value
                order, _ = resolve_contact_order(contact(), farm_client=client(pedido=pedido), captured_at=CAPTURED_AT)
                self.assertEqual(order["status_validacao"], "ERRO")

    def test_fractional_units_and_decimal_values_are_exact(self):
        pedido = pedido_payload()
        pedido["capa"]["frete"] = 0
        pedido["itens"][0].update(quantidade="1.5", valor="0.20", total="0.30")
        order, items = resolve_contact_order(contact(), farm_client=client(pedido=pedido), captured_at=CAPTURED_AT)
        self.assertEqual(order["quantidade_itens_api"], "1.5")
        self.assertEqual(order["valor_total_compra"], "0.30")
        self.assertEqual(items[0]["valor_unitario"], "0.20")

    def test_name_cannot_be_copied_by_position(self):
        payload = json.loads(raw_order())
        payload["produtos"][0]["codigo"] = "OTHER"
        order, items = confirm_weni_fixture(json.dumps(payload))
        self.assertEqual(items[0]["produto_codigo"], "9001")
        self.assertEqual(items[0]["produto_nome"], "")

    def test_ambiguous_financial_match_does_not_assign_a_name(self):
        payload = json.loads(raw_order())
        product = payload["produtos"][0]
        del product["codigo"]
        payload["produtos"].append(dict(product, nome="Outro produto"))
        payload["valor_total_compra"] = "77.80"
        _, items = confirm_weni_fixture(json.dumps(payload))
        self.assertEqual(items[0]["produto_nome"], "")

    def test_one_weni_line_matching_two_api_codes_is_not_unique(self):
        payload = json.loads(raw_order())
        del payload["produtos"][0]["codigo"]
        pedido = pedido_payload()
        pedido["itens"].append(dict(pedido["itens"][0], codProduto="9002"))
        _, items = confirm_weni_fixture(json.dumps(payload), pedido=pedido)
        self.assertEqual([item["produto_nome"] for item in items], ["", ""])

    def test_serialized_snapshot_is_deterministic_and_contains_no_contact_pii(self):
        order, items = resolve_contact_order(contact(), farm_client=client(), captured_at=CAPTURED_AT)
        serialized = serialize_pedido_products(order, items)
        order["capturado_em"] = "2026-10-07T18:00:00Z"
        order["farmalider_confirmado_em"] = "2026-10-07T18:00:00Z"
        self.assertEqual(serialized, serialize_pedido_products(order, items))
        self.assertNotIn(SYNTHETIC_CPF, serialized)
        self.assertNotIn("synthetic-contact", serialized)
        parsed = json.loads(serialized)
        self.assertIsNone(parsed["produtos"][0]["nome"])
        self.assertEqual(parsed["produtos"][0]["codigo"], "9001")
        self.assertEqual(parsed["valor_total_compra"], "48.89")
        self.assertEqual(parsed["farmalider_frete"], "9.99")

    def test_timezone_preserves_local_dates_and_converts_explicit_offsets(self):
        self.assertEqual(business_order_datetime("2026-10-06T00:30:00").isoformat(), "2026-10-06T00:30:00-03:00")
        self.assertEqual(business_order_datetime("2026-10-06T00:30:00Z").isoformat(), "2026-10-05T21:30:00-03:00")
        self.assertIsNone(business_order_datetime("not-a-date"))

    def test_cancellation_false_sentinels_and_unknown_status_codes(self):
        for value in (None, "", 0, False, "false", "null", "none", "nao", "não"):
            self.assertFalse(is_order_cancelled({"farmalider_cancelamento": value, "farmalider_status_pedido": 9}))
        self.assertTrue(is_order_cancelled({"farmalider_status_pedido": 3}))
        self.assertTrue(is_order_cancelled({"farmalider_status_pedido": "3"}))
        self.assertTrue(is_order_cancelled({"farmalider_status_pedido": "Cancelado"}))
        self.assertTrue(is_order_cancelled({"farmalider_cancelamento": "2026-10-06T11:00:00"}))


if __name__ == "__main__":
    unittest.main()
