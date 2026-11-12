"""Retoma apenas a outbox PostgreSQL; não coleta APIs comerciais ou Sheets."""

import argparse
import json

from bi_postgres_client import open_publisher
from bi_postgres_contract import PublicationError
from project_paths import load_private_settings


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operacao", choices=["status", "retomar", "arquivar-encerrada"])
    args = parser.parse_args(argv)
    from proxy_config import configure_proxy

    configure_proxy()
    publisher = None
    try:
        publisher = open_publisher(load_private_settings())
        if publisher is None:
            print(
                "Destino PostgreSQL desabilitado no perfil. Nenhuma publicação executada."
            )
            return 0
        if args.operacao == "status":
            publisher.simulate = True
        elif args.operacao == "retomar" and publisher.simulate:
            raise PublicationError("BI_PG_MODO_SIMULACAO; retomar exige aplicar")
        print(
            json.dumps(
                publisher.recover(archive_closed=args.operacao == "arquivar-encerrada"),
                ensure_ascii=False,
            )
        )
        return 0
    except PublicationError as error:
        print("[PENDÊNCIA] " + str(error))
        return 3
    finally:
        if publisher is not None:
            publisher.close()
