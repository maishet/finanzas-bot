from repositories import default_finance_repository
from utils.finance_format import normalize_text


def _category_icon(nombre):
    norm = normalize_text(nombre)
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
    if any(token in norm for token in ["deuda", "crédito", "tarjeta"]):
        return "card-outline"
    return "apps-outline"


def get_mobile_categories(tenant_id, tipo=None, repository=None):
    repository = repository or default_finance_repository
    categories = repository.list_categories(tenant_id, category_type=tipo)
    return [
        {
            "nombre": item["original"],
            "tipo": item["tipo"],
            "subcategorias": item.get("subcategorias", ""),
            "icono": _category_icon(item["original"]),
        }
        for item in sorted(categories, key=lambda row: normalize_text(row["original"]))
    ]


def create_mobile_category(tenant_id, payload, repository=None):
    repository = repository or default_finance_repository
    payload = payload or {}
    nombre = str(payload.get("nombre", "")).strip()
    tipo = str(payload.get("tipo", "Gasto")).strip().capitalize()
    subcategorias = str(payload.get("subcategorias", "")).strip()
    if not nombre:
        raise ValueError("nombre es obligatorio.")
    if tipo not in {"Gasto", "Ingreso"}:
        raise ValueError("tipo debe ser Gasto o Ingreso.")

    return repository.create_category_if_missing(tenant_id, nombre, tipo, subcategories=subcategorias)
