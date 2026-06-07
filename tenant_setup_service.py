import json
import re
import unicodedata
from pathlib import Path

from airtable_backend import api as default_airtable_api
from storage.airtable_store import AirtableTenantStore


TEMPLATE_PATH = Path(__file__).resolve().parent / "airtable_template" / "finance_base_template.json"

ACCOUNT_TYPES = {
    "efectivo": "Efectivo",
    "banco": "Banco",
    "credito": "Crédito",
    "crédito": "Crédito",
    "debito": "Debito",
    "débito": "Debito",
}

DEBT_TYPES = {
    "credito": "Crédito",
    "crédito": "Crédito",
    "servicio": "Servicio",
}


def normalizar_texto(texto):
    if not texto:
        return ""
    txt = str(texto).lower().strip()
    txt = unicodedata.normalize("NFD", txt)
    return txt.encode("ascii", "ignore").decode("utf-8")


def parsear_numero(valor):
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    txt = str(valor).strip()
    txt = txt.replace("S/", "").replace("PEN", "").replace("USD", "").replace("$", "").strip()
    txt = re.sub(r"[^\d,\.\-]", "", txt)
    if "," in txt and "." in txt:
        if txt.rfind(",") > txt.rfind("."):
            txt = txt.replace(".", "").replace(",", ".")
        else:
            txt = txt.replace(",", "")
    elif "," in txt:
        txt = txt.replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return 0.0


def load_template():
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def _store():
    return AirtableTenantStore(default_airtable_api)


def _records(tenant_id, table_name):
    return [
        {"_record_id": record.get("id"), **dict(record.get("fields", {}))}
        for record in _store().list_records(table_name, tenant_id)
    ]


def _next_prefixed_id(rows, field, prefix):
    max_num = 0
    for row in rows:
        raw = str(row.get(field, "")).strip().upper()
        if not raw.startswith(prefix):
            continue
        try:
            max_num = max(max_num, int(raw[len(prefix):]))
        except ValueError:
            continue
    return f"{prefix}{max_num + 1:05d}"


def _next_numeric_id(rows, field):
    max_num = 0
    for row in rows:
        try:
            max_num = max(max_num, int(str(row.get(field, "")).strip()))
        except ValueError:
            continue
    return str(max_num + 1)


def seed_categories(tenant_id):
    template = load_template()
    rows = template.get("seeds", {}).get("Categorias", []) or []
    existing = {
        (
            normalizar_texto(row.get("Nombre", "")),
            normalizar_texto(row.get("Tipo", "")),
        )
        for row in _records(tenant_id, "Categorias")
    }

    to_create = []
    for row in rows:
        key = (normalizar_texto(row.get("Nombre", "")), normalizar_texto(row.get("Tipo", "")))
        if not key[0] or key in existing:
            continue
        to_create.append(row)
        existing.add(key)

    for start in range(0, len(to_create), 10):
        _store().create_records("Categorias", tenant_id, to_create[start : start + 10])
    return len(to_create)


def list_accounts(tenant_id):
    accounts = _records(tenant_id, "Cuentas")
    return sorted(accounts, key=lambda row: normalizar_texto(row.get("Nombre", "")))


def add_account(tenant_id, nombre, tipo, moneda, saldo, numero_cuenta=""):
    nombre = str(nombre or "").strip()
    if not nombre:
        raise ValueError("Nombre de cuenta obligatorio.")
    tipo_norm = normalizar_texto(tipo)
    if tipo_norm not in ACCOUNT_TYPES:
        raise ValueError("Tipo inválido. Usa Efectivo, Banco, Crédito o Debito.")
    moneda = str(moneda or "PEN").strip().upper()
    if moneda not in {"PEN", "USD"}:
        raise ValueError("Moneda inválida. Usa PEN o USD.")

    accounts = list_accounts(tenant_id)
    if any(normalizar_texto(row.get("Nombre", "")) == normalizar_texto(nombre) for row in accounts):
        raise ValueError(f"Ya existe la cuenta '{nombre}'.")

    fields = {
        "ID": _next_prefixed_id(accounts, "ID", "CTA"),
        "Nombre": nombre,
        "NumeroCuenta": str(numero_cuenta or "").strip(),
        "Tipo": ACCOUNT_TYPES[tipo_norm],
        "Moneda": moneda,
        "SaldoActual": round(parsear_numero(saldo), 2),
    }
    _store().create_record("Cuentas", tenant_id, fields)
    return fields


def add_debt(tenant_id, descripcion, tipo, monto, moneda, fecha_vencimiento, cuenta_asociada):
    descripcion = str(descripcion or "").strip()
    if not descripcion:
        raise ValueError("Descripción de deuda obligatoria.")
    tipo_norm = normalizar_texto(tipo)
    if tipo_norm not in DEBT_TYPES:
        raise ValueError("Tipo inválido. Usa Crédito o Servicio.")
    moneda = str(moneda or "PEN").strip().upper()
    if moneda not in {"PEN", "USD"}:
        raise ValueError("Moneda inválida. Usa PEN o USD.")
    cuenta_asociada = str(cuenta_asociada or "").strip()
    if not any(normalizar_texto(row.get("Nombre", "")) == normalizar_texto(cuenta_asociada) for row in list_accounts(tenant_id)):
        raise ValueError(f"No existe la cuenta '{cuenta_asociada}'.")

    debts = _records(tenant_id, "Deudas")
    fields = {
        "ID": _next_numeric_id(debts, "ID"),
        "Descripcion": descripcion,
        "Tipo": DEBT_TYPES[tipo_norm],
        "MontoTotal": round(parsear_numero(monto), 2),
        "Moneda": moneda,
        "MontoPagado": 0,
        "FechaVencimiento": str(fecha_vencimiento or "").strip(),
        "Estado": "Activa",
        "CuentaAsociada": cuenta_asociada,
    }
    _store().create_record("Deudas", tenant_id, fields)
    return fields
