"""Autorização local e criação reconciliável de continuações no Meu Drive."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials
from requests import RequestException

from dedup_io import save_private
from project_paths import ROOT
from sheets_continuation import ContinuationError

DRIVE = "https://www.googleapis.com/drive/v3"
OAUTH_SCOPES = ["https://www.googleapis.com/auth/drive"]
CLIENT_FILE = ROOT / "credentials/google_oauth_client.json"
USER_FILE = ROOT / "credentials/google_oauth_user.json"


class CreationRejected(ContinuationError):
    """O Drive recusou a criação antes de produzir um arquivo."""


def authorize_user(client_file: Path = CLIENT_FILE, user_file: Path = USER_FILE):
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not client_file.is_file():
        raise ContinuationError(
            "Crie um cliente OAuth do tipo Aplicativo para computador no Google Cloud "
            "e salve seu JSON localmente em credentials/google_oauth_client.json. "
            "Não envie esse arquivo pelo chat nem o inclua no Git."
        )
    data = json.loads(client_file.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("installed"), dict):
        raise ContinuationError(
            "Use o JSON oficial de um cliente OAuth Google para computador."
        )
    client = data["installed"]
    if (
        client.get("auth_uri") != "https://accounts.google.com/o/oauth2/auth"
        or client.get("token_uri") != "https://oauth2.googleapis.com/token"
        or not client.get("client_id")
        or not client.get("client_secret")
    ):
        raise ContinuationError(
            "Use o JSON oficial de um cliente OAuth Google para computador."
        )
    flow = InstalledAppFlow.from_client_config(
        data, OAUTH_SCOPES, autogenerate_code_verifier=True
    )
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        open_browser=True,
        authorization_prompt_message="Conclua a autorização na janela do navegador.",
        success_message="Autorização NexoFlow concluída. Você pode fechar esta janela.",
        timeout_seconds=300,
    )
    if not credentials.refresh_token:
        raise ContinuationError(
            "A autorização não forneceu acesso offline. Autorize novamente."
        )
    save_private(user_file, json.loads(credentials.to_json()))
    return credentials


class MyDriveProvisioner:
    def __init__(
        self,
        service_session,
        service_email: str,
        *,
        user_file=USER_FILE,
        before_write=lambda: None,
    ):
        if not Path(user_file).is_file():
            raise ContinuationError(
                "A criação de continuações exige autorização Google neste computador. "
                "Execute nexo armazenamento configurar no perfil desejado."
            )
        credentials = Credentials.from_authorized_user_file(
            str(user_file), OAUTH_SCOPES
        )
        self.owner = AuthorizedSession(credentials)
        self.source = service_session
        self.service_email = service_email
        self.user_file = Path(user_file)
        self.before_write = before_write

    def close(self):
        self.owner.close()

    @staticmethod
    def _json(session, method, path, **kwargs):
        response = session.request(method, DRIVE + path, timeout=(10, 90), **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}

    def _get(self, session, path, **kwargs):
        # Leituras admitem repetição; criar arquivo nunca tem retry automático.
        for attempt in range(4):
            try:
                return self._json(session, "GET", path, **kwargs)
            except RequestException as exc:
                status = getattr(exc.response, "status_code", None)
                if status is not None and status not in (408, 429, 500, 502, 503, 504):
                    raise
                if attempt == 3:
                    raise
                time.sleep(min(2**attempt, 5))
        raise ContinuationError("Leitura do Drive não foi concluída.")

    def source_info(self, source_id: str) -> dict[str, Any]:
        result = self._get(
            self.source,
            f"/files/{source_id}",
            params={
                "fields": "id,name,mimeType,parents,trashed,driveId,capabilities(canEdit)",
                "supportsAllDrives": "true",
            },
        )
        if (
            result.get("id") != source_id
            or result.get("trashed")
            or result.get("mimeType") != "application/vnd.google-apps.spreadsheet"
        ):
            raise ContinuationError("A origem da continuação não é uma planilha ativa.")
        return result

    def locate(self, operation: str) -> str | None:
        if not operation or any(c not in "0123456789abcdef" for c in operation):
            raise ContinuationError("Identificador de criação inválido.")
        response = self._get(
            self.owner,
            "/files",
            params={
                "q": "trashed=false and properties has { key='nexoflow_operation' and value='"
                + operation
                + "' }",
                "fields": "files(id,mimeType),nextPageToken",
                "pageSize": 100,
            },
        )
        files = response.get("files", [])
        if len(files) > 1 or response.get("nextPageToken"):
            raise ContinuationError(
                "Mais de um arquivo corresponde à criação; preservar para revisão."
            )
        if (
            files
            and files[0].get("mimeType") != "application/vnd.google-apps.spreadsheet"
        ):
            raise ContinuationError(
                "O comprovante de criação aponta para outro tipo de arquivo."
            )
        return files[0]["id"] if files else None

    def prepare_intent(
        self,
        source_id: str,
        operation: str,
        *,
        hub: str,
        segment: str,
        role: str,
        number: int,
    ):
        source = self.source_info(source_id)
        if source.get("driveId"):
            raise ContinuationError(
                "Este provisionamento foi configurado para Meu Drive; confira a origem."
            )
        permissions = self._get(
            self.source,
            f"/files/{source_id}/permissions",
            params={
                "fields": "permissions(type,role,emailAddress,deleted,expirationTime),nextPageToken",
                "pageSize": 100,
            },
        )
        if permissions.get("nextPageToken"):
            raise ContinuationError(
                "A origem tem acessos demais para cópia automática; revise a configuração."
            )
        private = []
        for item in permissions.get("permissions", []):
            if item.get("deleted"):
                continue
            if item.get("type") not in ("user", "group") or not item.get(
                "emailAddress"
            ):
                raise ContinuationError(
                    "A origem possui compartilhamento amplo; revise os acessos antes de criar continuações."
                )
            if item.get("role") not in ("reader", "writer", "commenter", "owner"):
                raise ContinuationError("Permissão de origem não suportada.")
            private.append(
                {
                    k: item[k]
                    for k in ("type", "role", "emailAddress", "expirationTime")
                    if k in item
                }
            )
        owner_source = self._get(
            self.owner,
            f"/files/{source_id}",
            params={"fields": "id,parents,trashed,capabilities(canEdit)"},
        )
        if (
            owner_source.get("id") != source_id
            or owner_source.get("trashed")
            or (owner_source.get("capabilities") or {}).get("canEdit") is not True
        ):
            raise ContinuationError(
                "A conta autorizada precisa ter edição nos arquivos de origem."
            )
        parents = owner_source.get("parents", [])
        if not isinstance(parents, list) or len(parents) != 1:
            raise ContinuationError(
                "Não foi possível comprovar a pasta da origem na conta autorizada."
            )
        if parents:
            parent_permissions = self._get(
                self.owner,
                f"/files/{parents[0]}/permissions",
                params={
                    "fields": "permissions(type,deleted),nextPageToken",
                    "pageSize": 100,
                },
            )
            if parent_permissions.get("nextPageToken") or any(
                p.get("type") not in ("user", "group")
                for p in parent_permissions.get("permissions", [])
                if not p.get("deleted")
            ):
                raise ContinuationError(
                    "A pasta de destino possui compartilhamento amplo; criação bloqueada."
                )
        return {
            "operation": operation,
            "source": source_id,
            "hub": hub,
            "segment": segment,
            "role": role,
            "number": number,
            "parents": parents,
            "permissions": private,
            "name": f"{source['name']} — Continuação {number:03d} ({role})",
            "state": "prepared",
        }

    def create(self, intent, *, first_attempt: bool) -> str:
        found = self.locate(intent["operation"])
        if found:
            return found
        if not first_attempt:
            raise ContinuationError(
                "Criação anterior sem confirmação. Reautorize a mesma conta e confira o índice; "
                "um novo arquivo não será criado às cegas."
            )
        body = {
            "name": intent["name"],
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "properties": {
                "nexoflow_operation": intent["operation"],
                "nexoflow_hub": intent["hub"],
                "nexoflow_segment": intent["segment"],
                "nexoflow_role": intent["role"],
            },
        }
        if intent["parents"]:
            body["parents"] = intent["parents"]
        try:
            self.before_write()
            created = self._json(
                self.owner, "POST", "/files", json=body, params={"fields": "id"}
            )
            return created["id"]
        except RequestException as exc:
            code = getattr(exc.response, "status_code", None)
            if (
                code is not None
                and 400 <= code < 500
                and code not in (408, 409, 429, 499)
            ):
                raise CreationRejected(
                    "O Drive recusou a criação. Confira a autorização, a pasta e o espaço da conta; tente novamente após corrigir."
                ) from None
            found = self.locate(intent["operation"])
            if found:
                return found
            raise ContinuationError(
                "O Drive não confirmou a criação. O comprovante foi preservado; não repetir a criação manualmente."
            ) from None

    def verify_owned(self, file_id, intent):
        info = self._get(
            self.owner,
            f"/files/{file_id}",
            params={"fields": "id,mimeType,trashed,properties,parents"},
        )
        properties = info.get("properties", {})
        expected = {
            "nexoflow_hub": intent["hub"],
            "nexoflow_segment": intent["segment"],
            "nexoflow_role": intent["role"],
            "nexoflow_operation": intent["operation"],
        }
        if (
            info.get("id") != file_id
            or info.get("trashed")
            or info.get("mimeType") != "application/vnd.google-apps.spreadsheet"
            or info.get("parents", []) != intent["parents"]
            or any(properties.get(key) != value for key, value in expected.items())
        ):
            raise ContinuationError(
                "Arquivo de criação divergente; nenhuma permissão será concedida."
            )

    def share(self, file_id: str, intent):
        actual = self._get(
            self.owner,
            f"/files/{file_id}/permissions",
            params={
                "fields": "permissions(type,emailAddress,role),nextPageToken",
                "pageSize": 100,
            },
        )
        if actual.get("nextPageToken"):
            raise ContinuationError(
                "Não foi possível conferir todos os acessos da continuação."
            )
        present = {
            (p.get("type"), str(p.get("emailAddress", "")).lower()): p.get("role")
            for p in actual.get("permissions", [])
        }
        wanted = [
            *intent["permissions"],
            {"type": "user", "role": "writer", "emailAddress": self.service_email},
        ]
        for original in wanted:
            permission = dict(original)
            if permission["role"] == "owner":
                permission["role"] = "writer"
            key = (permission["type"], permission["emailAddress"].lower())
            if key in present:
                roles = {"reader": 1, "commenter": 2, "writer": 3, "owner": 4}
                if roles.get(present[key], 0) < roles[permission["role"]]:
                    raise ContinuationError(
                        "A conta que grava a continuação não possui edição."
                    )
                continue
            self.before_write()
            self._json(
                self.owner,
                "POST",
                f"/files/{file_id}/permissions",
                params={"sendNotificationEmail": "false"},
                json=permission,
            )
            present[key] = permission["role"]

    def verify(self, file_id, *, hub, segment, role=None):
        info = self._get(
            self.source,
            f"/files/{file_id}",
            params={
                "fields": "id,mimeType,trashed,properties",
                "supportsAllDrives": "true",
            },
        )
        props = info.get("properties", {})
        if (
            info.get("id") != file_id
            or info.get("trashed")
            or info.get("mimeType") != "application/vnd.google-apps.spreadsheet"
            or props.get("nexoflow_hub") != hub
            or props.get("nexoflow_segment") != segment
            or (role is not None and props.get("nexoflow_role") != role)
        ):
            raise ContinuationError(
                "Continuação não pertence ao índice e ao segmento atuais."
            )
