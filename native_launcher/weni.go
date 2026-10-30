//go:build windows && updateweni

package main

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
)

const iconMarker = "NexoFlowWeniIconRevision=1.5"

func main() {
	// Inspeção sem carga: não acessa BAT, Python, credenciais ou travas.
	// Usada pelo check-up enquanto o próprio segmento já está em execução.
	if len(os.Args) > 1 && os.Args[1] == "--build-info" {
		if len(os.Args) != 2 {
			fmt.Println("[ERRO] Use somente --build-info para inspecionar o launcher.")
			os.Exit(2)
		}
		fmt.Println(iconMarker)
		fmt.Println(buildMarker)
		return
	}
	if os.Getenv("NEXOFLOW_INTERNAL_BUILD_INFO") == "1" {
		fmt.Println(iconMarker)
	}
	runtime.KeepAlive(iconMarker)
	installDir, cleanup, rc := prepareLauncher()
	if rc != 0 {
		os.Exit(rc)
	}
	defer cleanup()
	batch := filepath.Join(installDir, "comandos/atualizar_weni.bat")
	if !requireFile(batch) {
		os.Exit(2)
	}
	os.Exit(runChild(cmdPath(), "/d", "/c", batch))
}
