"""Reconhecimento local com redes fictícias; sem sondagens comerciais."""
import unittest
from unittest.mock import patch

from tests import test_meta_optional_install as optional_tests
from tests import test_proxy_config as proxy_tests


@unittest.skipUnless(optional_tests.POWERSHELL, "PowerShell necessário")
class WindowsNetworkMemoryTests(unittest.TestCase):
    run_ps = optional_tests.OptionalInstallTests.run_ps

    def test_network_memory_is_scoped_and_domain_never_selects_personal(self):
        self.run_ps(r'''
. (Join-Path $repo 'scripts/reconhecer_rede.ps1') -FunctionsOnly
$env:LOCALAPPDATA=Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString('N'))
$script:id='synthetic-home';$script:category=0
function Get-NexoConnectedNetworks {
 $network=New-Object PSObject
 $network|Add-Member ScriptMethod GetNetworkId {return $script:id}
 $network|Add-Member ScriptMethod GetCategory {return $script:category}
 return $network
}
try {
 if(Invoke-NexoNetworkMemory){throw 'Rede desconhecida foi reconhecida'}
 Invoke-NexoNetworkMemory -Action Salvar -Mode personal
 if((Invoke-NexoNetworkMemory) -ne 'personal'){throw 'Casa não lembrada'}
 $script:id='synthetic-office'
 if(Invoke-NexoNetworkMemory){throw 'Escolha vazou para outra rede'}
 Invoke-NexoNetworkMemory -Action Salvar -Mode corporate
 if((Invoke-NexoNetworkMemory) -ne 'corporate'){throw 'Empresa não lembrada'}
 $script:id='synthetic-home';$script:category=2
 if((Invoke-NexoNetworkMemory) -ne 'corporate'){throw 'Domínio ignorado'}
 Invoke-NexoNetworkMemory -Action Salvar -Mode personal
 if((Invoke-NexoNetworkMemory) -ne 'corporate'){throw 'Domínio perdeu proteção'}
 $data=Get-ChildItem $env:LOCALAPPDATA -Recurse -Filter *.json | Get-Content -Raw
 if(($data -join '') -match 'synthetic|password|token'){throw 'Identidade ou segredo gravado'}
}finally{Remove-Item $env:LOCALAPPDATA -Force -Recurse}
''')

    def test_setup_unknown_network_retries_and_mcp_requires_s_or_n(self):
        self.run_ps(r''' 
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $repo 'installer/install.ps1'),[ref]$tokens,[ref]$errors)
foreach($name in @('Select-SetupNetwork','Invoke-OptionalMetaAdsSetup')) {
 $f=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
 . ([scriptblock]::Create($f.Extent.Text))
}
$PayloadDir=Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString('N'))
$NetworkMode='Auto';$NonInteractive=$false
Remove-Item Env:NEXOFLOW_NETWORK_MODE -ErrorAction SilentlyContinue
$script:answers=[Collections.Generic.Queue[string]]::new()
@('','x','1')|ForEach-Object {$script:answers.Enqueue($_)}
function Read-Host {param($Prompt) return $script:answers.Dequeue()}
Select-SetupNetwork
if($env:NEXOFLOW_NETWORK_MODE -ne 'personal' -or $script:answers.Count -ne 0){throw 'Seleção inválida não repetida'}
@('','x','n')|ForEach-Object {$script:answers.Enqueue($_)}
Invoke-OptionalMetaAdsSetup -Mode Clean
if($script:answers.Count -ne 0 -or $script:MetaOptionalStatus -notlike 'não solicitado*'){throw 'MCP instalou implicitamente'}
''')


class RememberedRouteTests(unittest.TestCase):
    setUp = proxy_tests.ProxyConfigTests.setUp
    tearDown = proxy_tests.ProxyConfigTests.tearDown
    _restore_modules = proxy_tests.ProxyConfigTests._restore_modules
    load_module = proxy_tests.ProxyConfigTests.load_module

    def test_remembered_personal_skips_proxy_and_asks_nothing(self):
        module = self.load_module(PROXY_ALLOW_DIRECT_FALLBACK=False)
        with (
            patch('network_session.windows_network_choice', return_value='personal'),
            patch.object(module, '_is_reachable') as tcp,
            patch('builtins.input') as ask,
        ):
            status = module.configure_proxy()
            self.assertFalse(status.active)
            self.assertIn("não sondado", status.safe_summary)
            tcp.assert_not_called()
            ask.assert_not_called()

    def test_remembered_corporate_outage_never_falls_back(self):
        module = self.load_module(PROXY_ALLOW_DIRECT_FALLBACK=True)
        with (
            patch('network_session.windows_network_choice', return_value='corporate'),
            patch.object(module, '_is_reachable', return_value=False),
            patch.object(module.sys.stdin, 'isatty', return_value=False),
            patch.object(module.time, 'sleep'),
            patch.object(module, '_direct_internet_available') as direct,
        ):
            with self.assertRaisesRegex(ValueError, 'PROXY_INDISPONIVEL'):
                module.configure_proxy()
            direct.assert_not_called()


if __name__ == '__main__':
    unittest.main()
