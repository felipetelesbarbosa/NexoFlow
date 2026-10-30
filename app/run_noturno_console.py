"""Entrada em script do Noturno; seleciona perfil antes dos imports operacionais."""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTEX_NAME = r"Local\NexoFlowOperationLock"


@contextmanager
def operation_lock(profile=None):
    if os.name != "nt":
        raise OSError("A entrada de console do Noturno exige Windows.")
    profile = profile or os.environ.get("NEXOFLOW_PERFIL", "FARMA")
    if profile not in ("FARMA", "PET"):
        raise ValueError("Perfil inválido para bloquear a execução.")
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateMutexW
    create.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    ctypes.set_last_error(0)
    handle = create(None, False, MUTEX_NAME + "_" + profile)
    if not handle:
        raise OSError("Não foi possível obter o bloqueio da execução.")
    try:
        if ctypes.get_last_error() == 183:
            raise RuntimeError("Existe uma carga deste segmento em andamento.")
        open_mutex = kernel.OpenMutexW
        open_mutex.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        open_mutex.restype = wintypes.HANDLE
        ctypes.set_last_error(0)
        maintenance = open_mutex(0x00100000, False, MUTEX_NAME)
        error = ctypes.get_last_error()
        if maintenance:
            close(maintenance)
            raise RuntimeError(
                "Existe uma instalação/desinstalação ou carga antiga em andamento."
            )
        if error != 2:
            raise OSError("Não foi possível conferir o bloqueio de manutenção.")
        yield
    finally:
        close(handle)


def choose(options, prompt, input_fn):
    while True:
        try:
            choice = input_fn(prompt).strip()
        except EOFError:
            raise ValueError("A entrada foi encerrada sem uma opção válida.") from None
        if choice in options:
            return options[choice]
        print("[AVISO] Opção inválida. Tente novamente.")


def run(
    argv=None, *, root=ROOT, runner=subprocess.run, lock=operation_lock, input_fn=input
):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--perfil", choices=("FARMA", "PET"))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--incremental", action="store_true")
    modes.add_argument("--full", action="store_true")
    args = parser.parse_args(argv)
    profile = args.perfil or os.environ.get("NEXOFLOW_PERFIL", "")
    if not profile:
        print("NexoFlow — escolha o segmento\n[1] FarmaLíder\n[2] Pets Líder")
        profile = choose({"1": "FARMA", "2": "PET"}, "Escolha: ", input_fn)
    if profile not in ("FARMA", "PET"):
        raise ValueError("Perfil inválido; escolha FARMA ou PET.")
    os.environ["NEXOFLOW_PERFIL"] = profile
    print(f"[INFO] Perfil: {profile}")
    if args.incremental or args.full:
        mode = "--full" if args.full else "--incremental"
    else:
        print(
            "NexoFlow Noturno — Weni + Analytics + Recompra\n[1] Incremental\n[2] Carga completa 100%\n[0] Sair"
        )
        mode = choose(
            {"1": "--incremental", "2": "--full", "0": None},
            "Escolha uma opção: ",
            input_fn,
        )
        if mode is None:
            return None
    root = Path(root).resolve()
    python, script = root / ".venv/Scripts/python.exe", root / "app/run_noturno.py"
    if not python.is_file() or not script.is_file():
        raise FileNotFoundError(
            "Ambiente do Noturno incompleto. Execute o Setup para reparar a instalação."
        )
    env = dict(os.environ)
    env.update(
        NEXOFLOW_PERFIL=profile,
        NEXOFLOW_UNATTENDED="1",
        PYTHONIOENCODING="utf-8",
        PYTHONUNBUFFERED="1",
    )
    env["PYTHONPATH"] = os.pathsep.join(
        [str(root), str(root / "app"), env.get("PYTHONPATH", "")]
    )
    with lock():
        result = runner(
            [str(python), str(script), mode], cwd=root, env=env, check=False
        )
    return result.returncode


def wait_console():
    """Um ENTER novo após o resultado; pipes e tarefas sem janela não aguardam."""
    if os.name != "nt":
        return
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetConsoleWindow.restype = wintypes.HWND
    if not kernel.GetConsoleWindow():
        return
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    handle = create("CONIN$", 0xC0000000, 3, None, 3, 0, None)
    invalid = ctypes.c_void_p(-1).value
    try:
        if handle in (None, invalid):
            raise OSError("Teclado do console indisponível.")
        kernel.FlushConsoleInputBuffer.argtypes = [wintypes.HANDLE]
        if not kernel.FlushConsoleInputBuffer(handle):
            raise OSError("Entrada do console indisponível.")

        class Event(ctypes.Structure):
            _fields_ = [
                ("type", wintypes.WORD),
                ("padding", wintypes.WORD),
                ("down", wintypes.BOOL),
                ("repeat", wintypes.WORD),
                ("key", wintypes.WORD),
                ("scan", wintypes.WORD),
                ("char", wintypes.WORD),
                ("control", wintypes.DWORD),
            ]

        read = kernel.ReadConsoleInputW
        read.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Event),
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        print("\nPressione ENTER para fechar esta janela...", flush=True)
        while True:
            event, count = Event(), wintypes.DWORD()
            if not read(handle, ctypes.byref(event), 1, ctypes.byref(count)):
                raise OSError("Leitura do console indisponível.")
            if count.value == 1 and event.type == 1 and event.down and event.key == 13:
                return
    except OSError:
        print(
            "[AVISO] A janela continuará aberta. Feche-a manualmente após conferir o resultado.",
            flush=True,
        )
        wait = kernel.WaitForSingleObject
        wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        wait(ctypes.c_void_p(-1), 0xFFFFFFFF)
    finally:
        if handle not in (None, invalid):
            close(handle)


def main():
    code = 1
    try:
        result = run()
        if result is None:
            return 0
        code = result
    except SystemExit as exc:
        code = int(exc.code or 0)
    except KeyboardInterrupt:
        code = 130
        print("[AVISO] Execução interrompida.")
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        code = 2
        print(f"[ERRO] {exc}")
    except OSError as exc:
        print(f"[ERRO] {exc}")
    label = (
        "concluído"
        if code == 0
        else "concluído com pendências"
        if code == 3
        else "interrompido"
    )
    print(f"\n[RESULTADO] NexoFlow Noturno {label}.\nCódigo de saída: {code}")
    logs = (
        "logs\\PET\\noturno\\"
        if os.environ.get("NEXOFLOW_PERFIL") == "PET"
        else "logs\\noturno\\"
    )
    print(f"Relatórios da rotina: {logs} (na pasta do NexoFlow).", flush=True)
    wait_console()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
