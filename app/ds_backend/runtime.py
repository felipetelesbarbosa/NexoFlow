"""Seleção explícita por perfil, preservando o transporte Sheets legado."""

from __future__ import annotations

from ds_backend.client import Client, configured, enabled

CURRENT_STORE = None


def open_store(settings, google_factory, *, purpose="analytics", readonly=False):
    global CURRENT_STORE
    if not enabled(settings):
        identifier = str(getattr(settings, "GOOGLE_SPREADSHEET_ID", "") or "").strip()
        return (
            google_factory.open_native_readonly(identifier)
            if readonly
            else google_factory(identifier)
        )
    from ds_backend.adapter import PostgresStore

    client = Client.from_settings(settings)
    try:
        from ds_backend.states import _DOCUMENTS, _VERSIONS

        _VERSIONS.clear()
        _DOCUMENTS.clear()
        if purpose == "weni" and client.config["segment"] == "FARMA" and not readonly:
            state = client.call("/v1/estados/ler", {"name": "weni_update"})
            if state.get("document") is None:
                from ds_backend.contract import StorageError

                raise StorageError("DS_ESTADO_EXIGE_MIGRACAO_INICIAL")
        CURRENT_STORE = PostgresStore(client, purpose=purpose, readonly=readonly)
        return CURRENT_STORE
    except Exception:
        client.close()
        raise


def complete(store, *, success=True):
    from ds_backend.adapter import PostgresStore

    if isinstance(store, PostgresStore):
        return store.finish(complete=success)
    return None


def backend_session(purpose):
    """Coleta/cache da mesma rotina fica em revisão remota, nunca em C: original."""
    from functools import wraps

    def decorate(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            import sys

            from project_paths import load_private_settings

            if not configured() or CURRENT_STORE is not None:
                return function(*args, **kwargs)
            supplied = (
                args[0] if args and isinstance(args[0], list) else kwargs.get("argv")
            )
            argv = supplied if isinstance(supplied, list) else sys.argv[1:]
            builder = function.__globals__.get(
                "build_parser"
            ) or function.__globals__.get("parser")
            from argparse import ArgumentParser

            built = builder() if callable(builder) else None
            parsed = (
                built.parse_args(argv) if isinstance(built, ArgumentParser) else None
            )
            from runtime_profile import segment

            if parsed is not None:
                profile = getattr(parsed, "perfil", None)
                if profile is not None and profile != segment():
                    from ds_backend.contract import StorageError

                    raise StorageError("DS_PERFIL_DIVERGENTE")
                if getattr(parsed, "quarter", None) is not None and not getattr(
                    parsed, "full", False
                ):
                    raise ValueError("--quarter exige --full.")
                if (
                    purpose == "recompra"
                    and (
                        getattr(parsed, "apply", False)
                        or getattr(parsed, "check_review", False)
                    )
                    and not getattr(parsed, "require_review", None)
                ):
                    raise ValueError("--apply exige --require-review.")
                if purpose == "historico" and getattr(parsed, "planilhas", None):
                    from ds_backend.contract import StorageError

                    raise StorageError("DS_USAR_ARMAZENAMENTO_POSTGRES")
                if (
                    purpose == "historico"
                    and getattr(parsed, "inicio", None)
                    and not getattr(parsed, "auditar_banco", None)
                ):
                    from order_history import HistoryQuery

                    HistoryQuery(
                        segment(),
                        parsed.inicio,
                        parsed.fim or parsed.inicio,
                        parsed.limite,
                    )
                if (
                    purpose == "historico"
                    and getattr(parsed, "max_paginas", None) is not None
                    and parsed.max_paginas < 1
                ):
                    raise ValueError("--max-paginas exige valor positivo.")
            from runtime_profile import segment

            weni_farma = purpose == "weni" and segment() == "FARMA"
            settings = load_private_settings()
            if purpose == "historico" and any(
                x in argv for x in ("--auditar-banco", "--excluir-pedidos")
            ):
                return function(*args, **kwargs)
            from google_sheets import GoogleSheetsStore

            readonly = (
                (purpose == "historico" and "--somente-resumo" in argv)
                or "--check-only" in argv
                or (weni_farma and "--dry-run" in argv)
            )
            store = open_store(
                settings, GoogleSheetsStore, purpose=purpose, readonly=readonly
            )
            try:
                if weni_farma and "--dry-run" in argv:
                    from ds_backend.contract import StorageError

                    info = store.client.info
                    if not info["version"] or info.get("pending"):
                        raise StorageError("DS_SIMULACAO_EXIGE_READY_SEM_PENDENCIA")
                    store.client.expected_read_version = info["version"]
                result = function(*args, **kwargs)
                if not readonly and (not weni_farma or result == 0):
                    complete(store)
                return result
            finally:
                store.close()

        return wrapper

    return decorate
