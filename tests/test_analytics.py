import json
import unittest

from analytics import (
    build_daily_metrics,
    is_meta_ads_contact,
    is_relevant_contact,
    normalize_contact,
    parse_ultimo_pedido,
)
from config import TIPO_PRIMEIRO_ANUNCIO, TIPO_ULTIMO_ANUNCIO


class AnalyticsTests(unittest.TestCase):
    def sample_contact(self):
        ultimo_pedido = json.dumps(
            {
                "pedido_id": 123456,
                "data_hora": "2026-09-30T16:07:00Z",
                "valor_total_compra": 25.00,
                "produtos": [
                    {
                        "nome": "Produto Teste",
                        "quantidade": 1,
                        "valor_unitario": 25.00,
                        "valor_total": 25.00,
                    }
                ],
            }
        )

        return {
            "uuid": "contact-1",
            "name": "Cliente Teste",
            "urns": ["tel:+5591999999999"],
            "created_on": "2026-09-29T10:00:00-03:00",
            "modified_on": "2026-09-30T10:00:00-03:00",
            "fields": {
                "nome": "Cliente Teste",
                "cpf": "529.982.247-25",
                "primeiro_anuncio_origem": "Meta Ads",
                "primeiro_anuncio_id": "AD-A",
                "primeiro_anuncio_titulo": "Oferta A",
                "primeiro_anuncio_data": "2026-09-29T10:00:00-03:00",
                "ultimo_anuncio_origem": "Meta Ads",
                "ultimo_anuncio_id": "AD-B",
                "ultimo_anuncio_titulo": "Oferta B",
                "ultimo_anuncio_data": "2026-09-30T10:00:00-03:00",
                "primeiro_anuncio_tipo_campanha": "Search",
                "primeiro_anuncio_canal_destino": "whatsapp",
                "ultimo_anuncio_tipo_campanha": "Performance Max",
                "ultimo_anuncio_canal_destino": "whatsapp",
                "ultimo_pedido": {"value": ultimo_pedido},
            },
        }

    def test_detects_relevant_contact(self):
        contact = self.sample_contact()
        self.assertTrue(is_meta_ads_contact(contact))
        self.assertTrue(is_relevant_contact(contact))

    def test_normalizes_uuid_cpf_and_ad_fields(self):
        row = normalize_contact(
            self.sample_contact(),
            "2026-09-30T14:00:00+00:00",
        )
        self.assertEqual(row["contact_uuid"], "contact-1")
        self.assertEqual(row["cpf_normalizado"], "52998224725")
        self.assertEqual(row["primeiro_anuncio_id"], "AD-A")
        self.assertEqual(row["ultimo_anuncio_id"], "AD-B")
        self.assertEqual(row["primeiro_anuncio_tipo_campanha"], "Search")
        self.assertEqual(row["ultimo_anuncio_tipo_campanha"], "Performance Max")
        self.assertEqual(row["ultimo_anuncio_canal_destino"], "whatsapp")
        self.assertEqual(row["voltou_por_outro_anuncio"], "Sim")

    def test_multichannel_fields_are_exposed_in_analytics(self):
        contact = self.sample_contact()
        contact["urns"] = [
            "instagram:222",
            "facebook:333",
            "whatsapp:5591999999999",
        ]
        row = normalize_contact(contact, "2026-09-30T14:00:00+00:00")
        self.assertEqual(row["contact_urn"], "whatsapp:5591999999999")
        self.assertEqual(row["contact_urn_whatsapp"], "whatsapp:5591999999999")
        self.assertEqual(row["contact_urn_instagram"], "instagram:222")
        self.assertEqual(row["contact_urn_facebook"], "facebook:333")
        self.assertEqual(row["contact_canal_principal"], "whatsapp")
        self.assertEqual(row["telefone"], "5591999999999")

    def test_instagram_contact_does_not_turn_instagram_id_into_phone(self):
        contact = self.sample_contact()
        contact["urns"] = ["instagram:222"]
        contact["fields"].pop("contact_urn", None)
        row = normalize_contact(contact, "2026-09-30T14:00:00+00:00")
        self.assertEqual(row["telefone"], "")
        self.assertEqual(row["contact_urn"], "instagram:222")
        self.assertEqual(row["contact_canal_principal"], "instagram")

    def test_metrics_keep_friendly_labels(self):
        row = normalize_contact(
            self.sample_contact(),
            "2026-09-30T14:00:00+00:00",
        )
        labels = {metric[1] for metric in build_daily_metrics([row])}
        self.assertIn(TIPO_PRIMEIRO_ANUNCIO, labels)
        self.assertIn(TIPO_ULTIMO_ANUNCIO, labels)

    def test_ultimo_pedido_accepts_pedido_id(self):
        order, items = parse_ultimo_pedido(
            self.sample_contact(),
            "2026-09-30T14:00:00+00:00",
        )
        self.assertEqual(order["pedido_id"], "123456")
        self.assertEqual(order["pedido_chave"], "FARMALIDER:123456")
        self.assertEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
