//go:build noturno

package main

import (
	"bytes"
	"fmt"
	"strings"
	"testing"
	"time"
)

func TestNightResultStaysOpenUntilDismissed(t *testing.T) {
	for _, code := range []int{0, 1, 2, 3, 7, 130} {
		t.Run(fmt.Sprint(code), func(t *testing.T) {
			var output bytes.Buffer
			waiting := make(chan struct{})
			dismiss := make(chan struct{})
			result := make(chan int, 1)
			go func() {
				result <- finishNight(code, &output, func() {
					close(waiting)
					<-dismiss
				})
			}()
			defer close(dismiss)
			select {
			case <-waiting:
			case <-time.After(2 * time.Second):
				t.Fatal("O resultado não aguardou o fechamento da janela")
			}
			select {
			case <-result:
				t.Fatal("O launcher encerrou antes da confirmação de fechamento")
			default:
			}
			text := output.String()
			if !strings.Contains(text, fmt.Sprintf("Código de saída: %d", code)) ||
				!strings.Contains(text, `logs\noturno\`) {
				t.Fatalf("Resultado ou caminho dos relatórios ausente: %s", text)
			}
			dismiss <- struct{}{}
			select {
			case got := <-result:
				if got != code {
					t.Fatalf("Código alterado: %d; esperado %d", got, code)
				}
			case <-time.After(2 * time.Second):
				t.Fatal("O launcher não encerrou depois da confirmação")
			}
		})
	}
}

func TestNightHeadlessResultPreservesExitCode(t *testing.T) {
	for _, code := range []int{0, 3, 7} {
		var output bytes.Buffer
		if got := finishNight(code, &output, func() {}); got != code {
			t.Fatalf("Código alterado sem console: %d; esperado %d", got, code)
		}
	}
}
