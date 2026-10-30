param()
$ErrorActionPreference = 'Stop'
foreach ($source in @('installer/install.ps1', 'installer/uninstall.ps1')) {
    $tokens = $null; $errors = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path (Split-Path -Parent $PSScriptRoot) $source), [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw 'Sintaxe de manutenção inválida.' }
    foreach ($name in @('Enter-NexoMaintenance', 'Exit-NexoMaintenance')) {
        $function = $ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
        if ($function.Count -ne 1) { throw 'Função de trava ausente ou duplicada.' }
        Invoke-Expression $function[0].Extent.Text
    }
    foreach ($profile in @('FARMA', 'PET')) {
        $created = $false
        $active = New-Object Threading.Mutex($false, ('Local\NexoFlowOperationLock_' + $profile), [ref]$created)
        try {
            $blocked = $false
            try { Enter-NexoMaintenance } catch { $blocked = $true }
            if (-not $blocked) { throw 'A manutenção não bloqueou uma carga ativa.' }
        } finally { $active.Dispose(); Exit-NexoMaintenance }
    }
    try {
        Enter-NexoMaintenance
        foreach ($name in @('Local\NexoFlowOperationLock', 'Local\NexoFlowOperationLock_FARMA', 'Local\NexoFlowOperationLock_PET')) {
            $created = $false
            $other = New-Object Threading.Mutex($false, $name, [ref]$created)
            try { if ($created) { throw 'Manutenção não manteve todas as travas.' } } finally { $other.Dispose() }
        }
    } finally { Exit-NexoMaintenance }
}
Write-Host '[OK] Manutenção: cargas FARMA/PET bloqueiam instalação e desinstalação, sem encerrar processos.'
