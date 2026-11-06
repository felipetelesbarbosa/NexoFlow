"""Worker sem GUI, com etapas limitadas e retomada de checkpoints."""

from __future__ import annotations

import argparse
import json
import signal
import time
from pathlib import Path

from .config import Settings
from .core import evaluate
from .store import LostLease, Store


def run_once(store: Store, *, interrupt_after=None):
    task = store.claim()
    if task is None:
        return False
    print(
        json.dumps(
            {
                "evento": "tarefa_iniciada",
                "execucao": str(task["id"]),
                "segmento": task["segmento"],
                "tentativa": task["tentativa"],
            }
        ),
        flush=True,
    )
    try:
        saved = store.checkpoints(task)
        for step in (1, 2):
            if step in saved:
                continue
            if (
                step == 2
                and task["cenario"] == "rede_temporaria"
                and task["tentativa"] == 1
            ):
                store.finish(task, "aguardando", error="REDE_SIMULADA")
                return True
            if step == 2 and task["cenario"] == "autenticacao":
                store.finish(task, "falhou", error="AUTENTICACAO_SIMULADA")
                return True
            if step == 2 and task["cenario"] == "resposta_incerta":
                store.finish(task, "revisao_necessaria", error="RESPOSTA_INCERTA")
                return True
            result = (
                {"fonte": "fixture", "cobertura": "parcial"}
                if step == 1
                else evaluate(task["segmento"], task["cenario"])
            )
            store.checkpoint(task, step, result)
            saved[step] = result
            if interrupt_after == step:
                # Exclusivo ponto de injeção de teste; simula término abrupto.
                raise SystemExit(75)
        result = {
            "etapas": len(saved),
            "externas_gravacoes": 0,
            "sintetico": True,
            "avaliacao": saved[2],
        }
        store.finish(
            task,
            "parcial" if saved[2]["estado"] == "pendente" else "concluida",
            result=result,
        )
    except LostLease:
        # Outro proprietário assumiu: nenhuma regravação de resultado antigo.
        print(
            json.dumps(
                {
                    "evento": "lease_perdido",
                    "execucao": str(task["id"]),
                    "segmento": task["segmento"],
                }
            ),
            flush=True,
        )
    except Exception:
        # Não registrar str(exc), traceback, DSN, payload ou credenciais.
        try:
            store.finish(task, "falhou", error="FALHA_INTERNA")
        except LostLease:
            pass
        raise RuntimeError("FALHA_INTERNA") from None
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args()
    store = Store(Settings.load())
    if args.health:
        heartbeat = Path("/tmp/hub-worker-heartbeat")
        if (
            not heartbeat.is_file()
            or time.time() - heartbeat.stat().st_mtime > 15
            or not store.ready()
        ):
            raise SystemExit(1)
        # Readiness DB não equivale a progresso do worker; operação acompanha
        # leases/tentativas. Processo principal deve continuar vivo no Docker.
        return
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        Path("/tmp/hub-worker-heartbeat").touch()
        try:
            run_once(store)
        except Exception:
            print('{"evento":"worker_indisponivel","erro":"FALHA_INTERNA"}', flush=True)
            if args.once:
                raise SystemExit(1) from None
        if args.once:
            break
        time.sleep(1)


if __name__ == "__main__":
    main()
