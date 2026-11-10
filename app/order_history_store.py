"""Migração aditiva no SQLite privado existente; páginas/checkpoint atômicos."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from order_history import (
    MAX_HISTORY_PAGE_SIZE,
    HistoryError,
    HistoryQuery,
    canonical,
    digest,
    financial_record_digest,
    ltv,
    normalize_order,
    page_envelope,
    preserve_item_positions,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS history_run_receipts (
 run TEXT NOT NULL, segment TEXT NOT NULL, id TEXT NOT NULL,
 occurrences INTEGER NOT NULL, fresh INTEGER NOT NULL, changed INTEGER NOT NULL,
 state TEXT NOT NULL, PRIMARY KEY(run,segment,id));
CREATE TABLE IF NOT EXISTS history_windows (
 key TEXT PRIMARY KEY, segment TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
 page_limit INTEGER NOT NULL, next_page INTEGER NOT NULL DEFAULT 1,
 total INTEGER, pages INTEGER, status TEXT NOT NULL DEFAULT 'incompleta',
 reason TEXT NOT NULL DEFAULT '', updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS history_seen (
 window_key TEXT NOT NULL, id TEXT NOT NULL, page INTEGER NOT NULL,
 PRIMARY KEY(window_key,id));
CREATE TABLE IF NOT EXISTS history_orders (
 segment TEXT NOT NULL, id TEXT NOT NULL, owner TEXT NOT NULL,
 record TEXT NOT NULL, first_seen TEXT NOT NULL, updated TEXT NOT NULL,
 PRIMARY KEY(segment,id));
CREATE TABLE IF NOT EXISTS history_issues (
 segment TEXT NOT NULL, id TEXT NOT NULL, reason TEXT NOT NULL,
 PRIMARY KEY(segment,id));
CREATE TABLE IF NOT EXISTS history_revisions (
 segment TEXT NOT NULL, id TEXT NOT NULL, old_digest TEXT NOT NULL,
 new_digest TEXT NOT NULL, mode TEXT NOT NULL, at TEXT NOT NULL,
 UNIQUE(segment,id,old_digest,new_digest));
"""


class HistoryStore:
    def __init__(self, db, segment):
        self.db, self.segment = db, segment
        db.executescript(SCHEMA)
        self.active_run = None

    def begin(self, query, *, restart=False):
        if query.segment != self.segment:
            raise HistoryError("SEGMENTO_DIVERGENTE")
        now = datetime.now(UTC).isoformat()
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO history_windows(key,segment,start,end,page_limit,updated) VALUES(?,?,?,?,?,?)",
                (query.key, self.segment, query.start, query.end, query.limit, now),
            )
            if restart:
                self.db.execute(
                    "DELETE FROM history_seen WHERE window_key=?", (query.key,)
                )
                self.db.execute(
                    "UPDATE history_windows SET next_page=1,total=NULL,pages=NULL,status='incompleta',reason='',updated=? WHERE key=?",
                    (now, query.key),
                )
        return self.state(query)

    def state(self, query):
        row = self.db.execute(
            "SELECT next_page,total,pages,status,reason FROM history_windows WHERE key=? AND segment=?",
            (query.key, self.segment),
        ).fetchone()
        if not row:
            raise HistoryError("JANELA_AUSENTE")
        count = self.db.execute(
            "SELECT count(*) FROM history_seen WHERE window_key=?", (query.key,)
        ).fetchone()[0]
        return dict(
            zip(("next_page", "total", "pages", "status", "reason"), row, strict=True),
            received=count,
            remaining=None if row[1] is None else max(0, row[1] - count),
            calendar_coverage="LIMITES_DA_API_NAO_HOMOLOGADOS",
        )

    def mark_failure(self, query, code):
        with self.db:
            self.db.execute(
                "UPDATE history_windows SET status='incompleta',reason=? WHERE key=?",
                (code, query.key),
            )

    def commit_page(
        self, query, page, payload, *, now, mode="historica", interrupt=None
    ):
        rows, total, pages = page_envelope(payload, query, page)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            state = self.state(query)
            if state["next_page"] != page or state["status"] == "extraida":
                raise HistoryError("CURSOR_CONCORRENTE")
            if state["total"] is not None and (state["total"], state["pages"]) != (
                total,
                pages,
            ):
                raise HistoryError("TOTAL_INSTAVEL_RECONCILIAR")
            for payload_row in rows:
                record = normalize_order(payload_row, query.segment, now)
                oid = record["id"]
                if self.db.execute(
                    "SELECT 1 FROM history_seen WHERE window_key=? AND id=?",
                    (query.key, oid),
                ).fetchone():
                    raise HistoryError("PAGINA_REPETIDA_RECONCILIAR")
                if record["date"] and not query.contains(record["date"]):
                    raise HistoryError("EMISSAO_FORA_DA_FAIXA")
                outcome = self.upsert(record, now=now, mode=mode)
                if self.active_run:
                    self.db.execute(
                        """INSERT INTO history_run_receipts VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(run,segment,id) DO UPDATE SET occurrences=occurrences+1,
                    changed=max(changed,excluded.changed),state=excluded.state""",
                        (
                            self.active_run,
                            self.segment,
                            oid,
                            1,
                            int(outcome == "novo"),
                            int(outcome == "atualizado"),
                            record["state"],
                        ),
                    )
                self.db.execute(
                    "INSERT INTO history_seen VALUES(?,?,?)", (query.key, oid, page)
                )
            count = self.db.execute(
                "SELECT count(*) FROM history_seen WHERE window_key=?", (query.key,)
            ).fetchone()[0]
            if count > total or (page >= pages and count != total):
                raise HistoryError("TOTAL_IDS_DIVERGENTE_RECONCILIAR")
            if interrupt:
                interrupt()
            status = "extraida" if page >= pages else "incompleta"
            self.db.execute(
                "UPDATE history_windows SET next_page=?,total=?,pages=?,status=?,reason='',updated=? WHERE key=?",
                (page + 1, total, pages, status, now, query.key),
            )
        return self.state(query)

    def upsert(self, record, *, now, mode):
        oid = record["id"]
        old = self.db.execute(
            "SELECT record FROM history_orders WHERE segment=? AND id=?",
            (self.segment, oid),
        ).fetchone()
        old_record = json.loads(old[0]) if old else None
        record = preserve_item_positions(old_record, record)
        reason = (
            record["reason"]
            if record["state"] == "pendente"
            or (old_record and record["state"] == "ignorado")
            else ""
        )
        if old_record and old_record["owner"] != record["owner"]:
            reason = "CLIENTE_OFICIAL_CONFLITANTE"
        if (
            old_record
            and old_record["date"]
            and record["date"]
            and old_record["date"] != record["date"]
        ):
            reason = "EMISSAO_CONFLITANTE"
        # O fechamento antigo só é reaberto por reconciliação explícita.
        from pedido_utils import business_order_datetime

        old_date = business_order_datetime(old_record["date"]) if old_record else None
        current = business_order_datetime(now)
        if (
            old_date
            and current
            and (current.date() - old_date.date()).days > 20
            and mode != "reconciliacao"
        ):
            if old_record and financial_digest(old_record) != financial_digest(record):
                reason = "FECHAMENTO_ANTIGO_REQUER_RECONCILIACAO"
        if reason:
            self.db.execute(
                "INSERT OR REPLACE INTO history_issues VALUES(?,?,?)",
                (self.segment, oid, reason),
            )
            if old_record:
                return "preservado"
        else:
            self.db.execute(
                "DELETE FROM history_issues WHERE segment=? AND id=?",
                (self.segment, oid),
            )
        if old_record:
            record = dict(record)
            record["contact_uuid"] = old_record.get("contact_uuid", "")
            record["link_state"] = old_record.get("link_state", "NAO_CONFERIDO")
            if digest(old_record) == digest(record):
                # Confirmação recente mantém precedência frente a snapshots antigos.
                self.db.execute(
                    "UPDATE history_orders SET updated=? WHERE segment=? AND id=?",
                    (now, self.segment, oid),
                )
                return "existente"
            self.db.execute(
                "INSERT OR IGNORE INTO history_revisions VALUES(?,?,?,?,?,?)",
                (self.segment, oid, digest(old_record), digest(record), mode, now),
            )
        self.db.execute(
            """INSERT INTO history_orders VALUES(?,?,?,?,?,?) ON CONFLICT(segment,id) DO UPDATE SET
            owner=excluded.owner,record=excluded.record,updated=excluded.updated""",
            (
                self.segment,
                oid,
                record["owner"],
                json.dumps(record, ensure_ascii=False),
                now,
                now,
            ),
        )
        return (
            "novo"
            if not old_record
            else "atualizado"
            if financial_digest(old_record) != financial_digest(record)
            else "existente"
        )

    def records(self):
        for (raw,) in self.db.execute(
            "SELECT record FROM history_orders WHERE segment=? ORDER BY id",
            (self.segment,),
        ):
            yield json.loads(raw)

    def link(self, directory, contacts):
        from order_history import IdentityIndex

        if directory.segment != self.segment:
            raise HistoryError("CADASTRO_DE_OUTRO_SEGMENTO")
        index = IdentityIndex(contacts)
        counts = {"vinculados": 0, "sem_vinculo": 0}
        # Impede que a mesma identidade Weni seja concedida a dois clientes oficiais.
        owners_by_contact = {}
        matches = {}
        for owner, customer in directory.by_id.items():
            uid, state = index.match(customer)
            matches[owner] = (uid, state)
            if uid:
                owners_by_contact.setdefault(uid, set()).add(owner)
        with self.db:
            for record in self.records():
                uid, state = matches.get(
                    record["owner"], ("", "CADASTRO_OFICIAL_AUSENTE")
                )
                if uid and len(owners_by_contact[uid]) != 1:
                    uid, state = "", "CLIENTE_OFICIAL_AMBIGUO"
                unchanged = (
                    record.get("contact_uuid") == uid
                    and record.get("link_state") == state
                )
                record.update(contact_uuid=uid, link_state=state)
                counts["vinculados" if uid else "sem_vinculo"] += 1
                if unchanged:
                    continue
                self.db.execute(
                    "UPDATE history_orders SET record=? WHERE segment=? AND id=?",
                    (
                        json.dumps(record, ensure_ascii=False),
                        self.segment,
                        record["id"],
                    ),
                )
        return counts

    def seed_observations(self, now):
        """Adota snapshots locais pela chave oficial, sem mudar sua proveniência."""
        if not self.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='orders'"
        ).fetchone():
            return
        with self.db:
            for oid, raw, observed in self.db.execute(
                "SELECT id,payload,last_seen FROM orders"
            ):
                if self.db.execute(
                    "SELECT 1 FROM history_orders WHERE segment=? AND id=?",
                    (self.segment, oid),
                ).fetchone():
                    continue
                snapshot = json.loads(raw)
                header = snapshot.get("ultimoPedido")
                if (
                    not isinstance(header, dict)
                    or str(header.get("segmento", "")).upper() != self.segment
                ):
                    continue
                record = normalize_order(
                    {
                        "capa": header,
                        **({"itens": snapshot["itens"]} if "itens" in snapshot else {}),
                    },
                    self.segment,
                    now,
                )
                record["source"] = "FARMALIDER_CLIENTES_" + self.segment
                self.upsert(record, now=observed, mode="observacao")

    def totals(self):
        summaries = ltv(self.records())
        return {
            "pedidos_validos": sum(r["orders"] for r in summaries),
            "clientes_oficiais": len(summaries),
            "faturamento_centavos": sum(r["revenue_cents"] for r in summaries),
            "pendencias": self.db.execute(
                "SELECT count(*) FROM history_issues WHERE segment=?", (self.segment,)
            ).fetchone()[0],
        }


def financial_digest(record):
    return financial_record_digest(record)


def collect(
    client,
    store,
    query,
    *,
    now,
    max_pages=None,
    restart=False,
    mode="historica",
    progress=None,
    include_totals=True,
):
    if max_pages is not None and (type(max_pages) is not int or max_pages < 1):
        raise HistoryError("MAXIMO_PAGINAS_INVALIDO")
    state = store.begin(query, restart=restart)
    processed = 0
    # Limite finito por execução: budget operacional, não limite da API.
    budget = max_pages if max_pages is not None else 10000
    while state["status"] != "extraida" and processed < budget:
        try:
            payload = client.get_pedidos_history(query, state["next_page"])
            state = store.commit_page(
                query, state["next_page"], payload, now=now, mode=mode
            )
        except Exception as exc:
            store.mark_failure(
                query,
                str(exc) if isinstance(exc, HistoryError) else "FALHA_LEITURA_API",
            )
            raise
        processed += 1
        if progress:
            progress(state)
    return dict(
        state, pages_this_run=processed, **(store.totals() if include_totals else {})
    )


def merge_canonical(store, orders, items):
    """Concilia por ID; nada é atribuído a anúncio por contato sozinho."""
    from analytics import _item_key
    from pedido_utils import business_order_datetime

    checked_at = dict(
        store.db.execute(
            "SELECT id,updated FROM history_orders WHERE segment=?", (store.segment,)
        )
    )
    by_id = {str(o.get("pedido_id")): o for o in orders}
    replacement_items = {}
    for record in store.records():
        old = by_id.get(record["id"])
        if record["state"] not in {"valido", "cancelado"}:
            continue
        if (
            old
            and str(
                old.get("farmalider_cliente_id")
                or old.get("farmalider_cod_cliente")
                or ""
            )
            != record["owner"]
        ):
            continue
        historical_time = business_order_datetime(checked_at.get(record["id"]))
        current_time = (
            business_order_datetime(old.get("farmalider_confirmado_em"))
            if old
            else None
        )
        if current_time and historical_time and current_time > historical_time:
            # Um cache antigo não desfaz uma confirmação/cancelamento recente.
            continue
        # Fonte histórica já reconcilia fechamentos; não altera metadados de anúncio.
        row = canonical(record)
        row["farmalider_confirmado_em"] = checked_at.get(record["id"], "")
        if old:
            row = dict(old, **row)
        by_id[record["id"]] = row
        replacement_items[record["id"]] = [
            {
                "item_chave": _item_key(row["pedido_chave"], i["position"]),
                "pedido_chave": row["pedido_chave"],
                "pedido_id": record["id"],
                "contact_uuid": record["contact_uuid"],
                "data_hora": record["date"],
                "data": record["date"][:10],
                "produto_codigo": i["sku"],
                "produto_nome": i["name"],
                "produto_ordem": str(i["position"]),
                "quantidade": i["quantity"],
                "valor_unitario": i["unit"],
                "valor_total": f"{Decimal(i['total_cents']) / 100:.2f}",
            }
            for i in record["items"]
            if not i["freight"] and record["state"] == "valido"
        ]
    return list(by_id.values()), [
        i for i in items if i.get("pedido_id") not in replacement_items
    ] + [i for batch in replacement_items.values() for i in batch]


def analytics_history(client, contacts, orders, items, *, now, settings):
    from config import LOG_DIR
    from recompra_lock import state_lock

    with state_lock(LOG_DIR / "historico_pedidos_state.json"):
        return _analytics_history(
            client, contacts, orders, items, now=now, settings=settings
        )


def _analytics_history(client, contacts, orders, items, *, now, settings):
    """Opt-in explícito; só hoje..D-20, nenhum backfill automático no Noturno."""
    from analytics_history_sync import requested_period
    from customer_observations import connect
    from farmalider_customers import directory_for
    from runtime_profile import segment

    query, historical = requested_period(settings, now, segment())
    if not historical and not getattr(settings, "FARMALIDER_HISTORY_ENABLED", False):
        with connect() as db:
            store = HistoryStore(db, segment())
            merged, details = merge_canonical(store, orders, items)
            return merged, details, None
    with connect() as db:
        store = HistoryStore(db, segment())
        store.seed_observations(now)
        result = collect_windows(
            client,
            store,
            query,
            now=now,
            mode="historica" if historical else "incremental",
            max_pages=None
            if historical
            else int(getattr(settings, "FARMALIDER_HISTORY_MAX_PAGES", 100)),
        )
        directory = directory_for(client)
        if directory is not None:
            result.update(store.link(directory, contacts))
        merged, details = merge_canonical(store, orders, items)
        return merged, details, result


def collect_windows(
    client,
    store,
    query,
    *,
    now,
    max_pages=None,
    window_days=31,
    restart=False,
    mode="historica",
    progress=None,
):
    """Faixas com fronteira compartilhada; cobertura civil continua não comprovada."""
    from datetime import timedelta

    if type(window_days) is not int or window_days < 1:
        raise HistoryError("JANELA_DIAS_INVALIDA")
    if max_pages is not None and (type(max_pages) is not int or max_pages < 1):
        raise HistoryError("MAXIMO_PAGINAS_INVALIDO")
    from time import perf_counter
    from uuid import uuid4

    started = perf_counter()
    store.active_run = uuid4().hex
    queries = []
    rejected_legacy_windows = 0
    if mode == "incremental":
        for key, start, end, limit, cursor, total in store.db.execute(
            "SELECT key,start,end,page_limit,next_page,total FROM history_windows WHERE segment=? AND status='incompleta' ORDER BY start",
            (store.segment,),
        ):
            if limit > MAX_HISTORY_PAGE_SIZE:
                if (
                    cursor != 1
                    or total is not None
                    or store.db.execute(
                        "SELECT 1 FROM history_seen WHERE window_key=? LIMIT 1", (key,)
                    ).fetchone()
                ):
                    raise HistoryError("JANELA_LEGADA_LIMITE_INVALIDO_REQUER_REVISAO")
                rejected_legacy_windows += 1
                continue
            queries.append(HistoryQuery(store.segment, start, end, limit))
    if len(query.start) == len(query.end) == 10:
        cursor = query.start_at.date()
        end = query.end_at.date()
        while True:
            stop = min(end, cursor + timedelta(days=window_days))
            queries.append(
                HistoryQuery(
                    query.segment, cursor.isoformat(), stop.isoformat(), query.limit
                )
            )
            if stop == end:
                break
            cursor = stop  # nunca pular um dia assumindo dataFim inclusivo
    else:
        queries.append(query)
    # Uma janela incompleta aparece só uma vez, mesmo se for a janela corrente.
    queries = list({q.key: q for q in queries}.values())
    budget = max_pages if max_pages is not None else 10000
    results = []
    for index, q in enumerate(queries, 1):
        state = store.begin(q)
        reset = restart or (mode == "incremental" and state["status"] == "extraida")
        if budget <= 0:
            break
        result = collect(
            client,
            store,
            q,
            now=now,
            max_pages=budget,
            restart=reset,
            mode=mode,
            progress=(
                lambda state, index=index: progress(
                    dict(
                        state,
                        window=index,
                        windows=len(queries),
                        current_page=state["next_page"] - 1,
                        pending_page=None
                        if state["status"] == "extraida"
                        else state["next_page"],
                    )
                )
            )
            if progress
            else None,
            include_totals=False,
        )
        results.append(result)
        budget -= result["pages_this_run"]
    incomplete = sum(store.begin(q)["status"] != "extraida" for q in queries)
    summary = dict(
        results[-1] if results else {},
        **store.totals(),
        execution=execution_totals(store, results, query, perf_counter() - started),
        audit=history_audit(store, query),
        status="incompleta" if incomplete else "extraida",
        windows=len(queries),
        incomplete_windows=incomplete,
        rejected_legacy_windows=rejected_legacy_windows,
        pages_this_run=sum(r["pages_this_run"] for r in results),
    )
    store.active_run = None
    return summary


def execution_totals(store, windows, query, elapsed):
    row = store.db.execute(
        """SELECT coalesce(sum(occurrences),0),count(*),
        coalesce(sum(fresh),0),coalesce(sum(changed),0),
        coalesce(sum(state='cancelado'),0),coalesce(sum(state='pendente'),0)
        FROM history_run_receipts WHERE run=? AND segment=?""",
        (store.active_run, store.segment),
    ).fetchone()
    return dict(
        execucao_id=store.active_run,
        segmento=store.segment,
        inicio=query.start,
        fim=query.end,
        fim_enviado_api=query.api_end,
        limite=query.limit,
        janelas_consultadas=sum(w["pages_this_run"] > 0 for w in windows),
        paginas_consultadas=sum(w["pages_this_run"] for w in windows),
        total_declarado_janelas_consultadas=sum(
            w["total"] or 0 for w in windows if w["pages_this_run"]
        ),
        registros_recebidos=row[0],
        ids_unicos=row[1],
        repetidos_entre_janelas=row[0] - row[1],
        novos=row[2],
        ja_existentes=row[1] - row[2],
        atualizados=row[3],
        cancelados_recebidos=row[4],
        pendentes_recebidos=row[5],
        duracao_segundos=round(elapsed, 3),
    )


def history_audit(store, query=None):
    """Uma passagem local; nenhum identificador pessoal é exibido."""

    def empty():
        return dict(
            pedidos_armazenados=0,
            pedidos_validos=0,
            cancelados=0,
            pendentes=0,
            ignorados=0,
            faturamento_centavos=0,
            pedidos_com_vinculo=0,
            pedidos_sem_vinculo=0,
            avisos_frete=0,
        )

    accumulated, period = empty(), empty()
    groups = {
        name: set()
        for name in (
            "compradores",
            "cancelados",
            "pendentes",
            "vinculados",
            "sem_vinculo",
            "contatos",
        )
    }
    period_buyers = set()
    sources = {}
    for record in store.records():
        in_period = (
            query is not None
            and bool(record["date"])
            and query.contains(record["date"])
        )
        for target in [accumulated, period] if in_period else [accumulated]:
            target["pedidos_armazenados"] += 1
            if any(
                w.get("reason") == "FRETE_DIVERGENTE"
                for w in record.get("warnings", [])
            ):
                target["avisos_frete"] += 1
            key = {
                "valido": "pedidos_validos",
                "cancelado": "cancelados",
                "pendente": "pendentes",
                "ignorado": "ignorados",
            }[record["state"]]
            target[key] += 1
            if record["state"] == "valido":
                target["faturamento_centavos"] += record["revenue_cents"]
            target[
                "pedidos_com_vinculo"
                if record.get("contact_uuid")
                else "pedidos_sem_vinculo"
            ] += 1
        owner = record["owner"]
        if record["state"] == "valido":
            groups["compradores"].add(owner)
            if in_period:
                period_buyers.add(owner)
        elif record["state"] in ("cancelado", "pendente"):
            groups[
                {"cancelado": "cancelados", "pendente": "pendentes"}[record["state"]]
            ].add(owner)
        groups["vinculados" if record.get("contact_uuid") else "sem_vinculo"].add(owner)
        if record.get("contact_uuid"):
            groups["contatos"].add(record["contact_uuid"])
        source = record.get("source", "NAO_INFORMADA")
        sources[source] = sources.get(source, 0) + 1
    for group in groups.values():
        group.discard("")
    accumulated.update(
        clientes_com_compras_validas=len(groups["compradores"]),
        clientes_com_cancelados=len(groups["cancelados"]),
        clientes_com_pendentes=len(groups["pendentes"]),
        clientes_com_vinculo=len(groups["vinculados"]),
        clientes_sem_vinculo=len(groups["sem_vinculo"]),
        contatos_weni_distintos=len(groups["contatos"]),
    )
    period["clientes_com_compras_validas"] = len(period_buyers)
    issues = []
    for reason, state, source, count in store.db.execute(
        """SELECT i.reason,json_extract(o.record,'$.state'),json_extract(o.record,'$.source'),count(*)
         FROM history_issues i LEFT JOIN history_orders o ON i.segment=o.segment AND i.id=o.id
         WHERE i.segment=? GROUP BY i.reason,json_extract(o.record,'$.state'),json_extract(o.record,'$.source')""",
        (store.segment,),
    ):
        issues.append(
            dict(
                motivo=reason,
                origem=source or "NAO_INFORMADA",
                quantidade=count,
                efeito="atualizacao_bloqueada_fato_anterior_preservado"
                if state == "valido"
                else "sem_compra_valida_para_LTV",
                acao="Conferir fonte oficial e revisões privadas; usar reconciliação explícita somente após validar a divergência.",
            )
        )
    windows = []
    keys = []
    for (
        key,
        start,
        end,
        limit,
        total,
        pages,
        cursor,
        status,
        received,
    ) in store.db.execute(
        """SELECT w.key,w.start,w.end,w.page_limit,w.total,w.pages,w.next_page,w.status,count(s.id)
        FROM history_windows w LEFT JOIN history_seen s ON s.window_key=w.key
        WHERE w.segment=? GROUP BY w.key ORDER BY w.start""",
        (store.segment,),
    ):
        window = HistoryQuery(store.segment, start, end)
        if query and (window.end_at < query.start_at or window.start_at > query.end_at):
            continue
        keys.append(key)
        windows.append(
            dict(
                inicio=start,
                fim=end,
                limite=limit,
                declarados=total,
                paginas=pages,
                recebidos=received,
                extracao=status,
                proxima_pagina_pendente=None if status == "extraida" else cursor,
            )
        )
    unique = (
        store.db.execute(
            "SELECT count(DISTINCT id) FROM history_seen WHERE window_key IN ("
            + ",".join("?" for _ in keys)
            + ")",
            keys,
        ).fetchone()[0]
        if keys
        else 0
    )
    return dict(
        janelas_persistidas=windows,
        ids_unicos_janelas_persistidas=unique,
        repeticoes_janelas_persistidas=sum(w["recebidos"] for w in windows) - unique,
        acumulado=accumulated,
        periodo=period if query else None,
        pendencias=issues,
        origens=sources,
        cobertura_temporal="LIMITES_DA_API_NAO_HOMOLOGADOS",
    )
