"""Regressão sem rede, com dados sintéticos dos dois dias omitidos."""

import unittest

from meta_ads_recovery import MetaReadError
from nexoflow_hub.meta_recovery import DAYS, FixtureMetaRead, run_meta_recovery


class MetaRecoveryTests(unittest.TestCase):
    def test_recuperacao_dos_dois_dias_sem_impressoes(self):
        client = FixtureMetaRead()
        result = run_meta_recovery(client)
        self.assertEqual(client.reads, list(DAYS))
        self.assertEqual((result["linhas_omitidas"], result["recuperadas"]), (2, 2))
        self.assertEqual(result["cobertura"], "completa")
        self.assertEqual(result["pendencias"], [])
        for row, day, spend in zip(result["linhas"], DAYS, ("10.00", "12.50")):
            self.assertEqual((row["data"], row["origem"]), (day, "consulta_direta"))
            self.assertEqual(row["conversas_iniciadas_meta"], "1.00")
            self.assertEqual(row["investimento_original"], spend)
            self.assertEqual((row["impressoes"], row["ctr_pct"], row["cpm"]), ("", "", ""))

    def test_falha_direta_preserva_valores_anteriores(self):
        client = FixtureMetaRead(fail_days=DAYS)
        result = run_meta_recovery(client)
        self.assertEqual(client.reads, list(DAYS))
        self.assertEqual(result["recuperadas"], 0)
        self.assertEqual(result["cobertura"], "parcial")
        self.assertEqual(result["pendencias"], list(DAYS))
        for row in result["linhas"]:
            self.assertEqual(row["origem"], "historico_preservado")
            self.assertEqual(row["conversas_iniciadas_meta"], "1.00")
            self.assertEqual(row["investimento_original"], "9.00")
            self.assertEqual((row["impressoes"], row["ctr_pct"], row["cpm"]),
                             ("100.00", "5.00", "90.00"))

    def test_falha_isolada_nao_impede_outro_dia(self):
        result = run_meta_recovery(FixtureMetaRead(fail_days=(DAYS[0],)))
        self.assertEqual(result["recuperadas"], 1)
        self.assertEqual(result["pendencias"], [DAYS[0]])
        self.assertEqual([row["origem"] for row in result["linhas"]],
                         ["historico_preservado", "consulta_direta"])

    def test_resposta_de_outra_conta_nao_substitui_historico(self):
        class WrongAccount(FixtureMetaRead):
            def daily_insights(self, *args, **kwargs):
                result = super().daily_insights(*args, **kwargs)
                result["dados"][0]["account_id"] = "99900003"
                return result

        result = run_meta_recovery(WrongAccount())
        self.assertEqual(result["recuperadas"], 0)
        self.assertEqual(result["pendencias"], list(DAYS))

    def test_falha_critica_nao_vira_sucesso(self):
        class Critical(FixtureMetaRead):
            def daily_insights(self, *args, **kwargs):
                raise MetaReadError("AUTENTICACAO_FIXTURE", critical=True)

        with self.assertRaises(MetaReadError):
            run_meta_recovery(Critical())


if __name__ == "__main__":
    unittest.main()
