//go:build windows

package main

import (
    "bufio"
    "fmt"
    "os"
    "os/exec"
    "path/filepath"
    "runtime"
    "syscall"
    "unsafe"
)

const (
    mutexName   = `Local\NexoFlowOperationLock`
    buildMarker = "NexoFlowNativeLauncher=1.0"
)

var (
    kernel32         = syscall.NewLazyDLL("kernel32.dll")
    procCreateMutexW = kernel32.NewProc("CreateMutexW")
    procGetLastError = kernel32.NewProc("GetLastError")
)

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
        fmt.Fprintf(os.Stderr, "[ERRO] Nao foi possivel iniciar o processo: %v\n", err)
        return 1
    }
    if cmd.ProcessState == nil {
        return 1
    }
    return cmd.ProcessState.ExitCode()
}

func prepareLauncher() (string, func(), int) {
    if os.Getenv("NEXOFLOW_INTERNAL_BUILD_INFO") == "1" {
        fmt.Println(buildMarker)
    }
    runtime.KeepAlive(buildMarker)

    exe, err := os.Executable()
    if err != nil {
        fmt.Fprintf(os.Stderr, "[ERRO] Nao foi possivel localizar o executavel: %v\n", err)
        waitEnter()
        return "", func(){}, 1
    }
    exe, _ = filepath.Abs(exe)
    installDir := filepath.Dir(exe)
    if err := os.Chdir(installDir); err != nil {
        fmt.Fprintf(os.Stderr, "[ERRO] Nao foi possivel acessar a pasta do NexoFlow: %v\n", err)
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
        fmt.Println("[AVISO] Existe uma sincronizacao, instalacao ou desinstalacao do NexoFlow em andamento.")
        waitEnter()
        cleanup()
        return "", func(){}, 2
    }
    return installDir, cleanup, 0
}

func requireFile(path string) bool {
    if _, err := os.Stat(path); err != nil {
        fmt.Printf("[ERRO] Arquivo nao encontrado: %s\n", path)
        waitEnter()
        return false
    }
    return true
}
