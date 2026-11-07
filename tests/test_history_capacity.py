import unittest

from history_capacity import allocate
from order_history import HistoryError
from sheets_continuation import CELL_LIMIT
from sheets_storage import storage_role


class CapacityTests(unittest.TestCase):
    def test_actual_grid_requires_continuations_and_crosses_two_boundaries(self):
        result = allocate(
            {"Historico_Pedidos": ["x"] * 15, "Historico_Itens": ["x"] * 11},
            {"Historico_Pedidos": 1_100_000, "Historico_Itens": 207_582},
            [],
            {"hist": 18_413_260, "dash": 100, "ops": 100},
            {"historico": "hist", "dashboard": "dash", "operacao": "ops"},
            threshold=18_000_000,
            max_rows=500_000,
        )
        self.assertEqual(len(result["ranges"]["Historico_Pedidos"]), 3)
        self.assertTrue(all(p["book"].startswith("new:") for p in result["creations"]))
        self.assertEqual(
            sum(r["rows"] for r in result["ranges"]["Historico_Pedidos"]), 1_100_000
        )
        self.assertTrue(all(b["after"] <= CELL_LIMIT for b in result["books"]))
        self.assertEqual(result["books"][0]["after"], 18_413_260)

    def test_tables_reserve_capacity_globally_not_independently(self):
        r = allocate(
            {"Historico_Pedidos": ["x"] * 15, "Historico_Itens": ["x"] * 11},
            {"Historico_Pedidos": 3, "Historico_Itens": 3},
            [],
            {"hist": 900, "dash": 0, "ops": 0},
            {"historico": "hist", "dashboard": "dash", "operacao": "ops"},
            threshold=1000,
            max_rows=100,
        )
        self.assertLessEqual(
            next(b["after"] for b in r["books"] if b["book"] == "hist"), 1000
        )
        self.assertEqual(len(r["ranges"]["Historico_Itens"]), 2)

    def test_existing_padding_does_not_expand_over_threshold(self):
        p = dict(
            title="Historico_Pedidos",
            number=0,
            book="hist",
            width=15,
            allocated_rows=5,
            used_rows=2,
        )
        r = allocate(
            {"Historico_Pedidos": ["x"] * 15},
            {"Historico_Pedidos": 3},
            [p],
            {"hist": 18_413_260, "dash": 0, "ops": 0},
            {"historico": "hist", "dashboard": "dash", "operacao": "ops"},
            threshold=18_000_000,
            max_rows=10,
        )
        self.assertFalse(r["creations"])
        self.assertEqual(r["books"][0]["after"], 18_413_260)

    def test_invalid_grid_and_routing(self):
        self.assertEqual(storage_role("Historico_Pedidos"), "historico")
        self.assertEqual(storage_role("Historico_Itens"), "historico")
        with self.assertRaises(HistoryError):
            allocate(
                {}, {}, [], {"hist": CELL_LIMIT + 1}, {}, threshold=1000, max_rows=10
            )
