//go:build windows && noturno

package main

import (
	"fmt"
	"os"
	"unsafe"
)

// INPUT_RECORD com a união KEY_EVENT_RECORD (20 bytes no Win32/Win64).
type nightConsoleEvent struct {
	EventType       uint16
	Padding         uint16
	KeyDown         int32
	RepeatCount     uint16
	VirtualKeyCode  uint16
	VirtualScanCode uint16
	UnicodeChar     uint16
	ControlKeyState uint32
}

func waitNightConsole() {
	if !nightHasConsole() {
		return
	}
	// A entrada padrão pode ser um pipe ou já ter sido encerrada, mesmo
	// com a janela aberta. CONIN$ acessa o console anexado ao processo.
	input, err := os.OpenFile("CONIN$", os.O_RDWR, 0)
	if err != nil {
		holdNightConsole()
		return
	}
	defer input.Close()

	flushed, _, _ := kernel32.NewProc("FlushConsoleInputBuffer").Call(input.Fd())
	if flushed == 0 {
		holdNightConsole()
		return
	}
	fmt.Println("\nPressione ENTER para fechar esta janela...")
	readInput := kernel32.NewProc("ReadConsoleInputW")
	for {
		var event nightConsoleEvent
		var count uint32
		read, _, _ := readInput.Call(
			input.Fd(), uintptr(unsafe.Pointer(&event)), 1,
			uintptr(unsafe.Pointer(&count)),
		)
		if read == 0 {
			holdNightConsole()
			return
		}
		// Ignora eventos de mouse, foco, teclas soltas e qualquer tecla
		// diferente de um ENTER novo, digitado após o resumo final.
		if count == 1 && event.EventType == 1 && event.KeyDown != 0 && event.VirtualKeyCode == 13 {
			return
		}
	}
}

func nightHasConsole() bool {
	// CREATE_NO_WINDOW pode manter um objeto console sem janela. O
	// Windows Terminal também fornece esse handle para seu pseudoconsole.
	window, _, _ := kernel32.NewProc("GetConsoleWindow").Call()
	return window != 0
}

func holdNightConsole() {
	fmt.Println("[AVISO] Não foi possível ler o teclado. A janela continuará aberta; feche-a manualmente após conferir o resultado.")
	// Aguarda o próprio processo, sem consumo de CPU nem timeout que
	// feche a janela. O usuário ainda pode encerrá-la pelo botão Fechar.
	kernel32.NewProc("WaitForSingleObject").Call(^uintptr(0), 0xffffffff)
}
