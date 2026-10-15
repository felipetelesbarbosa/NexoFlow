"""Caminhos públicos e configuração privada após a organização das pastas."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import project_paths

ROOT = Path(__file__).resolve().parents[1]


class ProjectLayoutTests(unittest.TestCase):
    def test_runtime_data_remains_at_installation_root(self):
        self.assertEqual(config.BASE_DIR, ROOT)
        self.assertEqual(config.CREDENTIALS_DIR, ROOT / "credentials")
        self.assertEqual(config.LOG_DIR, ROOT / "logs")
        self.assertEqual(project_paths.ROOT, ROOT)

    def test_private_configuration_loads_from_root_even_from_another_directory(self):
        with tempfile.TemporaryDirectory(prefix="nexo configuração ") as temporary:
            root = Path(temporary)
            (root / "secrets_config.py").write_text(
                "LAYOUT_SYNTHETIC = True\n", encoding="utf-8"
            )
            with (
                patch.object(project_paths, "ROOT", root),
                patch.object(sys, "path", list(sys.path)),
                patch.dict(sys.modules),
            ):
                sys.modules.pop("secrets_config", None)
                settings = project_paths.load_private_settings()
                self.assertTrue(settings.LAYOUT_SYNTHETIC)
                self.assertEqual(Path(settings.__file__), root / "secrets_config.py")
                project_paths.ensure_root_import_path()
                self.assertEqual(sys.path.count(str(root)), 1)

    def test_native_launcher_paths_exist_in_the_organized_layout(self):
        targets = {
            "analytics": "comandos/executar_carga_segura.bat",
            "weni": "comandos/atualizar_weni.bat",
            "recompra": "comandos/atualizar_recompra.bat",
            "planilha": "comandos/executar_planilha.bat",
            "terminal": "app/run_terminal.py",
        }
        for launcher, target in targets.items():
            with self.subTest(launcher=launcher):
                source = (ROOT / "native_launcher" / f"{launcher}.go").read_text(
                    encoding="utf-8"
                )
                self.assertIn(f'"{target}"', source)
                self.assertTrue((ROOT / target).is_file())

    def test_commands_resolve_installation_root_from_their_own_directory(self):
        for path in (ROOT / "comandos").glob("*.bat"):
            with self.subTest(command=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertIn('for %%I in ("%~dp0..")', content)
                self.assertIn('set "PYTHONPATH=%NEXOFLOW_HOME%;', content)
                self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))
