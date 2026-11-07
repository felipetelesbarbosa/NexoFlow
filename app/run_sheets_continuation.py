"""Configuração local das continuações no Meu Drive e das fontes Data Studio."""

from __future__ import annotations

import argparse
import json
from contextlib import nullcontext
from typing import Any

import gspread
from google.auth.exceptions import GoogleAuthError
from gspread.exceptions import APIError
from requests import RequestException

from sheets_continuation import (
    CELL_LIMIT,
    INDEX_TITLE,
    ContinuationError,
    ContinuationIndex,
    SheetsLease,
    allocated_cells,
    fingerprint,
    origin_diagnostic,
    stamp_book,
    verify_book_stamp,
)
from sheets_storage import STORAGE_SHEET, SheetsStorage, configured_storage

INDEX_SHEET_ID = 191126103


class StorageSetup:
    """Não inicializa/migra tabelas de negócio durante a configuração."""

    def __init__(self, client, hub_id, segment):
        self.client, self.hub_id, self.segment = client, hub_id, segment
        self.hub = client.open_by_key(hub_id)
        self.tabs = {ws.title: ws for ws in self.hub.worksheets()}
        configured = configured_storage(hub_id)
        self.layout = (
            SheetsStorage.from_values(self.tabs[STORAGE_SHEET].get("A1:B5"), hub_id)
            if STORAGE_SHEET in self.tabs
            else configured or SheetsStorage(hub_id, hub_id, hub_id)
        )
        if configured is not None and self.layout != configured:
            raise ContinuationError("Os IDs locais divergem do mapa NexoFlow_Arquivos.")
        from runtime_profile import validate_sheet_destinations

        validate_sheet_destinations(
            self.layout.dashboard, self.layout.operations, self.layout.history
        )
        self.roots = {
            "dashboard": hub_id,
            "operacao": self.layout.operations,
            "historico": self.layout.history,
        }
        self.books = {
            key: self.hub if key == hub_id else client.open_by_key(key)
            for key in set(self.roots.values())
        }
        self.lease = SheetsLease(self.hub)
        self.sheet = self.tabs.get(INDEX_TITLE)
        self.index = (
            ContinuationIndex.parse(
                self.sheet.get_all_values(),
                hub=hub_id,
                segment=segment,
                roots=self.roots,
            )
            if self.sheet is not None
            else None
        )

    def close(self):
        self.lease.release()

    def _stamp(self):
        try:
            for role, key in self.roots.items():
                self.lease.require()
                stamp_book(
                    self.books[key], hub=self.hub_id, segment=self.segment, role=role
                )
        except (APIError, RequestException, GoogleAuthError):
            self.lease.note_uncertain()
            raise

    def configure(self, provider):
        # Pré-voo sem escrita; a trava protege a reconferência e a configuração.
        if len(set(self.roots.values())) != 3:
            raise ContinuationError("Os três papéis exigem arquivos diferentes.")
        # Pré-voo somente leitura, inclusive antes de adquirir a trava remota.
        # Conferir TODOS os marcadores antes de criar o índice ou marcar origens.
        for role, key in self.roots.items():
            verify_book_stamp(
                self.books[key], hub=self.hub_id, segment=self.segment, role=role
            )
        # O provisionador comprova pasta privada e edição nas duas identidades.
        for role, key in self.roots.items():
            try:
                provider.prepare_intent(
                    key,
                    "0" * 32,
                    hub=self.hub_id,
                    segment=self.segment,
                    role=role,
                    number=1,
                    primary=True,
                )
            except ContinuationError as exc:
                raise ContinuationError(
                    f"Pré-voo bloqueado: arquivo={key}; papel={role}; {exc}"
                ) from None
        self.lease.require()
        # Reconferir sob lease: o pré-voo não autoriza usar marcadores obsoletos.
        for role, key in self.roots.items():
            verify_book_stamp(
                self.books[key], hub=self.hub_id, segment=self.segment, role=role
            )
        if self.index is not None:
            if self.sheet is None:
                raise ContinuationError(
                    "Índice sem aba comprovada; reabra a configuração."
                )
            current = ContinuationIndex.parse(
                self.sheet.get_all_values(),
                hub=self.hub_id,
                segment=self.segment,
                roots=self.roots,
            )
            if fingerprint(current.values()) != fingerprint(self.index.values()):
                raise ContinuationError(
                    "O índice mudou; reabra a configuração antes de continuar."
                )
            self._stamp()
            return False
        metadata = self.hub.fetch_sheet_metadata()
        if allocated_cells(metadata) + 192 > CELL_LIMIT:
            raise ContinuationError(
                "O Dashboard precisa de 192 células livres para registrar o índice. Reduza apenas a grade vazia antes de configurar."
            )
        if any(
            s["properties"]["sheetId"] == INDEX_SHEET_ID
            for s in metadata.get("sheets", [])
        ):
            raise ContinuationError(
                "O ID reservado para o índice já está em uso; exige revisão."
            )
        index = ContinuationIndex(self.hub_id, self.segment, self.roots)
        values = index.values()
        body = {
            "requests": [
                {
                    "addSheet": {
                        "properties": {
                            "sheetId": INDEX_SHEET_ID,
                            "title": INDEX_TITLE,
                            "gridProperties": {
                                "rowCount": 64,
                                "columnCount": 3,
                                "frozenRowCount": 1,
                            },
                        }
                    }
                },
                {
                    "updateCells": {
                        "range": {
                            "sheetId": INDEX_SHEET_ID,
                            "startRowIndex": 0,
                            "endRowIndex": len(values),
                            "startColumnIndex": 0,
                            "endColumnIndex": 3,
                        },
                        "rows": [
                            {
                                "values": [
                                    {"userEnteredValue": {"stringValue": v}}
                                    for v in row
                                ]
                            }
                            for row in values
                        ],
                        "fields": "userEnteredValue",
                    }
                },
            ]
        }
        try:
            self.hub.batch_update(body)
        except (APIError, RequestException, GoogleAuthError):
            self.lease.note_uncertain()
            tabs = {ws.title: ws for ws in self.hub.worksheets()}
            if INDEX_TITLE not in tabs or fingerprint(
                tabs[INDEX_TITLE].get_all_values()
            ) != fingerprint(values):
                raise
            self.lease.uncertain = False
        self.sheet = self.hub.worksheet(INDEX_TITLE)
        if fingerprint(self.sheet.get_all_values()) != fingerprint(values):
            raise ContinuationError(
                "O índice não foi confirmado; nenhuma continuação será criada."
            )
        self.index = index
        self._stamp()
        return True

    def activate_connector(self, titles):
        from google_sheets import GoogleSheetsStore

        allowed = set(GoogleSheetsStore.bi_schemas())
        if self.index is None or self.sheet is None:
            raise ContinuationError(
                "Configure a autorização e o índice antes de ativar as fontes Data Studio."
            )
        if not titles or not set(titles) <= allowed:
            raise ContinuationError(
                "Informe somente tabelas BI existentes no NexoFlow."
            )
        self.lease.require()
        current = self.sheet.get_all_values()
        if fingerprint(current) != fingerprint(self.index.values()):
            raise ContinuationError("O índice mudou; execute novamente a configuração.")
        self.index.config["connector_tables"] = sorted(
            set(self.index.config["connector_tables"]) | set(titles)
        )
        values = self.index.values()
        try:
            if self.sheet.row_count < len(values):
                self.sheet.resize(rows=len(values))
            self.lease.require()
            self.sheet.update(
                range_name=f"A1:C{len(values)}", values=values, value_input_option="RAW"
            )
        except (APIError, RequestException, GoogleAuthError):
            self.lease.note_uncertain()
            raise
        if fingerprint(self.sheet.get_all_values()) != fingerprint(values):
            raise ContinuationError("A ativação das fontes não foi confirmada.")

    def status(self):
        result = {
            "segmento": self.segment,
            "ativo": self.index is not None,
            "arquivos": [],
        }
        roles = dict(self.roots)
        if self.index is not None:
            roles.update(
                {
                    f"{data['role']}_continuacao_{data['number']}": key
                    for key, data in self.index.files.items()
                }
            )
            result["fontes_data_studio"] = self.index.config["connector_tables"]
        for role, key in roles.items():
            if self.index is not None and key in self.index.files:
                from sheets_provisioning import DRIVE

                info = self.client.http_client.request(
                    "get",
                    DRIVE + "/files/" + key,
                    params={"fields": "id,mimeType,trashed,properties"},
                ).json()
                properties = info.get("properties", {})
                if (
                    info.get("id") != key
                    or info.get("trashed")
                    or info.get("mimeType") != "application/vnd.google-apps.spreadsheet"
                    or properties.get("nexoflow_hub") != self.hub_id
                    or properties.get("nexoflow_segment") != self.segment
                    or properties.get("nexoflow_role") != self.index.files[key]["role"]
                ):
                    raise ContinuationError(
                        "Arquivo do índice pertence a outro perfil ou papel de armazenamento."
                    )
            book = self.books.get(key) or self.client.open_by_key(key)
            cells = allocated_cells(book.fetch_sheet_metadata())
            result["arquivos"].append(
                {
                    "papel": role,
                    "planilha_id": key,
                    "celulas_alocadas": cells,
                    "limite": CELL_LIMIT,
                }
            )
        return result


def _read_failure(exc):
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return {
        "resultado": "LEITURA_NEGADA"
        if code in (401, 403, 404) or isinstance(exc, PermissionError)
        else (
            "CONFIGURACAO_INVALIDA"
            if isinstance(exc, (ContinuationError, ValueError))
            else "FALHA_DE_LEITURA"
        ),
        "http": code if type(code) is int else None,
        "orientacao": "Conferir acesso/configuração; não tratar falha de leitura como marcador ausente.",
    }


def diagnose_origins(client, hub_id, segment):
    """Somente GETs: continua após erro de um arquivo, sem OAuth, lease ou escrita."""
    from sheets_provisioning import DRIVE

    report = {
        "diagnostico": "origens_v1",
        "segmento": segment,
        "somente_leitura": True,
        "pasta_e_permissoes_oauth": "NAO_VERIFICADAS_NESTE_DIAGNOSTICO",
        "origens_compativeis": False,
        "arquivos": [],
        "impedimentos": [],
        "nota": "Diagnóstico de origens não autoriza publicação nem confirma fontes Data Studio. A configuração ainda verifica pasta e permissões OAuth.",
    }
    try:
        hub = client.open_by_key(hub_id)
        tabs = {ws.title: ws for ws in hub.worksheets()}
        configured = configured_storage(hub_id)
        layout = (
            SheetsStorage.from_values(tabs[STORAGE_SHEET].get("A1:B5"), hub_id)
            if STORAGE_SHEET in tabs
            else configured
        )
        if layout is None or (configured is not None and configured != layout):
            raise ContinuationError("Mapa ausente ou divergente")
        from runtime_profile import validate_sheet_destinations

        validate_sheet_destinations(layout.dashboard, layout.operations, layout.history)
        roots = dict(
            dashboard=hub_id, operacao=layout.operations, historico=layout.history
        )
        if len(set(roots.values())) != 3:
            raise ContinuationError("IDs repetidos")
    except (
        APIError,
        RequestException,
        GoogleAuthError,
        OSError,
        ValueError,
        ContinuationError,
        gspread.exceptions.SpreadsheetNotFound,
    ) as exc:
        report["impedimentos"].append(
            {"etapa": "mapa_dos_destinos", **_read_failure(exc)}
        )
        return report
    files = [(role, key, "principal") for role, key in roots.items()]
    try:
        index = (
            ContinuationIndex.parse(
                tabs[INDEX_TITLE].get_all_values(),
                hub=hub_id,
                segment=segment,
                roots=roots,
            )
            if INDEX_TITLE in tabs
            else None
        )
        report["indice"] = "APROVADO" if index else "AUSENTE"
        if index:
            files.extend(
                (info["role"], key, "continuacao") for key, info in index.files.items()
            )
            report["fontes_data_studio_quantidade"] = len(
                index.config["connector_tables"]
            )
    except (
        APIError,
        RequestException,
        GoogleAuthError,
        ValueError,
        ContinuationError,
    ) as exc:
        report["indice"] = "NAO_COMPROVADO"
        report["impedimentos"].append({"etapa": "indice", **_read_failure(exc)})
    for role, key, kind in files:
        item: dict[str, Any] = {"papel": role, "planilha_id": key, "tipo": kind}
        report["arquivos"].append(item)
        try:
            book = hub if key == hub_id else client.open_by_key(key)
            meta = book.fetch_sheet_metadata(params={"fields": "developerMetadata"})
            item.update(origin_diagnostic(meta, hub=hub_id, segment=segment, role=role))
            if kind == "continuacao" and item["resultado"] == "AUSENTE":
                item["resultado"] = "BLOQUEADO"
                item["campos_divergentes"].append("origem_continuacao_ausente")
        except (
            APIError,
            RequestException,
            GoogleAuthError,
            OSError,
            ValueError,
            gspread.exceptions.SpreadsheetNotFound,
            ContinuationError,
        ) as exc:
            item.update(_read_failure(exc))
        try:
            info = client.http_client.request(
                "get",
                DRIVE + "/files/" + key,
                params={
                    "fields": "id,mimeType,trashed,properties,capabilities(canEdit),parents",
                },
            ).json()
            props = info.get("properties", {})
            continuation = "nexoflow_operation" in props
            valid = (
                info.get("id") == key
                and not info.get("trashed")
                and info.get("mimeType") == "application/vnd.google-apps.spreadsheet"
            )
            conflicts = []
            for field, expected in (
                ("nexoflow_hub", hub_id),
                ("nexoflow_role", role),
                ("nexoflow_segment", segment),
            ):
                if (field in props or kind == "continuacao") and props.get(
                    field
                ) != expected:
                    conflicts.append(field)
            if kind == "principal" and continuation:
                conflicts.append("principal_tem_intencao_de_continuacao")
            item["drive"] = {
                "arquivo_ativo_confirmado": valid,
                "edicao_conta_servico": info.get("capabilities", {}).get("canEdit")
                is True,
                "quantidade_pastas": len(info.get("parents", [])),
                "intencao_continuacao_presente": continuation,
                "campos_divergentes": conflicts,
            }
            if not valid or conflicts or not item["drive"]["edicao_conta_servico"]:
                item["resultado"] = "BLOQUEADO"
        except (
            APIError,
            RequestException,
            GoogleAuthError,
            OSError,
            ValueError,
        ) as exc:
            item["drive"] = _read_failure(exc)
            item["resultado"] = "LEITURA_DRIVE_NAO_COMPROVADA"
    report["origens_compativeis"] = not report["impedimentos"] and all(
        item["resultado"] in {"APROVADO", "AUSENTE"} for item in report["arquivos"]
    )
    return report


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=("configurar", "status", "diagnosticar-origens", "ativar-data-studio"),
    )
    parser.add_argument(
        "--abas",
        nargs="+",
        help="Tabelas BI cujas fontes já usam o conector de continuações.",
    )
    parser.add_argument(
        "--confirmar-fontes",
        action="store_true",
        help="Confirma a substituição das fontes selecionadas no Data Studio.",
    )
    args = parser.parse_args(argv)
    if args.operation == "ativar-data-studio" and (
        not args.confirmar_fontes or not args.abas
    ):
        parser.error(
            "Substitua primeiro as fontes pelo conector NexoFlow e use --abas ... --confirmar-fontes."
        )
    import os

    from config import GOOGLE_CREDENTIALS_FILE
    from project_paths import load_private_settings
    from proxy_config import configure_proxy
    from runtime_profile import segment
    from sheets_provisioning import MyDriveProvisioner, authorize_user

    configure_proxy()
    settings = load_private_settings()
    client = setup = provider = None
    try:
        if args.operation == "configurar":
            authorize_user()
        from run_noturno_console import operation_lock

        with operation_lock() if os.name == "nt" else nullcontext():
            kwargs = {}
            if args.operation == "diagnosticar-origens":
                kwargs["scopes"] = [
                    "https://www.googleapis.com/auth/spreadsheets.readonly",
                    "https://www.googleapis.com/auth/drive.metadata.readonly",
                ]
            client = gspread.service_account(
                filename=str(GOOGLE_CREDENTIALS_FILE), **kwargs
            )
            client.set_timeout((10, 60))
            if args.operation == "diagnosticar-origens":
                report = diagnose_origins(
                    client, settings.GOOGLE_SPREADSHEET_ID, segment()
                )
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 0 if report["origens_compativeis"] else 3
            setup = StorageSetup(client, settings.GOOGLE_SPREADSHEET_ID, segment())
            if args.operation == "configurar":
                provider = MyDriveProvisioner(
                    client.http_client.session,
                    getattr(client.http_client.auth, "service_account_email", ""),
                )
                setup.configure(provider)
                print(
                    "[OK] Origens Dashboard, Operação e Histórico comprovadas; índice de continuações configurado. Nenhum fato comercial foi publicado."
                )
                print(
                    "Para as tabelas BI, configure o conector e confirme as fontes. Guia: docs/CONTINUACOES.md"
                )
            elif args.operation == "ativar-data-studio":
                setup.activate_connector(args.abas)
                print(
                    "[OK] Fontes confirmadas. As próximas continuações dessas tabelas serão lidas pelo conector."
                )
            else:
                print(json.dumps(setup.status(), ensure_ascii=False, indent=2))
        return 0
    except ContinuationError as exc:
        print(f"[ERRO] {exc}")
        return 1
    except (APIError, RequestException, GoogleAuthError, OSError, ValueError):
        print(
            "[ERRO] Não foi possível configurar o armazenamento. Confira a autorização Google, os destinos e o acesso da conta de serviço."
        )
        return 1
    finally:
        if setup is not None:
            setup.close()
        if provider is not None:
            provider.close()
        if client is not None:
            client.http_client.session.close()


if __name__ == "__main__":
    raise SystemExit(run())
