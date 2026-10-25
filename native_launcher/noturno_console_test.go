//go:build windows && noturno

package main

import (
	"bufio"
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
	"unsafe"
)

func writeNightTestKey(input *os.File, key uint16) error {
	event := nightConsoleEvent{EventType: 1, KeyDown: 1, RepeatCount: 1, VirtualKeyCode: key, UnicodeChar: key}
	var written uint32
	ok, _, err := kernel32.NewProc("WriteConsoleInputW").Call(
		input.Fd(), uintptr(unsafe.Pointer(&event)), 1, uintptr(unsafe.Pointer(&written)),
	)
	if ok == 0 || written != 1 {
		return fmt.Errorf("não foi possível inserir tecla no console: %v", err)
	}
	return nil
}

func TestNightConsoleHelper(t *testing.T) {
	value := os.Getenv("NEXOFLOW_TEST_NIGHT_CONSOLE_CODE")
	if value == "" {
		return
	}
	code, err := strconv.Atoi(value)
	if err != nil {
		t.Fatal(err)
	}
	var mode uint32
	if ok, _, _ := kernel32.NewProc("GetConsoleMode").Call(os.Stdin.Fd(), uintptr(unsafe.Pointer(&mode))); ok != 0 {
		t.Fatal("O teste exige stdin redirecionado para reproduzir o encerramento prematuro")
	}
	input, err := os.OpenFile("CONIN$", os.O_RDWR, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer input.Close()
	// Simula um ENTER deixado na fila durante a execução: não pode fechar.
	if err := writeNightTestKey(input, 13); err != nil {
		t.Fatal(err)
	}
	go func() {
		scanner := bufio.NewScanner(os.Stdin)
		for scanner.Scan() {
			var key uint16 = 32
			if scanner.Text() == "ENTER" {
				key = 13
			}
			if err := writeNightTestKey(input, key); err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(99)
			}
		}
	}()
	os.Exit(finishNight(code, os.Stdout, waitNightConsole))
}

func TestNightRealConsoleIgnoresRedirectedStdinAndQueuedEnter(t *testing.T) {
	for _, code := range []int{0, 2, 3, 7} {
		t.Run(strconv.Itoa(code), func(t *testing.T) {
			command := exec.Command(os.Args[0], "-test.run=^TestNightConsoleHelper$")
			command.Env = append(os.Environ(), fmt.Sprintf("NEXOFLOW_TEST_NIGHT_CONSOLE_CODE=%d", code))
			// Console próprio, sem tocar no console do runner ou da sessão.
			command.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x00000010, HideWindow: true}
			stdin, err := command.StdinPipe()
			if err != nil {
				t.Fatal(err)
			}
			defer stdin.Close()
			stdout, err := command.StdoutPipe()
			if err != nil {
				t.Fatal(err)
			}
			var stderr bytes.Buffer
			command.Stderr = &stderr
			if err := command.Start(); err != nil {
				t.Fatal(err)
			}
			defer command.Process.Kill()
			ready := make(chan bool, 1)
			go func() {
				scanner := bufio.NewScanner(stdout)
				for scanner.Scan() {
					if strings.Contains(scanner.Text(), "Pressione ENTER") {
						ready <- true
						return
					}
				}
				ready <- false
			}()
			select {
			case found := <-ready:
				if !found {
					t.Fatal("O processo encerrou sem aguardar confirmação no console")
				}
			case <-time.After(15 * time.Second):
				t.Fatal("O processo não apresentou a espera final")
			}
			done := make(chan error, 1)
			go func() { done <- command.Wait() }()
			// Nem o ENTER antigo nem uma tecla diferente podem encerrar.
			if _, err := fmt.Fprintln(stdin, "SPACE"); err != nil {
				t.Fatal(err)
			}
			select {
			case err := <-done:
				t.Fatalf("Console fechou antes de novo ENTER: %v; %s", err, stderr.String())
			case <-time.After(200 * time.Millisecond):
			}
			if _, err := fmt.Fprintln(stdin, "ENTER"); err != nil {
				t.Fatal(err)
			}
			select {
			case <-done:
				if command.ProcessState.ExitCode() != code {
					t.Fatalf("Código alterado: %d; esperado %d; %s", command.ProcessState.ExitCode(), code, stderr.String())
				}
			case <-time.After(10 * time.Second):
				t.Fatal("O console não encerrou após novo ENTER")
			}
		})
	}
}
