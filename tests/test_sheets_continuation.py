"""Capacidade física, isolamento de perfil e concorrência das continuações."""

import copy
import json
import unittest

from requests import Timeout

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
        return {"developerMetadata": list(copy.deepcopy(self.metadata).values())}

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
