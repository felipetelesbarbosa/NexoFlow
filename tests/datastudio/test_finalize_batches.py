"""Volume lógico sem banco comercial: custo e tamanho limitados por bloco."""

from math import ceil

from integrations.datastudio.finalize_batches import FINALIZE_ROWS, write_stage


def test_sealed_volume_never_becomes_one_unbounded_statement():
    size = 2750730

    class Result:
        def __init__(self, rows=(), count=0):
            self.rows, self.rowcount = rows, count

        def fetchall(self):
            return self.rows

    class Database:
        writes = 0
        peak = 0

        def execute(self, query, params):
            assert "OFFSET" not in query
            if query.startswith("SELECT"):
                after = int(params[2] or 0)
                rows = [
                    dict(tabela="Controle", chave=f"{i:010}")
                    for i in range(after + 1, min(after + params[3], size) + 1)
                ]
                self.peak = max(self.peak, len(rows))
                return Result(rows)
            count = int(params[-1]) - int(params[-3] or 0)
            assert count <= FINALIZE_ROWS
            self.writes += 1
            return Result(count=0 if query.startswith("DELETE") else count)

    database = Database()
    assert write_stage(database, "farma", "synthetic-revision", 1) == size
    assert database.peak == FINALIZE_ROWS
    assert database.writes == 3 * ceil(size / FINALIZE_ROWS)
