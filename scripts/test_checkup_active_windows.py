"""Regressão do pacote instalado: dois Noturnos sintéticos, check-up real, sem APIs."""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path

BASELINE = "76fa473e99753886d6fcad4c0b5579d844163210"


def baseline(root, work):
    from run_noturno_console import operation_lock

    cases = (
        (
            "test_imports_lifecycle_windows",
            "ImportsLifecycleWindowsTests",
            "test_actual_stage2_preserves_imports_when_optional_data_is_removed",
        ),
        (
            "test_weni_review_windows",
            "WeniReviewBatchWindowsTests",
            "test_native_weni_launcher_runs_after_icon_update",
        ),
    )
    suite = unittest.TestSuite()
    repo = Path(__file__).resolve().parents[1]
    for name, class_name, method in cases:
        content = subprocess.check_output(
            ["git", "show", f"{BASELINE}:tests/{name}.py"], cwd=repo
        )
        path = work / (name + ".py")
        path.write_bytes(content)
        spec = importlib.util.spec_from_file_location("baseline_" + name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Não foi possível carregar a reprodução anterior.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ROOT = module.REPOSITORY = root
        suite.addTest(getattr(module, class_name)(method))
    report = io.StringIO()
    with operation_lock("FARMA"):
        result = unittest.TextTestRunner(stream=report, verbosity=0, buffer=True).run(
            suite
        )
    text = report.getvalue()
    if (
        result.testsRun != 2
        or len(result.failures) != 2
        or result.errors
        or "Existe uma carga Farma/Pets" not in text
        or "2 != 0" not in text
    ):
        print(text)
        raise RuntimeError("A versão anterior não reproduziu as duas falhas relatadas.")
    print("[OK] Testes da 1.5.5: duas falhas reproduzidas com a trava operacional ativa.")


def worker(root, work, profile, *, probe=False):
    from run_noturno_console import operation_lock

    try:
        with operation_lock(profile):
            if probe:
                raise RuntimeError(
                    "A segunda carga do mesmo segmento conseguiu iniciar."
                )
            (work / (profile + ".ready")).touch()
            deadline = time.monotonic() + 30
            while not (work / "start").exists():
                if time.monotonic() > deadline:
                    raise RuntimeError("O outro segmento não iniciou a regressão.")
                time.sleep(0.05)
            import socket
            from types import ModuleType

            synthetic = ModuleType("secrets_config")
            synthetic.PROXY_MODE = "off"
            synthetic.PERFIS = {
                name: {
                    "SEGMENTO": name,
                    "WENI_API_TOKEN": "FICTICIO_" + name,
                    "FARMALIDER_API_TOKEN": "FICTICIO_" + name,
                    "GOOGLE_SPREADSHEET_ID": "FICTICIO_" + name,
                    "RECOMPRA_ENABLED": False,
                }
                for name in ("FARMA", "PET")
            }
            sys.modules["secrets_config"] = synthetic

            def no_network(*args, **kwargs):
                raise RuntimeError("A regressão tentou acessar a rede.")

            socket.socket.connect = no_network
            socket.socket.connect_ex = no_network
            import run_noturno as engine

            fixture = work / profile
            fixture.mkdir()
            calls = []

            def run(arguments, **kwargs):
                calls.append(arguments)
                if arguments == ["app/run_checkup_tests.py"]:
                    return subprocess.run(
                        [sys.executable, str(root / arguments[0])],
                        cwd=root,
                        stdin=subprocess.DEVNULL,
                        check=False,
                        timeout=240,
                    ).returncode
                # Nenhum outro comando é executado: simular APIs e aplicações.
                return 0

            code = engine.execute(fixture, full=True, runner=run)
            files = list(fixture.rglob("resultado.json"))
            if len(files) != 1:
                raise RuntimeError("Relatório da execução ausente ou duplicado.")
            result = json.loads(files[0].read_text(encoding="utf-8"))
            if code or len(calls) != 11 or not result.get("fluxo_completo"):
                raise RuntimeError("O check-up bloqueou a sequência noturna sintética.")
            if calls[0] != ["app/run_checkup_tests.py"] or calls[-1] != [
                "app/run_main.py"
            ]:
                raise RuntimeError("A sequência esperada foi alterada.")
            print(
                f"[OK] {profile}: check-up real e 11 etapas sintéticas; nenhuma API chamada."
            )
            return 0
    except RuntimeError as exc:
        if probe and "em andamento" in str(exc):
            print("[OK] Outra carga do mesmo segmento permaneceu bloqueada.")
            return 2
        raise


def run(root):
    if os.name != "nt":
        raise RuntimeError("Exige Windows e o pacote instalado.")
    python = root / ".venv/Scripts/python.exe"
    script = Path(__file__).resolve()
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(root), str(root / "app")]),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "NEXOFLOW_UNATTENDED": "1",
    }
    with (
        tempfile.TemporaryDirectory(prefix="nexo active checkup ") as folder,
        ExitStack() as stack,
    ):
        work = Path(folder)
        base = [str(python), str(script), "--root", str(root), "--work", str(work)]
        subprocess.run(
            [*base, "--baseline", "--profile", "FARMA"],
            env={**env, "NEXOFLOW_PERFIL": "FARMA"},
            check=True,
            timeout=90,
        )
        processes = []
        try:
            for profile in ("FARMA", "PET"):
                output = stack.enter_context(
                    (work / (profile + ".log")).open("w", encoding="utf-8")
                )
                processes.append(
                    subprocess.Popen(
                        [*base, "--worker", "--profile", profile],
                        env={**env, "NEXOFLOW_PERFIL": profile},
                        cwd=root,
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                    )
                )
            deadline = time.monotonic() + 30
            while not all((work / (p + ".ready")).exists() for p in ("FARMA", "PET")):
                if time.monotonic() > deadline or any(
                    p.poll() is not None for p in processes
                ):
                    raise RuntimeError(
                        "Os dois segmentos não ficaram ativos ao mesmo tempo."
                    )
                time.sleep(0.05)
            probe = subprocess.run(
                [*base, "--probe", "--profile", "FARMA"],
                env={**env, "NEXOFLOW_PERFIL": "FARMA"},
                check=False,
                timeout=20,
            )
            if probe.returncode != 2:
                raise RuntimeError("A segunda carga FARMA não foi bloqueada.")
            (work / "start").touch()
            codes = [p.wait(timeout=300) for p in processes]
            if any(codes):
                raise RuntimeError(f"Check-ups concorrentes falharam: {codes}.")
        finally:
            for process in processes:
                if process.poll() is None:
                    subprocess.run(
                        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    process.wait(timeout=15)
            for profile in ("FARMA", "PET"):
                path = work / (profile + ".log")
                if path.exists():
                    print(path.read_text(encoding="utf-8", errors="replace"))
    print("[OK] Pacote instalado: dois check-ups simultâneos e proteções preservadas.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--profile", choices=("FARMA", "PET"))
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.root / "app"))
    if args.profile:
        os.environ["NEXOFLOW_PERFIL"] = args.profile
    if args.baseline:
        baseline(args.root, args.work)
        return 0
    if args.worker or args.probe:
        return worker(args.root, args.work, args.profile, probe=args.probe)
    run(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
