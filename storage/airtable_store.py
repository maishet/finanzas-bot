import re
from typing import Any, Dict, Iterable, List, Optional

from airtable_backend import AirtableAPI, create_airtable_api


class TenantStoreError(Exception):
    pass


def require_tenant_id(tenant_id: str) -> str:
    tenant_id = str(tenant_id or "").strip()
    if not tenant_id:
        raise TenantStoreError("tenant_id es obligatorio para acceder a datos financieros.")
    return tenant_id


def escape_airtable_string(value: Any) -> str:
    return str(value or "").replace("\\", "\\\\").replace("'", "\\'")


def build_formula(filters: Optional[Dict[str, Any]] = None) -> str:
    parts = []
    for field, value in (filters or {}).items():
        if value is None:
            continue
        field_name = str(field).strip()
        if not field_name or not re.fullmatch(r"[\wÁÉÍÓÚáéíóúÑñüÜ ./_-]+", field_name):
            raise TenantStoreError(f"Campo inválido para filtro Airtable: {field!r}")
        parts.append(f"{{{field_name}}}='{escape_airtable_string(value)}'")

    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "AND(" + ",".join(parts) + ")"


class AirtableTenantStore:
    """Airtable storage adapter that enforces tenant-scoped financial access."""

    def __init__(self, api: AirtableAPI):
        self.api = api

    @classmethod
    def from_credentials(cls, base_id: str, api_key: str):
        return cls(create_airtable_api(base_id, api_key))

    def list_records(self, table_name: str, tenant_id: str, filters: Optional[Dict[str, Any]] = None, page_size: int = 100) -> List[Dict[str, Any]]:
        tenant_id = require_tenant_id(tenant_id)
        scoped_filters = {"TenantID": tenant_id}
        scoped_filters.update(filters or {})
        formula = build_formula(scoped_filters)
        return self._list_records_raw(table_name, formula=formula, page_size=page_size)

    def get_record(self, table_name: str, tenant_id: str, id_field: str, id_value: Any) -> Optional[Dict[str, Any]]:
        rows = self.list_records(table_name, tenant_id, filters={id_field: id_value}, page_size=10)
        return rows[0] if rows else None

    def create_record(self, table_name: str, tenant_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        tenant_id = require_tenant_id(tenant_id)
        payload = dict(fields or {})
        payload["TenantID"] = tenant_id
        return self.api.create_record(table_name, payload)

    def create_records(self, table_name: str, tenant_id: str, records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        tenant_id = require_tenant_id(tenant_id)
        payload = []
        for record in records:
            fields = dict(record or {})
            fields["TenantID"] = tenant_id
            payload.append(fields)
        if not payload:
            return {"records": []}
        return self.api.create_records(table_name, payload)

    def update_record(self, table_name: str, tenant_id: str, record_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        require_tenant_id(tenant_id)
        existing = self._fetch_record_by_id(table_name, record_id)
        existing_tenant = str((existing.get("fields") or {}).get("TenantID", "")).strip()
        if existing_tenant != str(tenant_id).strip():
            raise TenantStoreError("El registro no pertenece al tenant solicitado.")
        payload = dict(fields or {})
        payload.pop("TenantID", None)
        return self.api.update_record(table_name, record_id, payload)

    def delete_record(self, table_name: str, tenant_id: str, record_id: str) -> Dict[str, Any]:
        require_tenant_id(tenant_id)
        existing = self._fetch_record_by_id(table_name, record_id)
        existing_tenant = str((existing.get("fields") or {}).get("TenantID", "")).strip()
        if existing_tenant != str(tenant_id).strip():
            raise TenantStoreError("El registro no pertenece al tenant solicitado.")
        return self.api.delete_record(table_name, record_id)

    def _list_records_raw(self, table_name: str, formula: str = "", page_size: int = 100) -> List[Dict[str, Any]]:
        import urllib.parse
        from airtable_backend import AIRTABLE_BASE_URL

        params = {"pageSize": min(100, page_size)}
        if formula:
            params["filterByFormula"] = formula

        records = []
        offset = None
        while True:
            page_params = dict(params)
            if offset:
                page_params["offset"] = offset
            data = self.api._request_json(
                "GET",
                f"{AIRTABLE_BASE_URL}/{self.api.base_id}/{urllib.parse.quote(table_name, safe='')}",
                params=page_params,
            )
            records.extend(data.get("records", []))
            offset = data.get("offset")
            if not offset:
                return records

    def _fetch_record_by_id(self, table_name: str, record_id: str) -> Dict[str, Any]:
        import urllib.parse
        from airtable_backend import AIRTABLE_BASE_URL

        return self.api._request_json(
            "GET",
            f"{AIRTABLE_BASE_URL}/{self.api.base_id}/{urllib.parse.quote(table_name, safe='')}/{record_id}",
        )
