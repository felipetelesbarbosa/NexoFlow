//go:build windows && noturno

package main

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"unsafe"
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
		if err != nil {
			return "", 2
		}
		switch strings.TrimSpace(line) {
		case "1":
			return "--incremental", 0
		case "2":
			return "--full", 0
		case "0":
			return "", 0
		default:
			fmt.Println("[AVISO] Opção inválida. Tente novamente.")
		}
	}
}

func runNight(mode string) int {
	os.Setenv("NEXOFLOW_UNATTENDED", "1")
	installDir, cleanup, rc := prepareLauncher()
	if rc != 0 {
		return rc
	}
	defer cleanup()
	python := filepath.Join(installDir, ".venv", "Scripts", "python.exe")
	script := filepath.Join(installDir, "app", "run_noturno.py")
	if !requireFile(python) || !requireFile(script) {
		return 2
	}
	return runChild(python, script, mode)
}

func waitNightConsole(input *bufio.Reader) {
	// Tarefas sem sessão e pipes não devem aguardar uma tecla indisponível.
	var mode uint32
	console, _, _ := kernel32.NewProc("GetConsoleMode").Call(
		os.Stdin.Fd(), uintptr(unsafe.Pointer(&mode)),
	)
	if console == 0 {
		return
	}
	fmt.Print("\nPressione ENTER para fechar esta janela...")
	_, _ = input.ReadString('\n')
}

func main() {
	input := bufio.NewReader(os.Stdin)
	mode, rc := selectNightMode(os.Args[1:], input)
	if rc == 0 && mode == "" {
		return
	}
	if rc == 0 {
		rc = runNight(mode)
	}
	// Libera a trava antes de deixar a janela com o resultado aberta.
	os.Exit(finishNight(rc, os.Stdout, func() { waitNightConsole(input) }))
}
