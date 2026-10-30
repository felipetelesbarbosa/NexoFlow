//go:build windows && setup

package main

import (
    "fmt"
    "os"
    "path/filepath"
)

func main() {
    installDir, cleanup, rc := prepareLauncherWithProfile(false)
    if rc != 0 { os.Exit(rc) }
    defer cleanup()

    script := filepath.Join(installDir, "installer", "install.ps1")
    if !requireFile(script) { os.Exit(2) }

    // Necessário enquanto o script PowerShell puder estar sem Authenticode.
    args := []string{"-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script}
    nonInteractive := os.Getenv("NEXOFLOW_SETUP_NONINTERACTIVE") == "1"
    if nonInteractive {
        args = append(args, "-NonInteractive")
        if mode := os.Getenv("NEXOFLOW_SETUP_INSTALL_MODE"); mode != "" {
            args = append(args, "-InstallMode", mode)
        }
    }
    rc = runChild(powershellPath(), args...)
    if rc == 2 {
        fmt.Println("[INFO] Instalação cancelada. Nenhum arquivo instalado foi alterado.")
        os.Exit(rc)
    }
    if rc != 0 {
        fmt.Printf("\n[ERRO] O NexoFlow Setup foi encerrado com o código %d.\n", rc)
        fmt.Println("Consulte também o log:", "%TEMP%\\NexoFlow-Setup.log")
        if !nonInteractive {
            fmt.Println("A janela permanecerá aberta para que a causa possa ser lida.")
            waitEnter()
        }
    }
    os.Exit(rc)
}
// NexoFlow 1.5.4
