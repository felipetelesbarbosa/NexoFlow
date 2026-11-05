"""O pip herda a rota e a CA sem expor argumentos/segredos no console."""

import contextlib
import io
import os
import unittest
from unittest.mock import Mock, patch

import run_pip


class ProxySubprocessTests(unittest.TestCase):
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
