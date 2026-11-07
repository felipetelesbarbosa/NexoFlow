"""Histórico oficial em homologação: contrato compartilhado e transporte sintético."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from psycopg.types.json import Jsonb

from order_history import (
    HistoryError,
    HistoryQuery,
    digest,
    normalize_order,
    page_envelope,
    preserve_item_positions,
)
from pedido_utils import business_order_datetime


def validate_parameters(segment, parameters, *, reference=None):
    if set(parameters) != {
        "inicio",
        "fim",
        "limite",
        "max_paginas",
        "modo",
        "reiniciar",
        "quantidade_sintetica",
    }:
        raise HistoryError("PARAMETROS_INVALIDOS")
    query = HistoryQuery(
        segment, parameters["inicio"], parameters["fim"], parameters["limite"]
    )
    if (
        type(parameters["max_paginas"]) is not int
        or not 1 <= parameters["max_paginas"] <= 10000
    ):
        raise HistoryError("ORCAMENTO_INVALIDO")
    if (
        type(parameters["quantidade_sintetica"]) is not int
        or not 0 <= parameters["quantidade_sintetica"] <= 1200
    ):
        raise HistoryError("FIXTURE_INVALIDA")
    if (
        parameters["modo"] not in {"historica", "incremental", "reconciliacao"}
        or type(parameters["reiniciar"]) is not bool
    ):
        raise HistoryError("MODO_INVALIDO")
    if parameters["modo"] == "incremental":
        current = business_order_datetime(reference or datetime.now(UTC))
        assert current is not None
        if (
            query.start != (current.date() - timedelta(days=20)).isoformat()
            or query.end != current.date().isoformat()
        ):
            raise HistoryError("INCREMENTAL_USA_HOJE_MENOS_20_DIAS")
    return query


class SyntheticHistorySource:
    """Mock HTTP em memória; não há token comercial nem endereço externo."""

    def __init__(self, count):
        self.count = count

    def get_pedidos_history(self, query, page):
        # Um transporte simulado verifica o contrato HTTP realmente serializado.
        import httpx

        def handle(request):
            params = request.url.params
            if (
                request.method != "GET"
                or request.url.path != f"/api/Delivery/pedidos/{query.segment.lower()}"
                or params["token"] != "fixture+/&=?%"
                or params["dataInicio"] != query.start
                or params["dataFim"] != query.api_end
            ):
                return httpx.Response(400)
            first = (int(params["pagina"]) - 1) * int(params["limite"])
            rows = []
            for n in range(first, min(self.count, first + query.limit)):
                oid = n + 1
                rows.append(
                    {
                        "capa": {
                            "id": oid,
                            "codCliente": 10,
                            "segmento": query.segment,
                            "emissao": query.start_at.isoformat(),
                            "status": 2,
                            "formaPagamento": 5,
                            "frete": 0,
                        },
                        "itens": [
                            {
                                "id": f"fixture-{oid}",
                                "codPedido": oid,
                                "codProduto": 8,
                                "descricao": "Produto sintético",
                                "quantidade": 1,
                                "valor": 80,
                                "total": 80,
                                "desconto": 0,
                            }
                        ],
                    }
                )
            return httpx.Response(
                200,
                json={
                    "pagina": page,
                    "limite": query.limit,
                    "totalRegistros": self.count,
                    "totalPaginas": (self.count + query.limit - 1) // query.limit,
                    "pedidos": rows,
                },
            )

        with httpx.Client(
            transport=httpx.MockTransport(handle), follow_redirects=False
        ) as client:
            response = client.get(
                f"https://fixture.invalid/api/Delivery/pedidos/{query.segment.lower()}",
                params={
                    "dataInicio": query.start,
                    "dataFim": query.api_end,
                    "pagina": page,
                    "limite": query.limit,
                    "token": "fixture+/&=?%",
                },
            )
            response.raise_for_status()
            return response.json()


class PgHistory:
    def __init__(self, store, task):
        self.store, self.task = store, task
        self.segment = task["segmento"]

    def begin(self, query, restart=False):
        with self.store.connect() as db:
            self.store.fenced(db, self.task)
            db.execute(
                """INSERT INTO hub.historico_janelas(segmento,chave,inicio,fim,limite) VALUES(%s,%s,%s,%s,%s)
                          ON CONFLICT DO NOTHING""",
                (self.segment, query.key, query.start, query.end, query.limit),
            )
            if restart:
                db.execute(
                    "DELETE FROM hub.historico_recebidos WHERE segmento=%s AND janela=%s",
                    (self.segment, query.key),
                )
                db.execute(
                    "UPDATE hub.historico_janelas SET proxima_pagina=1,total=NULL,paginas=NULL,estado='incompleta',motivo='' WHERE segmento=%s AND chave=%s",
                    (self.segment, query.key),
                )
            return self.state(db, query)

    def state(self, db, query):
        row = db.execute(
            "SELECT * FROM hub.historico_janelas WHERE segmento=%s AND chave=%s",
            (self.segment, query.key),
        ).fetchone()
        if row is None:
            raise HistoryError("JANELA_AUSENTE")
        count = db.execute(
            "SELECT count(*) AS n FROM hub.historico_recebidos WHERE segmento=%s AND janela=%s",
            (self.segment, query.key),
        ).fetchone()
        assert count is not None
        return {
            "next_page": row["proxima_pagina"],
            "total": row["total"],
            "pages": row["paginas"],
            "status": row["estado"],
            "received": count["n"],
        }

    def commit_page(self, query, page, payload, *, now, mode, step):
        rows, total, pages = page_envelope(payload, query, page)
        affected = set()
        with self.store.connect() as db:
            self.store.fenced(db, self.task)
            state = self.state(db, query)
            if state["next_page"] != page or state["status"] == "extraida":
                raise HistoryError("CURSOR_CONCORRENTE")
            if state["total"] is not None and (total, pages) != (
                state["total"],
                state["pages"],
            ):
                raise HistoryError("TOTAL_INSTAVEL_RECONCILIAR")
            for raw in rows:
                record = normalize_order(raw, self.segment, now)
                if record["date"] and not query.contains(record["date"]):
                    raise HistoryError("EMISSAO_FORA_DA_FAIXA")
                if db.execute(
                    "SELECT 1 FROM hub.historico_recebidos WHERE segmento=%s AND janela=%s AND pedido_id=%s",
                    (self.segment, query.key, record["id"]),
                ).fetchone():
                    raise HistoryError("PAGINA_REPETIDA_RECONCILIAR")
                self.upsert(db, record, now=now, mode=mode)
                affected.add(record["owner"])
                db.execute(
                    "INSERT INTO hub.historico_recebidos VALUES(%s,%s,%s,%s)",
                    (self.segment, query.key, record["id"], page),
                )
            count = self.state(db, query)["received"]
            if count > total or (page >= pages and count != total):
                raise HistoryError("TOTAL_IDS_DIVERGENTE_RECONCILIAR")
            status = "extraida" if page >= pages else "incompleta"
            db.execute(
                "UPDATE hub.historico_janelas SET proxima_pagina=%s,total=%s,paginas=%s,estado=%s,motivo='',atualizada_em=clock_timestamp() WHERE segmento=%s AND chave=%s",
                (page + 1, total, pages, status, self.segment, query.key),
            )
            for owner in affected:
                db.execute(
                    "DELETE FROM hub.historico_ltv WHERE segmento=%s AND cliente_id=%s",
                    (self.segment, owner),
                )
                db.execute(
                    """INSERT INTO hub.historico_ltv(segmento,cliente_id,valor_centavos,compras,primeira,ultima)
                    SELECT segmento,cliente_id,sum((registro->>'revenue_cents')::bigint),count(*)::integer,min(registro->>'date'),max(registro->>'date')
                    FROM hub.historico_pedidos WHERE segmento=%s AND cliente_id=%s AND registro->>'state'='valido'
                    GROUP BY segmento,cliente_id""",
                    (self.segment, owner),
                )
            result = self.state(db, query)
            db.execute(
                "INSERT INTO hub.checkpoints(segmento,tarefa_id,etapa,resultado) VALUES(%s,%s,%s,%s)",
                (self.segment, self.task["id"], step, Jsonb(result)),
            )
            db.execute(
                "UPDATE hub.tarefas SET lease_ate=clock_timestamp()+%s*interval '1 second' WHERE id=%s",
                (self.store.settings.lease_seconds, self.task["id"]),
            )
            db.execute(
                "UPDATE hub.coordenacao SET lease_ate=(SELECT lease_ate FROM hub.tarefas WHERE id=%s) WHERE segmento=%s AND dono=%s",
                (self.task["id"], self.segment, self.task["dono"]),
            )
            self.store.audit(db, self.task, "PAGINA_HISTORICA_CONFIRMADA")
            db.execute(
                """INSERT INTO hub.cobertura(segmento,fonte,contrato,inicio,fim,estado)
                VALUES(%s,'FARMALIDER_PEDIDOS_PAGINADOS','envelope-v1-limites-nao-homologados',%s,%s,'incompleta') ON CONFLICT DO NOTHING""",
                (self.segment, query.start_at, query.end_at),
            )
            return result

    def upsert(self, db, record, *, now, mode):
        found = db.execute(
            "SELECT registro FROM hub.historico_pedidos WHERE segmento=%s AND pedido_id=%s",
            (self.segment, record["id"]),
        ).fetchone()
        old = found["registro"] if found else None
        record = preserve_item_positions(old, record)
        reason = (
            record["reason"]
            if record["state"] == "pendente" or (old and record["state"] == "ignorado")
            else ""
        )
        if old and old["owner"] != record["owner"]:
            reason = "CLIENTE_OFICIAL_CONFLITANTE"
        if old and old["date"] and record["date"] and old["date"] != record["date"]:
            reason = "EMISSAO_CONFLITANTE"
        current = business_order_datetime(now)
        prior = business_order_datetime(old["date"]) if old else None
        if (
            old
            and prior
            and current
            and (current.date() - prior.date()).days > 20
            and mode != "reconciliacao"
        ):
            keys = set(record) - {"contact_uuid", "link_state", "source"}
            if digest({k: old.get(k) for k in keys}) != digest(
                {k: record[k] for k in keys}
            ):
                reason = "FECHAMENTO_ANTIGO_REQUER_RECONCILIACAO"
        if reason:
            db.execute(
                "INSERT INTO hub.historico_pendencias VALUES(%s,%s,%s) ON CONFLICT(segmento,pedido_id) DO UPDATE SET motivo=EXCLUDED.motivo",
                (self.segment, record["id"], reason),
            )
            if old:
                return
        else:
            db.execute(
                "DELETE FROM hub.historico_pendencias WHERE segmento=%s AND pedido_id=%s",
                (self.segment, record["id"]),
            )
        if old and digest(old) == digest(record):
            db.execute(
                "UPDATE hub.historico_pedidos SET atualizado_em=clock_timestamp() WHERE segmento=%s AND pedido_id=%s",
                (self.segment, record["id"]),
            )
            return
        if old:
            db.execute(
                "INSERT INTO hub.historico_revisoes(segmento,pedido_id,anterior,atual,modo,tarefa_id) VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    self.segment,
                    record["id"],
                    digest(old),
                    digest(record),
                    mode,
                    self.task["id"],
                ),
            )
        db.execute(
            """INSERT INTO hub.historico_pedidos(segmento,pedido_id,cliente_id,registro) VALUES(%s,%s,%s,%s)
            ON CONFLICT(segmento,pedido_id) DO UPDATE SET registro=EXCLUDED.registro,atualizado_em=clock_timestamp()""",
            (self.segment, record["id"], record["owner"], Jsonb(record)),
        )

    def totals(self):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT coalesce(sum(valor_centavos),0) AS cents,coalesce(sum(compras),0) AS orders,count(*) AS clients FROM hub.historico_ltv WHERE segmento=%s",
                (self.segment,),
            ).fetchone()
            pending = db.execute(
                "SELECT count(*) AS n FROM hub.historico_pendencias WHERE segmento=%s",
                (self.segment,),
            ).fetchone()
            assert row is not None and pending is not None
            return {
                "faturamento_centavos": int(row["cents"]),
                "pedidos_validos": int(row["orders"]),
                "clientes_oficiais": row["clients"],
                "pendencias": pending["n"],
            }


def run_history(store, task, *, source=None, interrupt_after=None):
    parameters = task["parametros"]
    query = validate_parameters(
        task["segmento"], parameters, reference=task["criada_em"]
    )
    history = PgHistory(store, task)
    saved = store.checkpoints(task)
    if saved and saved.get(0, {}).get("janela") != query.key:
        raise HistoryError("CONTRATO_CALENDARIO_ALTERADO_CRIAR_NOVA_TAREFA")
    # Reinício explícito uma vez por tarefa; crash não apaga cursor confirmado.
    if not saved:
        state = history.begin(query)
        if parameters["reiniciar"] or (
            parameters["modo"] == "incremental" and state["status"] == "extraida"
        ):
            state = history.begin(query, restart=True)
        store.checkpoint(task, 0, {"janela": query.key})
    else:
        state = history.begin(query)
    source = source or SyntheticHistorySource(parameters["quantidade_sintetica"])
    processed = len([s for s in saved if s > 0])
    while state["status"] != "extraida" and processed < parameters["max_paginas"]:
        page = state["next_page"]
        payload = source.get_pedidos_history(query, page)
        state = history.commit_page(
            query,
            page,
            payload,
            now=datetime.now(UTC).isoformat(),
            mode=parameters["modo"],
            step=processed + 1,
        )
        processed += 1
        if interrupt_after == processed:
            raise SystemExit(75)
    result = dict(
        state,
        **history.totals(),
        sintetico=True,
        externas_gravacoes=0,
        calendario="LIMITES_API_NAO_HOMOLOGADOS",
    )
    store.finish(
        task,
        "parcial"
        if state["status"] != "extraida" or result["pendencias"]
        else "concluida",
        result=result,
    )
