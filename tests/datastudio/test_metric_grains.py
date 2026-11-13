"""Contrato das métricas exercitado pelos geradores oficiais, sem dados comerciais."""

from contextlib import closing

import pytest

from analytics import build_bi_ads_rows, build_daily_metrics
from ds_backend.contract import REGISTRY, StorageError, normalize, record_key
from ds_backend.migration import Export


def contacts(prefix="primeiro_anuncio_", ad_id="same-ad"):
    return [
        dict(
            contact_uuid=f"synthetic-{i}",
            **{
                prefix + "data": "2026-11-02",
                prefix + "id": ad_id,
                prefix + "titulo": title,
            },
        )
        for i, title in enumerate(("Título A", "Título B", "Título B"))
    ]


@pytest.mark.parametrize("prefix", ["primeiro_anuncio_", "ultimo_anuncio_"])
@pytest.mark.parametrize("ad_id", ["same-ad", ""])
@pytest.mark.parametrize("segment", ["FARMA", "PET"])
@pytest.mark.parametrize("table", ["Metricas_Diarias", "BI_Ads"])
def test_official_metric_grain_preserves_titles_counts_and_replay(
    tmp_path, table, segment, prefix, ad_id
):
    values = (
        build_daily_metrics(contacts(prefix, ad_id))
        if table == "Metricas_Diarias"
        else build_bi_ads_rows(
            contacts(prefix, ad_id),
            [],
            snapshot_date="2026-11-02",
            updated_at="2026-11-03",
        )
    )
    records = [
        dict(zip(REGISTRY[table]["columns"], row, strict=True)) for row in values
    ]
    assert len(records) == 2
    normalized = normalize(table, records, segment)
    assert len({record_key(table, r) for r in normalized}) == 2
    with closing(Export(tmp_path / (table + ".sqlite"), create=True)) as out:
        out.add(table, records, segment)
        out.add(table, records, segment)
        assert out.db.execute("SELECT COUNT(*) FROM linhas").fetchone()[0] == 2
        assert sum(int(r["contatos"]) for r in normalized) == 3
        changed = dict(records[0], contatos=99)
        with pytest.raises(StorageError, match="DS_ORIGEM_CHAVE_DIVERGENTE"):
            out.add(table, [changed], segment)


def test_all_cache_keys_match_the_source_sqlite_contract():
    import json
    from pathlib import Path

    source = json.loads(
        Path("app/ds_backend/cache_schema.json").read_text(encoding="utf-8")
    )
    for table, spec in source.items():
        assert REGISTRY["Cache_" + table]["keys"] == spec["keys"]
