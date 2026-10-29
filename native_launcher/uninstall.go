//go:build windows && uninstall

package main

import (
    "os"
    "path/filepath"
)

func main() {
    installDir, cleanup, rc := prepareLauncherWithProfile(false)
    if rc != 0 { os.Exit(rc) }
    defer cleanup()
    script := filepath.Join(installDir, "installer", "uninstall.ps1")
    if !requireFile(script) { os.Exit(2) }
    // Necessário enquanto o script PowerShell puder estar sem Authenticode.
    os.Exit(runChild(powershellPath(), "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script))
}
