"""Ensaio FARMA com checkpoints locais e fontes sintéticas."""

from hashlib import sha256
from uuid import uuid5

from publication_receipt import ready_receipt_matches

from .contracts import NOTURNO_STAGES
from .core import evaluate


def publication(task_id, stage, *, response_uncertain=False):
    revision = str(uuid5(task_id, stage))
    manifest_hash = sha256(f"{revision}:{stage}".encode()).hexdigest()
    receipt = None if response_uncertain else {
        "state": "READY",
        "revision": revision,
        "version": 1 if stage == "publicacao" else 2,
        "manifest_hash": manifest_hash,
    }
    return receipt if ready_receipt_matches(
        receipt, revision=revision, manifest_hash=manifest_hash
    ) else None


def run_noturno(store, task, *, interrupt_after=None):
    saved = store.checkpoints(task)
    scenario = task["cenario"]
    partial_ads = scenario == "dados_incompletos"
    for step, stage in enumerate(NOTURNO_STAGES, start=1):
        if step in saved:
            continue
        if stage == "atualizacao_weni":
            result = {"fonte": "fixture"}
        elif stage == "analytics":
            if scenario == "fonte_essencial_incompleta":
                store.finish(task, "revisao_necessaria", error="FONTE_ESSENCIAL_INCOMPLETA")
                return
            result = {
                "venda": evaluate("FARMA", "normal")["venda"],
                "cobertura_anuncios": "parcial" if partial_ads else "completa",
            }
        elif stage == "publicacao":
            if scenario == "rede_temporaria" and task["tentativa"] == 1:
                store.finish(task, "aguardando", error="REDE_SIMULADA")
                return
            receipt = publication(task["id"], stage, response_uncertain=scenario == "resposta_incerta")
            if receipt is None:
                store.finish(task, "revisao_necessaria", error="RESPOSTA_INCERTA")
                return
            result = {"recibo_simulado": receipt}
        elif stage == "recompra":
            # As etapas são confirmadas em ordem. Uma publicação incerta
            # termina o ensaio antes de aplicar a regra da Recompra.
            result = {"elegivel": evaluate("FARMA", "normal")["recompra"]}
        else:
            result = {"recibo_simulado": publication(task["id"], stage)}
        store.checkpoint(task, step, result)
        saved[step] = result
        if interrupt_after == step:
            raise SystemExit(75)
    store.finish(
        task,
        "parcial" if partial_ads else "concluida",
        result={
            "sintetico": True,
            "externas_gravacoes": 0,
            "pendencias": [
                {"fonte": "anuncios", "motivo": "COBERTURA_PARCIAL", "tratamento": "proxima_carga"}
            ] if partial_ads else [],
            "etapas": {stage: saved[step] for step, stage in enumerate(NOTURNO_STAGES, start=1)},
        },
    )
