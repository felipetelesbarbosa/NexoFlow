"""Ensaio FARMA com checkpoints locais e fontes sintéticas."""

from hashlib import sha256
from typing import Any
from uuid import uuid5

from publication_receipt import ready_receipt_matches

from .contracts import NOTURNO_STAGES
from .core import evaluate


def publication(task_id, stage, *, response_uncertain=False):
    revision = str(uuid5(task_id, stage))
    manifest_hash = sha256(f"{revision}:{stage}".encode()).hexdigest()
    receipt = (
        None
        if response_uncertain
        else {
            "state": "READY",
            "revision": revision,
            "version": 1 if stage == "publicacao" else 2,
            "manifest_hash": manifest_hash,
        }
    )
    return (
        receipt
        if ready_receipt_matches(
            receipt, revision=revision, manifest_hash=manifest_hash
        )
        else None
    )


def run_noturno(store, task, *, interrupt_after=None):
    scenario = task["cenario"]
    if scenario in {"leitura_real_amostral", "planejamento_real"}:
        from .real_read_probe import run_noturno_probe

        return run_noturno_probe(store, task)
    saved = store.checkpoints(task)
    partial_ads = scenario in {"dados_incompletos", "reserva_anuncios_incompletos"}
    adapter = None
    if store.settings.noturno_test_dsn:
        from .noturno_adapters import Adapters, PublicationUncertain

        adapter = Adapters(store, task)
    elif scenario in {
        "reserva_isolada",
        "reserva_anuncios_incompletos",
        "recompra_resposta_perdida",
    }:
        raise RuntimeError("DESTINO_SINTETICO_OBRIGATORIO")
    result: dict[str, Any]
    for step, stage in enumerate(NOTURNO_STAGES, start=1):
        if step in saved:
            continue
        if stage == "atualizacao_weni":
            result = adapter.update() if adapter else {"fonte": "fixture"}
        elif stage == "analytics":
            if scenario == "fonte_essencial_incompleta":
                store.finish(
                    task, "revisao_necessaria", error="FONTE_ESSENCIAL_INCOMPLETA"
                )
                return
            result = {
                "venda": evaluate("FARMA", "normal")["venda"],
                "cobertura_anuncios": "parcial" if partial_ads else "completa",
            }
            if scenario in {"meta_recuperacao", "meta_consulta_direta_falha"}:
                from .meta_recovery import evaluate_meta_fixture

                meta_result = evaluate_meta_fixture(scenario)
                result["meta_recuperacao"] = meta_result
                result["cobertura_anuncios"] = meta_result["cobertura"]
        elif stage == "publicacao":
            if scenario == "rede_temporaria" and task["tentativa"] == 1:
                store.finish(task, "aguardando", error="REDE_SIMULADA")
                return
            if adapter:
                try:
                    receipt = adapter.publish(
                        stage, saved[2], uncertain=scenario == "resposta_incerta"
                    )
                except PublicationUncertain as exc:
                    store.finish(
                        task,
                        "revisao_necessaria",
                        error="RESPOSTA_INCERTA",
                        result={
                            "sintetico": True,
                            "externas_gravacoes": 0,
                            "publicacao": exc.evidence,
                        },
                    )
                    return
            else:
                receipt = publication(
                    task["id"], stage, response_uncertain=scenario == "resposta_incerta"
                )
            if receipt is None:
                store.finish(task, "revisao_necessaria", error="RESPOSTA_INCERTA")
                return
            result = {"recibo" if adapter else "recibo_simulado": receipt}
        elif stage == "recompra":
            # As etapas são confirmadas em ordem. Uma publicação incerta
            # termina o ensaio antes de aplicar a regra da Recompra.
            result = (
                adapter.recompra()
                if adapter
                else {"elegivel": evaluate("FARMA", "normal")["recompra"]}
            )
        else:
            result = (
                {"recibo": adapter.publish(stage, saved[4])}
                if adapter
                else {"recibo_simulado": publication(task["id"], stage)}
            )
        store.checkpoint(task, step, result)
        saved[step] = result
        if interrupt_after == step:
            raise SystemExit(75)
    # O checkpoint durável de Analytics governa a retomada, inclusive Meta.
    partial_ads = saved[2]["cobertura_anuncios"] == "parcial"
    pending = list(saved[1].get("pendencias", []))
    if partial_ads:
        pending.append(
            {
                "fonte": "anuncios",
                "motivo": "COBERTURA_PARCIAL",
                "tratamento": "proxima_carga",
            }
        )
    store.finish(
        task,
        "parcial" if pending else "concluida",
        result={
            "sintetico": True,
            "externas_gravacoes": 0,
            "pendencias": pending,
            "etapas": {
                stage: saved[step] for step, stage in enumerate(NOTURNO_STAGES, start=1)
            },
        },
    )
