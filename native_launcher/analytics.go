//go:build windows && analytics

package main

import (
    "os"
    "path/filepath"
)

func main() {
    installDir, cleanup, rc := prepareLauncher()
    if rc != 0 { os.Exit(rc) }
    defer cleanup()
    batch := filepath.Join(installDir, "comandos/executar_carga_segura.bat")
    if !requireFile(batch) { os.Exit(2) }
    os.Exit(runChild(cmdPath(), "/d", "/c", batch))
}
