"""Imagem real, conta mínima, HTTP autenticado e PostgreSQL sem porta publicada."""

import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest
from psycopg import sql

from integrations.datastudio.admin import grants
from tests.datastudio.test_ds_database import DSN, store  # noqa: F401

IMAGE = os.getenv("NEXOFLOW_DATASTUDIO_TEST_IMAGE")
pytestmark = pytest.mark.skipif(
    not IMAGE or not DSN, reason="Imagem e PostgreSQL descartáveis não configurados"
)


def test_image_health_private_http_and_no_reader_write(store):  # noqa: F811
    assert DSN and "application_name=nexoflow-datastudio-tests" in DSN
    token = "synthetic-test-" + secrets.token_hex(24)
    password = secrets.token_hex(24)
    with store.connect() as conn:
        grants(conn, "FARMA")
        for role in ("nf_ds_farma_publish", "nf_ds_farma_read"):
            conn.execute(
                sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(DSN)
    for mode, role in [
        ("publish", "nf_ds_farma_publish"),
        ("read", "nf_ds_farma_read"),
    ]:
        name = "nf-datastudio-api-test-" + uuid4().hex[:10]
        with tempfile.TemporaryDirectory(prefix="nf-ds-container-") as directory:
            root = Path(directory)
            # Arquivos sintéticos montados individualmente; diretório host é privado.
            files = {
                "dsn": urlunsplit(
                    (
                        parsed.scheme,
                        role
                        + ":"
                        + quote(password)
                        + "@"
                        + parsed.netloc.split("@")[-1],
                        parsed.path,
                        parsed.query,
                        "",
                    )
                ),
                "token": token,
                "config.json": json.dumps(
                    dict(
                        mode=mode,
                        segment="FARMA",
                        environment="homologacao",
                        dsn_file="/run/secrets/dsn",
                        token_file="/run/secrets/token",
                    )
                ),
            }
            command = [
                "docker",
                "run",
                "--rm",
                "-d",
                "--name",
                name,
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=32m",
                "-e",
                "DATASTUDIO_CONFIG_FILE=/run/secrets/config.json",
            ]
            for filename, value in files.items():
                path = root / filename
                path.write_text(value)
                path.chmod(0o444)
                command.extend(["-v", str(path) + ":/run/secrets/" + filename + ":ro"])
            command.append(IMAGE)
            subprocess.run(command, check=True, capture_output=True)
            try:
                # Healthcheck repete apenas GET no próprio contêiner temporário.
                script = """import json,time,urllib.request,urllib.error,pathlib
key=pathlib.Path('/run/secrets/token').read_text().strip()
for attempt in range(30):
 try:
  req=urllib.request.Request('http://127.0.0.1:8080/v1/destino',headers={'Authorization':'Bearer '+key})
  with urllib.request.urlopen(req,timeout=3) as reply:
   data=json.load(reply)
   assert data['protocol']=='nexoflow_datastudio_1' and data['target']=='nexoflow_datastudio_homologacao.farma'
   break
 except (OSError,urllib.error.URLError):time.sleep(0.2)
else:raise RuntimeError('health privado não confirmou')
try:urllib.request.urlopen('http://127.0.0.1:8080/v1/destino')
except urllib.error.HTTPError as error:assert error.code==401
else:raise AssertionError('API sem autenticação')
"""
                result = subprocess.run(
                    ["docker", "exec", "-i", name, "python", "-"],
                    input=script,
                    text=True,
                    capture_output=True,
                )
                assert result.returncode == 0, (
                    "Contêiner não confirmou contrato/saúde; saída bruta preservada fora de logs públicos."
                )
                bindings = json.loads(
                    subprocess.check_output(["docker", "inspect", name], text=True)
                )[0]["HostConfig"]["PortBindings"]
                assert not bindings
                assert (
                    subprocess.run(
                        [
                            "docker",
                            "exec",
                            name,
                            "python",
                            "-m",
                            "integrations.datastudio.health",
                        ],
                        capture_output=True,
                    ).returncode
                    == 0
                )
            finally:
                subprocess.run(
                    ["docker", "rm", "-f", name], capture_output=True, check=False
                )
