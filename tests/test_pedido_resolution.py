"""Synthetic tests for FarmaLíder-first order resolution."""

import json
import unittest
from unittest.mock import Mock

from analytics import build_sales_metrics, parse_ultimo_pedido
from farmalider_client import FarmaliderAuthError, FarmaliderError
from farmalider_integration import (
    apply_pedido_api_confirmation,
    cliente_link_status,
    resolve_contact_order,
)
from pedido_utils import (
    business_order_datetime,
    effective_order_status_code,
    farmalider_order_status_name,
    farmalider_payment_method_display,
    farmalider_payment_method_name,
    is_order_cancelled,
    is_order_completed,
    is_order_made,
    weni_order_datetime_text,
)

CAPTURED_AT = "2026-10-06T18:00:00Z"
SYNTHETIC_CPF = "52998224725"


def item(
    *,
    pedido=123,
    code="9001",
    description="Produto sintético",
    quantity=1,
    value="38.90",
    total="38.90",
):
    return {
        "codPedido": pedido,
        "codProduto": code,
        "descricao": description,
        "quantidade": quantity,
        "valor": value,
        "total": total,
    }


def cliente_payload():
    return {
        "cliente": {
            "id": 99,
            "cpf": SYNTHETIC_CPF,
            "nome": "Cliente sintético",
        },
        "ultimoPedido": {
            "id": 123,
            "codCliente": 99,
            "emissao": "2026-10-06T10:30:00",
            "cancelamento": None,
            "status": 1,
            "formaPagamento": 2,
            "frete": "9.99",
        },
        "itens": [item()],
    }


def pedido_payload():
    return {
        "capa": {
            "id": 123,
            "codCliente": 99,
            "emissao": "2026-10-06T10:30:00",
            "cancelamento": None,
            "status": 1,
            "formaPagamento": 2,
            "frete": "9.99",
        },
        "itens": [item()],
    }


def legacy_raw():
    return json.dumps(
        {
            "pedido_id": "777",
            "data_hora": "2026-10-01T10:00:00-03:00",
            "valor_total_compra": "10.00",
            "produtos": [
                {
                    "nome": "Pedido legado",
                    "quantidade": 1,
                    "valor_unitario": "10.00",
                    "valor_total": "10.00",
                }
            ],
        }
    )


def contact(*, cpf=SYNTHETIC_CPF, raw=None, pedido_id=None):
    fields = {}
    if cpf is not None:
        fields["cpf"] = cpf
    if pedido_id is not None:
        fields["pedido_id"] = pedido_id
    if raw is not None:
        fields["ultimo_pedido"] = raw
    return {"uuid": "synthetic-contact", "fields": fields}


def client(*, cliente=None, pedido=None):
    api = Mock()
    api.get_cliente_by_cpf.return_value = (
        cliente_payload() if cliente is None else cliente
    )
    api.get_pedido.return_value = pedido_payload() if pedido is None else pedido
    return api


class PedidoResolutionTests(unittest.TestCase):
    def test_cliente_envelope_validates_identity(self):
        self.assertEqual(
            cliente_link_status(SYNTHETIC_CPF, cliente_payload()),
            ("CPF_CONFIRMADO", "99", "Cliente sintético"),
        )

    def test_cliente_rejects_divergent_cpf(self):
        payload = cliente_payload()
        payload["cliente"]["cpf"] = "16899535009"
        self.assertEqual(
            cliente_link_status(SYNTHETIC_CPF, payload)[0],
            "CPF_DIVERGENTE_API",
        )

    def test_api_first_ignores_legacy_weni_order(self):
        api = client()
        order, items = resolve_contact_order(
            contact(raw=legacy_raw()),
            farm_client=api,
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(order["pedido_id"], "123")
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")
        api.get_cliente_by_cpf.assert_called_once_with(SYNTHETIC_CPF)
        api.get_pedido.assert_called_once_with("123")

    def test_cliente_get_is_complete_fallback_if_pedido_get_not_found(self):
        api = client()
        api.get_pedido.return_value = None
        order, items = resolve_contact_order(
            contact(), farm_client=api, captured_at=CAPTURED_AT
        )
        self.assertEqual(order["pedido_id"], "123")
        self.assertEqual(order["origem_pedido"], "FARMALIDER_CLIENTE_CPF")
        self.assertEqual(order["status_validacao"], "OK")
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")

    def test_pedido_id_locator_is_used_when_cpf_get_fails(self):
        api = client()
        api.get_cliente_by_cpf.side_effect = FarmaliderError("offline")
        order, items = resolve_contact_order(
            contact(pedido_id="123", raw=legacy_raw()),
            farm_client=api,
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(order["pedido_id"], "123")
        self.assertEqual(order["origem_pedido"], "FARMALIDER_PEDIDO_ID_WENI")
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")
        api.get_pedido.assert_called_once_with("123")

    def test_ultimo_pedido_is_last_locator_when_pedido_id_is_missing(self):
        api = client()
        api.get_cliente_by_cpf.side_effect = FarmaliderError("offline")
        fallback = pedido_payload()
        fallback["capa"]["id"] = 777
        fallback["itens"][0]["codPedido"] = 777
        api.get_pedido.return_value = fallback
        order, items = resolve_contact_order(
            contact(raw=legacy_raw()),
            farm_client=api,
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(order["pedido_id"], "777")
        self.assertEqual(order["origem_pedido"], "FARMALIDER_ULTIMO_PEDIDO_LOCATOR")
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")
        api.get_pedido.assert_called_once_with("777")

    def test_pedido_id_has_precedence_over_ultimo_pedido_locator(self):
        api = client()
        api.get_cliente_by_cpf.side_effect = FarmaliderError("offline")
        order, _ = resolve_contact_order(
            contact(pedido_id="123", raw=legacy_raw()),
            farm_client=api,
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(order["pedido_id"], "123")
        api.get_pedido.assert_called_once_with("123")

    def test_ultimo_pedido_is_not_used_as_order_data_without_api(self):
        order, items = resolve_contact_order(
            contact(raw=legacy_raw()),
            farm_client=None,
            captured_at=CAPTURED_AT,
        )
        self.assertIsNone(order)
        self.assertEqual(items, [])

    def test_pedido_get_is_preferred_over_cliente_snapshot(self):
        cliente = cliente_payload()
        cliente["itens"][0]["descricao"] = "Descrição antiga"
        pedido = pedido_payload()
        pedido["itens"][0]["descricao"] = "Descrição atual"
        pedido["capa"]["status"] = 2
        pedido["capa"]["formaPagamento"] = 3
        order, items = resolve_contact_order(
            contact(),
            farm_client=client(cliente=cliente, pedido=pedido),
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(order["origem_pedido"], "FARMALIDER_PEDIDO_API")
        self.assertEqual(items[0]["produto_nome"], "Descrição atual")
        self.assertEqual(order["farmalider_status_pedido"], "2")
        self.assertEqual(order["farmalider_forma_pagamento"], "3")
        self.assertEqual(order["farmalider_forma_pagamento_nome"], "Crédito")

    def test_descricao_is_required_for_product_name(self):
        pedido = pedido_payload()
        del pedido["itens"][0]["descricao"]
        cliente = cliente_payload()
        del cliente["itens"][0]["descricao"]
        order, items = resolve_contact_order(
            contact(),
            farm_client=client(cliente=cliente, pedido=pedido),
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(order["status_validacao"], "ERRO")
        self.assertEqual(items, [])

    def test_codproduto_never_replaces_missing_descricao(self):
        pedido = pedido_payload()
        pedido["itens"][0]["codProduto"] = "NÃO É NOME"
        pedido["itens"][0]["descricao"] = "Nome oficial"
        _, items = resolve_contact_order(
            contact(),
            farm_client=client(pedido=pedido),
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(items[0]["produto_nome"], "Nome oficial")
        self.assertEqual(items[0]["produto_codigo"], "NÃO É NOME")

    def test_total_is_sum_of_item_totals_and_excludes_freight(self):
        pedido = pedido_payload()
        pedido["capa"]["frete"] = "20.00"
        pedido["itens"].append(
            item(
                code="9002",
                description="Produto B",
                value="10.00",
                total="20.00",
                quantity=2,
            )
        )
        order, items = resolve_contact_order(
            contact(),
            farm_client=client(pedido=pedido),
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(order["valor_total_compra"], "58.90")
        self.assertEqual(order["valor_total_api_itens"], "58.90")
        self.assertEqual(order["farmalider_frete"], "20.00")
        self.assertEqual(order["valor_total_faturamento"], "78.90")
        self.assertEqual(order["valor_origem"], "SOMA_ITENS_API")
        self.assertEqual(len(items), 2)

    def test_explicit_capa_total_does_not_override_weni_order_total_contract(self):
        pedido = pedido_payload()
        pedido["capa"]["valorTotal"] = "999.00"
        order, _ = resolve_contact_order(
            contact(),
            farm_client=client(pedido=pedido),
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(order["valor_total_compra"], "38.90")
        self.assertEqual(order["valor_total_faturamento"], "48.89")
        self.assertEqual(order["total_api"], "999.00")

    def test_fractional_quantities_remain_exact(self):
        pedido = pedido_payload()
        pedido["itens"][0].update(quantidade="1.5", valor="0.20", total="0.30")
        order, items = resolve_contact_order(
            contact(),
            farm_client=client(pedido=pedido),
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(order["quantidade_itens_api"], "1.5")
        self.assertEqual(order["valor_total_compra"], "0.30")
        self.assertEqual(items[0]["valor_unitario"], "0.20")

    def test_status_mapping_is_official(self):
        expected = {
            -2: "Em aberto",
            -1: "Pendente de pagamento",
            0: "Em processamento",
            1: "Em trânsito",
            2: "Concluído",
            3: "Cancelado",
            4: "Pronto para rota",
        }
        for code, label in expected.items():
            self.assertEqual(farmalider_order_status_name(code), label)
            self.assertEqual(farmalider_order_status_name(str(code)), label)

    def test_official_status_enum_names_survive_api_resolution(self):
        for name, code, label in (
            ("EmAberto", -2, "Em aberto"),
            ("PendenteDePagamento", -1, "Pendente de pagamento"),
            ("EmProcessamento", 0, "Em processamento"),
            ("ProntoParaRota", 4, "Pronto para rota"),
            ("EmTransito", 1, "Em trânsito"),
            ("Concluido", 2, "Concluído"),
            ("Cancelado", 3, "Cancelado"),
            ("PendentePagamento", -1, "Pendente de pagamento"),
        ):
            with self.subTest(name=name):
                pedido = pedido_payload()
                pedido["capa"]["status"] = name
                order, items = resolve_contact_order(
                    contact(),
                    farm_client=client(pedido=pedido),
                    captured_at=CAPTURED_AT,
                )
                self.assertEqual(order["status_validacao"], "OK")
                self.assertEqual(order["farmalider_status_pedido"], name)
                self.assertEqual(effective_order_status_code(order), str(code))
                self.assertEqual(order["farmalider_status_pedido_nome"], label)
                self.assertEqual(
                    bool(build_sales_metrics([order], items)),
                    code in (-2, -1, 0, 4, 1, 2),
                )

    def test_payment_mapping_is_official(self):
        expected = {
            0: "Cancelado",
            1: "Dinheiro",
            2: "Débito",
            3: "Crédito",
            4: "Ticket",
            5: "Pix por Link de Pagamento",
            6: "Pix no POS",
        }
        for code, label in expected.items():
            self.assertEqual(farmalider_payment_method_name(code), label)
            self.assertEqual(farmalider_payment_method_name(str(code)), label)
            self.assertEqual(farmalider_payment_method_display(code), label)
            self.assertEqual(farmalider_payment_method_display(str(code)), label)

    def test_payment_display_exposes_undocumented_nonnegative_int32_codes(self):
        for code in (9, 2147483647):
            for value in (code, str(code)):
                with self.subTest(value=value):
                    self.assertEqual(
                        farmalider_payment_method_display(value),
                        f"Não identificado (código {code})",
                    )
                    self.assertEqual(farmalider_payment_method_name(value), "")

    def test_payment_display_normalizes_numeric_strings(self):
        for value, expected in (
            (" 0002 ", "Débito"),
            ("0000", "Cancelado"),
            (" 0006 ", "Pix no POS"),
        ):
            with self.subTest(value=value):
                self.assertEqual(farmalider_payment_method_display(value), expected)

    def test_cancelled_payment_literal_is_recognized(self):
        for value in ("CANCELADO", "Cancelado", "cancelado"):
            with self.subTest(value=value):
                self.assertEqual(farmalider_payment_method_name(value), "Cancelado")
                self.assertEqual(farmalider_payment_method_display(value), "Cancelado")

    def test_payment_display_rejects_missing_and_invalid_codes(self):
        invalid = (
            None,
            "",
            " ",
            True,
            False,
            "Pix",
            "1.5",
            1.5,
            2.0,
            -1,
            "-1",
            2147483648,
            "2147483648",
            "9" * 100,
            "６",
            [],
            {},
        )
        for value in invalid:
            with self.subTest(value=value):
                self.assertEqual(farmalider_payment_method_display(value), "")

    def test_unknown_pedido_payment_overrides_documented_cliente_payment(self):
        for code in (9, 2147483647):
            with self.subTest(code=code):
                pedido = pedido_payload()
                pedido["capa"]["formaPagamento"] = code
                order, _ = resolve_contact_order(
                    contact(),
                    farm_client=client(pedido=pedido),
                    captured_at=CAPTURED_AT,
                )
                self.assertEqual(order["farmalider_forma_pagamento"], str(code))
                self.assertEqual(
                    order["farmalider_forma_pagamento_nome"],
                    f"Não identificado (código {code})",
                )

    def test_cliente_fallback_preserves_unknown_payment_code_and_display(self):
        cliente = cliente_payload()
        cliente["ultimoPedido"]["formaPagamento"] = 9
        api = client(cliente=cliente)
        api.get_pedido.return_value = None
        order, _ = resolve_contact_order(
            contact(), farm_client=api, captured_at=CAPTURED_AT
        )
        self.assertEqual(order["origem_pedido"], "FARMALIDER_CLIENTE_CPF")
        self.assertEqual(order["farmalider_forma_pagamento"], "9")
        self.assertEqual(
            order["farmalider_forma_pagamento_nome"],
            "Não identificado (código 9)",
        )

    def test_unknown_status_and_payment_have_no_invented_label(self):
        self.assertEqual(farmalider_order_status_name(9), "")
        self.assertEqual(farmalider_payment_method_name(9), "")

    def test_cancelled_status_is_auditable_but_not_sale(self):
        pedido = pedido_payload()
        pedido["capa"]["status"] = 3
        order, items = resolve_contact_order(
            contact(),
            farm_client=client(pedido=pedido),
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(order["status_confirmacao"], "CANCELADO_API")
        self.assertTrue(is_order_cancelled(order))
        self.assertEqual(build_sales_metrics([order], items), [])

    def test_configured_documented_states_are_sales(self):
        for status in (-2, -1, 0, 1, 2, 4):
            with self.subTest(status=status):
                pedido = pedido_payload()
                pedido["capa"]["status"] = status
                order, items = resolve_contact_order(
                    contact(),
                    farm_client=client(pedido=pedido),
                    captured_at=CAPTURED_AT,
                )
                self.assertEqual(is_order_made(order), status in (0, 1, 2, 4))
                self.assertEqual(is_order_completed(order), status == 2)
                self.assertFalse(is_order_cancelled(order))
                self.assertEqual(
                    len(build_sales_metrics([order], items)),
                    int(status in (-2, -1, 0, 4, 1, 2)),
                )

    def test_payment_zero_or_cancelled_literal_cancels_any_api_status(self):
        for status in (-2, -1, 0, 1, 2, 4):
            for payment in (0, "0", "CANCELADO"):
                with self.subTest(status=status, payment=payment):
                    pedido = pedido_payload()
                    pedido["capa"].update(status=status, formaPagamento=payment)
                    order, items = resolve_contact_order(
                        contact(),
                        farm_client=client(pedido=pedido),
                        captured_at=CAPTURED_AT,
                    )
                    self.assertEqual(order["farmalider_status_pedido"], str(status))
                    self.assertEqual(order["farmalider_forma_pagamento"], str(payment))
                    self.assertEqual(
                        order["farmalider_status_pedido_nome"], "Cancelado"
                    )
                    self.assertEqual(order["status_confirmacao"], "CANCELADO_API")
                    self.assertEqual(effective_order_status_code(order), "3")
                    self.assertTrue(is_order_cancelled(order))
                    self.assertFalse(is_order_completed(order))
                    self.assertFalse(is_order_made(order))
                    self.assertEqual(build_sales_metrics([order], items), [])

    def test_effective_order_status_normalizes_documented_codes(self):
        for status in (-2, -1, 0, 1, 2, 3, 4):
            for value in (status, str(status)):
                with self.subTest(value=value):
                    self.assertEqual(
                        effective_order_status_code(
                            {
                                "farmalider_status_pedido": value,
                                "farmalider_forma_pagamento": 6,
                            }
                        ),
                        str(status),
                    )

    def test_unknown_status_has_no_effective_code(self):
        for value in (5, "5", "Estado desconhecido"):
            with self.subTest(value=value):
                order = {"farmalider_status_pedido": value}
                self.assertEqual(farmalider_order_status_name(value), "")
                self.assertEqual(effective_order_status_code(order), "")
                self.assertFalse(is_order_made(order))
                self.assertFalse(is_order_completed(order))

    def test_api_enum_aliases_preserve_raw_values_and_effective_status(self):
        for payment, status_code, status_name, confirmation, payment_name in (
            (
                "PIX no POS",
                "-1",
                "Pendente de pagamento",
                "CONFIRMADO_API",
                "Pix no POS",
            ),
            ("_", "3", "Cancelado", "CANCELADO_API", "Cancelado"),
        ):
            with self.subTest(payment=payment):
                pedido = pedido_payload()
                pedido["capa"].update(
                    status="PendentePagamento", formaPagamento=payment
                )
                order, items = resolve_contact_order(
                    contact(),
                    farm_client=client(pedido=pedido),
                    captured_at=CAPTURED_AT,
                )
                self.assertEqual(order["status_validacao"], "OK")
                self.assertEqual(order["farmalider_status_pedido"], "PendentePagamento")
                self.assertEqual(order["farmalider_forma_pagamento"], payment)
                self.assertEqual(effective_order_status_code(order), status_code)
                self.assertEqual(order["farmalider_status_pedido_nome"], status_name)
                self.assertEqual(order["farmalider_forma_pagamento_nome"], payment_name)
                self.assertEqual(order["status_confirmacao"], confirmation)
                self.assertEqual(is_order_cancelled(order), payment == "_")
                self.assertEqual(
                    len(build_sales_metrics([order], items)), int(payment != "_")
                )

    def test_effective_order_status_uses_each_cancellation_signal(self):
        for cancellation in (
            {"farmalider_forma_pagamento": 0},
            {"farmalider_forma_pagamento": "0000"},
            {"farmalider_forma_pagamento": "CANCELADO"},
            {"farmalider_status_pedido": 3},
            {"farmalider_status_pedido": "Cancelado"},
            {"farmalider_cancelamento": "2026-10-06T11:00:00"},
        ):
            with self.subTest(cancellation=cancellation):
                order = {"farmalider_status_pedido": 2, **cancellation}
                self.assertEqual(effective_order_status_code(order), "3")
                self.assertTrue(is_order_cancelled(order))
                self.assertFalse(is_order_completed(order))
                self.assertFalse(is_order_made(order))

    def test_missing_or_boolean_payment_does_not_cancel_completed_order(self):
        for payment in (None, "", False, True):
            with self.subTest(payment=payment):
                order = {
                    "farmalider_status_pedido": 2,
                    "farmalider_forma_pagamento": payment,
                }
                self.assertEqual(effective_order_status_code(order), "2")
                self.assertFalse(is_order_cancelled(order))
                self.assertTrue(is_order_completed(order))

    def test_completed_code_is_completed(self):
        self.assertTrue(is_order_completed({"farmalider_status_pedido": 2}))
        self.assertFalse(is_order_completed({"farmalider_status_pedido": 1}))

    def test_business_datetime_formats_for_weni(self):
        value = business_order_datetime("2026-06-05T15:45:27.497")
        self.assertEqual(value.isoformat(), "2026-06-05T15:45:27.497000-03:00")
        self.assertEqual(weni_order_datetime_text(value), "05/06/26 15:45:27")
        self.assertEqual(
            business_order_datetime("05/06/26 15:45:27").isoformat(),
            "2026-06-05T15:45:27-03:00",
        )

    def test_api_identity_mismatch_is_rejected(self):
        pedido = pedido_payload()
        pedido["capa"]["codCliente"] = 100
        order, items = resolve_contact_order(
            contact(),
            farm_client=client(pedido=pedido),
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(order["status_validacao"], "ERRO")
        self.assertEqual(items, [])

    def test_business_datetime_accepts_explicit_brazilian_export_formats(self):
        for date in ("18/09/26", "18/09/2026", "18-09-26", "18-09-2026"):
            for time, seconds in (("12:21", "00"), ("12:21:37", "37")):
                with self.subTest(date=date, time=time):
                    parsed = business_order_datetime(f"{date} {time}")
                    self.assertIsNotNone(parsed)
                    self.assertEqual(
                        parsed.isoformat(), f"2026-09-18T12:21:{seconds}-03:00"
                    )

    def test_business_datetime_keeps_day_first_and_rejects_invalid_exports(self):
        self.assertEqual(
            business_order_datetime("09-10-2026 12:21").isoformat(),
            "2026-10-09T12:21:00-03:00",
        )
        for raw in (
            "31-09-2026 12:21",
            "10-18-2026 12:21",
            "18-09-2026 25:21",
            "18-09-2026",
            "18 de setembro de 2026 12:21",
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(business_order_datetime(raw))

    def test_item_order_identity_mismatch_is_rejected(self):
        pedido = pedido_payload()
        pedido["itens"][0]["codPedido"] = 999
        order, items = resolve_contact_order(
            contact(),
            farm_client=client(pedido=pedido),
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(order["status_confirmacao"], "ITEM_PEDIDO_DIVERGENTE_API")
        self.assertEqual(items, [])

    def test_invalid_cpf_queries_api_but_rejects_different_customer(self):
        api = client()
        order, _ = resolve_contact_order(
            contact(cpf="11111111111"),
            farm_client=api,
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(order["status_confirmacao"], "CPF_DIVERGENTE_API")
        api.get_cliente_by_cpf.assert_called_once_with("11111111111")
        api.get_pedido.assert_not_called()

    def test_client_api_error_returns_structured_diagnostic(self):
        api = client()
        api.get_cliente_by_cpf.side_effect = FarmaliderError("synthetic")
        order, items = resolve_contact_order(
            contact(), farm_client=api, captured_at=CAPTURED_AT
        )
        self.assertEqual(order["status_confirmacao"], "ERRO_API")
        self.assertEqual(order["status_validacao"], "ERRO")
        self.assertEqual(items, [])
        self.assertNotIn(SYNTHETIC_CPF, order["farmalider_erro"])

    def test_order_api_error_falls_back_to_cliente_payload(self):
        api = client()
        api.get_pedido.side_effect = FarmaliderError("synthetic")
        order, items = resolve_contact_order(
            contact(), farm_client=api, captured_at=CAPTURED_AT
        )
        self.assertEqual(order["origem_pedido"], "FARMALIDER_CLIENTE_CPF")
        self.assertEqual(order["status_validacao"], "OK")
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")

    def test_auth_error_stops_batch(self):
        api = client()
        api.get_cliente_by_cpf.side_effect = FarmaliderAuthError("synthetic")
        with self.assertRaises(FarmaliderAuthError):
            resolve_contact_order(contact(), farm_client=api, captured_at=CAPTURED_AT)

    def test_no_api_preserves_existing_fields_without_using_ultimo_pedido_as_data(self):
        order, items = resolve_contact_order(
            contact(raw=legacy_raw()),
            farm_client=None,
            captured_at=CAPTURED_AT,
        )
        self.assertIsNone(order)
        self.assertEqual(items, [])

    def test_apply_confirmation_uses_descricao_not_legacy_item_name(self):
        legacy_order, legacy_items = parse_ultimo_pedido(
            contact(raw=legacy_raw()), CAPTURED_AT
        )
        legacy_order["pedido_id"] = "123"
        pedido = pedido_payload()
        pedido["itens"][0]["descricao"] = "Descrição oficial"
        order, items = apply_pedido_api_confirmation(
            legacy_order,
            legacy_items,
            pedido,
            linked_cliente_id="99",
            confirmed_at=CAPTURED_AT,
        )
        self.assertEqual(order["status_validacao"], "OK")
        self.assertEqual(items[0]["produto_nome"], "Descrição oficial")

    def test_current_api_payment_clears_previous_payment_zero_cancellation(self):
        previous_pedido = pedido_payload()
        previous_pedido["capa"].update(status=2, formaPagamento=0)
        previous_order, previous_items = resolve_contact_order(
            contact(),
            farm_client=client(pedido=previous_pedido),
            captured_at=CAPTURED_AT,
        )
        self.assertEqual(previous_order["status_confirmacao"], "CANCELADO_API")
        self.assertEqual(build_sales_metrics([previous_order], previous_items), [])

        current_pedido = pedido_payload()
        current_pedido["capa"].update(status=2, formaPagamento=6)
        order, items = apply_pedido_api_confirmation(
            previous_order,
            previous_items,
            current_pedido,
            linked_cliente_id="99",
            confirmed_at="2026-10-06T19:00:00Z",
        )
        self.assertEqual(order["status_validacao"], "OK")
        self.assertEqual(order["status_confirmacao"], "CONFIRMADO_API")
        self.assertEqual(order["farmalider_status_pedido"], "2")
        self.assertEqual(order["farmalider_status_pedido_nome"], "Concluído")
        self.assertEqual(order["farmalider_forma_pagamento"], "6")
        self.assertEqual(order["farmalider_forma_pagamento_nome"], "Pix no POS")
        self.assertFalse(is_order_cancelled(order))
        self.assertEqual(len(build_sales_metrics([order], items)), 1)


if __name__ == "__main__":
    unittest.main()

# NexoFlow 1.5.5
