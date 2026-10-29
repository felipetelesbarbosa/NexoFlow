"""O check-up mantém erros visíveis, sem imprimir fluxos simulados aprovados."""

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import run_checkup_tests


class CheckupOutputTests(unittest.TestCase):
    def invoke(self, failure):
        class SyntheticCase(unittest.TestCase):
            def runTest(self):
                print("FLUXO_SIMULADO_DO_TESTE")
                if failure:
                    self.fail("FALHA_SINTETICA_VISIVEL")

        suite = unittest.TestSuite([SyntheticCase()])
        output, error = io.StringIO(), io.StringIO()
        with (
            patch(
                "run_checkup_tests.unittest.defaultTestLoader.discover",
                return_value=suite,
            ),
            redirect_stdout(output),
            redirect_stderr(error),
        ):
            code = run_checkup_tests.main()
        return code, output.getvalue(), error.getvalue()

    def test_successful_mock_output_is_not_presented_as_an_operational_load(self):
        code, output, error = self.invoke(False)
        self.assertEqual(code, 0)
        self.assertNotIn("FLUXO_SIMULADO_DO_TESTE", output + error)
        self.assertIn("OK", error)

    def test_real_failure_and_failed_test_output_remain_visible(self):
        code, output, error = self.invoke(True)
        self.assertEqual(code, 1)
        self.assertIn("FALHA_SINTETICA_VISIVEL", error)
        self.assertIn("FLUXO_SIMULADO_DO_TESTE", output + error)
