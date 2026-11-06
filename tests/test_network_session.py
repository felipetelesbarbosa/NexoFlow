"""Escolha compartilhada por etapas, com três falhas antes de perguntar."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import network_session
from tests.test_network_choice import NetworkChoiceTests


class SessionTests(NetworkChoiceTests):
    def test_unavailable_proxy_gets_three_tcp_attempts_before_prompt(self):
        module = self.load_module(PROXY_ALLOW_DIRECT_FALLBACK=False)
        with (
            patch.dict(os.environ, {"NEXOFLOW_NETWORK_MODE": "corporate"}),
            patch.object(module.sys.stdin, "isatty", return_value=True),
            patch.object(module, "_is_reachable", return_value=False) as tcp,
            patch.object(module, "_direct_internet_available") as direct,
            patch.object(module.time, "sleep"),
            patch("builtins.input", return_value="1") as ask,
        ):
            self.assertFalse(module.configure_proxy(detection_attempts=1).active)
            self.assertEqual(tcp.call_count, 3)
            ask.assert_called_once()
            direct.assert_not_called()

    def test_real_sibling_processes_inherit_only_the_session_choice(self):
        root = Path(__file__).resolve().parents[1]
        code = """
import sys, types
settings = types.ModuleType('secrets_config')
settings.PROXY_MODE = 'auto'
settings.PROXY_HOST = 'proxy.example.invalid'
settings.PROXY_PORT = 8020
sys.modules['secrets_config'] = settings
import proxy_config
proxy_config._is_reachable = lambda *args: False
proxy_config.time.sleep = lambda *args: None
if sys.argv[1] == 'first':
    sys.stdin.isatty = lambda: True
assert proxy_config.configure_proxy().active is False
"""
        with tempfile.TemporaryDirectory() as directory:
            env = {
                **os.environ,
                "NEXOFLOW_NETWORK_MODE": "auto",
                "NEXOFLOW_NETWORK_SESSION": "synthetic-process-session",
                "TMPDIR": directory,
                "TEMP": directory,
                "TMP": directory,
                "PYTHONPATH": os.pathsep.join([str(root), str(root / "app")]),
            }
            for phase in ("first", "apply"):
                result = subprocess.run(
                    [sys.executable, "-c", code, phase],
                    env=env,
                    input="3\n\ntexto\n1\n" if phase == "first" else "",
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    result.stdout.count("Rede não confirmada"),
                    4 if phase == "first" else 0,
                )

    def test_eof_in_interactive_child_exits_without_an_input_loop(self):
        root = Path(__file__).resolve().parents[1]
        code = """
import sys, types
settings = types.ModuleType('secrets_config')
settings.PROXY_MODE = 'auto'
settings.PROXY_HOST = 'proxy.example.invalid'
settings.PROXY_PORT = 8020
sys.modules['secrets_config'] = settings
import proxy_config
proxy_config._is_reachable = lambda *args: False
proxy_config.time.sleep = lambda *args: None
sys.stdin.isatty = lambda: True
try:
    proxy_config.configure_proxy()
except ValueError as error:
    assert str(error).startswith('Entrada de rede encerrada')
    raise SystemExit(3)
raise SystemExit('Rota escolhida sem entrada')
"""
        env = {
            **os.environ,
            "NEXOFLOW_NETWORK_MODE": "auto",
            "PYTHONPATH": os.pathsep.join([str(root), str(root / "app")]),
        }
        env.pop("NEXOFLOW_NETWORK_SESSION", None)
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            input="",
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(result.stdout.count("Rede não confirmada"), 1)

    def test_sibling_steps_reuse_choice_without_new_prompt(self):
        module = self.load_module(PROXY_ALLOW_DIRECT_FALLBACK=False)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NEXOFLOW_NETWORK_SESSION": "synthetic-session"}),
            patch.object(
                network_session.tempfile, "gettempdir", return_value=directory
            ),
            patch.object(module.sys.stdin, "isatty", return_value=True),
            patch.object(module, "_is_reachable", return_value=False),
            patch.object(module.time, "sleep"),
            patch("builtins.input", return_value="1") as ask,
        ):
            self.assertFalse(module.configure_proxy().active)
            # Processo irmão volta com o ambiente original do BAT, sem escolha.
            os.environ["NEXOFLOW_NETWORK_MODE"] = "auto"
            self.assertFalse(module.configure_proxy().active)
            ask.assert_called_once()
            self.assertEqual(network_session.read_choice(), "personal")
            content = next(Path(directory).glob("*.json")).read_text()
            self.assertNotIn("usuario", content)
            self.assertNotIn("password", content)

    def test_three_failed_attempts_before_explicit_route_switch(self):
        module = self.load_module(PROXY_ALLOW_DIRECT_FALLBACK=False)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NEXOFLOW_NETWORK_SESSION": "synthetic-session"}),
            patch.object(
                network_session.tempfile, "gettempdir", return_value=directory
            ),
            patch.object(module.sys.stdin, "isatty", return_value=True),
            patch.object(module, "_is_reachable", return_value=True),
            patch("builtins.input", return_value="2") as ask,
        ):
            network_session.save_choice("personal")
            module.configure_proxy()
            for attempt in (1, 2):
                self.assertFalse(module.refresh_network_route(attempt=attempt).changed)
            ask.assert_not_called()
            self.assertTrue(module.refresh_network_route(attempt=3).changed)
            self.assertEqual(network_session.read_choice(), "corporate")
            ask.assert_called_once()

    def test_third_failure_repeats_invalid_answers_and_keeps_session_until_choice(self):
        for answer, expected in (("1", "personal"), ("2", "corporate"), ("0", None)):
            with self.subTest(answer=answer):
                module = self.load_module(PROXY_ALLOW_DIRECT_FALLBACK=False)
                answers = iter(["3", "", "texto", "12", answer])

                def choose(_prompt, answers=answers):
                    self.assertEqual(network_session.read_choice(), "personal")
                    self.assertEqual(os.environ["NEXOFLOW_NETWORK_MODE"], "personal")
                    return next(answers)

                with (
                    tempfile.TemporaryDirectory() as directory,
                    patch.dict(
                        os.environ, {"NEXOFLOW_NETWORK_SESSION": "synthetic-session"}
                    ),
                    patch.object(
                        network_session.tempfile, "gettempdir", return_value=directory
                    ),
                    patch.object(module.sys.stdin, "isatty", return_value=True),
                    patch.object(module, "_is_reachable", return_value=True) as tcp,
                    patch("builtins.input", side_effect=choose) as ask,
                    patch("builtins.print") as output,
                ):
                    network_session.save_choice("personal")
                    module.configure_proxy()
                    for attempt in (1, 2):
                        self.assertFalse(
                            module.refresh_network_route(attempt=attempt).changed
                        )
                    ask.assert_not_called()
                    tcp.assert_not_called()
                    if expected is None:
                        with self.assertRaisesRegex(ValueError, "cancelada"):
                            module.refresh_network_route(attempt=3)
                    else:
                        result = module.refresh_network_route(attempt=3)
                        self.assertEqual(result.changed, expected == "corporate")
                    self.assertEqual(
                        network_session.read_choice(), expected or "personal"
                    )
                    self.assertEqual(ask.call_count, 5)
                    self.assertEqual(output.call_count, 4)
                    for prompt in ask.call_args_list:
                        self.assertNotIn("[3]", prompt.args[0])

    def test_eof_after_third_failure_preserves_the_saved_route(self):
        module = self.load_module(PROXY_ALLOW_DIRECT_FALLBACK=False)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"NEXOFLOW_NETWORK_SESSION": "synthetic-session"}),
            patch.object(
                network_session.tempfile, "gettempdir", return_value=directory
            ),
            patch.object(module.sys.stdin, "isatty", return_value=True),
            patch.object(module, "_is_reachable") as tcp,
            patch("builtins.input", side_effect=EOFError) as ask,
        ):
            network_session.save_choice("personal")
            module.configure_proxy()
            with self.assertRaisesRegex(ValueError, "Entrada de rede encerrada"):
                module.refresh_network_route(attempt=3)
            self.assertEqual(network_session.read_choice(), "personal")
            self.assertEqual(os.environ["NEXOFLOW_NETWORK_MODE"], "personal")
            self.assertEqual(os.environ["WENI_PROXY_ACTIVE"], "0")
            ask.assert_called_once()
            tcp.assert_not_called()

    def test_session_scope_cleans_its_own_file_and_leaves_no_global_choice(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ),
            patch.object(
                network_session.tempfile, "gettempdir", return_value=directory
            ),
        ):
            os.environ.pop("NEXOFLOW_NETWORK_SESSION", None)
            with network_session.session_scope():
                network_session.save_choice("personal")
                self.assertEqual(network_session.read_choice(), "personal")
            self.assertNotIn("NEXOFLOW_NETWORK_SESSION", os.environ)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_bat_entrypoints_create_a_shared_session(self):
        root = Path(__file__).resolve().parents[1]
        for filename in (
            "atualizar_weni.bat",
            "atualizar_weni_carga_completa.bat",
            "atualizar_tudo.bat",
            "executar_noturno.bat",
        ):
            text = (root / "comandos" / filename).read_text(encoding="utf-8")
            self.assertIn("if not defined NEXOFLOW_NETWORK_SESSION", text)
