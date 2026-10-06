//go:build windows && updateweni

package main

import (
    "fmt"
    "os"
    "path/filepath"
    "runtime"
)

const iconMarker = "NexoFlowWeniIconRevision=1.0"

func main() {
    if os.Getenv("NEXOFLOW_INTERNAL_BUILD_INFO") == "1" { fmt.Println(iconMarker) }
    runtime.KeepAlive(iconMarker)
    installDir, cleanup, rc := prepareLauncher()
    if rc != 0 { os.Exit(rc) }
    defer cleanup()
    batch := filepath.Join(installDir, "atualizar_weni.bat")
    if !requireFile(batch) { os.Exit(2) }
    os.Exit(runChild(cmdPath(), "/d", "/c", batch))
}
