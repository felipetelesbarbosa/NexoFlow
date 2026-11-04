"""Transporte SDK STDIO e contrato do instalador, sempre sem rede real."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HAS_MCP = importlib.util.find_spec("mcp") is not None
TOOLS = {
    "contas_permitidas",
    "detalhes_conta",
    "campanhas",
    "conjuntos",
    "anuncios",
    "insights",
}


class InstallerContractTests(unittest.TestCase):
    def test_registration_preserves_others_and_never_embeds_credentials(self):
        path = ROOT / "scripts/instalar_meta_ads_mcp.ps1"
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        code = path.read_text(encoding="utf-8-sig")
        self.assertIn("codex mcp get nexoflow-meta-read --json", code)
        self.assertIn("codex mcp add nexoflow-meta-read -- $venvPython $server", code)
        self.assertNotIn("codex mcp remove", code)
        self.assertNotIn("codex mcp list", code)
        self.assertNotIn("--env", code)
        self.assertNotIn("Get-Content", code)
        self.assertIn("3.14", code)
        self.assertIn("Confirm-McpRegistration", code)


@unittest.skipUnless(
    HAS_MCP, "Executar com o ambiente isolado do MCP para testar o SDK real."
)
class StdioProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_exact_read_tools_and_sanitized_calls_over_stdio(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "connectors/meta_ads_mcp"
            target.mkdir(parents=True)
            for name in ("__init__.py", "server.py", "client.py", "settings.py"):
                shutil.copy2(ROOT / "connectors/meta_ads_mcp" / name, target / name)
            creds = root / "credentials/mcp"
            creds.mkdir(parents=True)
            (creds / "meta_ads_credentials.json").write_text(
                json.dumps(
                    {
                        "access_token": "FAKE_SECRET_NEVER_RETURN",
                        "api_version": "v26.0",
                        "allowed_ad_account_ids": ["898435729140540"],
                    }
                )
            )
            bootstrap = (
                "import runpy,socket; "
                "socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('FAKE_SECRET_NEVER_RETURN')); "
                f"runpy.run_path({str(target / 'server.py')!r},run_name='__main__')"
            )
            params = StdioServerParameters(
                command=sys.executable, args=["-c", bootstrap]
            )
            async with (
                stdio_client(params) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
                self.assertEqual({tool.name for tool in tools.tools}, TOOLS)
                for tool in tools.tools:
                    self.assertTrue(tool.annotations.readOnlyHint)
                    self.assertFalse(tool.annotations.destructiveHint)
                allowed = await session.call_tool("contas_permitidas", {})
                self.assertFalse(allowed.isError)
                self.assertIn("898435729140540", allowed.model_dump_json())
                self.assertNotIn("FAKE_SECRET", allowed.model_dump_json())
                failure = await session.call_tool(
                    "detalhes_conta", {"conta_id": "898435729140540"}
                )
                self.assertTrue(failure.isError)
                self.assertNotIn("FAKE_SECRET", failure.model_dump_json())
                denied = await session.call_tool(
                    "campanhas", {"conta_id": "111111111111111"}
                )
                self.assertTrue(denied.isError)
                self.assertNotIn("FAKE_SECRET", denied.model_dump_json())
