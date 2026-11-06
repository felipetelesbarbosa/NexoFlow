"""Migração explícita; API/worker não migram o banco ao iniciar."""

import argparse

from .config import Settings
from .store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollback-schema-vazio", action="store_true")
    args = parser.parse_args()
    Store(Settings.load()).migrate(down=args.rollback_schema_vazio)
    print("Migração de homologação concluída.")


if __name__ == "__main__":
    main()
