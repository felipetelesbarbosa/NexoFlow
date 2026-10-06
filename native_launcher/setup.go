//go:build windows && setup

package main

import (
    "fmt"
    "os"
    "path/filepath"
)

func main() {
    installDir, cleanup, rc := prepareLauncher()
    if rc != 0 { os.Exit(rc) }
    defer cleanup()

    script := filepath.Join(installDir, "installer", "install.ps1")
    if !requireFile(script) { os.Exit(2) }

    // Necessário enquanto o script PowerShell puder estar sem Authenticode.
    rc = runChild(powershellPath(), "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script)
    if rc != 0 {
        fmt.Printf("\n[ERRO] O NexoFlow Setup foi encerrado com o codigo %d.\n", rc)
        fmt.Println("A janela permanecera aberta para que a causa possa ser lida.")
        fmt.Println("Consulte tambem o log: %TEMP%\\NexoFlow-Setup.log")
        waitEnter()
    }
    os.Exit(rc)
}
