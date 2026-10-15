//go:build windows && planilha

package main

import (
    "os"
    "path/filepath"
)

func main() {
    installDir, cleanup, rc := prepareLauncher()
    if rc != 0 { os.Exit(rc) }
    // A trava operacional permanece enquanto o menu e a carga estão abertos.
    batch := filepath.Join(installDir, "comandos/executar_planilha.bat")
    if !requireFile(batch) { cleanup(); os.Exit(2) }
    rc = runChild(cmdPath(), "/d", "/c", batch)
    cleanup()
    os.Exit(rc)
}
