//go:build windows && recompra

package main

import (
    "fmt"
    "os"
    "path/filepath"
)

// Executa a rotina dedicada com check-up, dry-run, revisão humana e apply.
// Nunca adiciona contatos sem passar pela auditoria do .bat.
func main() {
    installDir, cleanup, rc := prepareLauncher()
    if rc != 0 { os.Exit(rc) }
    defer cleanup()
    batch := filepath.Join(installDir, "comandos/atualizar_recompra.bat")
    if !requireFile(batch) { os.Exit(2) }
    fmt.Println("NexoFlow Recompra FarmaLider D+25: auditoria e confirmacao obrigatorias.")
    os.Exit(runChild(cmdPath(), "/d", "/c", batch))
}
