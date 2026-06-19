import hmac

import config


class MobileAPIError(Exception):
    def __init__(self, status_code, message, code="mobile_api_error"):
        super().__init__(message)
        self.status_code = int(status_code)
        self.message = str(message)
        self.code = str(code)

    def to_payload(self):
        return {"ok": False, "error": self.code, "message": self.message}


def validate_mobile_api_key(api_key):
    expected = str(config.MOBILE_API_KEY or "").strip()
    if not expected:
        raise MobileAPIError(
            503,
            "MOBILE_API_KEY no esta configurado. Define esta variable antes de exponer /api/*.",
            "mobile_api_not_configured",
        )

    provided = str(api_key or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise MobileAPIError(401, "API key invalida o ausente.", "invalid_api_key")


def require_tenant_header(tenant_id):
    tenant_id = str(tenant_id or "").strip()
    if not tenant_id:
        raise MobileAPIError(400, "X-Tenant-ID es obligatorio para endpoints financieros.", "missing_tenant_id")
    return tenant_id
