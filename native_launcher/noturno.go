//go:build windows && noturno

package main

import (
    "bufio"
    "fmt"
    "os"
    "path/filepath"
    "strings"
)

func selectNightMode(args []string, input *bufio.Reader) (string, int) {
    if len(args) == 1 && (args[0] == "--incremental" || args[0] == "--full") {
        return args[0], 0
    }
    if len(args) != 0 {
        fmt.Println("[ERRO] Use --incremental ou --full para iniciar sem menu.")
        return "", 2
    }
    for {
        fmt.Println("NexoFlow Noturno — Weni + Analytics + Recompra")
        fmt.Println("[1] Incremental")
        fmt.Println("[2] Carga completa 100%")
        fmt.Println("[0] Sair")
        fmt.Print("Escolha uma opção: ")
        line, err := input.ReadString('\n')
        if err != nil { return "", 2 }
        switch strings.TrimSpace(line) {
        case "1": return "--incremental", 0
        case "2": return "--full", 0
        case "0": return "", 0
        default: fmt.Println("[AVISO] Opção inválida. Tente novamente.")
        }
    }
}

func main() {
    os.Setenv("NEXOFLOW_UNATTENDED", "1")
    installDir, cleanup, rc := prepareLauncher()
    if rc != 0 { os.Exit(rc) }
    defer cleanup()
    mode, rc := selectNightMode(os.Args[1:], bufio.NewReader(os.Stdin))
    if rc != 0 || mode == "" { os.Exit(rc) }
    python := filepath.Join(installDir, ".venv", "Scripts", "python.exe")
    script := filepath.Join(installDir, "app", "run_noturno.py")
    if !requireFile(python) || !requireFile(script) { os.Exit(2) }
    os.Exit(runChild(python, script, mode))
}
