import importlib
import os
import sys
import types
import unittest
from unittest.mock import patch


class ProxyConfigTests(unittest.TestCase):
    def setUp(self):
        self._module_snapshot = {
            name: sys.modules.get(name) for name in ("secrets_config", "proxy_config")
        }
        self._environment_patch = patch.dict(os.environ)
        self._environment_patch.start()
        self.addCleanup(self._environment_patch.stop)
        self.addCleanup(self._restore_modules)

    def _restore_modules(self):
        for name, module in self._module_snapshot.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def load_module(self, **values):
        fake = types.ModuleType("secrets_config")
        defaults = {
            "PROXY_MODE": "auto",
            "PROXY_HOST": "proxy.test.invalid",
            "PROXY_PORT": 8020,
            "PROXY_USER": "usuario",
            "PROXY_PASSWORD": "s@nh:a/complexa",
            "PROXY_BYPASS": "localhost,127.0.0.1",
            "PROXY_DETECTION_TIMEOUT": 0.1,
        }
        defaults.update(values)
        for key, value in defaults.items():
            setattr(fake, key, value)

        sys.modules["secrets_config"] = fake
        sys.modules.pop("proxy_config", None)
        return importlib.import_module("proxy_config")

    def tearDown(self) -> None:
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "http_proxy",
            "https_proxy",
            "NO_PROXY",
            "no_proxy",
            "WENI_PROXY_ACTIVE",
        ):
            os.environ.pop(name, None)

    def test_auto_uses_direct_when_proxy_unreachable(self) -> None:
        module = self.load_module()
        with (
            patch.object(module, "_is_reachable", return_value=False),
            patch.object(module, "_direct_internet_available", return_value=True),
            patch.object(module.time, "sleep", return_value=None),
        ):
            status = module.configure_proxy()
        self.assertFalse(status.active)
        self.assertEqual(os.environ.get("WENI_PROXY_ACTIVE"), "0")

    def test_auto_activates_when_proxy_reachable(self) -> None:
        module = self.load_module()
        with patch.object(module, "_is_reachable", return_value=True):
            status = module.configure_proxy()
        self.assertTrue(status.active)
        self.assertTrue(status.has_credentials)
        self.assertEqual(os.environ.get("WENI_PROXY_ACTIVE"), "1")
        self.assertIn("HTTP_PROXY", os.environ)
        self.assertIn("proxy.test.invalid:8020", os.environ["HTTP_PROXY"])
        self.assertNotIn("s@nh:a/complexa", os.environ["HTTP_PROXY"])
        self.assertIn("s%40nh%3Aa%2Fcomplexa", os.environ["HTTP_PROXY"])

    def test_refresh_switches_direct_to_proxy(self) -> None:
        module = self.load_module()
        with (
            patch.object(module, "_is_reachable", return_value=False),
            patch.object(module, "_direct_internet_available", return_value=True),
            patch.object(module.time, "sleep", return_value=None),
        ):
            initial = module.configure_proxy()
        self.assertFalse(initial.active)

        with patch.object(module, "_is_reachable", return_value=True):
            refreshed = module.refresh_network_route(reason="teste")

        self.assertTrue(refreshed.changed)
        self.assertFalse(refreshed.previous_active)
        self.assertTrue(refreshed.current_active)
        self.assertEqual(os.environ.get("WENI_PROXY_ACTIVE"), "1")
        self.assertEqual(refreshed.transition, "direta -> proxy")

    def test_refresh_switches_proxy_to_direct(self) -> None:
        module = self.load_module()
        with patch.object(module, "_is_reachable", return_value=True):
            initial = module.configure_proxy()
        self.assertTrue(initial.active)

        with (
            patch.object(module, "_is_reachable", return_value=False),
            patch.object(module, "_direct_internet_available", return_value=True),
            patch.object(module.time, "sleep", return_value=None),
        ):
            refreshed = module.refresh_network_route(reason="teste")

        self.assertTrue(refreshed.changed)
        self.assertTrue(refreshed.previous_active)
        self.assertFalse(refreshed.current_active)
        self.assertEqual(os.environ.get("WENI_PROXY_ACTIVE"), "0")
        self.assertEqual(refreshed.transition, "proxy -> direta")

    def test_off_never_activates(self) -> None:
        module = self.load_module(PROXY_MODE="off")
        status = module.configure_proxy()
        self.assertFalse(status.active)
        self.assertEqual(os.environ.get("WENI_PROXY_ACTIVE"), "0")

    def test_partial_credentials_are_rejected(self) -> None:
        module = self.load_module(PROXY_PASSWORD="")
        with self.assertRaises(ValueError):
            module.configure_proxy()


if __name__ == "__main__":
    unittest.main()
