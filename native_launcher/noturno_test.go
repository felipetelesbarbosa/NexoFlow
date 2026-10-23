//go:build windows && noturno

package main

import (
    "bufio"
    "strings"
    "testing"
)

func TestNightModeSelection(t *testing.T) {
    cases := []struct {
        name string
        args []string
        input string
        mode string
        code int
    }{
        {"incremental", nil, "1\n", "--incremental", 0},
        {"completa", nil, "2\r\n", "--full", 0},
        {"corrigir opcao", nil, "errado\n2\n", "--full", 0},
        {"sair", nil, "0\n", "", 0},
        {"sem entrada", nil, "", "", 2},
        {"agendamento incremental", []string{"--incremental"}, "", "--incremental", 0},
        {"agendamento completo", []string{"--full"}, "", "--full", 0},
        {"argumento invalido", []string{"--outro"}, "", "", 2},
        {"modos conflitantes", []string{"--full", "--incremental"}, "", "", 2},
    }
    for _, c := range cases {
        t.Run(c.name, func(t *testing.T) {
            mode, code := selectNightMode(c.args, bufio.NewReader(strings.NewReader(c.input)))
            if mode != c.mode || code != c.code { t.Fatalf("mode=%q code=%d", mode, code) }
        })
    }
}
