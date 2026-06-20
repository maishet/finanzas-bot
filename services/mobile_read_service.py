import config
from services.account_service import get_mobile_accounts, get_mobile_summary
from services.debt_service import get_mobile_debts
from services.pending_service import get_mobile_pending_movements
from services.transaction_service import get_mobile_transactions
from tenant_context import list_users


API_VERSION = "0.1.0"


def get_version():
    return {
        "ok": True,
        "name": "finanzas-bot-mobile-api",
        "version": API_VERSION,
        "phase": "phase-2-otp-jwt",
        "auth": "telegram-otp-jwt",
    }


def get_me(tenant_id):
    tenant_id = str(tenant_id or "").strip()
    for user in list_users():
        if str(user.get("tenant_id", "")).strip() == tenant_id:
            return {
                "tenant_id": tenant_id,
                "telegram_user_id": user.get("telegram_user_id", ""),
                "nombre": user.get("nombre", ""),
                "estado": user.get("estado", ""),
                "rol": user.get("rol", ""),
                "setup_completo": bool(user.get("setup_completo")),
                "gmail_enabled": bool(user.get("gmail_enabled")),
                "voice_enabled": bool(user.get("voice_enabled")),
            }

    if tenant_id == str(config.SYSTEM_TENANT_ID or "").strip():
        return {
            "tenant_id": tenant_id,
            "telegram_user_id": str(config.ADMIN_TELEGRAM_USER_ID),
            "nombre": "Admin principal",
            "estado": "Activo",
            "rol": "Admin",
            "setup_completo": True,
            "gmail_enabled": bool(config.GMAIL_PUSH_ENABLED),
            "voice_enabled": bool(config.VOICE_ENABLED),
        }

    return {
        "tenant_id": tenant_id,
        "telegram_user_id": "",
        "nombre": "",
        "estado": "Desconocido",
        "rol": "",
        "setup_completo": False,
        "gmail_enabled": False,
        "voice_enabled": False,
    }


def get_accounts(tenant_id):
    return get_mobile_accounts(tenant_id)


def get_summary(tenant_id):
    return get_mobile_summary(tenant_id)


def get_transactions(tenant_id, limit=50):
    return get_mobile_transactions(tenant_id, limit=limit)


def get_debts(tenant_id):
    return get_mobile_debts(tenant_id)


def get_pending_movements(tenant_id, limit=50):
    return get_mobile_pending_movements(tenant_id, limit=limit)
