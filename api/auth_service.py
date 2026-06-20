import base64
import hashlib
import hmac
import json
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import config
from airtable_backend import api as airtable_api
from tenant_context import TenantContextError, resolve_tenant_context


AUTH_TABLE = "AuthCodes"


def _utcnow():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _parse_dt(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _ensure_auth_table():
    airtable_api.ensure_table(AUTH_TABLE, [])


def _secret():
    secret = str(config.MOBILE_JWT_SECRET or config.MOBILE_API_KEY or "").strip()
    if not secret:
        raise ValueError("MOBILE_JWT_SECRET o MOBILE_API_KEY debe estar configurado para autenticacion movil.")
    return secret


def _b64url_encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(raw):
    value = str(raw or "").encode("ascii")
    padding = b"=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _json_b64(payload):
    return _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def hash_otp(tenant_id, telegram_user_id, code):
    message = f"{tenant_id}:{telegram_user_id}:{code}".encode("utf-8")
    return hmac.new(_secret().encode("utf-8"), message, hashlib.sha256).hexdigest()


def create_jwt(payload):
    now = int(_utcnow().timestamp())
    exp = int((_utcnow() + timedelta(hours=config.MOBILE_JWT_EXPIRES_HOURS)).timestamp())
    token_payload = dict(payload or {})
    token_payload.update({"iat": now, "exp": exp})
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_json_b64(header)}.{_json_b64(token_payload)}"
    signature = hmac.new(_secret().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def verify_jwt(token):
    token = str(token or "").strip()
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Token invalido.")
    signing_input = f"{parts[0]}.{parts[1]}"
    expected = hmac.new(_secret().encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    received = _b64url_decode(parts[2])
    if not hmac.compare_digest(received, expected):
        raise ValueError("Firma de token invalida.")
    payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    if int(payload.get("exp", 0)) < int(_utcnow().timestamp()):
        raise ValueError("Token expirado.")
    if not str(payload.get("tenant_id", "")).strip():
        raise ValueError("Token sin tenant_id.")
    return payload


def create_login_code(telegram_user_id):
    tenant = resolve_tenant_context(telegram_user_id)
    code = f"{secrets.randbelow(1000000):06d}"
    now = _utcnow()
    expires_at = now + timedelta(minutes=config.MOBILE_OTP_EXPIRES_MINUTES)
    _ensure_auth_table()
    airtable_api.create_record(
        AUTH_TABLE,
        {
            "TenantID": tenant.tenant_id,
            "TelegramUserID": str(telegram_user_id).strip(),
            "CodeHash": hash_otp(tenant.tenant_id, telegram_user_id, code),
            "ExpiresAt": _iso(expires_at),
            "CreatedAt": _iso(now),
            "Attempts": 0,
        },
    )
    return {
        "code": code,
        "tenant": tenant,
        "expires_at": expires_at,
        "expires_in_minutes": config.MOBILE_OTP_EXPIRES_MINUTES,
    }


def _candidate_auth_codes(telegram_user_id):
    _ensure_auth_table()
    target = str(telegram_user_id).strip()
    rows = []
    for record in airtable_api.list_records(AUTH_TABLE):
        fields = dict(record.get("fields", {}))
        if str(fields.get("TelegramUserID", "")).strip() != target:
            continue
        fields["_record_id"] = record.get("id")
        rows.append(fields)
    return sorted(rows, key=lambda row: str(row.get("CreatedAt", "")), reverse=True)


def verify_login_code(telegram_user_id, code):
    tenant = resolve_tenant_context(telegram_user_id)
    expected_hash = hash_otp(tenant.tenant_id, telegram_user_id, str(code or "").strip())
    now = _utcnow()
    last_error = "Codigo invalido o expirado."

    for row in _candidate_auth_codes(telegram_user_id):
        if str(row.get("TenantID", "")).strip() != tenant.tenant_id:
            continue
        if str(row.get("UsedAt", "")).strip():
            continue
        expires_at = _parse_dt(row.get("ExpiresAt"))
        if not expires_at or expires_at < now:
            last_error = "Codigo expirado. Solicita uno nuevo."
            continue

        attempts = int(float(str(row.get("Attempts", 0) or 0)))
        if attempts >= config.MOBILE_OTP_MAX_ATTEMPTS:
            last_error = "Demasiados intentos. Solicita un codigo nuevo."
            continue

        record_id = row.get("_record_id")
        if hmac.compare_digest(str(row.get("CodeHash", "")), expected_hash):
            airtable_api.update_record(AUTH_TABLE, record_id, {"UsedAt": _iso(now), "Attempts": attempts + 1})
            token = create_jwt(
                {
                    "tenant_id": tenant.tenant_id,
                    "telegram_user_id": tenant.telegram_user_id,
                    "rol": tenant.rol,
                }
            )
            return {
                "access_token": token,
                "token_type": "Bearer",
                "expires_in_hours": config.MOBILE_JWT_EXPIRES_HOURS,
                "tenant_id": tenant.tenant_id,
                "telegram_user_id": tenant.telegram_user_id,
                "rol": tenant.rol,
            }

        airtable_api.update_record(AUTH_TABLE, record_id, {"Attempts": attempts + 1})
        last_error = "Codigo invalido."
        break

    raise ValueError(last_error)


def build_login_message(code, expires_in_minutes):
    return (
        "Codigo de acceso para Finanzas App\n\n"
        f"Codigo: {code}\n"
        f"Vence en {expires_in_minutes} minutos.\n\n"
        "Si no fuiste tu, ignora este mensaje."
    )


def send_login_code_via_telegram(telegram_user_id, code, expires_in_minutes):
    message = build_login_message(code, expires_in_minutes)
    data = urllib.parse.urlencode({"chat_id": str(telegram_user_id).strip(), "text": message}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {"ok": True}


def request_login_code(telegram_user_id):
    created = create_login_code(telegram_user_id)
    send_login_code_via_telegram(
        telegram_user_id,
        created["code"],
        created["expires_in_minutes"],
    )
    return {
        "telegram_user_id": str(telegram_user_id).strip(),
        "tenant_id": created["tenant"].tenant_id,
        "expires_in_minutes": created["expires_in_minutes"],
        "delivery": "telegram",
    }
