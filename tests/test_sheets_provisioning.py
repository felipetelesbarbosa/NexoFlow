"""OAuth e criação de arquivos: sem credenciais reais, sem chamadas de rede."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from requests import HTTPError, Response, Timeout

from sheets_continuation import ContinuationError
from sheets_provisioning import CreationRejected, MyDriveProvisioner, authorize_user


def http_error(code):
    response = Response()
    response.status_code = code
    return HTTPError(response=response)


class ProvisioningTests(unittest.TestCase):
    def provider(self):
        p = MyDriveProvisioner.__new__(MyDriveProvisioner)
        p.source, p.owner = object(), object()
        p.service_email = "test@project.example.invalid"
        p.before_write = Mock()
        return p

    def intent(self):
        return {
            "operation": "a" * 32,
            "hub": "dashboard",
            "segment": "PET",
            "role": "operacao",
            "name": "Continuação",
            "parents": ["folder"],
            "permissions": [],
        }

    def test_location_uses_authorized_oauth_and_never_grants_folder_access(self):
        p = self.provider()
        info = dict(
            id="created",
            mimeType="application/vnd.google-apps.spreadsheet",
            parents=["folder"],
            capabilities=dict(canEdit=True),
        )
        with patch.object(p, "_get", return_value=info) as read:
            p.verify_location("created", parents=["folder"])
            self.assertIs(read.call_args.args[0], p.owner)
            self.assertEqual(read.call_count, 1)
        for changed, code in (
            (dict(info, parents=["moved"]), "PASTA_OAUTH_ALTERADA"),
            (dict(info, parents=[]), "PASTA_OAUTH_ATUAL_NAO_COMPROVADA"),
            (dict(info, capabilities=dict(canEdit=False)), "ACESSO_OAUTH"),
            (dict(info, trashed=True), "ACESSO_OAUTH"),
            (dict(info, driveId="shared"), "ACESSO_OAUTH"),
            (dict(info, id="other"), "ACESSO_OAUTH"),
        ):
            with self.subTest(code=code), patch.object(p, "_get", return_value=changed):
                with self.assertRaisesRegex(ContinuationError, code):
                    p.verify_location("created", parents=["folder"])
        with self.assertRaisesRegex(ContinuationError, "APROVADA_NAO_COMPROVADA"):
            p.verify_location("created", parents=[])
        with patch.object(p, "_get", side_effect=http_error(403)):
            with self.assertRaisesRegex(
                ContinuationError, "VERIFICACAO_PASTA_OAUTH_FALHOU.*HTTP=403"
            ):
                p.verify_location("created", parents=["folder"])
        p.before_write.assert_not_called()

    def test_reconciliation_access_is_exact_readonly_and_service_is_writer(self):
        p = self.provider()
        intent = self.intent()
        intent["permissions"] = [
            dict(type="user", role="owner", emailAddress="owner@example.invalid"),
            dict(type="user", role="reader", emailAddress="reader@example.invalid"),
            dict(type="user", role="reader", emailAddress=p.service_email),
        ]
        valid = [
            dict(type="user", role="owner", emailAddress="owner@example.invalid"),
            dict(type="user", role="reader", emailAddress="reader@example.invalid"),
            dict(type="user", role="writer", emailAddress=p.service_email),
        ]
        with patch.object(p, "_get", return_value=dict(permissions=valid)):
            self.assertTrue(p.verify_private_access("created", intent))
        valid[0]["role"] = "writer"  # Owner da origem vira writer ao compartilhar.
        with patch.object(p, "_get", return_value=dict(permissions=valid)):
            self.assertTrue(p.verify_private_access("created", intent))
        cases = [
            [*valid, dict(type="anyone", role="reader")],
            [*valid, valid[1]],
            valid[:2],
            [valid[0], dict(valid[1], role="writer"), valid[2]],
            [valid[0], valid[1], dict(valid[2], role="owner")],
            [valid[0], dict(valid[1], expirationTime="2030-01-01T00:00:00Z"), valid[2]],
        ]
        for permissions in cases:
            with (
                self.subTest(permissions=permissions),
                patch.object(p, "_get", return_value=dict(permissions=permissions)),
            ):
                with self.assertRaises(ContinuationError):
                    p.verify_private_access("created", intent)
        with patch.object(
            p, "_get", return_value=dict(permissions=valid, nextPageToken="next")
        ):
            with self.assertRaises(ContinuationError):
                p.verify_private_access("created", intent)
        p.before_write.assert_not_called()

    def test_lost_creation_response_adopts_same_file_without_second_post(self):
        p = self.provider()
        with (
            patch.object(p, "locate", side_effect=[None, "created", "created"]),
            patch.object(p, "_json", side_effect=Timeout("sintético")) as post,
        ):
            self.assertEqual(p.create(self.intent(), first_attempt=True), "created")
            self.assertEqual(p.create(self.intent(), first_attempt=False), "created")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(p.before_write.call_count, 1)

    def test_unknown_creation_never_repeats_post_but_definitive_rejection_can_be_retried(
        self,
    ):
        p = self.provider()
        with (
            patch.object(p, "locate", return_value=None),
            patch.object(p, "_json", side_effect=Timeout("sintético")) as post,
        ):
            with self.assertRaises(ContinuationError):
                p.create(self.intent(), first_attempt=True)
            with self.assertRaises(ContinuationError):
                p.create(self.intent(), first_attempt=False)
            self.assertEqual(post.call_count, 1)
        with (
            patch.object(p, "locate", return_value=None),
            patch.object(
                p, "_json", side_effect=[http_error(403), {"id": "created"}]
            ) as post,
        ):
            with self.assertRaises(CreationRejected):
                p.create(self.intent(), first_attempt=True)
            self.assertEqual(p.create(self.intent(), first_attempt=True), "created")
            self.assertEqual(post.call_count, 2)

    def test_source_and_folder_must_be_private_and_editable_by_authorized_user(self):
        p = self.provider()

        def get(session, path, **kwargs):
            if path.endswith("/permissions"):
                return {
                    "permissions": [
                        {
                            "type": "user",
                            "role": "owner",
                            "emailAddress": "owner@example.invalid",
                        }
                    ]
                }
            return {
                "id": "source",
                "name": "Operação",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "parents": ["folder"],
                "capabilities": {"canEdit": True},
            }

        with patch.object(p, "_get", side_effect=get):
            intent = p.prepare_intent(
                "source",
                "a" * 32,
                hub="dashboard",
                segment="PET",
                role="operacao",
                number=1,
            )
            self.assertEqual(intent["parents"], ["folder"])
            self.assertEqual(intent["permissions"][0]["role"], "owner")
        with (
            patch.object(p, "source_info", return_value={"id": "source", "name": "X"}),
            patch.object(
                p,
                "_get",
                return_value={"permissions": [{"type": "anyone", "role": "reader"}]},
            ),
        ):
            with self.assertRaisesRegex(ContinuationError, "compartilhamento amplo"):
                p.prepare_intent(
                    "source",
                    "a" * 32,
                    hub="dashboard",
                    segment="PET",
                    role="operacao",
                    number=1,
                )
        p.before_write.assert_not_called()

    def test_share_resumes_from_existing_permissions_without_notifications_or_repeating(
        self,
    ):
        p = self.provider()
        intent = self.intent()
        intent["permissions"] = [
            {"type": "user", "role": "owner", "emailAddress": "owner@example.invalid"}
        ]
        with (
            patch.object(
                p,
                "_get",
                return_value={
                    "permissions": [
                        {
                            "type": "user",
                            "role": "owner",
                            "emailAddress": "owner@example.invalid",
                        }
                    ]
                },
            ),
            patch.object(p, "_json", return_value={}) as post,
        ):
            p.share("created", intent)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(
                post.call_args.kwargs["json"]["emailAddress"], p.service_email
            )
            self.assertEqual(
                post.call_args.kwargs["params"]["sendNotificationEmail"], "false"
            )
        with (
            patch.object(
                p,
                "_get",
                return_value={
                    "permissions": intent["permissions"]
                    + [
                        {
                            "type": "user",
                            "role": "writer",
                            "emailAddress": p.service_email,
                        }
                    ]
                },
            ),
            patch.object(p, "_json") as post,
        ):
            p.share("created", intent)
            post.assert_not_called()

    def test_wrong_segment_or_role_never_passes_service_account_verification(self):
        p = self.provider()
        for props in (
            {
                "nexoflow_hub": "dashboard",
                "nexoflow_segment": "FARMA",
                "nexoflow_role": "operacao",
            },
            {
                "nexoflow_hub": "dashboard",
                "nexoflow_segment": "PET",
                "nexoflow_role": "historico",
            },
        ):
            with patch.object(
                p,
                "_get",
                return_value={
                    "id": "created",
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                    "properties": props,
                },
            ):
                with self.assertRaises(ContinuationError):
                    p.verify("created", hub="dashboard", segment="PET", role="operacao")

    def test_wrong_owner_operation_is_rejected_before_sharing(self):
        p = self.provider()
        intent = self.intent()
        with (
            patch.object(
                p,
                "_get",
                return_value={
                    "id": "created",
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                    "parents": ["folder"],
                    "properties": {
                        "nexoflow_hub": "dashboard",
                        "nexoflow_segment": "PET",
                        "nexoflow_role": "operacao",
                        "nexoflow_operation": "b" * 32,
                    },
                },
            ),
            patch.object(p, "_json") as write,
        ):
            with self.assertRaisesRegex(ContinuationError, "nenhuma permissão"):
                p.verify_owned("created", intent)
            write.assert_not_called()


class OAuthSetupTests(unittest.TestCase):
    def test_missing_client_does_not_start_browser_or_create_credentials(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch(
                "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config"
            ) as flow,
        ):
            root = Path(folder)
            with self.assertRaises(ContinuationError):
                authorize_user(root / "absent.json", root / "user.json")
            flow.assert_not_called()
            self.assertFalse((root / "user.json").exists())

    def test_google_desktop_authorization_uses_pkce_localhost_and_offline_private_save(
        self,
    ):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            client = root / "client.json"
            user = root / "user.json"
            client.write_text(
                json.dumps(
                    {
                        "installed": {
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token",
                            "client_id": "FICTICIO",
                            "client_secret": "FICTICIO",
                        }
                    }
                )
            )
            credential = Mock(refresh_token="FICTICIO")
            credential.to_json.return_value = '{"refresh_token":"FICTICIO"}'
            flow = Mock()
            flow.run_local_server.return_value = credential
            with patch(
                "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
                return_value=flow,
            ) as factory:
                authorize_user(client, user)
            self.assertTrue(factory.call_args.kwargs["autogenerate_code_verifier"])
            self.assertEqual(
                flow.run_local_server.call_args.kwargs["host"], "localhost"
            )
            self.assertEqual(flow.run_local_server.call_args.kwargs["port"], 0)
            self.assertEqual(
                flow.run_local_server.call_args.kwargs.get("prompt"), "consent"
            )
            self.assertEqual(
                json.loads(user.read_text()), {"refresh_token": "FICTICIO"}
            )
            import os

            if os.name != "nt":
                self.assertEqual(user.stat().st_mode & 0o777, 0o600)
