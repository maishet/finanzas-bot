from airtable_handler import (
    _cache_invalidate,
    _leer_records_cacheados,
    _row_with_tenant,
    categorias_ws,
    normalizar_texto,
    obtener_categorias,
)


def _category_icon(nombre):
    norm = normalizar_texto(nombre)
    if any(token in norm for token in ["aliment", "comida", "supermerc"]):
        return "restaurant-outline"
    if any(token in norm for token in ["transport", "taxi", "uber"]):
        return "car-outline"
    if any(token in norm for token in ["vivienda", "hogar", "alquiler"]):
        return "home-outline"
    if any(token in norm for token in ["servicio", "luz", "agua", "internet"]):
        return "flash-outline"
    if any(token in norm for token in ["salud", "medic"]):
        return "medical-outline"
    if any(token in norm for token in ["sueldo", "salario"]):
        return "briefcase-outline"
    if any(token in norm for token in ["deuda", "credito", "tarjeta"]):
        return "card-outline"
    return "apps-outline"


def get_mobile_categories(tenant_id, tipo=None):
    categories = obtener_categorias(tipo, tenant_id=tenant_id)
    return [
        {
            "nombre": item["original"],
            "tipo": item["tipo"],
            "subcategorias": item.get("subcategorias", ""),
            "icono": _category_icon(item["original"]),
        }
        for item in sorted(categories, key=lambda row: normalizar_texto(row["original"]))
    ]


def create_mobile_category(tenant_id, payload):
    payload = payload or {}
    nombre = str(payload.get("nombre", "")).strip()
    tipo = str(payload.get("tipo", "Gasto")).strip().capitalize()
    subcategorias = str(payload.get("subcategorias", "")).strip()
    if not nombre:
        raise ValueError("nombre es obligatorio.")
    if tipo not in {"Gasto", "Ingreso"}:
        raise ValueError("tipo debe ser Gasto o Ingreso.")

    existing = _leer_records_cacheados(categorias_ws, "categorias_records", tenant_id=tenant_id)
    key = (normalizar_texto(nombre), normalizar_texto(tipo))
    for row in existing:
        if (normalizar_texto(row.get("Nombre", "")), normalizar_texto(row.get("Tipo", ""))) == key:
            return {"nombre": str(row.get("Nombre", nombre)).strip(), "tipo": str(row.get("Tipo", tipo)).strip(), "created": False}

    categorias_ws.append_row(_row_with_tenant(categorias_ws, [nombre, tipo, subcategorias], tenant_id), value_input_option="RAW")
    _cache_invalidate("categorias_records")
    return {"nombre": nombre, "tipo": tipo, "created": True}
