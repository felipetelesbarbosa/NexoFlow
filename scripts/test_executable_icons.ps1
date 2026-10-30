param([string]$Version = "1.5.9")

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Dist = Join-Path $RepoRoot "dist"
$Project = Join-Path $Dist "NexoFlow"
$Setup = Join-Path $Dist "NexoFlow Setup"

if (-not ('NexoFlowIconProbe' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class NexoFlowIconProbe
{
    [DllImport("shell32.dll", EntryPoint = "ExtractIconExW", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern uint ExtractIconEx(
        string fileName, int iconIndex, out IntPtr largeIcon, out IntPtr smallIcon, uint count);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool DestroyIcon(IntPtr hIcon);

    public static bool ContainsBytes(byte[] haystack, byte[] needle)
    {
        if (needle == null || needle.Length == 0 || haystack == null || needle.Length > haystack.Length)
            return false;
        for (int i = 0; i <= haystack.Length - needle.Length; i++)
        {
            if (haystack[i] != needle[0]) continue;
            int j = 1;
            while (j < needle.Length && haystack[i + j] == needle[j]) j++;
            if (j == needle.Length) return true;
        }
        return false;
    }
}
'@
}

function Assert-ExecutableIcon {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string]$Icon
    )

    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "Executável ausente: $Executable"
    }
    if (-not (Test-Path -LiteralPath $Icon -PathType Leaf)) {
        throw "Ícone fonte ausente: $Icon"
    }

    $metadata = [Diagnostics.FileVersionInfo]::GetVersionInfo($Executable)
    if ($metadata.ProductName -ne "NexoFlow 1.5.9" -or $metadata.ProductVersion -ne "1.5.9.0") {
        throw "Metadados de versão incorretos: $Executable"
    }
    # The 0416/04B0 string table is Brazilian Portuguese with Unicode encoding.
    $metadataBytes = [IO.File]::ReadAllBytes($Executable)
    if (-not [NexoFlowIconProbe]::ContainsBytes($metadataBytes, [Text.Encoding]::Unicode.GetBytes("041604B0"))) {
        throw "Metadados pt-BR ausentes no executável: $Executable"
    }

    # ExtractIconEx consulta o grupo RT_GROUP_ICON registrado no PE.
    # Isso detecta executáveis Go sem ícone, mesmo que um .ico separado exista.
    $large = [IntPtr]::Zero
    $small = [IntPtr]::Zero
    $number = [NexoFlowIconProbe]::ExtractIconEx(
        $Executable, -1, [ref]$large, [ref]$small, [uint32]0
    )
    if ($number -lt 1) {
        throw "Executável sem grupo de ícone Windows: $Executable"
    }

    $large = [IntPtr]::Zero
    $small = [IntPtr]::Zero
    try {
        $extracted = [NexoFlowIconProbe]::ExtractIconEx(
            $Executable, 0, [ref]$large, [ref]$small, [uint32]1
        )
        if ($extracted -lt 1 -or ($large -eq [IntPtr]::Zero -and $small -eq [IntPtr]::Zero)) {
            throw "Windows não consegue extrair o ícone do .exe: $Executable"
        }
    }
    finally {
        if ($large -ne [IntPtr]::Zero) { [void][NexoFlowIconProbe]::DestroyIcon($large) }
        if ($small -ne [IntPtr]::Zero) { [void][NexoFlowIconProbe]::DestroyIcon($small) }
    }

    # Verifica também que TODAS as imagens embutidas correspondem ao .ico
    # certo (Analytics, Weni, Terminal, Setup ou Uninstall).
    $exeBytes = [IO.File]::ReadAllBytes($Executable)
    $icoBytes = [IO.File]::ReadAllBytes($Icon)
    if ($icoBytes.Length -lt 22 -or [BitConverter]::ToUInt16($icoBytes, 2) -ne 1) {
        throw "ICO inválido: $Icon"
    }
    $count = [int][BitConverter]::ToUInt16($icoBytes, 4)
    if ($count -lt 1 -or $icoBytes.Length -lt 6 + (16 * $count)) {
        throw "Tabela ICO inválida: $Icon"
    }

    for ($i = 0; $i -lt $count; $i++) {
        $length = [int][BitConverter]::ToUInt32($icoBytes, 6 + (16 * $i) + 8)
        $offset = [int][BitConverter]::ToUInt32($icoBytes, 6 + (16 * $i) + 12)
        if ($length -lt 1 -or $offset -lt 0 -or ([long]$offset + [long]$length) -gt $icoBytes.Length) {
            throw "Entrada ICO inválida: $Icon"
        }
        $image = [byte[]]::new($length)
        [Array]::Copy($icoBytes, $offset, $image, 0, $length)
        if (-not [NexoFlowIconProbe]::ContainsBytes($exeBytes, $image)) {
            throw "Imagem $($i + 1)/$count não está embutida em $Executable"
        }
    }
    Write-Host "[OK] Ícone Windows extraivel e correto: $([IO.Path]::GetFileName($Executable)) ($count imagens)"
}

$icons = @(
    @{ Executable = "NexoFlow Noturno.exe"; Icon = "NexoFlow_Noturno.ico" },
    @{ Executable = "NexoFlow Analytics.exe"; Icon = "NexoFlow.ico" },
    @{ Executable = "NexoFlow Weni.exe"; Icon = "NexoFlow_Weni.ico" },
    @{ Executable = "NexoFlow Recompra.exe"; Icon = "NexoFlow_Recompra.ico" },
    @{ Executable = "NexoFlow Planilha.exe"; Icon = "NexoFlow_Planilha.ico" },
    @{ Executable = "NexoFlow Terminal.exe"; Icon = "NexoFlow_Terminal.ico" },
    @{ Executable = "NexoFlow Uninstall.exe"; Icon = "uninstaller.ico" }
)

foreach ($base in @($Project, (Join-Path $Setup "payload"))) {
    foreach ($item in $icons) {
        Assert-ExecutableIcon -Executable (Join-Path $base $item.Executable) -Icon (Join-Path $base ("assets\" + $item.Icon))
    }
}

Assert-ExecutableIcon -Executable (Join-Path $Setup "NexoFlow Setup.exe") -Icon (Join-Path $RepoRoot "assets\installer.ico")

Write-Host "[OK] Os onze executáveis distribuídos possuem seus ícones PE corretos."
