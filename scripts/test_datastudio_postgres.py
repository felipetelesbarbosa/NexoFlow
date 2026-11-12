"""Homologação descartável: PostgreSQL Docker sem portas e dados sintéticos."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from uuid import uuid4


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--image", help="Imagem já compilada para o smoke HTTP em rede privada"
    )
    args = parser.parse_args()
    name = "nf-bi-publisher-test-" + uuid4().hex[:12]
    password = secrets.token_hex(24)
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "--name",
            name,
            "--tmpfs",
            "/var/lib/postgresql:rw,size=512m",
            "-e",
            "POSTGRES_DB=nexoflow_datastudio_homologacao",
            "-e",
            "POSTGRES_PASSWORD=" + password,
            "postgres:18.6-alpine@sha256:9ba53c7d41ea093baf5c1ba635ba5434c4f979880527d49bb7d9237d3193085b",
            "postgres",
            "-c",
            "nexoflow.test_instance=isolated_synthetic_only",
        ],
        check=True,
        capture_output=True,
    )
    try:
        for _ in range(40):
            ready = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-U", "postgres"],
                capture_output=True,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("PostgreSQL temporário não ficou pronto")
        ip = subprocess.check_output(
            [
                "docker",
                "inspect",
                "--format",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                name,
            ],
            text=True,
        ).strip()
        environment = dict(
            os.environ,
            NEXOFLOW_DATASTUDIO_TEST_DSN=f"postgresql://postgres:{password}@{ip}/nexoflow_datastudio_homologacao?application_name=nexoflow-datastudio-tests",
        )
        if args.image:
            environment["NEXOFLOW_DATASTUDIO_TEST_IMAGE"] = args.image
        environment["PYTHONPATH"] = os.pathsep.join(["app", "."])
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests/datastudio"], env=environment
        ).returncode
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
