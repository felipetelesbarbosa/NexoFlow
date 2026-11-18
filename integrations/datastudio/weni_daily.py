"""Dados diários independentes da revisão de vendas. Projeto único fixado pelo administrador."""

from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from ds_backend.contract import StorageError, digest

TABLE = "BI_Weni_Conversas_Diarias"
FIELDS = ("conversas_weni", "resolvidas", "nao_resolvidas", "transferidas")
COLUMNS = ["data", "segmento", *FIELDS, "origem", "fuso"]


def install(store, project):
    if store.segment != "FARMA":
        raise StorageError("DS_INSIGHTS_SEGMENTO")
    project = str(UUID(project))
    with store.connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS farma.nf_weni_projeto(
            unico boolean PRIMARY KEY CHECK(unico), projeto uuid NOT NULL UNIQUE)""")
        conn.execute(
            "INSERT INTO farma.nf_weni_projeto VALUES(true,%s) ON CONFLICT(unico) DO NOTHING",
            (project,),
        )
        if (
            str(
                conn.execute(
                    "SELECT projeto FROM farma.nf_weni_projeto WHERE unico"
                ).fetchone()["projeto"]
            )
            != project
        ):
            raise StorageError("DS_INSIGHTS_PROJETO_DIVERGENTE")
        conn.execute("""CREATE TABLE IF NOT EXISTS farma.nf_weni_dias(
          projeto uuid REFERENCES farma.nf_weni_projeto(projeto), data date NOT NULL, observado timestamptz NOT NULL,
          conversas_weni integer NOT NULL CHECK(conversas_weni>=0), resolvidas integer NOT NULL CHECK(resolvidas>=0),
          nao_resolvidas integer NOT NULL CHECK(nao_resolvidas>=0), transferidas integer NOT NULL CHECK(transferidas>=0),
          hash text NOT NULL, PRIMARY KEY(projeto,data))""")
        conn.execute("""ALTER TABLE farma.nf_weni_dias ADD COLUMN IF NOT EXISTS origem text NOT NULL
            DEFAULT 'WENI_INSIGHTS' CHECK(origem IN ('WENI_INSIGHTS','WENI_FLOWS_V2'))""")
        conn.execute("""CREATE OR REPLACE VIEW farma.ds_bi_weni_conversas_diarias WITH(security_barrier=true) AS
            SELECT data,'FARMA'::text AS segmento,conversas_weni,resolvidas,nao_resolvidas,transferidas,
            origem,'America/Belem'::text AS fuso FROM farma.nf_weni_dias""")
        conn.execute("GRANT SELECT ON farma.nf_weni_projeto TO nf_ds_farma_publish")
        conn.execute(
            "GRANT SELECT, INSERT ON farma.nf_weni_dias TO nf_ds_farma_publish"
        )
        conn.execute(
            "GRANT UPDATE(observado,conversas_weni,resolvidas,nao_resolvidas,transferidas,hash,origem) ON farma.nf_weni_dias TO nf_ds_farma_publish"
        )
        conn.execute(
            "GRANT SELECT ON farma.ds_bi_weni_conversas_diarias TO nf_ds_farma_read"
        )


def put(store, project, day, observed, metrics, origin="WENI_INSIGHTS"):
    if store.segment != "FARMA":
        raise StorageError("DS_INSIGHTS_SEGMENTO")
    try:
        observed_at = datetime.fromisoformat(observed)
        local_day = date.fromisoformat(day)
        if (
            str(UUID(project)) != project
            or local_day.isoformat() != day
            or observed_at.utcoffset() != UTC.utcoffset(None)
            or local_day >= observed_at.astimezone(ZoneInfo("America/Belem")).date()
            or not isinstance(metrics, dict)
            or set(metrics) != set(FIELDS)
            or any(
                type(v) is not int or not 0 <= v <= 2147483647 for v in metrics.values()
            )
        ):
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        raise StorageError("DS_INSIGHTS_DIA_INVALIDO") from None
    payload = dict(project=project, day=day, observed=observed, metrics=metrics)
    if origin == "WENI_FLOWS_V2":
        payload["origin"] = origin
    elif origin != "WENI_INSIGHTS":
        raise StorageError("DS_INSIGHTS_ORIGEM_DIVERGENTE")
    fingerprint = digest(payload)
    with store.connect() as conn:
        if not conn.execute(
            "SELECT 1 FROM farma.nf_weni_projeto WHERE projeto=%s", (project,)
        ).fetchone():
            raise StorageError("DS_INSIGHTS_PROJETO_DIVERGENTE")
        conn.execute(
            """INSERT INTO farma.nf_weni_dias AS d
            (projeto,data,observado,conversas_weni,resolvidas,nao_resolvidas,transferidas,hash,origem)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(projeto,data) DO UPDATE SET
            (observado,conversas_weni,resolvidas,nao_resolvidas,transferidas,hash,origem)=
            (excluded.observado,excluded.conversas_weni,excluded.resolvidas,excluded.nao_resolvidas,excluded.transferidas,excluded.hash,excluded.origem)
            WHERE d.observado < excluded.observado""",
            (
                project,
                day,
                observed,
                *(metrics[k] for k in FIELDS),
                fingerprint,
                origin,
            ),
        )
        current = conn.execute(
            "SELECT hash FROM farma.nf_weni_dias WHERE projeto=%s AND data=%s",
            (project, day),
        ).fetchone()
        if current["hash"] != fingerprint:
            raise StorageError("DS_INSIGHTS_DIA_SUPERADO")
    return dict(state="CONFIRMADO", hash=fingerprint, target=store.target)
