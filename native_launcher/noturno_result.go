//go:build noturno

package main

import (
	"fmt"
	"io"
	"os"
)

func finishNight(code int, output io.Writer, wait func()) int {
	switch code {
	case 0:
		fmt.Fprintln(output, "\n[OK] NexoFlow Noturno concluído com sucesso.")
	case 3:
		fmt.Fprintln(output, "\n[AVISO] NexoFlow Noturno terminou com resultado parcial.")
	case 130:
		fmt.Fprintln(output, "\n[AVISO] NexoFlow Noturno foi interrompido.")
	default:
		fmt.Fprintln(output, "\n[ERRO] NexoFlow Noturno não foi concluído.")
	}
	fmt.Fprintf(output, "Código de saída: %d\n", code)
	if os.Getenv("NEXOFLOW_PERFIL") == "PET" {
		fmt.Fprintln(output, `Relatórios da rotina: logs\PET\noturno\ (na pasta do NexoFlow).`)
	} else {
		fmt.Fprintln(output, `Relatórios da rotina: logs\noturno\ (na pasta do NexoFlow).`)
	}
	fmt.Fprintln(output, "Se a rotina não chegou a iniciar, confira a mensagem de erro acima.")
	wait()
	return code
}
