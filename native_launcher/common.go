//go:build windows

package main

import (
    "bufio"
    "fmt"
    "io"
    "strings"
    "os"
    "os/exec"
    "path/filepath"
    "runtime"
    "syscall"
    "unsafe"
)

const (
    mutexName   = `Local\NexoFlowOperationLock`
    buildMarker = "NexoFlowNativeLauncher=1.5"
)

var (
    kernel32         = syscall.NewLazyDLL("kernel32.dll")
    procCreateMutexW = kernel32.NewProc("CreateMutexW")
    procGetLastError = kernel32.NewProc("GetLastError")
)

// UTF-8 keeps accented Portuguese readable in CMD and redirected diagnostics.
func init() {
    kernel32.NewProc("SetConsoleCP").Call(65001)
    kernel32.NewProc("SetConsoleOutputCP").Call(65001)
    args, profile, err := profileArguments(os.Args)
    if err != nil { fmt.Println("[ERRO]", err); os.Exit(2) }
    os.Args = args
    if profile != "" { os.Setenv("NEXOFLOW_PERFIL", profile) }
    if selected := os.Getenv("NEXOFLOW_PERFIL"); selected != "" { fmt.Println("[INFO] Perfil:", selected) }

}

func selectProfile(input *bufio.Reader, output io.Writer) (string, int) {
    for {
        fmt.Fprintln(output, "NexoFlow — escolha o segmento")
        fmt.Fprintln(output, "[1] FarmaLíder")
        fmt.Fprintln(output, "[2] Pets Líder")
        fmt.Fprint(output, "Escolha: ")
        line, err := input.ReadString('\n')
        if err != nil { return "", 2 }
        switch strings.TrimSpace(line) {
        case "1": return "FARMA", 0
        case "2": return "PET", 0
        default: fmt.Fprintln(output, "[AVISO] Opção inválida. Tente novamente.")
        }
    }
}

func ensureProfile(input *bufio.Reader) int {
    existing := os.Getenv("NEXOFLOW_PERFIL")
    if existing == "FARMA" || existing == "PET" { return 0 }
    if existing != "" { fmt.Println("[ERRO] Perfil inválido."); return 2 }
    if os.Getenv("NEXOFLOW_INTERNAL_BUILD_INFO") == "1" { os.Setenv("NEXOFLOW_PERFIL", "FARMA"); return 0 }
    profile, rc := selectProfile(input, os.Stdout)
    if rc == 0 { os.Setenv("NEXOFLOW_PERFIL", profile); fmt.Println("[INFO] Perfil:", profile) }
    return rc
}

func profileArguments(args []string) ([]string, string, error) {
    out := []string{}
    profile := ""
    for i := 0; i < len(args); i++ {
        if args[i] != "--perfil" { out = append(out, args[i]); continue }
        if i+1 >= len(args) || (args[i+1] != "FARMA" && args[i+1] != "PET") {
            return nil, "", fmt.Errorf("--perfil exige FARMA ou PET")
        }
        if profile != "" && profile != args[i+1] { return nil, "", fmt.Errorf("Perfis divergentes") }
        profile = args[i+1]; i++
    }
    return out, profile, nil
}

const errorAlreadyExists = 183

func utf16Ptr(s string) *uint16 {
    p, _ := syscall.UTF16PtrFromString(s)
    return p
}

func acquireMutex() (syscall.Handle, bool) {
    handle, _, _ := procCreateMutexW.Call(0, 0, uintptr(unsafe.Pointer(utf16Ptr(mutexName))))
    if handle == 0 {
        return 0, false
    }
    lastErr, _, _ := procGetLastError.Call()
    return syscall.Handle(handle), lastErr != errorAlreadyExists
}

func waitEnter() {
    if os.Getenv("NEXOFLOW_UNATTENDED") == "1" { return }
    fmt.Print("\nPressione ENTER para fechar...")
    _, _ = bufio.NewReader(os.Stdin).ReadString('\n')
}

func system32(parts ...string) string {
    root := os.Getenv("SystemRoot")
    if root == "" {
        root = `C:\Windows`
    }
    args := append([]string{root, "System32"}, parts...)
    return filepath.Join(args...)
}

func cmdPath() string {
    return system32("cmd.exe")
}

func powershellPath() string {
    return system32("WindowsPowerShell", "v1.0", "powershell.exe")
}

func runChild(name string, args ...string) int {
    cmd := exec.Command(name, args...)
    cmd.Stdin = os.Stdin
    cmd.Stdout = os.Stdout
    cmd.Stderr = os.Stderr
    cmd.Env = os.Environ()
    if err := cmd.Run(); err != nil {
        if exitErr, ok := err.(*exec.ExitError); ok {
            return exitErr.ExitCode()
        }
        fmt.Fprintf(os.Stderr, "[ERRO] Não foi possível iniciar o processo: %v\n", err)
        return 1
    }
    if cmd.ProcessState == nil {
        return 1
    }
    return cmd.ProcessState.ExitCode()
}

func prepareLauncher() (string, func(), int) {
    return prepareLauncherWithProfile(true)
}

func prepareLauncherWithProfile(selectSegment bool) (string, func(), int) {
    if selectSegment {
        if rc := ensureProfile(bufio.NewReader(os.Stdin)); rc != 0 { return "", func(){}, rc }
    }
    if os.Getenv("NEXOFLOW_INTERNAL_BUILD_INFO") == "1" {
        fmt.Println(buildMarker)
    }
    runtime.KeepAlive(buildMarker)

    exe, err := os.Executable()
    if err != nil {
        fmt.Fprintf(os.Stderr, "[ERRO] Não foi possível localizar o executável: %v\n", err)
        waitEnter()
        return "", func(){}, 1
    }
    exe, _ = filepath.Abs(exe)
    installDir := filepath.Dir(exe)
    if err := os.Chdir(installDir); err != nil {
        fmt.Fprintf(os.Stderr, "[ERRO] Não foi possível acessar a pasta do NexoFlow: %v\n", err)
        waitEnter()
        return "", func(){}, 1
    }

    handle, acquired := acquireMutex()
    cleanup := func() {
        if handle != 0 {
            syscall.CloseHandle(handle)
        }
    }
    if !acquired {
        fmt.Println("[AVISO] Existe uma sincronização, instalação ou desinstalação do NexoFlow em andamento.")
        waitEnter()
        cleanup()
        return "", func(){}, 2
    }
    return installDir, cleanup, 0
}

func requireFile(path string) bool {
    if _, err := os.Stat(path); err != nil {
        fmt.Printf("[ERRO] Arquivo não encontrado: %s\n", path)
        waitEnter()
        return false
    }
    return true
}
