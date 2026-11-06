"""Homologação Docker local descartável, sem portas ou integrações comerciais.

Nunca aponta para a VPS. Os únicos recursos removidos têm o UUID desta execução.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from nexoflow_hub.config import Settings
from nexoflow_hub.store import Store

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--pytest", action="store_true")
    args = parser.parse_args()
    project = "nexoflow-hub-test-" + uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="hub-hml-") as directory:
        secret_dir = Path(directory)
        os.chmod(secret_dir, 0o700)
        for name in ("admin_password", "runtime_password", "farma", "pet"):
            (secret_dir / name).write_text(secrets.token_hex(32))
            # O diretório externo é 0700. Apenas os serviços selecionados recebem
            # o arquivo por bind read-only; o UID do PostgreSQL pode lê-lo.
            (secret_dir / name).chmod(0o644)
        runtime_pw = (secret_dir / "runtime_password").read_text()
        dsn = f"host=postgres-hml dbname=nexoflow_hub_hml user=hub_hml password={runtime_pw}"
        (secret_dir / "dsn").write_text(dsn)
        (secret_dir / "dsn").chmod(0o644)
        env = dict(os.environ, HUB_SEGREDOS_DIR=directory)
        # Endpoint Docker fixado no daemon LOCAL; não usar contexto salvo da VPS.
        docker = ["docker", "--host=unix:///var/run/docker.sock"]
        for key in (
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_TLS",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        ):
            env.pop(key, None)
        compose = [
            *docker,
            "compose",
            "-p",
            project,
            "-f",
            str(ROOT / "hub/compose.homologacao.yaml"),
        ]

        def command(command_args, *, expected=0):
            result = subprocess.run(
                command_args,
                env=env,
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode != expected:
                # Subprocessos podem conter DSNs/variáveis. Não imprimir stdout.
                action = next(
                    (
                        v
                        for v in command_args
                        if v
                        in {
                            "build",
                            "up",
                            "run",
                            "restart",
                            "exec",
                            "inspect",
                            "down",
                            "rm",
                        }
                    ),
                    "comando",
                )
                raise RuntimeError(
                    f"SUBPROCESSO_{action.upper()}_CODIGO_{result.returncode}"
                )
            return result.stdout.strip()

        def wait(predicate, description):
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    if predicate():
                        print(
                            json.dumps({"teste": description, "estado": "aprovado"}),
                            flush=True,
                        )
                        return
                except Exception:
                    pass
                time.sleep(1)
            raise RuntimeError("PRAZO_HOMOLOGACAO_EXCEDIDO: " + description)

        def cid(service):
            value = command([*compose, "ps", "-q", service])
            if not value:
                raise RuntimeError("CONTEINER_AUSENTE")
            return value

        def pg_ready():
            r = subprocess.run(
                [
                    *docker,
                    "exec",
                    cid("postgres-hml"),
                    "pg_isready",
                    "-U",
                    "hub_hml",
                    "-d",
                    "nexoflow_hub_hml",
                ],
                env=env,
                capture_output=True,
                timeout=5,
            )
            return r.returncode == 0

        try:
            if args.build:
                build = [
                    *docker,
                    "build",
                    "-f",
                    "hub/Dockerfile",
                    "-t",
                    "nexoflow-hub:hml",
                ]
                if Path("/etc/ssl/certs/ca-certificates.crt").is_file():
                    build += [
                        "--secret",
                        "id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt",
                    ]
                command([*build, "."])
            command([*compose, "up", "-d", "postgres-hml"])
            wait(pg_ready, "postgresql_18_temporario")
            ip = command(
                [
                    *docker,
                    "inspect",
                    "-f",
                    "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                    cid("postgres-hml"),
                ]
            )
            if not ip:
                raise RuntimeError("ENDERECO_INTERNO_AUSENTE")
            (secret_dir / "test_dsn").write_text(
                dsn.replace("host=postgres-hml", "host=" + ip)
            )
            test_settings = Settings(
                (secret_dir / "test_dsn").read_text(),
                {s: (secret_dir / s.lower()).read_text() for s in ("FARMA", "PET")},
            )
            store = Store(test_settings)
            store.migrate()
            if args.pytest:
                test_env = dict(
                    env,
                    HUB_TEST_DSN_FILE=str(secret_dir / "test_dsn"),
                    PYTHONPATH=str(ROOT / "hub") + os.pathsep + str(ROOT / "app"),
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "hub/tests/test_hub.py",
                        "hub/tests/test_orders.py",
                        "hub/tests/test_history.py",
                        "-q",
                    ],
                    cwd=ROOT,
                    env=test_env,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode:
                    # Somente nomes de testes sintéticos; sem tracebacks/DSNs.
                    import re

                    names = re.findall(
                        r"^(?:FAILED|ERROR) ([A-Za-z0-9_./:\[\]-]+)",
                        result.stdout,
                        re.MULTILINE,
                    )
                    print(json.dumps({"testes_reprovados": names}), flush=True)
                    raise RuntimeError("PYTEST_HUB_FALHOU")
                print(
                    json.dumps(
                        {"teste": "suite_postgresql_real", "estado": "aprovado"}
                    ),
                    flush=True,
                )
            command([*compose, "run", "--rm", "migracao"])
            # A suíte pode terminar com fixtures válidas de outra janela.
            # A prova entre processos começa vazia neste banco UUID descartável.
            with store.connect() as db:
                db.execute(
                    "TRUNCATE hub.historico_ltv,hub.historico_revisoes,hub.historico_pendencias,hub.historico_pedidos,hub.historico_recebidos,hub.historico_janelas,hub.auditoria,hub.checkpoints,hub.tentativas,hub.coordenacao,hub.tarefas,hub.cobertura"
                )
            command([*compose, "up", "-d", "api", "worker"])
            first = store.create("FARMA", "teste", "persistencia", "normal")

            def completed(item, segment="FARMA"):
                return store.get(segment, item["id"])["estado"] == "concluida"

            wait(lambda: completed(first), "worker_real")
            api = cid("api")
            request = "import json,urllib.request;from pathlib import Path;op=urllib.request.build_opener(urllib.request.ProxyHandler({}));r=urllib.request.Request('http://127.0.0.1:8000/prontidao',headers={'Authorization':'Bearer '+Path('/run/secrets/farma').read_text().strip()});assert json.load(op.open(r,timeout=3))['estado']=='pronto'"
            command([*docker, "exec", api, "python", "-c", request])
            print('{"teste":"api_http_autenticada","estado":"aprovado"}', flush=True)
            history_body = {
                "segmento": "PET",
                "chave": "historico-http",
                "inicio": "2026-11-01",
                "fim": "2026-11-06",
                "limite": 100,
                "max_paginas": 10,
                "quantidade_sintetica": 205,
            }
            history_request = (
                "import json,urllib.request;from pathlib import Path;op=urllib.request.build_opener(urllib.request.ProxyHandler({}));body="
                + repr(history_body)
                + ";r=urllib.request.Request('http://127.0.0.1:8000/tarefas/historico',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+Path('/run/secrets/pet').read_text().strip()});assert op.open(r,timeout=5).status==202"
            )
            command([*docker, "exec", api, "python", "-c", history_request])
            history_task = next(
                t for t in store.list("PET") if t["chave"] == "historico-http"
            )
            wait(
                lambda: completed(history_task, "PET"),
                "historico_api_worker_postgresql",
            )
            assert (
                store.get("PET", history_task["id"])["resultado"][
                    "faturamento_centavos"
                ]
                == 1640000
            )
            command([*compose, "stop", "worker"])
            crashed = store.create("FARMA", "teste", "interrupcao", "normal")
            command(
                [
                    *compose,
                    "run",
                    "--rm",
                    "worker",
                    "python",
                    "-c",
                    "from nexoflow_hub.store import Store;from nexoflow_hub.config import Settings;from nexoflow_hub.worker import run_once;run_once(Store(Settings.load()),interrupt_after=1)",
                ],
                expected=75,
            )
            assert set(store.checkpoints(crashed)) == {1}
            command([*compose, "up", "-d", "worker"])
            wait(
                lambda: completed(crashed),
                "retomada_lease_real_apos_processo_interrompido",
            )
            assert store.get("FARMA", crashed["id"])["tentativa"] == 2
            assert len(store.checkpoints(crashed)) == 2
            command([*compose, "restart", "api", "worker", "postgres-hml"])
            wait(pg_ready, "postgresql_reiniciado")
            wait(lambda: store.ready(), "schema_persistido")
            assert completed(first) and completed(crashed)
            assert completed(history_task, "PET")
            assert store.get("PET", history_task["id"])["resultado"]["received"] == 205
            other = store.create("PET", "n8n", "recuperacao", "normal")
            wait(lambda: completed(other, "PET"), "pet_apos_reinicio")
            for service in ("api", "worker", "postgres-hml"):
                container = cid(service)
                binding = json.loads(
                    command(
                        [
                            *docker,
                            "inspect",
                            "-f",
                            "{{json .HostConfig.PortBindings}}",
                            container,
                        ]
                    )
                )
                assert not binding
                wait(
                    lambda container=container: (
                        command(
                            [
                                *docker,
                                "inspect",
                                "-f",
                                "{{.State.Health.Status}}",
                                container,
                            ]
                        )
                        == "healthy"
                    ),
                    "health_" + service,
                )
            with store.connect() as db:
                assert not db.execute(
                    "SELECT rolsuper FROM pg_roles WHERE rolname=current_user"
                ).fetchone()["rolsuper"]
            print(
                '{"estado":"homologacao_docker_aprovada","escritas_externas":0}',
                flush=True,
            )
        finally:
            # Projeto com UUID gerado aqui; nunca recebe nome de projeto por CLI.
            command([*compose, "down", "--remove-orphans"])
            volumes = command(
                [
                    *docker,
                    "volume",
                    "ls",
                    "-q",
                    "--filter",
                    "label=com.docker.compose.project=" + project,
                ]
            ).splitlines()
            for volume in volumes:
                if not volume.startswith(project + "_"):
                    raise RuntimeError("VOLUME_FORA_DO_ENSAIO")
                command([*docker, "volume", "rm", volume])


if __name__ == "__main__":
    main()
