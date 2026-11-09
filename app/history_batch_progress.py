"""Diagnóstico privado do cursor de lotes; não modifica journal ou revisão."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from dedup_io import save_private
from order_history import HistoryError
from order_history_sheets import SCHEMAS


def pending_cursor(review):
    with closing(
        sqlite3.connect(
            Path(review["journal"]).resolve().as_uri() + "?mode=ro", uri=True
        )
    ) as db:
        db.execute("PRAGMA query_only=ON")
        row = db.execute(
            "SELECT n,t,p,state FROM batches WHERE state!='done' ORDER BY n LIMIT 1"
        ).fetchone()
    if row and (
        type(row[0]) is not int
        or row[0] < 1
        or row[1] not in SCHEMAS
        or type(row[2]) is not int
        or row[2] < 0
        or row[3] not in ("pending", "sending", "restoring")
    ):
        raise ValueError("Cursor inválido")
    return dict(batch=row[0], table=row[1], part=row[2], state=row[3]) if row else None


def retry_budget(review, requested, maximum, percent):
    if requested is None:
        return None
    if (
        maximum is not None
        or percent is not None
        or type(requested) is not int
        or requested < 1
    ):
        raise HistoryError(
            "RETOMAR_LOTE_REQUER_NUMERO_POSITIVO_SEM_FRACAO_OU_MAX_LOTES"
        )
    cursor = pending_cursor(review)
    if not cursor or cursor["batch"] != requested or cursor["state"] == "restoring":
        raise HistoryError(
            "RETOMAR_LOTE_DEVE_SER_O_PRIMEIRO_PENDENTE; preservar ordem e dependências"
        )
    return 1


def record_failure(args, error):
    """Erro de transporte/validação não prova qual lote falhou: registrar cursor."""
    if args.planilhas != "aplicar" or args.revisao is None:
        return
    try:
        review = json.loads(Path(args.revisao).read_text(encoding="utf-8"))
        cursor = pending_cursor(review)
        status = getattr(getattr(error, "response", None), "status_code", None)
        event = uuid4().hex
        report = dict(
            recorded_at=datetime.now(UTC).isoformat(),
            error_class=type(error).__name__,
            http_status=status
            if type(status) is int and 100 <= status <= 599
            else None,
            format="historico_interrupcao_v1",
            event=event,
            cursor=cursor,
            interpretation="Cursor pendente no momento da interrupção; não prova falha exclusiva nesse lote. Revalidar contexto e valores antes de escrever.",
            action="Retomar a mesma revisão; não alterar estados, recibos ou assinaturas.",
        )
        path = Path(review["journal"]).parent / "ultima_interrupcao.json"
        save_private(path.parent / ("interrupcao_" + event + ".json"), report)
        save_private(path, report)
        if cursor:
            print(
                f"[LOTE PENDENTE] número={cursor['batch']}; tabela={cursor['table']}; parte={cursor['part']}; estado={cursor['state']}. Diagnóstico privado: ultima_interrupcao.json. Isso não comprova a causa do erro."
            )
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        # Falha de diagnóstico não pode ocultar o erro original.
        pass
