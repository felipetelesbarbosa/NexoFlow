import unittest

from nexoflow_hub.farma_read_probe import inspect_sources


class Client:
    segment = "FARMA"

    def get_pedidos_history(self, query, page):
        assert query.segment == "FARMA" and page == 1
        return {
            "pedidos": [{"capa": {"id": 7, "segmento": self.segment}}],
            "pagina": 1,
            "limite": query.limit,
            "totalRegistros": 1,
            "totalPaginas": 1,
        }

    def get_pedido(self, code):
        return {
            "capa": {"id": code, "segmento": self.segment},
            "itens": [{"codPedido": code}],
        }


class ProbeTests(unittest.TestCase):
    def test_amostra(self):
        r = inspect_sources(Client(), "2026-11-07", "2026-11-09")
        self.assertEqual(r["escritas"], 0)
        self.assertEqual(r["fontes"]["itens"]["linhas"], 1)
        self.assertEqual(
            r["fontes"]["cadastros"]["estado"], "pendente_validacao_diretorio"
        )

    def test_pet_rejeitado(self):
        c = Client()
        c.segment = "PET"
        with self.assertRaises(ValueError):
            inspect_sources(c, "2026-11-07", "2026-11-09")
