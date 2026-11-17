"""Executa o roteiro do Work com psql e a conta leitora na instância descartável."""

import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from integrations.datastudio.admin import grants
from tests.datastudio.test_daily_financial_views import published as published
from tests.datastudio.test_ds_database import DSN
from tests.datastudio.test_ds_database import store as store

pytestmark = pytest.mark.skipif(
    not DSN or not os.getenv("NEXOFLOW_DATASTUDIO_TEST_CONTAINER"),
    reason="Requer o cliente psql do PostgreSQL descartável da suíte",
)


def test_reconciliation_script_checks_ready_keys_and_missing_values(store, published):
    # O lançador da suíte cria o contêiner sem porta pública. O cliente psql
    # usa socket local; nenhum segredo do DSN é passado na linha de comando.
    name = os.environ["NEXOFLOW_DATASTUDIO_TEST_CONTAINER"]
    with store.connect() as conn:
        grants(conn, "FARMA")
        revision = conn.execute(
            "SELECT execucao FROM controle.nf_publicacoes WHERE segmento='FARMA'"
        ).fetchone()["execucao"]
    script = (
        Path(__file__).resolve().parents[2]
        / "integrations/datastudio/auditar_projecoes_farma.sql"
    ).read_text(encoding="utf-8")

    def audit(rev, start="2026-04-01", end="2026-04-30"):
        return subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                name,
                "psql",
                "-XAtq",
                "-w",
                "-U",
                "postgres",
                "-d",
                "nexoflow_datastudio_homologacao",
                "-v",
                "revisao=" + str(rev),
                "-v",
                "inicio=" + start,
                "-v",
                "fim=" + end,
                "-v",
                "somente_diferencas=true",
                "-f",
                "-",
            ],
            input="SET ROLE nf_ds_farma_read;\n" + script,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )

    result = audit(revision)
    assert result.returncode == 0, result.stderr
    assert "2026-04-11|" not in result.stdout  # impressão restrita a diferenças
    summary, _, items, orders = _total(result)
    assert summary["produtos"] == 8501
    assert items["unidades"] == 5 and items["skus"] == 2
    assert orders["pedidos"] == 3 and orders["linhas_duplicadas"] == 0
    assert "clientes=1 pedidos=1 centavos=7789 clientes_divergentes=0" in result.stdout

    result = audit(revision, "2027-01-01", "2027-01-01")
    assert result.returncode == 0 and _total(result)[2]["itens"] == 0
    stale = audit(uuid4())
    assert (
        stale.returncode == 3
        and "DS_AUDITORIA_REVISAO_ATIVA_DIVERGENTE" in stale.stderr
    )

    # Injeta um frete desconhecido na base sintética. A omissão de NULL
    # em várias linhas não pode aprovar uma conferência.
    with store.connect() as conn:
        conn.execute("""
            UPDATE farma.nf_atuais SET registro=registro-'pedido_frete'
            WHERE tabela='BI_Pedidos' AND registro->>'pedido_chave'='FARMALIDER:502'
        """)
    invalid = audit(revision)
    assert (
        invalid.returncode == 3
        and "DS_AUDITORIA_PROJECOES_DIVERGENTES" in invalid.stderr
    )
    assert _total(invalid)[3]["campos_ausentes"] == 1


def _total(result):
    line = next(s for s in result.stdout.splitlines() if s.startswith("TOTAL|"))
    return [json.loads(field) for field in line.split("|")[1:5]]
