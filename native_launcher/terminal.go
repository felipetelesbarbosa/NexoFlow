//go:build windows && terminal

package main

import (
    "fmt"
    "os"
    "os/exec"
    "path/filepath"
    "runtime"
)

const terminalMarker = "NexoFlowTerminalIconRevision=1.0"

func findPython(installDir string) (string, []string) {
    local := filepath.Join(installDir, ".venv", "Scripts", "python.exe")
    if _, err := os.Stat(local); err == nil {
        return local, nil
    }
    if configured := os.Getenv("NEXOFLOW_PYTHON_EXE"); configured != "" {
        if _, err := os.Stat(configured); err == nil {
            return configured, nil
        }
    }
    for _, name := range []string{"python.exe", "python3.14.exe"} {
        if path, err := exec.LookPath(name); err == nil {
            return path, nil
        }
    }
    if path, err := exec.LookPath("py.exe"); err == nil {
        return path, []string{"-3"}
    }
    return "", nil
}

func main() {
    if os.Getenv("NEXOFLOW_INTERNAL_BUILD_INFO") == "1" {
        fmt.Println(buildMarker)
        fmt.Println(terminalMarker)
    }
    runtime.KeepAlive(buildMarker)
    runtime.KeepAlive(terminalMarker)

    exe, err := os.Executable()
    if err != nil {
        fmt.Fprintf(os.Stderr, "[ERRO] Nao foi possivel localizar o NexoFlow Terminal: %v\n", err)
        waitEnter()
        os.Exit(1)
    }
    exe, _ = filepath.Abs(exe)
    installDir := filepath.Dir(exe)
    if err := os.Chdir(installDir); err != nil {
        fmt.Fprintf(os.Stderr, "[ERRO] Nao foi possivel acessar a pasta do NexoFlow: %v\n", err)
        waitEnter()
        os.Exit(1)
    }

    runner := filepath.Join(installDir, "run_terminal.py")
    if !requireFile(runner) {
        os.Exit(2)
    }
    python, prefix := findPython(installDir)
    if python == "" {
        fmt.Println("[ERRO] Python compativel nao foi encontrado.")
        fmt.Println("Execute o NexoFlow Setup para preparar o ambiente.")
        waitEnter()
        os.Exit(2)
    }
    args := append(prefix, runner)
    os.Exit(runChild(python, args...))
}
