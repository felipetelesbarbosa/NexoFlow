"""Administração local, sem rotas administrativas públicas."""

import argparse
import json
from pathlib import Path

from integrations.bi_itens_publisher.store import Store, migrate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn-file", required=True, type=Path)
    parser.add_argument("--migrar", action="store_true")
    parser.add_argument("--reverter-lote")
    parser.add_argument("--encerrar-plano")
    args = parser.parse_args()
    dsn = args.dsn_file.read_text().strip()
    if args.migrar:
        migrate(dsn)
        print("Migração aditiva concluída no piloto.")
    elif args.encerrar_plano:
        print(json.dumps(Store(dsn).close_plan(args.encerrar_plano)))
    elif args.reverter_lote:
        print(json.dumps(Store(dsn).rollback(args.reverter_lote)))
    else:
        with Store(dsn).connect() as conn:
            Store(dsn).check(conn)
        print("Destino e schema conferidos.")


if __name__ == "__main__":
    main()
