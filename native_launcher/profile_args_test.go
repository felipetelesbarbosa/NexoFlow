//go:build windows

package main

import "testing"

func TestProfileArgumentsKeepNightModeAndRejectUnknownProfile(t *testing.T) {
    args, profile, err := profileArguments([]string{"nexo.exe", "--perfil", "PET", "--full"})
    if err != nil || profile != "PET" || len(args) != 2 || args[1] != "--full" { t.Fatal(args, profile, err) }
    for _, invalid := range [][]string{{"nexo.exe", "--perfil"}, {"nexo.exe", "--perfil", "OUTRO"}, {"nexo.exe", "--perfil", "PET", "--perfil", "FARMA"}} {
        if _, _, err := profileArguments(invalid); err == nil { t.Fatal("Perfil inválido aceito", invalid) }
    }
}
