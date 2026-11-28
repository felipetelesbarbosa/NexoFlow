"""Only synthetic archive/rows, no commercial connector or private input."""
import hashlib
import json
from types import SimpleNamespace

import pytest
from nexoflow_hub import frozen_replay as replay
from nexoflow_hub.real_read_transport import ProbePending


def test_archive_refuses_modified_hash_before_reading(tmp_path):
    file = tmp_path / "reference.zip"
    file.write_bytes(b"synthetic not zip")
    with pytest.raises(ProbePending, match="REFERENCIA_DIVERGENTE"):
        replay.Capture(file, hashlib.sha256(b"other").hexdigest())


def test_frozen_scope_rejects_pet_and_production(monkeypatch):
    for key, value in {
        "HUB_AMBIENTE": "homologacao",
        "HUB_ESCRITA_REAL": "false",
        "NEXOFLOW_PERFIL": "FARMA",
        "HUB_FROZEN_REPLAY_ENABLED": "true",
    }.items():
        monkeypatch.setenv(key, value)
    item = {"segmento": "FARMA", "cenario": replay.SCENARIO}
    replay.scope(item)
    with pytest.raises(ProbePending):
        replay.scope({**item, "segmento": "PET"})
    with pytest.raises(ProbePending):
        replay.scope({**item, "cenario": replay.INTERRUPTION})
    monkeypatch.setenv("HUB_AMBIENTE", "producao")
    with pytest.raises(ProbePending):
        replay.scope(item)


def test_checkpoint_rejects_changed_reference(monkeypatch):
    from threading import Event

    monkeypatch.setattr(replay, "BATCH_SIZE", 2)
    inputs = [{"contato": {"uuid": uid}} for uid in ["a", "b", "c"]]
    capture = SimpleNamespace(rows=lambda _: iter(inputs), sha="a"*64)
    rules = SimpleNamespace(weni={uid: {} for uid in ["a","b","c"]}, weni_row=lambda *_: None)
    saved = {1001: {"protocolo":replay.PROTOCOL,"sha256_referencia":"b"*64,
                    "fase":"weni","lote":1,"linhas":2,"contagens":{"contatos":2}}}
    with pytest.raises(ProbePending, match="REFERENCIA_DIVERGENTE"):
        replay.replay_rows(None,{},capture,rules,"weni",1000,"ignored",saved,Event(),None)


def test_frozen_duplicate_uuid_rejected():
    capture = SimpleNamespace(rows=lambda _: iter([{"contato":{"uuid":"a"}}]*2))
    rules = SimpleNamespace(weni={"a":{}})
    with pytest.raises(ProbePending, match="REFERENCIA_DIVERGENTE"):
        replay.reference_ids(capture,rules,"weni","ignored")


def test_frozen_disallows_http_even_get(monkeypatch):
    import requests

    # No actual network needed; the call must stop before requests sends.
    with replay.offline_rules(), pytest.raises(ProbePending, match="ESCRITA_O_REDE_BLOQUEADA"):
        requests.get("https://example.invalid", timeout=1)


def test_replay_result_contains_aggregates_only():
    result = replay.progress("weni",1,51,{"contatos":120})
    text = json.dumps(result)
    assert result["publicacoes"] == result["externas_gravacoes"] == 0
    assert "cpf" not in text and "uuid" not in text
