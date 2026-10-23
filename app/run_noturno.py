"""Sequência autorizada sem interação, mantendo auditorias e snapshots próprios."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from recompra import atomic_json
from recompra_lock import execution_file_lock

ROOT = Path(__file__).resolve().parents[1]


def run_step(
    arguments: list[str], *, root: Path, log: Path, full_sync: bool = False
) -> int:
    env = dict(os.environ)
    # O modo escolhido prevalece sobre variáveis de cargas anteriores;
    # o Analytics final continua incremental mesmo na sequência completa.
    for name in ("FORCE_FULL_SYNC", "FULL_SYNC_QUARTER"):
        env.pop(name, None)
    if full_sync:
        env["FORCE_FULL_SYNC"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    with log.open("a", encoding="utf-8") as output:
        with subprocess.Popen(
            [sys.executable, *arguments],
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as process:
            if process.stdout is None:
                raise RuntimeError("Saída do processo indisponível.")
            for line in process.stdout:
                output.write(line)
                output.flush()
                print(line, end="", flush=True)
            return process.wait()


def execute(root: Path = ROOT, *, runner=run_step, full: bool = False) -> int:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ_") + uuid4().hex[:8]
    directory = root / "logs" / "noturno" / run_id
    directory.mkdir(parents=True, mode=0o700)
    summary = {
        "execucao": run_id,
        "inicio_utc": datetime.now(UTC).isoformat(),
        "modo": "completo" if full else "incremental",
        "confirmacao_humana": False,
        "status": "em_execucao",
        "etapas": [],
    }
    summary_path = directory / "resultado.json"
    atomic_json(summary_path, summary)
    print(f"NexoFlow Noturno — relatórios: {directory}", flush=True)

    def step(name: str, arguments: list[str], *, full_sync: bool = False) -> int:
        print(f"\n[ETAPA] {name}", flush=True)
        result = runner(
            arguments, root=root, log=directory / "execucao.log", full_sync=full_sync
        )
        summary["etapas"].append({"etapa": name, "codigo": result})
        atomic_json(summary_path, summary)
        return result

    def run_flow() -> int:
        for name, arguments in (
            ("Check-up", ["app/run_checkup_tests.py"]),
            ("Consistência", ["app/auditar_consistencia.py"]),
            ("Conexões Weni", ["app/run_update_weni.py", "--check-only"]),
        ):
            code = step(name, arguments)
            if code:
                return code
        weni_review = str(directory / "weni_review.json")
        for name, arguments in (
            (
                "Weni: simulação e auditoria",
                ["app/run_update_weni.py", "--dry-run", "--review-out", weni_review],
            ),
            (
                "Weni: aplicação auditada",
                ["app/run_update_weni.py", "--apply", "--require-review", weni_review],
            ),
            ("Analytics: sincronização incremental", ["app/run_main.py"]),
            ("Recompra: estrutura", ["app/run_recompra.py", "--check-only"]),
        ):
            if full and arguments[0] == "app/run_update_weni.py":
                arguments.append("--full")
            if full and arguments == ["app/run_main.py"]:
                name = "Analytics: carga completa 100%"
            code = step(
                name, arguments, full_sync=full and arguments == ["app/run_main.py"]
            )
            if code:
                return code
        # Uma revisão que atravessa a meia-noite precisa ser gerada novamente;
        # nunca remover os bloqueios de data ou repetir uma aplicação incerta.
        for attempt in range(2):
            review = str(directory / f"recompra_review_{attempt + 1}.json")
            for name, arguments in (
                (
                    "Recompra: simulação",
                    [
                        "app/run_recompra.py",
                        "--dry-run",
                        "--require-complete",
                        "--review-out",
                        review,
                    ],
                ),
                (
                    "Recompra: conferir revisão",
                    [
                        "app/run_recompra.py",
                        "--check-review",
                        "--require-review",
                        review,
                    ],
                ),
                (
                    "Recompra: aplicação auditada",
                    ["app/run_recompra.py", "--apply", "--require-review", review],
                ),
            ):
                if full and "--dry-run" in arguments:
                    arguments.append("--full")
                code = step(name, arguments)
                if code:
                    break
            if code != 4:
                break
        if code:
            return code
        return step("Analytics: refletir alterações da Recompra", ["app/run_main.py"])

    code = 1
    try:
        with execution_file_lock(
            root / "logs" / "noturno.lock",
            protocol="nexoflow-noturno-v1",
            operation="NexoFlow Noturno",
        ):
            code = run_flow()
    except KeyboardInterrupt:
        code = 130
        print("[AVISO] Execução interrompida; confira os relatórios antes de retomar.")
    except (OSError, RuntimeError) as exc:
        print(
            f"[ERRO] Rotina noturna interrompida ({type(exc).__name__}). Consulte os logs da etapa."
        )
    finally:
        summary["status"] = (
            "concluido" if code == 0 else "parcial" if code == 3 else "interrompido"
        )
        summary["codigo"] = code
        summary["fim_utc"] = datetime.now(UTC).isoformat()
        atomic_json(summary_path, summary)
        print(
            f"[RESULTADO] {summary['status']} — código {code}. Relatório: {summary_path}",
            flush=True,
        )
    return code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Weni, Analytics e Recompra sem confirmação humana."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--incremental", action="store_true", help="executa o fluxo incremental"
    )
    modes.add_argument(
        "--full", action="store_true", help="executa carga completa 100%"
    )
    args = parser.parse_args()
    return execute(full=args.full)


if __name__ == "__main__":
    raise SystemExit(main())
