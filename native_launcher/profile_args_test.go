//go:build windows

package main

import ("testing"; "bufio"; "strings"; "bytes")

func TestProfileArgumentsKeepNightModeAndRejectUnknownProfile(t *testing.T) {
    args, profile, err := profileArguments([]string{"nexo.exe", "--perfil", "PET", "--full"})
    if err != nil || profile != "PET" || len(args) != 2 || args[1] != "--full" { t.Fatal(args, profile, err) }
    for _, invalid := range [][]string{{"nexo.exe", "--perfil"}, {"nexo.exe", "--perfil", "OUTRO"}, {"nexo.exe", "--perfil", "PET", "--perfil", "FARMA"}} {
        if _, _, err := profileArguments(invalid); err == nil { t.Fatal("Perfil inválido aceito", invalid) }
    }
}

func TestSegmentMenuRetriesAndLeavesNextAnswerForNightMode(t *testing.T) {
    input := bufio.NewReader(strings.NewReader("errado\n2\n1\n"))
    var output bytes.Buffer
    profile, rc := selectProfile(input, &output)
    if rc != 0 || profile != "PET" { t.Fatal(profile, rc) }
    remaining, _ := input.ReadString('\n')
    if remaining != "1\n" { t.Fatal("Menu consumiu a próxima resposta", remaining) }
    if !strings.Contains(output.String(), "Opção inválida") { t.Fatal("Não ofereceu nova tentativa") }
}
