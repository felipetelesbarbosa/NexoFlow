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
    campaign := "FarmaLíder D+25"
    if os.Getenv("NEXOFLOW_PERFIL") == "PET" { campaign = "Pets Líder D+30" }
    fmt.Println("NexoFlow Recompra " + campaign + ": auditoria e confirmação obrigatórias.")
    os.Exit(runChild(cmdPath(), "/d", "/c", batch))
}
