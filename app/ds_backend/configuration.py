"""Configuração atômica do perfil; não executa nem substitui credenciais locais."""

from __future__ import annotations

import ast
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from ds_backend.contract import StorageError


def configure(
    path, segment, environment, credential_path, *, backend="sheets", activate=False
):
    from ds_backend.client import Client

    if (
        segment not in ("FARMA", "PET")
        or environment not in ("homologacao", "producao")
        or backend not in ("sheets", "postgres")
    ):
        raise StorageError("DS_CONFIGURACAO_INVALIDA")
    if activate and backend != "postgres":
        raise StorageError("DS_ATIVACAO_EXIGE_BACKEND_POSTGRES")
    if backend == "postgres" and not activate:
        raise StorageError("DS_ATIVACAO_EXIGE_FLAG_EXPLICITA")
    path = Path(path)
    source = path.read_text(encoding="utf-8-sig")
    try:
        ast.parse(source)  # configuração é dado; nunca importar/executar para editar
    except SyntaxError:
        raise StorageError("DS_CONFIGURACAO_SINTAXE_INVALIDA") from None
    if activate:
        candidate = Path(credential_path)
        if not candidate.is_absolute():
            candidate = path.parent / candidate
        config = json.loads(candidate.read_text(encoding="utf-8-sig"))
        if config.get("segment") != segment or config.get("environment") != environment:
            raise StorageError("DS_CONFIGURACAO_PERFIL_DIVERGENTE")
        client = Client(config)
        try:
            if not client.info["version"] or client.info.get("pending"):
                raise StorageError("DS_ATIVACAO_EXIGE_READY_SEM_PENDENCIA")
            for name in ("weni_update", "recompra", "carga_fracionada"):
                if (
                    client.call("/v1/estados/ler", dict(name=name)).get("document")
                    is None
                ):
                    raise StorageError("DS_ESTADO_EXIGE_MIGRACAO_INICIAL")
        finally:
            client.close()
    begin = "# NEXOFLOW_DS_CONFIG_BEGIN " + segment
    end = "# NEXOFLOW_DS_CONFIG_END " + segment
    pattern = re.compile(
        "^" + re.escape(begin) + r"\n.*?^" + re.escape(end) + r"\n?", re.M | re.S
    )
    if len(pattern.findall(source)) > 1:
        raise StorageError("DS_BLOCO_CONFIGURACAO_DUPLICADO")
    source = pattern.sub("", source)
    values: dict[str, object] = dict(
        ARMAZENAMENTO_BACKEND=backend,
        DATASTUDIO_AMBIENTE=environment,
        DATASTUDIO_CREDENTIALS_FILE=str(credential_path),
    )
    if activate:
        values.update(
            FARMALIDER_HISTORY_ENABLED=True, FARMALIDER_HISTORY_STORAGE_ENABLED=True
        )
    block = (
        "\n"
        + begin
        + """\nif "PERFIS" not in globals():
    PERFIS = {}
if not isinstance(PERFIS, dict):
    raise RuntimeError("PERFIS deve ser um dicionário; preserve as credenciais.")
PERFIS.setdefault("""
        + repr(segment)
        + """, {}).update("""
        + repr(values)
        + """)\n"""
        + end
        + "\n"
    )
    output = source.rstrip() + "\n" + block
    ast.parse(output)

    backup_dir = path.parent / "credentials" / "datastudio" / "backup-configuracao"
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = backup_dir / (
        "secrets_config-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".bak"
    )
    with backup.open("xb") as handle:
        handle.write(path.read_bytes())
        handle.flush()
        os.fsync(handle.fileno())
    backup.chmod(0o600)
    temporary = path.with_name(path.name + ".datastudio.tmp")
    with temporary.open("x", encoding="utf-8-sig", newline="") as handle:
        handle.write(output)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, path)
    return dict(
        state="CONFIGURADA",
        segment=segment,
        backend=backend,
        activated=activate,
        backup_created=True,
    )
