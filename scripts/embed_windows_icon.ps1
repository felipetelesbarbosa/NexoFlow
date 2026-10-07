param(
    [Parameter(Mandatory = $true)][string]$ExecutablePath,
    [Parameter(Mandatory = $true)][string]$IconPath
)

$ErrorActionPreference = "Stop"

$exe = (Resolve-Path -LiteralPath $ExecutablePath -ErrorAction Stop).Path
$ico = (Resolve-Path -LiteralPath $IconPath -ErrorAction Stop).Path
if ([IO.Path]::GetExtension($exe) -ine ".exe") {
    throw "O destino precisa ser um executavel .exe: $exe"
}

if (-not ('NexoFlowIconResources' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class NexoFlowIconResources
{
    [DllImport("kernel32.dll", EntryPoint = "BeginUpdateResourceW", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr BeginUpdateResourceW(
        string fileName, [MarshalAs(UnmanagedType.Bool)] bool deleteExisting);

    [DllImport("kernel32.dll", EntryPoint = "UpdateResourceW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool UpdateResourceW(
        IntPtr handle, IntPtr type, IntPtr name, ushort language,
        byte[] data, uint length);

    [DllImport("kernel32.dll", EntryPoint = "EndUpdateResourceW", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool EndUpdateResourceW(
        IntPtr handle, [MarshalAs(UnmanagedType.Bool)] bool discard);

    [DllImport("kernel32.dll", EntryPoint = "LoadLibraryExW", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr LoadLibraryExW(string fileName, IntPtr hFile, uint flags);

    [DllImport("kernel32.dll", EntryPoint = "FindResourceExW", SetLastError = true)]
    public static extern IntPtr FindResourceExW(
        IntPtr module, IntPtr type, IntPtr name, ushort language);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool FreeLibrary(IntPtr module);

    [DllImport("shell32.dll", EntryPoint = "ExtractIconExW", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern uint ExtractIconExW(
        string fileName, int iconIndex,
        ref IntPtr largeIcon, ref IntPtr smallIcon, uint icons);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool DestroyIcon(IntPtr icon);
}
'@
}

# ICO: ICONDIR (6 bytes), ICONDIRENTRY (16 bytes por imagem).
# PE: RT_ICON (3) por imagem e RT_GROUP_ICON (14) com entradas de 14 bytes.
$iconBytes = [IO.File]::ReadAllBytes($ico)
if ($iconBytes.Length -lt 22) { throw "Arquivo .ico incompleto: $ico" }

$memory = [IO.MemoryStream]::new($iconBytes, $false)
$reader = [IO.BinaryReader]::new($memory)
try {
    $reserved = $reader.ReadUInt16()
    $kind = $reader.ReadUInt16()
    $count = [int]$reader.ReadUInt16()
    if ($reserved -ne 0 -or $kind -ne 1 -or $count -lt 1 -or $count -gt 255) {
        throw "Cabecalho ICO invalido: $ico"
    }
    if ($iconBytes.Length -lt 6 + (16 * $count)) {
        throw "Tabela de imagens ICO incompleta: $ico"
    }

    $images = @()
    for ($i = 0; $i -lt $count; $i++) {
        $reader.BaseStream.Position = 6 + (16 * $i)
        $width = $reader.ReadByte()
        $height = $reader.ReadByte()
        $colors = $reader.ReadByte()
        $reservedByte = $reader.ReadByte()
        $planes = $reader.ReadUInt16()
        $bits = $reader.ReadUInt16()
        $size = [int]$reader.ReadUInt32()
        $offset = [int]$reader.ReadUInt32()
        if (
            $reservedByte -ne 0 -or $size -le 0 -or $offset -lt 0 -or
            ([long]$offset + [long]$size) -gt $iconBytes.Length
        ) {
            throw "Imagem ICO invalida na posicao $i ($ico)"
        }

        # Alguns ICOs baseados em PNG trazem planes/bits como zero. O shell do
        # Windows e mais consistente quando o GRPICONDIR informa 1/32.
        if ($planes -eq 0) { $planes = 1 }
        if ($bits -eq 0) { $bits = 32 }

        $payload = [byte[]]::new($size)
        [Array]::Copy($iconBytes, $offset, $payload, 0, $size)
        $images += [pscustomobject]@{
            Width = $width
            Height = $height
            Colors = $colors
            Planes = $planes
            Bits = $bits
            Size = $size
            Id = ($i + 1)
            Bytes = $payload
        }
    }
}
finally {
    $reader.Dispose()
    $memory.Dispose()
}

# GRPICONDIR preserva a ordem e os tamanhos da fonte .ico.
$groupStream = [IO.MemoryStream]::new()
$groupWriter = [IO.BinaryWriter]::new($groupStream)
try {
    $groupWriter.Write([uint16]0)
    $groupWriter.Write([uint16]1)
    $groupWriter.Write([uint16]$count)
    foreach ($item in $images) {
        $groupWriter.Write([byte]$item.Width)
        $groupWriter.Write([byte]$item.Height)
        $groupWriter.Write([byte]$item.Colors)
        $groupWriter.Write([byte]0)
        $groupWriter.Write([uint16]$item.Planes)
        $groupWriter.Write([uint16]$item.Bits)
        $groupWriter.Write([uint32]$item.Size)
        $groupWriter.Write([uint16]$item.Id)
    }
    $groupWriter.Flush()
    $groupBytes = $groupStream.ToArray()
}
finally {
    $groupWriter.Dispose()
    $groupStream.Dispose()
}

# O build anterior gravava apenas en-US (1033). Em Windows pt-BR isso pode
# resultar em Explorer/atalhos exibindo o icone generico. Gravamos a mesma
# arvore como neutral (0), pt-BR (1046) e en-US (1033).
$languages = @([uint16]0, [uint16]1046, [uint16]1033)

$handle = [NexoFlowIconResources]::BeginUpdateResourceW($exe, $false)
if ($handle -eq [IntPtr]::Zero) {
    $code = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    throw "BeginUpdateResourceW falhou ($code) para $exe"
}

$committed = $false
try {
    foreach ($language in $languages) {
        foreach ($item in $images) {
            $ok = [NexoFlowIconResources]::UpdateResourceW(
                $handle, [IntPtr]3, [IntPtr]$item.Id, $language,
                [byte[]]$item.Bytes, [uint32]$item.Size
            )
            if (-not $ok) {
                $code = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
                throw "Nao foi possivel embutir RT_ICON $($item.Id), lang=$language em $exe ($code)"
            }
        }

        $ok = [NexoFlowIconResources]::UpdateResourceW(
            $handle, [IntPtr]14, [IntPtr]1, $language,
            [byte[]]$groupBytes, [uint32]$groupBytes.Length
        )
        if (-not $ok) {
            $code = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
            throw "Nao foi possivel embutir RT_GROUP_ICON, lang=$language em $exe ($code)"
        }
    }

    if (-not [NexoFlowIconResources]::EndUpdateResourceW($handle, $false)) {
        $code = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        throw "EndUpdateResourceW falhou ($code) para $exe"
    }
    $committed = $true
}
finally {
    if (-not $committed) {
        [void][NexoFlowIconResources]::EndUpdateResourceW($handle, $true)
    }
}

# Validacao real do PE depois da gravacao. A release deve falhar se o recurso
# neutral/pt-BR nao existir ou se o shell32 nao conseguir extrair o icone.
$LOAD_LIBRARY_AS_DATAFILE = [uint32]2
$module = [NexoFlowIconResources]::LoadLibraryExW(
    $exe, [IntPtr]::Zero, $LOAD_LIBRARY_AS_DATAFILE
)
if ($module -eq [IntPtr]::Zero) {
    $code = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    throw "Nao foi possivel reabrir o PE para validar o icone ($code): $exe"
}
try {
    foreach ($language in @([uint16]0, [uint16]1046)) {
        $resource = [NexoFlowIconResources]::FindResourceExW(
            $module, [IntPtr]14, [IntPtr]1, $language
        )
        if ($resource -eq [IntPtr]::Zero) {
            throw "RT_GROUP_ICON ausente apos o build (lang=$language): $exe"
        }
    }
}
finally {
    [void][NexoFlowIconResources]::FreeLibrary($module)
}

$large = [IntPtr]::Zero
$small = [IntPtr]::Zero
$extracted = [NexoFlowIconResources]::ExtractIconExW(
    $exe, 0, [ref]$large, [ref]$small, [uint32]1
)
try {
    if ($extracted -lt 1 -or ($large -eq [IntPtr]::Zero -and $small -eq [IntPtr]::Zero)) {
        throw "shell32 nao conseguiu extrair o icone do executavel: $exe"
    }
}
finally {
    if ($large -ne [IntPtr]::Zero) { [void][NexoFlowIconResources]::DestroyIcon($large) }
    if ($small -ne [IntPtr]::Zero) { [void][NexoFlowIconResources]::DestroyIcon($small) }
}

Write-Host "[OK] Icone PE embutido e validado: $([IO.Path]::GetFileName($exe)) ($count tamanhos; neutral/pt-BR/en-US)"
