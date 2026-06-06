import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRIVATE_EXPORT_DIR = PROJECT_ROOT / "local_exports"
TEMPLATE_DIR = PROJECT_ROOT / "airtable_template"

FINANCE_TABLES = [
    "Transacciones",
    "Cuentas",
    "Categorias",
    "Deudas",
    "MovimientosPendientes",
    "GmailEstado",
    "SaldosHistoricos",
]

SEED_TABLES = {"Categorias"}

FIELD_TYPE_OVERRIDES = {
    ("Transacciones", "Categoría"): {"type": "singleLineText"},
    ("Transacciones", "Cuenta"): {"type": "singleLineText"},
    ("Deudas", "CuentaAsociada"): {"type": "singleLineText"},
    ("MovimientosPendientes", "Cuenta"): {"type": "singleLineText"},
    ("SaldosHistoricos", "Cuenta"): {"type": "singleLineText"},
}


def load_dotenv(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def airtable_request(method, url, api_key, params=None, body=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(f"Airtable HTTP {exc.code}: {detail}") from exc


def list_records(base_id, api_key, table_name):
    records = []
    offset = None
    while True:
        params = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        url = f"https://api.airtable.com/v0/{base_id}/{urllib.parse.quote(table_name, safe='')}"
        data = airtable_request("GET", url, api_key, params=params)
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            return records


def public_field_def(table_name, field):
    clean = {
        "name": field.get("name", ""),
        "type": field.get("type", ""),
    }
    override = FIELD_TYPE_OVERRIDES.get((table_name, clean["name"]))
    if override:
        clean.update(override)
        return clean

    options = field.get("options")
    if isinstance(options, dict):
        safe_options = {}
        if "choices" in options:
            safe_options["choices"] = [
                {"name": choice.get("name", "")}
                for choice in options.get("choices", [])
                if choice.get("name")
            ]
        for key in ("precision", "dateFormat", "timeFormat", "timeZone"):
            if key in options:
                safe_options[key] = options[key]
        if safe_options:
            clean["options"] = safe_options
    return clean


def public_record(record):
    return dict(record.get("fields", {}))


def main():
    load_dotenv(PROJECT_ROOT / ".env")
    base_id = os.getenv("AIRTABLE_BASE_ID", "").strip()
    api_key = os.getenv("AIRTABLE_API_KEY", "").strip()
    if not base_id or not api_key:
        raise SystemExit("Faltan AIRTABLE_BASE_ID o AIRTABLE_API_KEY en .env.")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    meta_url = f"https://api.airtable.com/v0/meta/bases/{base_id}/tables"
    meta = airtable_request("GET", meta_url, api_key)
    tables_by_name = {table.get("name"): table for table in meta.get("tables", [])}

    private_export = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_base_id": base_id,
        "tables": {},
    }
    clean_template = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "sanitized_airtable_schema",
        "tables": {},
        "seeds": {},
    }

    for table_name in FINANCE_TABLES:
        table_meta = tables_by_name.get(table_name)
        if not table_meta:
            continue

        fields = [public_field_def(table_name, field) for field in table_meta.get("fields", [])]
        records = list_records(base_id, api_key, table_name)

        private_export["tables"][table_name] = {
            "schema": fields,
            "records": [
                {
                    "id": record.get("id"),
                    "createdTime": record.get("createdTime"),
                    "fields": record.get("fields", {}),
                }
                for record in records
            ],
        }
        clean_template["tables"][table_name] = {"schema": fields}

        if table_name in SEED_TABLES:
            clean_template["seeds"][table_name] = [public_record(record) for record in records]
        else:
            clean_template["seeds"][table_name] = []

    PRIVATE_EXPORT_DIR.mkdir(exist_ok=True)
    TEMPLATE_DIR.mkdir(exist_ok=True)

    private_path = PRIVATE_EXPORT_DIR / f"airtable_private_backup_{timestamp}.json"
    template_path = TEMPLATE_DIR / "finance_base_template.json"

    private_path.write_text(json.dumps(private_export, indent=2, ensure_ascii=False), encoding="utf-8")
    template_path.write_text(json.dumps(clean_template, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Private backup: {private_path}")
    print(f"Clean template: {template_path}")
    print("Template seeds include only: " + ", ".join(sorted(SEED_TABLES)))


if __name__ == "__main__":
    main()
