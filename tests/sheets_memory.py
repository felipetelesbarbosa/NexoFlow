"""Modelo pequeno do protocolo Sheets/Drive, sem rede e com intervalos reais."""

import copy
import re
from types import SimpleNamespace

from gspread.exceptions import WorksheetNotFound
from requests import Timeout

from tests.test_sheets_continuation import MetadataBook


def bounds(target):
    match = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", target)
    if not match:
        raise AssertionError(f"Range not modeled: {target}")

    def col(word):
        value = 0
        for char in word:
            value = value * 26 + ord(char) - 64
        return value - 1

    return col(match[1]), int(match[2]) - 1, col(match[3]) + 1, int(match[4])


class Sheet:
    def __init__(self, book, title, values, sheet_id, *, rows=None, cols=None):
        self.book, self.title, self.id = book, title, sheet_id
        self.values = copy.deepcopy(values)
        self.row_count = rows or max(len(values), 1)
        self.col_count = cols or max(map(len, values), default=1)
        self.lose_response = False
        self.native_cells = {}
        self.writes = 0

    def get_all_values(self, **kwargs):
        values = copy.deepcopy(self.values)
        while values and not any(v not in (None, "") for v in values[-1]):
            values.pop()
        return values

    def get(self, target, **kwargs):
        first_col, first_row, last_col, last_row = bounds(target)
        result = [
            copy.deepcopy(row[first_col:last_col])
            for row in self.values[first_row:last_row]
        ]
        while result and not any(v not in (None, "") for v in result[-1]):
            result.pop()
        return result

    def update(self, *, range_name, values, **kwargs):
        left, first, right, last = bounds(range_name)
        if last > self.row_count or right > self.col_count:
            raise AssertionError("Write exceeds reserved grid")
        while len(self.values) < last:
            self.values.append([])
        for number, row in enumerate(values, first):
            target = self.values[number]
            target.extend([""] * max(0, right - len(target)))
            target[left : left + len(row)] = copy.deepcopy(row)
        self.writes += 1
        if self.lose_response:
            self.lose_response = False
            raise Timeout("synthetic response lost after writing cells")
        return {}

    def batch_update(self, batch, **kwargs):
        for update in batch:
            self.update(range_name=update["range"], values=update["values"], **kwargs)
        return {}

    def batch_clear(self, ranges):
        for target in ranges:
            left, first, right, last = bounds(target)
            for row in self.values[first:last]:
                row.extend([""] * max(0, right - len(row)))
                row[left:right] = [""] * (right - left)
        return {}

    def resize(self, *, rows=None, cols=None):
        if rows is not None:
            self.row_count = rows
            self.values = self.values[:rows]
        if cols is not None:
            self.col_count = cols
            self.values = [row[:cols] for row in self.values]
        return {}

    def update_title(self, title):
        self.title = title

    def freeze(self, **kwargs):
        return {}

    def batch_format(self, *args, **kwargs):
        return {}

    def col_values(self, number):
        return [
            row[number - 1] if len(row) >= number else ""
            for row in self.get_all_values()
        ]


class Book(MetadataBook):
    def __init__(self, key):
        super().__init__()
        self.id, self.title = key, "NexoFlow " + key
        self.sheets = []
        self.lose_data_response = False
        self.data_writes = 0

    def add(self, title, values, **kwargs):
        ws = Sheet(self, title, values, len(self.sheets) + 1, **kwargs)
        self.sheets.append(ws)
        return ws

    def worksheets(self):
        return self.sheets[:]

    def worksheet(self, title):
        for sheet in self.sheets:
            if sheet.title == title:
                return sheet
        raise WorksheetNotFound(title)

    def get_worksheet_by_id(self, sheet_id):
        return next(ws for ws in self.sheets if ws.id == sheet_id)

    def add_worksheet(self, *, title, rows, cols):
        return self.add(title, [], rows=rows, cols=cols)

    def fetch_sheet_metadata(self, **kwargs):
        result = {
            **super().fetch_sheet_metadata(**kwargs),
            "sheets": [
                {
                    "properties": {
                        "sheetId": ws.id,
                        "title": ws.title,
                        "gridProperties": {
                            "rowCount": ws.row_count,
                            "columnCount": ws.col_count,
                        },
                    }
                }
                for ws in self.sheets
            ],
        }
        params = kwargs.get("params", {})
        if params.get("includeGridData"):
            result["sheets"] = []
            for target in params["ranges"]:
                title, area = target.split("!", 1)
                ws = self.worksheet(title.strip("'"))
                left, first, right, last = bounds(area)
                rows = []
                for row in range(first, last):
                    cells = []
                    for col in range(left, right):
                        value = (
                            ws.values[row][col]
                            if row < len(ws.values) and col < len(ws.values[row])
                            else ""
                        )
                        kind = (
                            "boolValue"
                            if isinstance(value, bool)
                            else "numberValue"
                            if isinstance(value, (float, int))
                            else "stringValue"
                        )
                        cells.append(
                            copy.deepcopy(
                                ws.native_cells.get(
                                    (row, col), {"userEnteredValue": {kind: value}}
                                )
                            )
                        )
                    rows.append({"values": cells})
                result["sheets"].append(
                    {
                        "properties": {"sheetId": ws.id, "title": ws.title},
                        "data": [
                            {"startRow": first, "startColumn": left, "rowData": rows}
                        ],
                    }
                )
        return result

    def batch_update(self, body):
        metadata_requests = [
            r for r in body["requests"] if "DeveloperMetadata" in next(iter(r))
        ]
        if metadata_requests:
            super().batch_update({"requests": metadata_requests})
        for request in body["requests"]:
            if "addSheet" in request:
                p = request["addSheet"]["properties"]
                if any(
                    w.id == p["sheetId"] or w.title == p["title"] for w in self.sheets
                ):
                    raise RuntimeError("Duplicate worksheet identity")
                ws = self.add(
                    p["title"],
                    [],
                    rows=p["gridProperties"]["rowCount"],
                    cols=p["gridProperties"]["columnCount"],
                )
                ws.id = p["sheetId"]
            if "updateCells" in request:
                data = request["updateCells"]
                area = data["range"]
                ws = self.get_worksheet_by_id(area["sheetId"])
                rows = [
                    [
                        next(iter(c.get("userEnteredValue", {}).values()), "")
                        for c in row["values"]
                    ]
                    for row in data.get("rows", [])
                ]
                first, last = area.get("startRowIndex", 0), area["endRowIndex"]
                left, right = (
                    area.get("startColumnIndex", 0),
                    area.get("endColumnIndex", ws.col_count),
                )
                while len(ws.values) < last:
                    ws.values.append([])
                for row in range(first, last):
                    values = rows[row - first] if row - first < len(rows) else []
                    ws.values[row].extend([""] * max(0, right - len(ws.values[row])))
                    ws.values[row][left:right] = values + [""] * (
                        right - left - len(values)
                    )
                    for col in range(left, right):
                        if (row, col) in ws.native_cells:
                            value = ws.values[row][col]
                            kind = (
                                "numberValue"
                                if isinstance(value, (float, int))
                                else "stringValue"
                            )
                            ws.native_cells[row, col]["userEnteredValue"] = {
                                kind: value
                            }
            if "deleteDimension" in request:
                area = request["deleteDimension"]["range"]
                ws = self.get_worksheet_by_id(area["sheetId"])
                del ws.values[area["startIndex"] : area["endIndex"]]
                count = area["endIndex"] - area["startIndex"]
                ws.row_count -= count
                ws.native_cells = {
                    (row - count if row >= area["endIndex"] else row, col): cell
                    for (row, col), cell in ws.native_cells.items()
                    if not area["startIndex"] <= row < area["endIndex"]
                }
        if any("updateCells" in q or "deleteDimension" in q for q in body["requests"]):
            self.data_writes += 1
            if self.lose_data_response:
                self.lose_data_response = False
                raise Timeout("synthetic response lost after native commit")
        return {}


class Client:
    def __init__(self, books):
        self.books = books
        self.properties = {}
        self.http_client = SimpleNamespace(request=self.request)

    def open_by_key(self, key):
        return self.books[key]

    def request(self, method, url, **kwargs):
        key = url.rsplit("/", 1)[-1]
        return SimpleNamespace(
            json=lambda: {
                "id": key,
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "properties": self.properties[key],
            }
        )


class Provisioner:
    def __init__(self, client):
        self.client, self.creations = client, 0
        self.shared = []

    def prepare_intent(self, source_id, operation, *, hub, segment, role, number):
        return {
            "operation": operation,
            "source": source_id,
            "hub": hub,
            "segment": segment,
            "role": role,
            "number": number,
            "parents": [],
            "permissions": [],
            "name": "Continuação",
        }

    def create(self, intent, *, first_attempt):
        if not first_attempt:
            raise AssertionError("unexpected blind retry")
        self.creations += 1
        key = "continuation" + str(self.creations)
        book = Book(key)
        book.add("Sheet1", [], rows=1000, cols=26)
        self.client.books[key] = book
        self.client.properties[key] = {
            "nexoflow_hub": intent["hub"],
            "nexoflow_segment": intent["segment"],
            "nexoflow_role": intent["role"],
        }
        return key

    def verify_owned(self, file_id, intent):
        return None

    def share(self, file_id, intent):
        self.shared.append(file_id)

    def verify(self, *args, **kwargs):
        return None

    def close(self):
        pass
