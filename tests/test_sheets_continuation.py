"""Capacidade física, isolamento de perfil e concorrência das continuações."""

import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from gspread.exceptions import APIError
from requests import Response, Timeout

from sheets_continuation import (
    LEASE_ID,
    LEASE_SECONDS,
    ContinuationError,
    ContinuationIndex,
    Part,
    SheetsLease,
    additional_rows,
    allocated_cells,
    fingerprint,
)


class MetadataBook:
    def __init__(self):
        self.metadata = {}
        self.writes = 0
        self.lose_response = False

    def fetch_sheet_metadata(self, **kwargs):
        markers = list(copy.deepcopy(self.metadata).values())
        for marker in markers:
            if marker.get("location", {}).get("spreadsheet") is True:
                marker["location"].setdefault("locationType", "SPREADSHEET")
        return {"developerMetadata": markers}

    def batch_update(self, body):
        proposed = copy.deepcopy(self.metadata)
        for request in body["requests"]:
            if "deleteDeveloperMetadata" in request:
                match = request["deleteDeveloperMetadata"]["dataFilter"][
                    "developerMetadataLookup"
                ]
                old = proposed.get(match["metadataId"])
                if old and all(old.get(k) == v for k, v in match.items()):
                    del proposed[match["metadataId"]]
            else:
                item = copy.deepcopy(
                    request["createDeveloperMetadata"]["developerMetadata"]
                )
                if "metadataId" not in item:
                    item["metadataId"] = max(proposed, default=0) + 1
                if item["metadataId"] in proposed:
                    raise RuntimeError("duplicate metadata ID")
                proposed[item["metadataId"]] = item
        self.writes += 1
        self.metadata = proposed
        if self.lose_response:
            self.lose_response = False
            raise Timeout("synthetic response lost after commit")
        return {}


class ContinuationContractTests(unittest.TestCase):
    def test_capacity_counts_allocated_blank_cells_in_every_grid_tab(self):
        metadata = {
            "sheets": [
                {
                    "properties": {
                        "gridProperties": {"rowCount": 100, "columnCount": 58}
                    }
                },
                {
                    "properties": {
                        "gridProperties": {"rowCount": 20, "columnCount": 200}
                    }
                },
                {"properties": {"sheetType": "OBJECT"}},
            ]
        }
        self.assertEqual(allocated_cells(metadata), 9800)
        self.assertEqual(additional_rows(9800, 58, threshold=10000), 3)
        self.assertEqual(additional_rows(10001, 58, threshold=10000), 0)
        self.assertEqual(additional_rows(9999, 1, threshold=10000), 1)
        with self.assertRaises(ContinuationError):
            allocated_cells({"sheets": [{"properties": {"gridProperties": {}}}]})

    def test_manifest_round_trip_and_cross_profile_rejection(self):
        roots = {"dashboard": "d", "operacao": "o", "historico": "h"}
        index = ContinuationIndex("d", "FARMA", roots)
        headers = ["pedido_chave", "valor_produtos"]
        first = Part("Pedidos_FarmaLider", 0, "o", 10, 2, fingerprint(headers))
        second = Part("Pedidos_FarmaLider", 1, "o2", 20, 2, fingerprint(headers))
        index.files["o2"] = {"role": "operacao", "number": 1, "source": "o"}
        index.parts = {p.key: p for p in (first, second)}
        loaded = ContinuationIndex.parse(
            index.values(), hub="d", segment="FARMA", roots=roots
        )
        self.assertEqual(loaded.table_parts(first.title), [first, second])
        for profile, target, destinations in (
            ("PET", "d", roots),
            ("FARMA", "other", roots),
            ("FARMA", "d", {**roots, "operacao": "other"}),
        ):
            with (
                self.subTest(profile=profile, target=target),
                self.assertRaises(ContinuationError),
            ):
                ContinuationIndex.parse(
                    index.values(), hub=target, segment=profile, roots=destinations
                )
        invalid = index.values()
        invalid.append(invalid[-1])
        with self.assertRaises(ContinuationError):
            ContinuationIndex.parse(invalid, hub="d", segment="FARMA", roots=roots)

    def test_missing_part_and_duplicate_physical_destination_are_rejected(self):
        roots = {"dashboard": "d", "operacao": "o", "historico": "h"}
        for parts in (
            [Part("T", 1, "o", 1, 1, "a" * 64)],
            [Part("T", 0, "o", 1, 1, "a" * 64), Part("T", 1, "o", 1, 1, "a" * 64)],
            [Part("T", 0, "foreign", 1, 1, "a" * 64)],
        ):
            index = ContinuationIndex("d", "FARMA", roots)
            index.parts = {p.key: p for p in parts}
            with self.subTest(parts=parts), self.assertRaises(ContinuationError):
                ContinuationIndex.parse(
                    index.values(), hub="d", segment="FARMA", roots=roots
                )


class RemoteWriterLeaseTests(unittest.TestCase):
    def test_active_writer_blocks_another_and_old_owner_cannot_release_successor(self):
        book, clock = MetadataBook(), [1000]
        first = SheetsLease(book, now=lambda: clock[0])
        other = SheetsLease(book, now=lambda: clock[0])
        first.require()
        with self.assertRaisesRegex(ContinuationError, "Outra carga"):
            other.require()
        clock[0] += LEASE_SECONDS + 1
        other.require()
        first.release()
        self.assertEqual(
            json.loads(book.metadata[LEASE_ID]["metadataValue"])["owner"], other.owner
        )
        other.release()
        self.assertFalse(book.metadata)

    def test_lost_success_response_is_confirmed_without_second_mutation(self):
        book = MetadataBook()
        book.lose_response = True
        lease = SheetsLease(book, now=lambda: 10)
        lease.require()
        self.assertEqual(book.writes, 1)
        self.assertEqual(
            json.loads(book.metadata[LEASE_ID]["metadataValue"])["owner"], lease.owner
        )

    def test_writer_that_lost_ownership_stops_before_next_mutation(self):
        book, clock = MetadataBook(), [10]
        first = SheetsLease(book, now=lambda: clock[0])
        first.require()
        clock[0] += LEASE_SECONDS + 1
        other = SheetsLease(book, now=lambda: clock[0])
        other.require()
        with self.assertRaisesRegex(ContinuationError, "bloqueio da carga mudou"):
            first.require()
        self.assertEqual(book.writes, 2)


class UncertainLeaseTests(unittest.TestCase):
    def test_uncertain_write_holds_lease_until_expiry_and_prevents_more_writes(self):
        book, clock = MetadataBook(), [1000]
        first = SheetsLease(book, now=lambda: clock[0])
        first.require()
        first.note_uncertain()
        with self.assertRaisesRegex(ContinuationError, "sem confirmação"):
            first.require()
        first.release()
        self.assertIn(LEASE_ID, book.metadata)
        second = SheetsLease(
            book,
            now=lambda: clock[0],
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        )
        second.require(wait_seconds=LEASE_SECONDS + 1)
        self.assertEqual(clock[0], 1300)
        self.assertEqual(
            json.loads(book.metadata[LEASE_ID]["metadataValue"])["owner"], second.owner
        )


class ServerClockLeaseTests(unittest.TestCase):
    def test_computer_clock_in_future_cannot_steal_active_google_lease(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        book = MetadataBook()
        book.id = "synthetic"
        owner = SheetsLease(book, now=lambda: 1000)
        owner.require()
        response = Mock()
        response.headers = {"Date": "Thu, 01 Jan 1970 00:16:40 GMT"}
        response.json.return_value = book.fetch_sheet_metadata()
        book.client = SimpleNamespace(request=Mock(return_value=response))
        with patch("sheets_continuation.time.time", return_value=9999999):
            other = SheetsLease(book)
            with self.assertRaisesRegex(ContinuationError, "Outra carga"):
                other.require()
        self.assertEqual(book.writes, 1)

    def test_missing_server_date_blocks_before_any_mutation(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        book = MetadataBook()
        book.id = "synthetic"
        book.client = SimpleNamespace(
            request=Mock(return_value=SimpleNamespace(headers={}))
        )
        with self.assertRaisesRegex(ContinuationError, "horário"):
            SheetsLease(book).require()
        self.assertEqual(book.writes, 0)


def metadata_api_error(status, retry_after=None):
    response = Response()
    response.status_code = status
    response._content = json.dumps(
        {"error": {"code": status, "message": "synthetic-private-marker"}}
    ).encode()
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    return APIError(response)


class LeaseMetadataRecoveryTests(unittest.TestCase):
    def test_reset_after_renewal_recovers_get_without_reposting(self):
        book, clock = MetadataBook(), [1000]
        lease = SheetsLease(book, now=lambda clock=clock: clock[0], sleep=Mock())
        lease.require()
        clock[0] += 31
        original = book.fetch_sheet_metadata
        failed = [0]

        def metadata(**kwargs):
            if book.writes == 2 and failed[0] < 2:
                failed[0] += 1
                raise Timeout("synthetic-private-secret")
            return original(**kwargs)

        book.fetch_sheet_metadata = Mock(side_effect=metadata)
        book.lose_response = True
        with self.assertLogs(level="WARNING") as logs:
            lease.require()
        self.assertNotIn("synthetic-private-secret", str(logs.output))
        self.assertEqual(book.writes, 2)
        self.assertEqual(failed[0], 2)
        self.assertEqual(lease.value, book.metadata[LEASE_ID]["metadataValue"])
        self.assertFalse(lease.uncertain)

    def test_unconfirmed_renewal_blocks_control_write_and_release(self):
        for lost_post in (False, True):
            with self.subTest(lost_post=lost_post):
                book, clock = MetadataBook(), [1000]
                lease = SheetsLease(
                    book, now=lambda clock=clock: clock[0], sleep=Mock()
                )
                lease.require()
                clock[0] += 31
                original = book.fetch_sheet_metadata

                def metadata(book=book, original=original, **kwargs):
                    if book.writes == 2:
                        raise Timeout("synthetic-private-secret")
                    return original(**kwargs)

                book.fetch_sheet_metadata = Mock(side_effect=metadata)
                book.lose_response = lost_post
                with self.assertRaises(ContinuationError):
                    lease.require()
                self.assertTrue(lease.uncertain)
                with self.assertRaisesRegex(ContinuationError, "sem confirmação"):
                    lease.require()  # Same path used by the error handler / Controle.
                lease.release()
                self.assertEqual(book.writes, 2)
                self.assertIn(LEASE_ID, book.metadata)
                book.fetch_sheet_metadata = original
                clock[0] += LEASE_SECONDS + 1
                successor = SheetsLease(book, now=lambda clock=clock: clock[0])
                successor.require()
                self.assertEqual(book.writes, 3)
                self.assertNotEqual(successor.owner, lease.owner)

    def test_error_handler_cannot_write_control_after_uncertain_renewal(self):
        from google_sheets import GoogleSheetsStore

        book, clock = MetadataBook(), [1000]
        lease = SheetsLease(book, now=lambda: clock[0], sleep=Mock())
        lease.require()
        clock[0] += 31
        original = book.fetch_sheet_metadata

        def metadata(**kwargs):
            if book.writes == 1:
                return original(**kwargs)
            raise Timeout("private-token")

        book.fetch_sheet_metadata = Mock(side_effect=metadata)
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._wait_before_write = Mock()
        store._continuity = SimpleNamespace(require=lease.require)
        write_fact, write_control = Mock(), Mock()
        with self.assertRaises(ContinuationError):
            store._write_with_retry("update sintético", write_fact)
        with self.assertRaises(ContinuationError):
            store._write_with_retry("Controle sintético", write_control)
        write_fact.assert_not_called()
        write_control.assert_not_called()
        self.assertEqual(book.writes, 2)
        self.assertTrue(lease.uncertain)

    def test_conflict_or_stale_confirmation_preserves_marker_without_retry(self):
        for foreign in (False, True):
            with self.subTest(foreign=foreign):
                book, clock = MetadataBook(), [1000]
                lease = SheetsLease(book, now=lambda clock=clock: clock[0])
                lease.require()
                previous = book.fetch_sheet_metadata()
                clock[0] += 31
                marker = copy.deepcopy(previous)
                if foreign:
                    data = json.loads(marker["developerMetadata"][0]["metadataValue"])
                    data["owner"] = "a" * 32
                    marker["developerMetadata"][0]["metadataValue"] = json.dumps(data)
                book.fetch_sheet_metadata = Mock(side_effect=[previous, marker])
                book.batch_update = Mock(side_effect=metadata_api_error(400))
                with self.assertRaises(ContinuationError):
                    lease.require()
                with self.assertRaises(ContinuationError):
                    lease.require()
                lease.release()
                self.assertEqual(book.batch_update.call_count, 1)
                self.assertTrue(lease.uncertain)

    def test_expired_confirmation_never_authorizes_data_write(self):
        book, clock = MetadataBook(), [1000]
        original = book.fetch_sheet_metadata

        def metadata(**kwargs):
            if book.writes:
                clock[0] = 1400
            return original(**kwargs)

        book.fetch_sheet_metadata = Mock(side_effect=metadata)
        lease = SheetsLease(book, now=lambda clock=clock: clock[0], sleep=Mock())
        with self.assertRaises(ContinuationError):
            lease.require()
        self.assertTrue(lease.uncertain)
        self.assertEqual(book.writes, 1)

    def test_quota_after_lease_post_retries_confirmation_without_second_post(self):
        book = MetadataBook()
        original = book.fetch_sheet_metadata
        injected = [False]

        def metadata(**kwargs):
            if book.writes == 1 and not injected[0]:
                injected[0] = True
                raise metadata_api_error(429)
            return original(**kwargs)

        book.fetch_sheet_metadata = Mock(side_effect=metadata)
        sleep = Mock()
        lease = SheetsLease(book, now=lambda: 1000, sleep=sleep)
        with self.assertLogs(level="WARNING"):
            lease.require()
        self.assertTrue(injected[0])
        self.assertEqual(book.fetch_sheet_metadata.call_count, 3)
        self.assertEqual(book.writes, 1)
        sleep.assert_called_once_with(65)
        self.assertEqual(book.metadata[LEASE_ID]["metadataValue"], lease.value)
        self.assertEqual(json.loads(lease.value)["owner"], lease.owner)

    def test_http_date_retry_after_is_respected(self):
        book = MetadataBook()
        book.fetch_sheet_metadata = Mock(
            side_effect=[
                metadata_api_error(429, "Thu, 01 Jan 1970 00:20:00 GMT"),
                {"developerMetadata": []},
            ]
        )
        sleep = Mock()
        with self.assertLogs(level="WARNING"):
            self.assertIsNone(
                SheetsLease(book, now=lambda: 1000, sleep=sleep)._lookup()
            )
        sleep.assert_called_once_with(200)
        self.assertEqual(book.writes, 0)

    def test_lookup_recovers_quota_without_a_metadata_write(self):
        book = MetadataBook()
        original = book.fetch_sheet_metadata
        book.fetch_sheet_metadata = Mock(
            side_effect=[
                metadata_api_error(429),
                metadata_api_error(429, "90"),
                original(),
            ]
        )
        sleep = Mock()
        with self.assertLogs(level="WARNING") as logs:
            self.assertIsNone(
                SheetsLease(book, now=lambda: 1000, sleep=sleep)._lookup()
            )
        self.assertEqual(book.fetch_sheet_metadata.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [65, 90])
        self.assertEqual(book.writes, 0)
        self.assertNotIn("synthetic-private-marker", "\n".join(logs.output))

    def test_persistent_quota_stops_before_any_write(self):
        book = MetadataBook()
        book.fetch_sheet_metadata = Mock(side_effect=metadata_api_error(429))
        sleep = Mock()
        with self.assertRaises(APIError), self.assertLogs(level="WARNING"):
            SheetsLease(book, now=lambda: 1000, sleep=sleep).require()
        self.assertEqual(book.fetch_sheet_metadata.call_count, 6)
        self.assertEqual(sleep.call_count, 5)
        self.assertEqual(book.writes, 0)

    def test_permanent_failures_are_not_retried_or_written(self):
        for status in (400, 401, 403, 404):
            with self.subTest(status=status):
                book = MetadataBook()
                book.fetch_sheet_metadata = Mock(side_effect=metadata_api_error(status))
                sleep = Mock()
                with self.assertRaises(APIError):
                    SheetsLease(book, now=lambda: 1000, sleep=sleep).require()
                self.assertEqual(book.fetch_sheet_metadata.call_count, 1)
                sleep.assert_not_called()
                self.assertEqual(book.writes, 0)

    def test_server_clock_is_still_required_after_quota_recovery(self):
        book = MetadataBook()
        book.id = "synthetic"
        book.client = SimpleNamespace(
            request=Mock(
                side_effect=[metadata_api_error(429), SimpleNamespace(headers={})]
            )
        )
        sleep = Mock()
        with (
            self.assertRaisesRegex(ContinuationError, "horário"),
            self.assertLogs(level="WARNING"),
        ):
            SheetsLease(book, sleep=sleep).require()
        sleep.assert_called_once_with(65)
        self.assertEqual(book.writes, 0)

    def test_foreign_owner_still_blocks_after_transient_server_error(self):
        book = MetadataBook()
        first = SheetsLease(book, now=lambda: 1000)
        first.require()
        original = book.fetch_sheet_metadata()
        book.fetch_sheet_metadata = Mock(
            side_effect=[metadata_api_error(500), original]
        )
        sleep = Mock()
        with (
            self.assertRaisesRegex(ContinuationError, "Outra carga"),
            self.assertLogs(level="WARNING"),
        ):
            SheetsLease(book, now=lambda: 1000, sleep=sleep).require()
        sleep.assert_called_once_with(2)
        self.assertEqual(book.writes, 1)
