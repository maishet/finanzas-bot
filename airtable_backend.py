import json
import logging
import os
import re
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import config

logger = logging.getLogger(__name__)

HAS_GOOGLE_API = False
sheets_api = None

AIRTABLE_BASE_URL = "https://api.airtable.com/v0"
AIRTABLE_META_URL = "https://api.airtable.com/v0/meta"


class WorksheetNotFound(Exception):
    pass


DEFAULT_HEADERS = {
    "Transacciones": ["ID", "Fecha", "Tipo", "Monto", "Moneda", "Categoría", "Subcategoría", "Cuenta", "Método", "Nota", "DeudaID"],
    "Cuentas": ["ID", "Nombre", "NumeroCuenta", "Tipo", "Moneda", "SaldoActual", "LímiteCrédito", "DíaCorte", "DíaPago"],
    "Categorias": ["Nombre", "Tipo", "Subcategorías"],
    "Deudas": ["ID", "Descripcion", "Tipo", "MontoTotal", "Moneda", "MontoPagado", "FechaVencimiento", "Estado", "CuentaAsociada", "Periodo", "FechaCorte"],
    "MovimientosPendientes": ["ID", "FechaDetectada", "Fuente", "Cuenta", "Tipo", "Monto", "Moneda", "Descripcion", "Referencia", "Estado", "Confianza", "TXID", "FechaResolucion", "Observacion"],
    "GmailEstado": ["Clave", "Valor", "ActualizadoEn"],
    "SaldosHistoricos": ["SnapshotID", "FechaHora", "Cuenta", "TipoCuenta", "Moneda", "Saldo", "SaldoPEN", "Origen"],
}


def _text(name: str) -> Dict[str, Any]:
    return {"name": name, "type": "singleLineText"}


def _multiline(name: str) -> Dict[str, Any]:
    return {"name": name, "type": "multilineText"}


def _number(name: str) -> Dict[str, Any]:
    return {"name": name, "type": "number", "options": {"precision": 2}}


def _integer(name: str) -> Dict[str, Any]:
    return {"name": name, "type": "number", "options": {"precision": 0}}


def _date(name: str) -> Dict[str, Any]:
    return {"name": name, "type": "date", "options": {"dateFormat": {"name": "iso", "format": "YYYY-MM-DD"}}}


def _datetime(name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "dateTime",
        "options": {
            "dateFormat": {"name": "iso", "format": "YYYY-MM-DD"},
            "timeFormat": {"name": "24hour", "format": "HH:mm"},
            "timeZone": "America/Lima",
        },
    }


def _single_select(name: str, choices: Iterable[str]) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "singleSelect",
        "options": {"choices": [{"name": choice} for choice in choices]},
    }


def _schema_headers(fields: List[Dict[str, Any]]) -> List[str]:
    return [field["name"] for field in fields]


DEFAULT_FIELD_DEFS = {
    "Transacciones": [
        _text("ID"),
        _datetime("Fecha"),
        _single_select("Tipo", ["Gasto", "Ingreso"]),
        _number("Monto"),
        _single_select("Moneda", ["PEN", "USD"]),
        _text("Categoría"),
        _text("Subcategoría"),
        _text("Cuenta"),
        _single_select("Método", ["Tarjeta de Crédito", "Tarjeta de crédito", "Transferencia"]),
        _multiline("Nota"),
        _text("DeudaID"),
    ],
    "Cuentas": [
        _text("ID"),
        _text("Nombre"),
        _text("NumeroCuenta"),
        _single_select("Tipo", ["Efectivo", "Banco", "Crédito", "Debito"]),
        _single_select("Moneda", ["PEN", "USD"]),
        _number("SaldoActual"),
        _number("LímiteCrédito"),
        _integer("DíaCorte"),
        _integer("DíaPago"),
    ],
    "Categorias": [
        _text("Nombre"),
        _single_select("Tipo", ["Gasto", "Ingreso"]),
        _multiline("Subcategorías"),
    ],
    "Deudas": [
        _text("ID"),
        _text("Descripcion"),
        _single_select("Tipo", ["Credito", "Crédito", "Servicio"]),
        _number("MontoTotal"),
        _single_select("Moneda", ["PEN", "USD"]),
        _number("MontoPagado"),
        _date("FechaVencimiento"),
        _single_select("Estado", ["Activa", "Pagada"]),
        _text("CuentaAsociada"),
        _text("Periodo"),
        _date("FechaCorte"),
    ],
    "MovimientosPendientes": [
        _text("ID"),
        _datetime("FechaDetectada"),
        _single_select("Fuente", ["GmailPush", "ManualTelegram", "Manual"]),
        _text("Cuenta"),
        _single_select("Tipo", ["Gasto", "Ingreso"]),
        _number("Monto"),
        _single_select("Moneda", ["PEN", "USD"]),
        _multiline("Descripcion"),
        _text("Referencia"),
        _single_select("Estado", ["Confirmado", "Descartado", "Pendiente"]),
        _number("Confianza"),
        _text("TXID"),
        _datetime("FechaResolucion"),
        _multiline("Observacion"),
    ],
    "GmailEstado": [
        _text("Clave"),
        _text("Valor"),
        _datetime("ActualizadoEn"),
    ],
    "SaldosHistoricos": [
        _text("SnapshotID"),
        _datetime("FechaHora"),
        _text("Cuenta"),
        _single_select("TipoCuenta", ["Banco", "Crédito", "Efectivo"]),
        _single_select("Moneda", ["PEN", "USD"]),
        _number("Saldo"),
        _number("SaldoPEN"),
        _single_select("Origen", ["AutoDiario", "ManualTelegram"]),
    ],
}


TEXT_FIELDS = {
    "ID",
    "Fecha",
    "Tipo",
    "Moneda",
    "Categoría",
    "Subcategoría",
    "Cuenta",
    "Método",
    "Nota",
    "DeudaID",
    "Nombre",
    "NumeroCuenta",
    "LímiteCrédito",
    "DíaCorte",
    "DíaPago",
    "Subcategorías",
    "Descripcion",
    "MontoTotal",
    "MontoPagado",
    "FechaVencimiento",
    "Estado",
    "CuentaAsociada",
    "Periodo",
    "FechaCorte",
    "FechaDetectada",
    "Fuente",
    "Referencia",
    "Confianza",
    "TXID",
    "FechaResolucion",
    "Observacion",
    "Clave",
    "Valor",
    "ActualizadoEn",
    "SnapshotID",
    "FechaHora",
    "TipoCuenta",
    "Saldo",
    "SaldoPEN",
    "Origen",
    "SaldoActual",
}


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _base_id() -> str:
    base_id = _env("AIRTABLE_BASE_ID")
    if not base_id:
        raise ValueError("No se encontró AIRTABLE_BASE_ID en variables de entorno")
    return base_id


def _api_key() -> str:
    token = _env("AIRTABLE_API_KEY") or _env("AIRTABLE_TOKEN")
    if not token:
        raise ValueError("No se encontró AIRTABLE_API_KEY en variables de entorno")
    return token


@dataclass
class _Cell:
    value: Any


class AirtableAPI:
    def __init__(self, base_id: str, api_key: str):
        self.base_id = base_id
        self.api_key = api_key
        self._tables_cache: Optional[Dict[str, Dict[str, Any]]] = None

    def _request_json(self, method: str, url: str, params: Optional[Dict[str, Any]] = None, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if params:
            query = urllib.parse.urlencode(params, doseq=True)
            url = f"{url}?{query}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                raw_err = e.read().decode("utf-8") if e.fp else ""
                if raw_err:
                    parsed = json.loads(raw_err)
                    detail = parsed.get("error", {}).get("message") or raw_err
            except Exception:
                detail = ""
            raise RuntimeError(f"HTTP Error {e.code}: {e.reason}. {detail}".strip()) from e

    def list_tables(self) -> Dict[str, Dict[str, Any]]:
        if self._tables_cache is not None:
            return self._tables_cache
        data = self._request_json("GET", f"{AIRTABLE_META_URL}/bases/{self.base_id}/tables")
        tables = {}
        for table in data.get("tables", []):
            tables[table["name"]] = table
        self._tables_cache = tables
        return tables

    def refresh_cache(self) -> None:
        self._tables_cache = None

    def table_meta(self, name: str) -> Optional[Dict[str, Any]]:
        return self.list_tables().get(name)

    def ensure_table(self, name: str, fields: Iterable[str]) -> Dict[str, Any]:
        tables = self.list_tables()
        if name in tables:
            return tables[name]
        field_defs = DEFAULT_FIELD_DEFS.get(name)
        if field_defs is None:
            field_defs = [{"name": field, "type": "singleLineText"} for field in fields if field]
        payload = {
            "name": name,
            "fields": field_defs,
        }
        created = self._request_json("POST", f"{AIRTABLE_META_URL}/bases/{self.base_id}/tables", body=payload)
        self.refresh_cache()
        return created

    def list_records(self, table_name: str, page_size: int = 100) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        offset = None
        while True:
            params = {"pageSize": min(100, page_size)}
            if offset:
                params["offset"] = offset
            data = self._request_json("GET", f"{AIRTABLE_BASE_URL}/{self.base_id}/{urllib.parse.quote(table_name, safe='')} ".strip(), params=params)
            records.extend(data.get("records", []))
            offset = data.get("offset")
            if not offset:
                break
        return records

    def create_record(self, table_name: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        return self._request_json("POST", f"{AIRTABLE_BASE_URL}/{self.base_id}/{urllib.parse.quote(table_name, safe='')} ".strip(), body={"fields": fields})

    def create_records(self, table_name: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self._request_json("POST", f"{AIRTABLE_BASE_URL}/{self.base_id}/{urllib.parse.quote(table_name, safe='')} ".strip(), body={"records": [{"fields": r} for r in records]})

    def update_record(self, table_name: str, record_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        return self._request_json("PATCH", f"{AIRTABLE_BASE_URL}/{self.base_id}/{urllib.parse.quote(table_name, safe='')}/{record_id}", body={"fields": fields})

    def delete_record(self, table_name: str, record_id: str) -> Dict[str, Any]:
        return self._request_json("DELETE", f"{AIRTABLE_BASE_URL}/{self.base_id}/{urllib.parse.quote(table_name, safe='')}/{record_id}")


class AirtableWorksheet:
    def __init__(self, api: AirtableAPI, title: str):
        self.api = api
        self.title = title

    @property
    def headers(self) -> List[str]:
        meta = self.api.table_meta(self.title)
        if meta:
            fields = meta.get("fields", [])
            return [f.get("name", "") for f in fields if f.get("name", "")]
        return list(DEFAULT_HEADERS.get(self.title, []))

    def _all_records(self) -> List[Dict[str, Any]]:
        records = self.api.list_records(self.title)
        return sorted(records, key=lambda r: r.get("createdTime", ""))

    def _record_for_row(self, row: int) -> Dict[str, Any]:
        if row <= 1:
            raise IndexError("row 1 is header")
        records = self._all_records()
        idx = row - 2
        if idx < 0 or idx >= len(records):
            raise IndexError(f"row {row} out of range")
        return records[idx]

    def _row_values(self, record: Dict[str, Any]) -> List[Any]:
        fields = record.get("fields", {})
        return [fields.get(h, "") for h in self.headers]

    def get_all_records(self) -> List[Dict[str, Any]]:
        rows = []
        for record in self._all_records():
            fields = record.get("fields", {})
            rows.append({h: fields.get(h, "") for h in self.headers})
        return rows

    def get_all_values(self) -> List[List[Any]]:
        return [self.headers] + [self._row_values(r) for r in self._all_records()]

    def row_values(self, row: int) -> List[Any]:
        if row == 1:
            return self.headers
        return self._row_values(self._record_for_row(row))

    def col_values(self, col: int) -> List[Any]:
        values = [self.headers[col - 1] if 1 <= col <= len(self.headers) else ""]
        for record in self._all_records():
            row = self._row_values(record)
            values.append(row[col - 1] if 1 <= col <= len(row) else "")
        return values

    def acell(self, cell: str, value_render_option: Optional[str] = None) -> _Cell:
        match = re.fullmatch(r"([A-Za-z]+)(\d+)", cell.strip())
        if not match:
            raise ValueError(f"Celda inválida: {cell}")
        col_letters, row_txt = match.groups()
        row = int(row_txt)
        col = 0
        for ch in col_letters.upper():
            col = col * 26 + (ord(ch) - ord('A') + 1)
        row_vals = self.row_values(row)
        value = row_vals[col - 1] if 1 <= col <= len(row_vals) else ""
        return _Cell(value)

    def _row_to_fields(self, row_values: List[Any]) -> Dict[str, Any]:
        fields = {}
        for header, value in zip(self.headers, row_values):
            if header:
                fields[header] = value
        return fields

    def append_row(self, values: List[Any], value_input_option: str = "RAW") -> Dict[str, Any]:
        if values and list(values) == self.headers and not self._all_records():
            return {"id": None, "fields": self._row_to_fields(values)}
        fields = self._row_to_fields(values)
        return self.api.create_record(self.title, fields)

    def update(self, cell_range: str, values: List[List[Any]], value_input_option: str = "RAW") -> Dict[str, Any]:
        cell_range = cell_range.strip()
        m = re.fullmatch(r"([A-Za-z]+)(\d+)(?::([A-Za-z]+)(\d+))?", cell_range)
        if not m:
            m = re.fullmatch(r"(\d+):(\d+)", cell_range)
            if not m:
                raise ValueError(f"Rango inválido: {cell_range}")
            start_row = int(m.group(1))
            end_row = int(m.group(2))
            start_col = 1
            end_col = len(self.headers)
        else:
            start_col_letters, start_row_txt, end_col_letters, end_row_txt = m.groups()
            start_row = int(start_row_txt)
            end_row = int(end_row_txt or start_row_txt)
            def colnum(letters: str) -> int:
                n = 0
                for ch in letters.upper():
                    n = n * 26 + (ord(ch) - ord('A') + 1)
                return n
            start_col = colnum(start_col_letters)
            end_col = colnum(end_col_letters or start_col_letters)

        if start_row <= 1 and end_row <= 1:
            return {"ok": True}

        if start_row == end_row and start_row > 1:
            record = self._record_for_row(start_row)
            fields = dict(record.get("fields", {}))
            row_values = values[0] if values else []
            for idx, value in enumerate(row_values, start=start_col):
                if idx <= len(self.headers):
                    fields[self.headers[idx - 1]] = value
            return self.api.update_record(self.title, record["id"], fields)

        updated = []
        for r_offset, row_num in enumerate(range(start_row, end_row + 1)):
            if row_num <= 1:
                continue
            record = self._record_for_row(row_num)
            row_values = values[r_offset] if r_offset < len(values) else []
            fields = dict(record.get("fields", {}))
            for idx, value in enumerate(row_values, start=start_col):
                if idx <= len(self.headers):
                    fields[self.headers[idx - 1]] = value
            updated.append(self.api.update_record(self.title, record["id"], fields))
        return {"records": updated}

    def update_cell(self, row: int, col: int, value: Any) -> Dict[str, Any]:
        if row <= 1:
            return {"ok": True}
        record = self._record_for_row(row)
        fields = dict(record.get("fields", {}))
        if 1 <= col <= len(self.headers):
            fields[self.headers[col - 1]] = value
        return self.api.update_record(self.title, record["id"], fields)

    def delete_rows(self, row: int, number: int = 1) -> Dict[str, Any]:
        deleted = []
        for r in range(row, row + number):
            if r <= 1:
                continue
            record = self._record_for_row(r)
            deleted.append(self.api.delete_record(self.title, record["id"]))
        return {"records": deleted}

    def find(self, value: Any):
        for idx, record in enumerate(self._all_records(), start=2):
            row = self._row_values(record)
            for cell in row:
                if str(cell) == str(value):
                    return _Cell(cell)
        raise ValueError(f"{value!r} not found")


class AirtableWorkbook:
    def __init__(self, api: AirtableAPI):
        self.api = api

    def worksheet(self, title: str) -> AirtableWorksheet:
        if title not in self.api.list_tables():
            raise WorksheetNotFound(title)
        return AirtableWorksheet(self.api, title)

    def add_worksheet(self, title: str, rows: int = 1000, cols: int = 20) -> AirtableWorksheet:
        headers = DEFAULT_HEADERS.get(title, [])
        self.api.ensure_table(title, headers)
        return AirtableWorksheet(self.api, title)


api = AirtableAPI(_base_id(), _api_key())
sheet = AirtableWorkbook(api)
