from dataclasses import dataclass
from datetime import datetime, timezone

import config
from airtable_backend import api as default_airtable_api
from storage.airtable_store import AirtableTenantStore


class TenantContextError(Exception):
    pass


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    telegram_user_id: str
    nombre: str
    rol: str
    setup_completo: bool
    gmail_enabled: bool
    voice_enabled: bool


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def is_admin(telegram_user_id) -> bool:
    return int(telegram_user_id) == int(config.ADMIN_TELEGRAM_USER_ID)


def tenant_id_for_telegram(telegram_user_id) -> str:
    return f"TEN_TG_{str(telegram_user_id).strip()}"


def user_id_for_telegram(telegram_user_id) -> str:
    return f"USR_TG_{str(telegram_user_id).strip()}"


def _store():
    return AirtableTenantStore(default_airtable_api)


def ensure_identity_tables():
    default_airtable_api.ensure_table("Tenants", [])
    default_airtable_api.ensure_table("Usuarios", [])
    default_airtable_api.refresh_cache()


def _fields(record):
    return dict((record or {}).get("fields", {}))


def _yes(value) -> bool:
    return str(value or "").strip().lower() in {"si", "sí", "true", "1", "yes", "on"}


def _list_all_usuarios():
    ensure_identity_tables()
    return default_airtable_api.list_records("Usuarios")


def find_user_by_telegram(telegram_user_id):
    target = str(telegram_user_id).strip()
    for record in _list_all_usuarios():
        fields = _fields(record)
        if str(fields.get("TelegramUserID", "")).strip() == target:
            return {"_record_id": record.get("id"), **fields}
    return None


def resolve_tenant_context(telegram_user_id, require_setup=False) -> TenantContext:
    user = find_user_by_telegram(telegram_user_id)
    if not user:
        if int(telegram_user_id) == int(config.USER_ID):
            tenant_id = tenant_id_for_telegram(telegram_user_id)
            return TenantContext(
                tenant_id=tenant_id,
                telegram_user_id=str(telegram_user_id),
                nombre="Admin principal",
                rol="Admin",
                setup_completo=True,
                gmail_enabled=bool(config.GMAIL_PUSH_ENABLED),
                voice_enabled=bool(config.VOICE_ENABLED),
            )
        raise TenantContextError("No tienes acceso al bot. Pide autorización al administrador.")

    if str(user.get("Estado", "")).strip().lower() != "activo":
        raise TenantContextError("Tu usuario no está activo. Pide acceso al administrador.")
    if require_setup and not _yes(user.get("SetupCompleto")):
        raise TenantContextError("Tu configuración inicial todavía no está completa.")

    return TenantContext(
        tenant_id=str(user.get("TenantID", "")).strip(),
        telegram_user_id=str(user.get("TelegramUserID", "")).strip(),
        nombre=str(user.get("Nombre", "")).strip(),
        rol=str(user.get("Rol", "")).strip() or "Owner",
        setup_completo=_yes(user.get("SetupCompleto")),
        gmail_enabled=_yes(user.get("GmailEnabled")),
        voice_enabled=_yes(user.get("VoiceEnabled")),
    )


def is_authorized_user(telegram_user_id) -> bool:
    try:
        resolve_tenant_context(telegram_user_id)
        return True
    except TenantContextError:
        return False


def create_or_update_user(telegram_user_id, nombre, rol="Owner"):
    telegram_user_id = str(telegram_user_id).strip()
    nombre = str(nombre or "").strip()
    if not telegram_user_id:
        raise ValueError("TelegramUserID es obligatorio.")
    if not nombre:
        raise ValueError("Nombre es obligatorio.")

    ensure_identity_tables()
    tenant_id = tenant_id_for_telegram(telegram_user_id)
    user_id = user_id_for_telegram(telegram_user_id)
    store = _store()
    now = now_iso()

    tenant = store.get_record("Tenants", tenant_id, "TenantID", tenant_id)
    tenant_fields = {
        "TenantID": tenant_id,
        "Nombre": nombre,
        "Estado": "Activo",
        "Plan": "Personal",
        "UpdatedAt": now,
    }
    if tenant:
        store.update_record("Tenants", tenant_id, tenant["id"], tenant_fields)
    else:
        tenant_fields["CreatedAt"] = now
        store.create_record("Tenants", tenant_id, tenant_fields)

    existing = find_user_by_telegram(telegram_user_id)
    user_fields = {
        "UserID": user_id,
        "TenantID": tenant_id,
        "TelegramUserID": telegram_user_id,
        "Nombre": nombre,
        "Estado": "Activo",
        "Rol": rol,
        "SetupCompleto": "No",
        "GmailEnabled": "No",
        "VoiceEnabled": "No",
        "UpdatedAt": now,
    }
    if existing:
        store.update_record("Usuarios", tenant_id, existing["_record_id"], user_fields)
    else:
        user_fields["CreatedAt"] = now
        store.create_record("Usuarios", tenant_id, user_fields)

    return resolve_tenant_context(telegram_user_id)


def list_users():
    users = []
    for record in _list_all_usuarios():
        fields = _fields(record)
        users.append({
            "telegram_user_id": str(fields.get("TelegramUserID", "")).strip(),
            "tenant_id": str(fields.get("TenantID", "")).strip(),
            "nombre": str(fields.get("Nombre", "")).strip(),
            "estado": str(fields.get("Estado", "")).strip(),
            "rol": str(fields.get("Rol", "")).strip(),
            "setup_completo": _yes(fields.get("SetupCompleto")),
            "gmail_enabled": _yes(fields.get("GmailEnabled")),
            "voice_enabled": _yes(fields.get("VoiceEnabled")),
        })
    return sorted(users, key=lambda item: (item["estado"], item["nombre"], item["telegram_user_id"]))


def block_user(telegram_user_id):
    user = find_user_by_telegram(telegram_user_id)
    if not user:
        raise ValueError(f"No existe usuario {telegram_user_id}.")
    store = _store()
    store.update_record(
        "Usuarios",
        user["TenantID"],
        user["_record_id"],
        {"Estado": "Bloqueado", "UpdatedAt": now_iso()},
    )
    return True


def mark_setup_complete(telegram_user_id, complete=True):
    user = find_user_by_telegram(telegram_user_id)
    if not user:
        raise ValueError(f"No existe usuario {telegram_user_id}.")
    store = _store()
    store.update_record(
        "Usuarios",
        user["TenantID"],
        user["_record_id"],
        {
            "SetupCompleto": "Si" if complete else "No",
            "UpdatedAt": now_iso(),
        },
    )
    return resolve_tenant_context(telegram_user_id)
