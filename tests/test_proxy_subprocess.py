"""O pip herda a rota e a CA sem expor argumentos/segredos no console."""

import contextlib
import io
import os
import sys
import unittest
import urllib.error
from unittest.mock import MagicMock, Mock, patch

import run_pip


class ProxySubprocessTests(unittest.TestCase):
    def test_install_keeps_the_proxy_across_preflight_recovery(self):
        proxy = "http://synthetic:SECRET_MARKER@proxy.invalid:8020"
        arguments = ["install", "setuptools>=77", "wheel", "-r", "requirements.txt"]

        for refusal in (False, True):
            with (
                self.subTest(refusal=refusal),
                patch.dict(os.environ, {"HTTPS_PROXY": proxy}, clear=True),
                patch.dict(
                    sys.modules,
                    {
                        "proxy_config": Mock(
                            configure_proxy=Mock(
                                return_value=Mock(
                                    active=True, safe_summary="proxy ativo"
                                )
                            )
                        ),
                    },
                ),
                patch("pip_network.urllib.request.build_opener") as build,
                patch("time.sleep") as delay,
                patch.object(run_pip.sys, "argv", ["run_pip.py", *arguments]),
                patch.object(
                    run_pip.subprocess, "run", return_value=Mock(returncode=0)
                ) as install,
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                opener = build.return_value
                opener.open.side_effect = (
                    urllib.error.URLError(
                        OSError("Tunnel connection failed: 407 SECRET_MARKER")
                    )
                    if refusal
                    else [TimeoutError("SECRET_MARKER"), MagicMock()]
                )
                self.assertEqual(run_pip.main(), int(refusal))
                self.assertEqual(build.call_args.args[1].proxies, {"https": proxy})
                self.assertNotIn("SECRET_MARKER", output.getvalue())
                if refusal:
                    self.assertIn("PROXY_CONNECT_407", output.getvalue())
                    delay.assert_not_called()
                    install.assert_not_called()
                else:
                    self.assertIn("REDE_PIP_TIMEOUT", output.getvalue())
                    delay.assert_called_once_with(2)
                    install.assert_called_once()
                    self.assertEqual(os.environ["PIP_PROXY"], proxy)
                    self.assertEqual(
                        install.call_args.args[0][4:],
                        [*arguments, "--retries", "2", "--timeout", "15"],
                    )

    def test_pip_child_inherits_route_and_ca_for_both_profiles(self):
        for profile in ("FARMA", "PET"):
            for proxy in ("http://synthetic:secret@proxy.invalid:8020", ""):
                with patch.dict(
                    os.environ,
                    {
                        "NEXOFLOW_PERFIL": profile,
                        "NEXOFLOW_NETWORK_MODE": "corporate" if proxy else "personal",
                        "HTTPS_PROXY": proxy,
                        "REQUESTS_CA_BUNDLE": "corporate-approved.pem",
                    },
                ):

                    def child(command, proxy=proxy, profile=profile, **kwargs):
                        self.assertNotIn("env", kwargs)
                        self.assertEqual(
                            os.environ["NEXOFLOW_NETWORK_MODE"],
                            "corporate" if proxy else "personal",
                        )
                        self.assertEqual(os.environ["HTTPS_PROXY"], proxy)
                        self.assertEqual(os.environ["NEXOFLOW_PERFIL"], profile)
                        self.assertEqual(
                            os.environ["REQUESTS_CA_BUNDLE"], "corporate-approved.pem"
                        )
                        self.assertNotIn(proxy, command)
                        return Mock(returncode=0)

                    output = io.StringIO()
                    with (
                        patch.object(run_pip, "_configure_proxy"),
                        patch.object(run_pip.sys, "argv", ["run_pip.py", "--version"]),
                        patch.object(run_pip.subprocess, "run", side_effect=child),
                        contextlib.redirect_stdout(output),
                    ):
                        self.assertEqual(run_pip.main(), 0)
                    self.assertNotIn("secret", output.getvalue())

    def test_uncontrolled_pip_output_is_never_logged(self):
        output = io.StringIO()
        with (
            patch.object(run_pip, "_configure_proxy"),
            patch.object(run_pip.sys, "argv", ["run_pip.py", "install", "synthetic"]),
            patch.object(
                run_pip.subprocess,
                "run",
                return_value=Mock(
                    returncode=1,
                    stdout="https://user:SECRET_MARKER@private.invalid/?token=SECRET_MARKER",
                ),
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(run_pip.main(), 1)
        self.assertNotIn("SECRET_MARKER", output.getvalue())
