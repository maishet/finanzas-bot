import asyncio
import base64
import email
from email import policy
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

import config
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from airtable_handler import (
    normalizar_texto,
    parsear_numero,
    obtener_nombres_cuentas,
    detectar_cuenta_por_ultimos_digitos,
    registrar_movimiento_pendiente,
    existe_movimiento_pendiente_duplicado,
    obtener_estado_gmail_push,
    guardar_estado_gmail_push,
    resolver_tenant_gmail_por_email,
)

logger = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
_GMAIL_AUTH_ERROR_LOGGED_AT = None  # Controlar frecuencia de logs de error


class GmailPushError(Exception):
    pass


def _log_descarte_gmail_push(motivo, **campos):
    extras = " ".join(f"{k}={v}" for k, v in campos.items() if v not in [None, ""])
    logger.info("GMAIL_PUSH_DROP | motivo=%s%s%s", motivo, " | " if extras else "", extras)


def _normalizar_correo(texto):
    return normalizar_texto(texto or "").replace(" ", "")


def _extraer_correo_emisor(from_header):
    txt = str(from_header or "").strip().lower()
    m = re.search(r"<([^>]+@[^>]+)>", txt)
    if m:
        return m.group(1).strip()
    m = re.search(r"([a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,})", txt)
    if m:
        return m.group(1).strip()
    return ""


def _remitente_permitido(sender_email):
    if not config.GMAIL_ALLOWED_SENDERS:
        return True

    sender = _normalizar_correo(sender_email)
    if not sender:
        return False

    for allowed in config.GMAIL_ALLOWED_SENDERS:
        allow = _normalizar_correo(allowed)
        if not allow:
            continue
        if sender == allow:
            return True
        if "@" in allow:
            domain = allow.split("@", 1)[1]
            if domain and sender.endswith(domain):
                return True
        elif sender.endswith(allow):
            return True

    return False


def _credenciales_gmail(tenant_id=None):
    global _GMAIL_AUTH_ERROR_LOGGED_AT
    tenant_id = str(tenant_id or config.SYSTEM_TENANT_ID or "").strip()

    # Intentar cargar el token desde Airtable primero (permite actualizar sin reinicio)
    refresh_token = None
    try:
        estado = obtener_estado_gmail_push("GMAIL_REFRESH_TOKEN", tenant_id=tenant_id)
        if estado:
            refresh_token = estado.strip()
    except Exception:
        pass  # Si Airtable falla, usar el de config

    # Si no está en Airtable, usar el de config
    if not refresh_token:
        refresh_token = config.GMAIL_REFRESH_TOKEN

    if not config.GMAIL_CLIENT_ID or not config.GMAIL_CLIENT_SECRET or not refresh_token:
        raise GmailPushError(
            "Faltan credenciales de Gmail. Revisa GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET y GMAIL_REFRESH_TOKEN."
        )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.GMAIL_CLIENT_ID,
        client_secret=config.GMAIL_CLIENT_SECRET,
        scopes=GMAIL_SCOPES,
    )

    if not creds.valid or creds.expired:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            error_txt = str(e)
            # Limitar frecuencia de logs para no saturar con el mismo error
            ahora = datetime.now()
            if _GMAIL_AUTH_ERROR_LOGGED_AT is None or (ahora - _GMAIL_AUTH_ERROR_LOGGED_AT).total_seconds() > 3600:
                _GMAIL_AUTH_ERROR_LOGGED_AT = ahora
                if "invalid_grant" in error_txt:
                    logger.error(
                        "Error de autenticación Gmail (invalid_grant): refresh token fue revocado o expiró. "
                        "Ejecuta /gmail_regenerate_token para ver opciones, o /setear_gmail_token <nuevo_token> para actualizar."
                    )
                else:
                    logger.error(f"Error refrescando token de Gmail: {error_txt}")
            raise GmailPushError(f"No se pudo refrescar el token de Gmail: {error_txt}") from e
    return creds


def _gmail_api_request(method, endpoint, params=None, body=None, timeout=30, tenant_id=None):
    creds = _credenciales_gmail(tenant_id=tenant_id)
    query = ""
    if params:
        query = "?" + urllib.parse.urlencode(params, doseq=True)

    url = f"{GMAIL_API_BASE}/{endpoint.lstrip('/')}" + query
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
        raise GmailPushError(f"Gmail API {method} {endpoint} falló: {e.code} {detail}") from e
    except Exception as e:
        raise GmailPushError(f"Gmail API {method} {endpoint} falló: {e}") from e


def _decode_subject(msg):
    raw = msg.get("Subject", "") or ""
    try:
        decoded = str(email.header.make_header(email.header.decode_header(raw)))
        return decoded.strip()
    except Exception:
        return raw.strip()


def _extract_text(msg):
    texts = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            if ctype in {"text/plain", "text/html"}:
                try:
                    payload = part.get_content()
                except Exception:
                    payload = ""
                if payload:
                    texts.append(str(payload))
    else:
        try:
            payload = msg.get_content()
        except Exception:
            payload = ""
        if payload:
            texts.append(str(payload))

    full = "\n".join(texts)
    full = re.sub(r"<[^>]+>", " ", full)
    full = re.sub(r"\s+", " ", full).strip()
    return full


def _detectar_moneda(texto):
    texto_norm = normalizar_texto(texto)
    if "usd" in texto_norm or "dolar" in texto_norm or "dolares" in texto_norm or "$" in texto:
        return "USD"
    if "s/" in texto or "pen" in texto_norm or "soles" in texto_norm:
        return "PEN"
    return "PEN"


def _detectar_tipo(texto):
    texto_norm = normalizar_texto(texto)

    # Correos de Yape saliente: si el texto indica que realizaste el yapeo,
    # se registra como gasto porque representa una salida de dinero hacia un tercero.
    kw_yape_gasto = [
        "realizaste un yapeo",
        "yapeo a celular",
        "yapear a celular",
        "enviaste un yapeo",
        "yape enviado",
        "yapeo enviado",
    ]
    if any(kw in texto_norm for kw in kw_yape_gasto):
        return "Gasto"

    kw_transferencia = [
        "transferencia entre mis cuentas",
        "transferencia propia",
        "constancia de transferencia",
        "realizaste una transferencia",
        "realizaste un deposito",
        "realizaste un deposito en",
        "deposito en tu cuenta",
        "envio automatico",
        "pago de tarjeta propia",
    ]

    kw_ingreso = [
        "abono",
        "deposito",
        "transferencia recibida",
        "pago recibido",
        "acreditado",
        "ingreso",
        "te enviaron",
        "te depositaron",
    ]
    kw_gasto = [
        "cargo",
        "consumo",
        "compra",
        "debito",
        "retiro",
        "transferencia enviada",
        "pago realizado",
        "pago de servicios",
        "consumo tarjeta de credito",
        "yape",
        "yapear",
    ]

    if any(kw in texto_norm for kw in kw_transferencia):
        # Retorna tipo especial "Transferencia" para procesamiento posterior con cuenta
        return "Transferencia"

    score_ingreso = sum(1 for kw in kw_ingreso if kw in texto_norm)
    score_gasto = sum(1 for kw in kw_gasto if kw in texto_norm)

    if score_ingreso == 0 and score_gasto == 0:
        return ""
    if score_ingreso >= score_gasto:
        return "Ingreso"
    return "Gasto"


def _extraer_monto(texto):
    # 1) Priorizar montos explícitamente etiquetados (más robusto para correos HTML de BCP).
    patrones_prioritarios = [
        r"(?:monto\s*total|importe|monto\s*(?:pagado|enviado|transferido|del\s*consumo)?)\s*[:\-]?\s*(?:s/|pen|usd|us\$|\$)\s*([\d\.,]+)",
        r"(?:s/|pen|usd|us\$|\$)\s*([\d\.,]+)\s*(?:monto\s*total|importe)",
    ]
    for patron_lbl in patrones_prioritarios:
        m = re.search(patron_lbl, texto, flags=re.IGNORECASE)
        if m:
            val = parsear_numero(m.group(1))
            if val > 0:
                return round(val, 2)

    patron = re.compile(r"(?<!\d)(\d[\d\.,]{0,20}\d|\d)(?!\d)")
    candidatos = []

    for m in patron.finditer(texto):
        raw = m.group(1)
        # Evitar tomar como monto los últimos 4 dígitos de una cuenta/tarjeta.
        if re.fullmatch(r"\d{4}", raw):
            nearby = texto[max(0, m.start() - 30) : min(len(texto), m.end() + 30)].lower()
            if "****" in nearby or "cuenta" in nearby or "tarjeta" in nearby or "numero" in nearby:
                continue

        val = parsear_numero(raw)
        if val <= 0:
            continue

        if "." not in raw and "," not in raw and val > 999999:
            continue

        inicio = max(0, m.start() - 30)
        fin = min(len(texto), m.end() + 30)
        tramo = texto[inicio:fin]
        contexto = normalizar_texto(tramo)
        score = 0
        if any(k in contexto for k in ["monto", "importe", "total", "consumo", "cargo", "abono", "pago", "transferencia"]):
            score += 2
        if any(sym in tramo for sym in ["S/", "$", "PEN", "USD"]):
            score += 1
        if "." in raw or "," in raw:
            score += 1

        # Penalizar años/fechas para evitar falsos positivos como 2026.
        if re.fullmatch(r"\d{4}", raw):
            anio = int(raw)
            if 1900 <= anio <= 2100 and any(k in contexto for k in ["fecha", "vencimiento", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "setiembre", "septiembre", "octubre", "noviembre", "diciembre"]):
                score -= 4

        candidatos.append((score, val))

    if not candidatos:
        return 0.0

    candidatos.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return round(candidatos[0][1], 2)


def _detectar_cuenta(texto, nombres_cuentas, modo_estricto=False, tenant_id=None):
    """Detecta cuenta en el texto.
    
    Args:
        texto: Texto del email
        nombres_cuentas: Lista de nombres de cuenta válidos
        modo_estricto: Si True (Gmail Push), solo acepta últimos 4 dígitos.
                      Si False (Manual), también busca nombre de cuenta.
    
    Returns:
        Nombre de cuenta si encuentra con confianza, "" si no.
    """
    texto_norm = normalizar_texto(texto)
    
    # PRIORIDAD 1: Buscar últimos 4 dígitos (MÁS CONFIABLE)
    ultimos4 = re.findall(r"(?<!\d)(\d{4})(?!\d)", texto or "")
    for suf in ultimos4:
        cuenta_obj = detectar_cuenta_por_ultimos_digitos(suf, tenant_id=tenant_id)
        if cuenta_obj and cuenta_obj.get("Nombre"):
            return cuenta_obj["Nombre"]
    
    # Si modo estricto (Gmail Push), SOLO acepta últimos 4 dígitos
    # No adivinar por nombre de cuenta
    if modo_estricto:
        return ""
    
    # PRIORIDAD 2: Buscar nombre de cuenta en el texto (MENOS CONFIABLE)
    nombres_ordenados = sorted(nombres_cuentas, key=lambda c: len(str(c or "")), reverse=True)
    for nombre in nombres_ordenados:
        nombre_norm = normalizar_texto(nombre)
        if not nombre_norm:
            continue
        patron = rf"(^|\s){re.escape(nombre_norm)}(\s|$)"
        if re.search(patron, texto_norm):
            return nombre
    return ""


def _refinar_tipo_transferencia(texto, cuenta):
    """Si el tipo es 'Transferencia', refina a Ingreso o Gasto basado en la cuenta detectada."""
    texto_norm = normalizar_texto(texto)
    cuenta_norm = normalizar_texto(cuenta)
    
    # Buscar si la cuenta aparece en contexto "Enviado a" (destino = Ingreso)
    if re.search(rf"enviado\s+a.*{re.escape(cuenta_norm)}", texto_norm):
        return "Ingreso"
    
    # Buscar si la cuenta aparece en contexto "Desde" (origen = Gasto)
    if re.search(rf"desde.*{re.escape(cuenta_norm)}", texto_norm):
        return "Gasto"
    
    # Si no se puede determinar, por defecto Gasto (prudencia)
    return "Gasto"


def _base64url_decode(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    padding = b"=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _parsear_mensaje_rfc822(raw_bytes, fallback_message_id="", tenant_id=None):
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)
    subject = _decode_subject(msg)
    body = _extract_text(msg)
    texto = f"{subject} {body}".strip()

    from_header = (msg.get("From", "") or "").strip()
    sender_email = _extraer_correo_emisor(from_header)
    if not _remitente_permitido(sender_email):
        _log_descarte_gmail_push(
            "remitente_no_permitido",
            sender=sender_email or "—",
            from_header=from_header or "—",
            subject=subject[:120] if subject else "—",
        )
        return None

    # FILTRO: Rechazar notificaciones sin valor transaccional
    kw_notificaciones = [
        "constancia de configuracion",
        "aviso de seguridad",
        "cambio de contrasena",
        "confirmacion de identidad",
        "verificacion de cuenta",
        "autenticacion requerida",
        "actualizacion de datos",
        "cambio de datos",
        "confirmacion de cambios",
        "cambios realizados",
        "configuracion realizada",
    ]
    texto_norm = normalizar_texto(texto)
    if any(kw in texto_norm for kw in kw_notificaciones):
        _log_descarte_gmail_push(
            "notificacion_sin_valor",
            sender=sender_email or "—",
            subject=subject[:120] if subject else "—",
        )
        return None

    tipo = _detectar_tipo(texto)
    if not tipo:
        _log_descarte_gmail_push(
            "tipo_no_detectado",
            sender=sender_email or "—",
            subject=subject[:120] if subject else "—",
        )
        return None

    monto = _extraer_monto(texto)
    if monto <= 0:
        _log_descarte_gmail_push(
            "monto_no_detectado",
            sender=sender_email or "—",
            subject=subject[:120] if subject else "—",
        )
        return None

    cuenta = _detectar_cuenta(
        texto,
        obtener_nombres_cuentas(tenant_id=tenant_id),
        modo_estricto=True,
        tenant_id=tenant_id,
    )
    if not cuenta:
        _log_descarte_gmail_push(
            "cuenta_no_detectada",
            sender=sender_email or "—",
            subject=subject[:120] if subject else "—",
        )
        return None

    texto_norm = normalizar_texto(texto)
    observacion_extra = f"From={from_header}; Date={msg.get('Date', '') or ''}"[:250]

    if "pago de tarjeta propia" in texto_norm or "constancia de pago de tarjeta" in texto_norm:
        raw_html = ""
        try:
            html_part = msg.get_body(preferencelist=("html",))
            if html_part is not None:
                raw_html = html_part.get_content() or ""
        except Exception:
            raw_html = ""

        source_text = raw_html or texto
        origen_match = re.search(
            r"Desde</td>\s*<td[^>]*>\s*<b>([^<]+)</b><br>\*{4}\s*(\d{4})",
            source_text,
            re.IGNORECASE | re.DOTALL,
        )
        destino_match = re.search(
            r"Pagado a</td>\s*<td[^>]*>\s*<b>([^<]+)</b><br>\*{4}\s*(\d{4})",
            source_text,
            re.IGNORECASE | re.DOTALL,
        )
        origen_nombre = ""
        destino_nombre = ""
        origen_ult4 = ""
        destino_ult4 = ""

        if origen_match:
            origen_nombre = origen_match.group(1).strip()
            origen_ult4 = origen_match.group(2).strip()
            origen_cuenta = detectar_cuenta_por_ultimos_digitos(origen_ult4, tenant_id=tenant_id)
            if origen_cuenta and origen_cuenta.get("Nombre"):
                cuenta = origen_cuenta["Nombre"]
                origen_nombre = origen_cuenta["Nombre"]
            elif origen_nombre:
                cuenta = origen_nombre

        if destino_match:
            destino_nombre = destino_match.group(1).strip()
            destino_ult4 = destino_match.group(2).strip()
            destino_cuenta = detectar_cuenta_por_ultimos_digitos(destino_ult4, tenant_id=tenant_id)
            if destino_cuenta and destino_cuenta.get("Nombre"):
                destino_nombre = destino_cuenta["Nombre"]

        observacion_extra = (
            f"PAGO_TARJETA_PROPIA|origen={origen_nombre or cuenta}|destino={destino_nombre}|"
            f"origen4={origen_ult4}|destino4={destino_ult4}|{observacion_extra}"
        )[:250]

    if tipo == "Transferencia":
        tipo = _refinar_tipo_transferencia(texto, cuenta)

    moneda = _detectar_moneda(texto)
    mensaje_id = (msg.get("Message-ID", "") or "").strip().strip("<>")
    referencia_base = mensaje_id or fallback_message_id or subject or f"{cuenta}|{monto:.2f}|{moneda}"
    referencia = f"gmail:{referencia_base}"

    fecha_header = msg.get("Date", "") or ""
    fecha_iso = ""
    if fecha_header:
        try:
            fecha_iso = parsedate_to_datetime(fecha_header).isoformat()
        except Exception:
            fecha_iso = fecha_header

    return {
        "tipo": tipo,
        "monto": monto,
        "cuenta": cuenta,
        "moneda": moneda,
        "descripcion": subject[:140] if subject else "Movimiento detectado por Gmail Push",
        "referencia": referencia,
        "fuente": "GmailPush",
        "confianza": "alta" if sender_email else "media",
        "observacion": observacion_extra,
        "sender_email": sender_email,
    }



def _obtener_mensajes_desde_historial(start_history_id, tenant_id=None):
    mensajes = []
    page_token = None
    current_history_id = None
    params = {
        "startHistoryId": str(start_history_id),
        "historyTypes": "messageAdded",
        "maxResults": 500,
    }

    while True:
        if page_token:
            params["pageToken"] = page_token
        elif "pageToken" in params:
            params.pop("pageToken", None)

        data = _gmail_api_request("GET", "users/me/history", params=params, tenant_id=tenant_id)
        current_history_id = str(data.get("historyId", current_history_id or start_history_id))
        for history_item in data.get("history", []) or []:
            for added in history_item.get("messagesAdded", []) or []:
                message = added.get("message", {}) or {}
                message_id = message.get("id")
                if message_id:
                    mensajes.append(str(message_id))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    # Mantener solo ids únicos en orden.
    vistos = set()
    salida = []
    for item in mensajes:
        if item not in vistos:
            vistos.add(item)
            salida.append(item)

    return salida, current_history_id


def iniciar_watch_gmail(force=False, tenant_id=None):
    if not config.GMAIL_PUSH_ENABLED:
        raise GmailPushError("La ingesta Gmail Push está desactivada. Activa GMAIL_PUSH_ENABLED=true.")
    if not config.GMAIL_PUSH_TOPIC_NAME:
        raise GmailPushError("Falta GMAIL_PUSH_TOPIC_NAME para registrar el watch.")

    estado = obtener_estado_gmail_push(tenant_id=tenant_id)
    if not force:
        expiracion = estado.get("watch_expiration", "")
        if expiracion:
            try:
                exp_dt = datetime.fromisoformat(expiracion)
                if exp_dt > datetime.utcnow() + timedelta(hours=config.GMAIL_WATCH_RENEW_BUFFER_HOURS):
                    return {"watch_active": True, "expiration": expiracion, "historyId": estado.get("last_history_id", "")}
            except Exception:
                pass

    body = {"topicName": config.GMAIL_PUSH_TOPIC_NAME}
    if config.GMAIL_WATCH_LABEL_IDS:
        body["labelIds"] = config.GMAIL_WATCH_LABEL_IDS
        body["labelFilterAction"] = "include"

    response = _gmail_api_request("POST", "users/me/watch", body=body, tenant_id=tenant_id)
    history_id = str(response.get("historyId", "")).strip()
    expiration = str(response.get("expiration", "")).strip()

    guardar_estado_gmail_push(
        tenant_id=tenant_id,
        last_history_id=history_id,
        watch_expiration=expiration,
        watch_email=config.GMAIL_USER_EMAIL or "",
        watch_topic=config.GMAIL_PUSH_TOPIC_NAME,
        watch_updated_at=datetime.utcnow().isoformat(),
    )

    return response


def renovar_watch_si_necesario(force=False, tenant_id=None):
    return iniciar_watch_gmail(force=force, tenant_id=tenant_id)


async def procesar_notificacion_gmail_push(envelope):
    return await asyncio.to_thread(_procesar_notificacion_gmail_push_sync, envelope)


def _procesar_notificacion_gmail_push_sync(envelope):
    if not config.GMAIL_PUSH_ENABLED:
        logger.warning("Gmail Push ignorado porque está deshabilitado en configuración.")
        return {"registrados": 0, "duplicados": 0, "omitidos": 0, "errores": 0, "detalle": "push deshabilitado"}

    message = envelope.get("message", {}) or {}
    data = message.get("data", "")
    if not data:
        logger.warning("Notificación Pub/Sub sin payload message.data; se descarta.")
        raise GmailPushError("Notificación Pub/Sub sin payload message.data.")

    payload_raw = _base64url_decode(data)
    payload = json.loads(payload_raw.decode("utf-8"))
    notification_history_id = str(payload.get("historyId", "")).strip()
    notification_email = str(payload.get("emailAddress", "")).strip()

    tenant_id = resolver_tenant_gmail_por_email(notification_email)
    if not tenant_id and config.GMAIL_USER_EMAIL and notification_email and _normalizar_correo(notification_email) == _normalizar_correo(config.GMAIL_USER_EMAIL):
        tenant_id = config.SYSTEM_TENANT_ID

    if not tenant_id:
        logger.warning(
            "Notificación Gmail descartada porque no se pudo resolver tenant | notification_email=%s",
            notification_email or "—",
        )
        return {"registrados": 0, "duplicados": 0, "omitidos": 0, "errores": 1, "detalle": "tenant no resuelto"}

    estado = obtener_estado_gmail_push(tenant_id=tenant_id)
    watch_email = str(estado.get("watch_email", "")).strip()
    if watch_email and notification_email and _normalizar_correo(notification_email) != _normalizar_correo(watch_email):
        logger.info(
            "Notificación Gmail descartada por email distinto | notification_email=%s expected=%s",
            notification_email,
            watch_email,
        )
        return {"registrados": 0, "duplicados": 0, "omitidos": 0, "errores": 0, "detalle": "email distinto"}

    last_history_id = str(estado.get("last_history_id", "")).strip()
    if not last_history_id:
        logger.warning(
            "Notificación Gmail descartada porque no existe history inicial | notification_history_id=%s",
            notification_history_id or "—",
        )
        guardar_estado_gmail_push(tenant_id=tenant_id, last_history_id=notification_history_id or "", last_push_at=datetime.utcnow().isoformat())
        return {"registrados": 0, "duplicados": 0, "omitidos": 0, "errores": 0, "detalle": "sin history inicial"}

    try:
        if notification_history_id and int(notification_history_id) <= int(last_history_id):
            logger.info(
                "Notificación Gmail descartada por ser antigua | notification_history_id=%s last_history_id=%s",
                notification_history_id,
                last_history_id,
            )
            return {"registrados": 0, "duplicados": 0, "omitidos": 0, "errores": 0, "detalle": "notificacion vieja"}
    except ValueError:
        pass

    mensajes, current_history_id = _obtener_mensajes_desde_historial(last_history_id, tenant_id=tenant_id)
    stats = {"registrados": 0, "duplicados": 0, "omitidos": 0, "errores": 0, "tenant_id": tenant_id}
    nuevos_ids = []

    for message_id in mensajes:
        try:
            message_data = _gmail_api_request(
                "GET",
                f"users/me/messages/{message_id}",
                params={"format": "raw"},
                tenant_id=tenant_id,
            )
            raw = message_data.get("raw", "")
            if not raw:
                logger.warning("Mensaje Gmail %s descartado porque no trae raw.", message_id)
                stats["omitidos"] += 1
                continue

            parsed = _parsear_mensaje_rfc822(_base64url_decode(raw), fallback_message_id=message_id, tenant_id=tenant_id)
            if not parsed:
                logger.info("Mensaje Gmail %s descartado tras parseo y filtros.", message_id)
                stats["omitidos"] += 1
                continue

            is_dup = existe_movimiento_pendiente_duplicado(
                referencia=parsed["referencia"],
                cuenta=parsed["cuenta"],
                tipo=parsed["tipo"],
                monto=parsed["monto"],
                moneda=parsed["moneda"],
                tenant_id=tenant_id,
            )
            if is_dup:
                logger.info(
                    "Mensaje Gmail %s descartado por duplicado | referencia=%s cuenta=%s tipo=%s monto=%s moneda=%s",
                    message_id,
                    parsed["referencia"],
                    parsed["cuenta"],
                    parsed["tipo"],
                    parsed["monto"],
                    parsed["moneda"],
                )
                stats["duplicados"] += 1
                continue

            pend_id = registrar_movimiento_pendiente(
                tipo=parsed["tipo"],
                monto=parsed["monto"],
                cuenta=parsed["cuenta"],
                descripcion=parsed["descripcion"],
                fuente=parsed["fuente"],
                moneda=parsed["moneda"],
                referencia=parsed["referencia"],
                confianza=parsed["confianza"],
                observacion=parsed["observacion"],
                tenant_id=tenant_id,
            )
            nuevos_ids.append(pend_id)
            stats["registrados"] += 1
        except GmailPushError as e:
            error_txt = str(e)
            if "404" in error_txt and "not found" in error_txt.lower():
                logger.info(
                    "Mensaje Gmail %s omitido porque Gmail API ya no lo encuentra | error=%s",
                    message_id,
                    error_txt,
                )
                stats["omitidos"] += 1
                continue

            logger.error("Error procesando mensaje Gmail %s: %s", message_id, e)
            stats["errores"] += 1
        except Exception as e:
            logger.error("Error procesando mensaje Gmail %s: %s", message_id, e)
            stats["errores"] += 1

    guardar_estado_gmail_push(
        tenant_id=tenant_id,
        last_history_id=current_history_id or notification_history_id or last_history_id,
        last_push_at=datetime.utcnow().isoformat(),
        last_push_message_count=len(mensajes),
    )

    stats["nuevos_ids"] = nuevos_ids
    stats["history_id"] = current_history_id or notification_history_id or last_history_id
    stats["tenant_id"] = tenant_id
    return stats


def obtener_estado_gmail_push_resumido(tenant_id=None):
    estado = obtener_estado_gmail_push(tenant_id=tenant_id)
    return {
        "last_history_id": estado.get("last_history_id", ""),
        "watch_expiration": estado.get("watch_expiration", ""),
        "watch_email": estado.get("watch_email", ""),
        "watch_topic": estado.get("watch_topic", ""),
        "last_push_at": estado.get("last_push_at", ""),
        "last_push_message_count": estado.get("last_push_message_count", ""),
    }
