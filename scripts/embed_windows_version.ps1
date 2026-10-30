param(
    [Parameter(Mandatory = $true)][string]$ExecutablePath,
    [Parameter(Mandatory = $true)][string]$Description,
    [string]$Version = "1.5.4"
)

$ErrorActionPreference = "Stop"
if (-not ('NexoFlowVersionResource' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Text;
using System.Runtime.InteropServices;

public static class NexoFlowVersionResource {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr BeginUpdateResourceW(string path, bool delete);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool UpdateResourceW(IntPtr handle, IntPtr type, IntPtr name,
        ushort language, byte[] data, uint size);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool EndUpdateResourceW(IntPtr handle, bool discard);

    static void Align(BinaryWriter writer) {
        while (writer.BaseStream.Position % 4 != 0) writer.Write((byte)0);
    }
    static byte[] Block(string key, ushort type, byte[] value, ushort length, params byte[][] children) {
        using (var stream = new MemoryStream())
        using (var writer = new BinaryWriter(stream)) {
            writer.Write((ushort)0); writer.Write(length); writer.Write(type);
            writer.Write(Encoding.Unicode.GetBytes(key + "\0")); Align(writer);
            writer.Write(value);
            foreach (var child in children) { Align(writer); writer.Write(child); }
            var bytes = stream.ToArray();
            var size = BitConverter.GetBytes(checked((ushort)bytes.Length));
            bytes[0] = size[0]; bytes[1] = size[1];
            return bytes;
        }
    }
    static byte[] Text(string key, string value) {
        return Block(key, 1, Encoding.Unicode.GetBytes(value + "\0"),
            checked((ushort)(value.Length + 1)));
    }
    public static void Embed(string path, string description, string release) {
        var parsed = Version.Parse(release);
        int build = Math.Max(parsed.Build, 0);
        string windowsVersion = parsed.Major + "." + parsed.Minor + "." + build + ".0";
        uint high = ((uint)parsed.Major << 16) | (uint)parsed.Minor;
        uint low = (uint)build << 16;
        byte[] fixedInfo;
        using (var stream = new MemoryStream())
        using (var writer = new BinaryWriter(stream)) {
            foreach (uint value in new uint[] {
                0xFEEF04BD, 0x00010000, high, low, high, low,
                0x3F, 0, 0x00040004, 1, 0, 0, 0
            }) writer.Write(value);
            fixedInfo = stream.ToArray();
        }
        var strings = Block("StringFileInfo", 1, new byte[0], 0,
            Block("041604B0", 1, new byte[0], 0,
                Text("CompanyName", "Grupo Líder"),
                Text("FileDescription", description),
                Text("FileVersion", windowsVersion),
                Text("ProductName", "NexoFlow " + release),
                Text("ProductVersion", windowsVersion),
                Text("OriginalFilename", Path.GetFileName(path))));
        var translation = Block("VarFileInfo", 1, new byte[0], 0,
            Block("Translation", 0, new byte[] {0x16, 0x04, 0xB0, 0x04}, 4));
        var data = Block("VS_VERSION_INFO", 0, fixedInfo, 52, strings, translation);
        var handle = BeginUpdateResourceW(path, false);
        if (handle == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
        bool success = false;
        try {
            if (!UpdateResourceW(handle, (IntPtr)16, (IntPtr)1, 1046, data, (uint)data.Length))
                throw new System.ComponentModel.Win32Exception();
            // Rebuilding a PE also requires restoring its privilege manifest.
            string manifest = @"<?xml version=""1.0"" encoding=""UTF-8"" standalone=""yes""?>
<assembly xmlns=""urn:schemas-microsoft-com:asm.v1"" manifestVersion=""1.0"">
<assemblyIdentity name=""NexoFlow"" version=""%VERSION%"" processorArchitecture=""amd64"" type=""win32""/>
<trustInfo xmlns=""urn:schemas-microsoft-com:asm.v3""><security><requestedPrivileges>
<requestedExecutionLevel level=""asInvoker"" uiAccess=""false""/>
</requestedPrivileges></security></trustInfo>
</assembly>";
            var manifestBytes = Encoding.UTF8.GetBytes(manifest.Replace("%VERSION%", windowsVersion));
            if (!UpdateResourceW(handle, (IntPtr)24, (IntPtr)1, 0, manifestBytes, (uint)manifestBytes.Length))
                throw new System.ComponentModel.Win32Exception();
            success = true;
        } finally {
            if (!EndUpdateResourceW(handle, !success))
                throw new System.ComponentModel.Win32Exception();
        }
    }
}
'@
}

[NexoFlowVersionResource]::Embed((Resolve-Path -LiteralPath $ExecutablePath).Path, $Description, $Version)
Write-Host "[OK] Metadados do executável em português brasileiro (pt-BR): $Description"
