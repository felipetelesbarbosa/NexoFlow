//go:build windows && noturno

package main

import (
	"syscall"
	"testing"
	"unsafe"
)

func TestSegmentLocksAllowDifferentProfilesAndBlockSameProfile(t *testing.T) {
	t.Setenv("NEXOFLOW_PERFIL", "FARMA")
	farma, ok := acquireMutex()
	if farma != 0 {
		defer syscall.CloseHandle(farma)
	}
	if !ok {
		t.Fatal("não adquiriu FARMA")
	}
	same, ok := acquireMutex()
	if same != 0 {
		syscall.CloseHandle(same)
	}
	if ok {
		t.Fatal("admitiu duas cargas FARMA")
	}
	t.Setenv("NEXOFLOW_PERFIL", "PET")
	pet, ok := acquireMutex()
	if pet != 0 {
		defer syscall.CloseHandle(pet)
	}
	if !ok {
		t.Fatal("FARMA bloqueou PET")
	}
}

func TestMaintenanceAndLegacyLockBlockBothProfiles(t *testing.T) {
	legacy, _, _ := procCreateMutexW.Call(0, 0, uintptr(unsafe.Pointer(utf16Ptr(mutexName))))
	if legacy == 0 {
		t.Fatal("não adquiriu manutenção")
	}
	defer syscall.CloseHandle(syscall.Handle(legacy))
	for _, profile := range []string{"FARMA", "PET"} {
		t.Setenv("NEXOFLOW_PERFIL", profile)
		handle, ok := acquireMutex()
		if handle != 0 {
			syscall.CloseHandle(handle)
		}
		if ok {
			t.Fatalf("manutenção não bloqueou %s", profile)
		}
	}
}
