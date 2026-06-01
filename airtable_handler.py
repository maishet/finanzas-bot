from datetime import datetime
from zoneinfo import ZoneInfo
import os
import calendar
import unicodedata
import re
import config
import logging

from airtable_backend import api as airtable_api, sheet, WorksheetNotFound

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

trans_ws = sheet.worksheet("Transacciones")
cuentas_ws = sheet.worksheet("Cuentas")
categorias_ws = sheet.worksheet("Categorias")
deudas_ws = sheet.worksheet("Deudas")


def _asegurar_hoja_pendientes():
    """Obtiene o crea la hoja MovimientosPendientes con cabeceras estándar."""
    try:
        ws = sheet.worksheet("MovimientosPendientes")
    except WorksheetNotFound:
        ws = sheet.add_worksheet(title="MovimientosPendientes", rows=1000, cols=20)
        ws.append_row(
            [
                "ID",
                "FechaDetectada",
                "Fuente",
                "Cuenta",
                "Tipo",
                "Monto",
                "Moneda",
                "Descripcion",
                "Referencia",
                "Estado",
                "Confianza",
                "TXID",
                "FechaResolucion",
                "Observacion",
            ],
            value_input_option="RAW",
        )
    return ws


pend_ws = _asegurar_hoja_pendientes()


def _asegurar_hoja_gmail_estado():
    """Obtiene o crea la hoja GmailEstado para persistir historyId y watch."""
    try:
        ws = sheet.worksheet("GmailEstado")
    except WorksheetNotFound:
        ws = sheet.add_worksheet(title="GmailEstado", rows=100, cols=10)
        ws.append_row(["Clave", "Valor", "ActualizadoEn"], value_input_option="RAW")
    return ws


gmail_estado_ws = _asegurar_hoja_gmail_estado()


def _asegurar_hoja_snapshots():
    """Obtiene o crea la hoja SaldosHistoricos para snapshots diarios."""
    try:
        ws = sheet.worksheet("SaldosHistoricos")
    except WorksheetNotFound:
        ws = sheet.add_worksheet(title="SaldosHistoricos", rows=2000, cols=20)
        ws.append_row(
            [
                "SnapshotID",
                "FechaHora",
                "Cuenta",
                "TipoCuenta",
                "Moneda",
                "Saldo",
                "SaldoPEN",
                "Origen",
            ],
            value_input_option="RAW",
        )
    return ws


snap_ws = _asegurar_hoja_snapshots()

_SHEET_CACHE = {}
_CACHE_TTL_SECONDS = 10


def _cache_get(key):
    entry = _SHEET_CACHE.get(key)
    if not entry:
        return None
    timestamp, value = entry
    if (get_now() - timestamp).total_seconds() > _CACHE_TTL_SECONDS:
        _SHEET_CACHE.pop(key, None)
        return None
    return value


def _cache_set(key, value):
    _SHEET_CACHE[key] = (get_now(), value)
    return value


def _cache_invalidate(*keys):
    if not keys:
        _SHEET_CACHE.clear()
        return
    for key in keys:
        _SHEET_CACHE.pop(key, None)


def _leer_records_cacheados(worksheet, cache_key):
    valor = _cache_get(cache_key)
    if valor is not None:
        return valor

    return _cache_set(cache_key, worksheet.get_all_records())


def _leer_values_cacheados(worksheet, cache_key):
    valor = _cache_get(cache_key)
    if valor is not None:
        return valor
    return _cache_set(cache_key, worksheet.get_all_values())


def _leer_registros_cacheados_formateado(nombre_hoja, cache_key):
    """Lee registros de una hoja con FORMATTED_VALUE y cachea el resultado."""
    valor = _cache_get(cache_key)
    if valor is not None:
        return valor
    # Leer directamente de Airtable con FORMATTED_VALUE
    registros = _leer_registros_formateado(nombre_hoja)
    return _cache_set(cache_key, registros)


def _columna_a_indice(col_str):
    """Convierte "A" → 0, "B" → 1, "Z" → 25, "AA" → 26, "AB" → 27, etc."""
    col_str = col_str.upper()
    indice = 0
    for char in col_str:
        indice = indice * 26 + (ord(char) - ord('A') + 1)
    return indice - 1

def _leer_rango_formateado(nombre_hoja, rango):
    """Compatibilidad con el código existente: devuelve un rango de valores desde Airtable."""
    try:
        ws = sheet.worksheet(nombre_hoja)
        valores = ws.get_all_values()
        if not valores or ":" not in rango:
            return []
        inicio, fin = rango.split(":")
        col_inicio_str = ''.join(c for c in inicio if c.isalpha())
        fila_inicio = int(''.join(c for c in inicio if c.isdigit())) - 1
        col_fin_str = ''.join(c for c in fin if c.isalpha())
        fila_fin = int(''.join(c for c in fin if c.isdigit()))
        col_inicio = _columna_a_indice(col_inicio_str)
        col_fin = _columna_a_indice(col_fin_str) + 1
        resultado = []
        for fila_idx in range(fila_inicio, min(fila_fin, len(valores))):
            fila = valores[fila_idx]
            resultado.append(fila[col_inicio:col_fin])
        return resultado
    except Exception as e:
        logger.error(f"Error crítico leyendo {nombre_hoja}!{rango}: {e}")
        return []


def _leer_celda_formateada(nombre_hoja, celda):
    """Compatibilidad con el código existente: lee una celda desde Airtable."""
    try:
        ws = sheet.worksheet(nombre_hoja)
        return ws.acell(celda).value
    except Exception as e:
        logger.error(f"Error crítico leyendo celda {nombre_hoja}!{celda}: {e}")
        return None


def _leer_registros_formateado(nombre_hoja):
    """Lee TODOS los registros de una hoja con FORMATTED_VALUE (preserva formato regional de números).
    Retorna lista de dicts con keys del encabezado (fila 1)."""
    try:
        # Leer cabecera (fila 1) sin FORMATTED_VALUE (no debe tener números)
        headers_raw = sheet.worksheet(nombre_hoja).row_values(1)
        if not headers_raw:
            return []
        
        # Leer todos los datos (desde fila 2) con FORMATTED_VALUE
        valores_formateados = _leer_rango_formateado(nombre_hoja, f"A2:Z1000")
        
        resultado = []
        for idx, fila in enumerate(valores_formateados, start=2):
            if not fila or not any(fila):  # Saltear filas vacías
                continue
            
            # Crear dict mapeando headers con valores
            registro = {}
            for i, header in enumerate(headers_raw):
                if i < len(fila):
                    registro[header] = str(fila[i]).strip() if fila[i] else ""
                else:
                    registro[header] = ""
            
            # Solo agregar si hay al menos un valor significativo
            if any(registro.values()):
                resultado.append(registro)
        
        return resultado
    except Exception as e:
        logger.error(f"Error en _leer_registros_formateado({nombre_hoja}): {e}")
        return []

# ---------- FUNCIONES DE NORMALIZACIÓN ----------
def normalizar_texto(texto):
    """
    Elimina tildes, convierte a minúsculas y quita caracteres especiales.
    Ej: 'Alimentación' -> 'alimentacion'
    """
    if not texto:
        return ""
    texto = texto.lower().strip()
    # Descomponer caracteres unicode (NFD) y eliminar marcas diacríticas
    texto = unicodedata.normalize('NFD', texto)
    texto = texto.encode('ascii', 'ignore').decode('utf-8')
    return texto

def parsear_numero(valor):
    """Convierte valores tipo '1.314,13' o '1314.13' a float."""
    if isinstance(valor, (int, float)):
        return float(valor)

    txt = str(valor or "").strip().replace(" ", "")
    if not txt:
        return 0.0

    # Mantener solo dígitos y separadores comunes.
    txt = re.sub(r"[^0-9,.-]", "", txt)
    if not txt or txt in ["-", ".", ","]:
        return 0.0

    # Caso con ambos separadores.
    if "," in txt and "." in txt:
        if txt.rfind(",") > txt.rfind("."):
            # Formato latam: 1.234,56
            txt = txt.replace(".", "").replace(",", ".")
        else:
            # Formato en-US: 1,234.56
            txt = txt.replace(",", "")
    elif "," in txt:
        # Solo coma: decimal o miles
        if re.fullmatch(r"-?\d{1,3}(,\d{3})+", txt):
            txt = txt.replace(",", "")
        else:
            txt = txt.replace(",", ".")
    elif "." in txt:
        # Solo punto: decimal o miles (latam formateado)
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", txt):
            txt = txt.replace(".", "")

    try:
        return float(txt)
    except ValueError:
        logger.warning(f"No se pudo parsear número '{valor}'. Se usará 0.0")
        return 0.0


def _get_tz_name():
    # Preferir la configuración en config, luego variable de entorno
    try:
        return getattr(config, "TIMEZONE", os.getenv("TIMEZONE", "America/Lima"))
    except Exception:
        return os.getenv("TIMEZONE", "America/Lima")


def get_now(tz_name=None):
    """Devuelve datetime.now() con la zona horaria configurada (IANA)."""
    name = tz_name or _get_tz_name() or "America/Lima"
    try:
        tz = ZoneInfo(name)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


def now_str(fmt="%Y-%m-%d %H:%M:%S", tz_name=None):
    return get_now(tz_name).strftime(fmt)

def parsear_fecha(valor):
    """Intenta parsear fechas en formatos frecuentes de la hoja/Airtable."""
    if isinstance(valor, datetime):
        return valor

    txt = str(valor or "").strip()
    if not txt:
        return None

    # 1) ISO 8601 (Airtable DateTime suele devolver algo como 2026-05-25T14:30:00.000Z)
    try:
        iso_txt = txt.replace("Z", "+00:00")
        return datetime.fromisoformat(iso_txt)
    except Exception:
        pass

    # 2) Formatos legacy/manuales
    formatos = [
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%d-%m-%Y",
    ]
    for fmt in formatos:
        try:
            return datetime.strptime(txt, fmt)
        except ValueError:
            continue
    return None


def avanzar_un_mes(fecha_base):
    """Avanza una fecha un mes, conservando día cuando sea posible."""
    if fecha_base is None:
        fecha_base = get_now()

    if fecha_base.month == 12:
        nuevo_mes = 1
        nuevo_anio = fecha_base.year + 1
    else:
        nuevo_mes = fecha_base.month + 1
        nuevo_anio = fecha_base.year

    ultimo_dia = calendar.monthrange(nuevo_anio, nuevo_mes)[1]
    nuevo_dia = min(fecha_base.day, ultimo_dia)
    return fecha_base.replace(year=nuevo_anio, month=nuevo_mes, day=nuevo_dia)

def convertir_moneda(monto, moneda_origen, moneda_destino):
    """Convierte entre PEN y USD usando EXCHANGE_RATE."""
    origen = (moneda_origen or "PEN").upper()
    destino = (moneda_destino or "PEN").upper()

    if origen == destino:
        return monto
    if origen == "USD" and destino == "PEN":
        return monto * config.EXCHANGE_RATE
    if origen == "PEN" and destino == "USD":
        return monto / config.EXCHANGE_RATE
    raise ValueError(f"Conversión de moneda no soportada: {origen} -> {destino}")

# ---------- FUNCIONES BÁSICAS ----------
def obtener_siguiente_id(worksheet, prefix="TX"):
    """Devuelve el siguiente correlativo basado en el máximo ID existente, no en la última fila."""
    try:
        col_a = worksheet.col_values(1)
        if len(col_a) <= 1:
            return 1

        max_num = 0
        pref = str(prefix or "").upper()
        for raw in col_a[1:]:
            txt = str(raw or "").strip().upper()
            if not txt:
                continue
            if pref:
                if not txt.startswith(pref):
                    continue
                txt = txt[len(pref):]
            if txt.isdigit():
                max_num = max(max_num, int(txt))

        if max_num > 0:
            return max_num + 1

        # Fallback legacy: correlativo por cantidad de filas con datos
        data_rows = sum(1 for v in col_a[1:] if str(v or "").strip())
        return max(1, data_rows + 1)
    except Exception as e:
        logger.error(f"Error obteniendo siguiente ID: {e}")
        try:
            col_a = worksheet.col_values(1)
            data_rows = sum(1 for v in col_a[1:] if str(v or "").strip())
            return max(1, data_rows + 1)
        except Exception:
            return 1

def convertir_a_pen(monto, moneda):
    if moneda.upper() == "PEN":
        return monto
    elif moneda.upper() == "USD":
        return monto * config.EXCHANGE_RATE
    else:
        raise ValueError(f"Moneda no soportada: {moneda}")


def _metodo_por_cuenta(nombre_cuenta):
    tipo = normalizar_texto(obtener_tipo_cuenta(nombre_cuenta) or "")
    if tipo in ["credito", "debito"]:
        return "Tarjeta de crédito"
    if tipo == "banco":
        return "Transferencia"
    return "Efectivo"


def _metodo_compatible_airtable(metodo):
    """Ajusta el método al catálogo real del single select 'Transacciones.Método'."""
    try:
        meta = airtable_api.table_meta("Transacciones") or {}
        fields = meta.get("fields", [])
        metodo_field = next((f for f in fields if f.get("name") == "Método"), None)
        choices = [c.get("name", "") for c in (metodo_field or {}).get("options", {}).get("choices", []) if c.get("name")]
    except Exception:
        choices = []

    metodo_txt = str(metodo or "").strip()
    if not choices:
        return metodo_txt or "Transferencia"

    # Match exacto
    if metodo_txt in choices:
        return metodo_txt

    # Match normalizado (sin acentos / casefold)
    metodo_norm = normalizar_texto(metodo_txt)
    for c in choices:
        if normalizar_texto(c) == metodo_norm:
            return c

    # Sinónimos útiles
    candidatos = []
    if metodo_norm in ["tarjeta de credito", "tarjeta de debito", "efectivo"]:
        candidatos = ["Tarjeta de crédito", "Transferencia", "Efectivo"]
    elif metodo_norm == "transferencia":
        candidatos = ["Transferencia"]

    for cand in candidatos:
        for c in choices:
            if normalizar_texto(c) == normalizar_texto(cand):
                return c

    # Fallback seguro: primera opción disponible
    return choices[0]


def _siguiente_id_pendiente():
    next_num = obtener_siguiente_id(pend_ws, prefix="MP")
    return f"MP{int(next_num):05d}"


def registrar_movimiento_pendiente(
    tipo,
    monto,
    cuenta,
    descripcion="",
    fuente="Manual",
    moneda="PEN",
    referencia="",
    confianza="",
    observacion="",
):
    """Registra un movimiento detectado para confirmación posterior."""
    tipo_norm = normalizar_texto(tipo)
    if tipo_norm not in ["ingreso", "gasto"]:
        raise ValueError("Tipo inválido. Usa Ingreso o Gasto.")

    monto_num = parsear_numero(monto)
    if monto_num <= 0:
        raise ValueError("El monto pendiente debe ser mayor a 0.")

    cuenta_info = obtener_cuenta_por_nombre(cuenta)
    if not cuenta_info:
        raise ValueError(f"Cuenta '{cuenta}' no existe.")

    pend_id = _siguiente_id_pendiente()
    fecha_detectada = get_now().isoformat(timespec="seconds")

    fields = {
        "ID": pend_id,
        "FechaDetectada": fecha_detectada,
        "Fuente": str(fuente or "Manual").strip(),
        "Cuenta": cuenta_info["Nombre"],
        "Tipo": "Ingreso" if tipo_norm == "ingreso" else "Gasto",
        "Monto": round(float(monto_num), 2),
        "Moneda": (moneda or "PEN").upper(),
        "Descripcion": descripcion or "",
        "Referencia": referencia or "",
        "Estado": "Pendiente",
    }

    if str(confianza).strip() != "":
        fields["Confianza"] = parsear_numero(confianza)
    if str(observacion).strip():
        fields["Observacion"] = str(observacion).strip()

    airtable_api.create_record("MovimientosPendientes", fields)
    _cache_invalidate("pendientes_values")
    return pend_id


def listar_movimientos_pendientes(limit=20, include_resueltos=False):
    valores = _leer_values_cacheados(pend_ws, "pendientes_values")
    if not valores or len(valores) <= 1:
        return []

    headers = valores[0]
    filas = [dict(zip(headers, f)) for f in valores[1:] if any(str(c).strip() for c in f)]
    if include_resueltos:
        filas.reverse()
        return filas[: max(1, int(limit))]

    pendientes = [f for f in filas if normalizar_texto(f.get("Estado", "")) == "pendiente"]
    pendientes.reverse()
    return pendientes[: max(1, int(limit))]


def existe_movimiento_pendiente_duplicado(referencia="", cuenta="", tipo="", monto=0, moneda="PEN", limit=500):
    """Detecta duplicados por referencia exacta o por similitud cuenta/tipo/monto."""
    rows = listar_movimientos_pendientes(limit=limit, include_resueltos=True)
    if not rows:
        return False

    referencia_norm = str(referencia or "").strip().lower()
    cuenta_norm = normalizar_texto(cuenta)
    tipo_norm = normalizar_texto(tipo)
    monto_pen = convertir_a_pen(parsear_numero(monto), moneda)

    for r in rows:
        ref_row = str(r.get("Referencia", "")).strip().lower()
        if referencia_norm and ref_row == referencia_norm:
            return True

        if not (cuenta_norm and tipo_norm):
            continue

        if normalizar_texto(r.get("Cuenta", "")) != cuenta_norm:
            continue
        if normalizar_texto(r.get("Tipo", "")) != tipo_norm:
            continue

        try:
            monto_row_pen = convertir_a_pen(
                parsear_numero(r.get("Monto", 0)),
                str(r.get("Moneda", "PEN")).upper(),
            )
        except ValueError:
            continue

        if abs(monto_row_pen - monto_pen) <= 0.01:
            return True

    return False


def _buscar_pendiente_por_id(pendiente_id):
    pid = str(pendiente_id or "").strip().upper()
    if not pid:
        return None

    valores = _leer_values_cacheados(pend_ws, "pendientes_values")
    if not valores or len(valores) <= 1:
        return None

    headers = valores[0]
    for i, fila in enumerate(valores[1:], start=2):
        reg = dict(zip(headers, fila))
        if str(reg.get("ID", "")).strip().upper() == pid:
            reg["_row"] = i
            return reg
    return None


def _extraer_deuda_id_desde_texto(*textos):
    """Extrae un posible ID de deuda desde textos libres.
    Soporta formatos como: deuda:12, deuda=12, id deuda 12, D12."""
    patrones = [
        r"\bdeuda\s*[:=#-]?\s*([dD]?\d{1,9})\b",
        r"\bid\s*deuda\s*[:=#-]?\s*([dD]?\d{1,9})\b",
        r"\b([dD]\d{1,9})\b",
    ]
    for texto in textos:
        t = str(texto or "")
        if not t:
            continue
        for patron in patrones:
            m = re.search(patron, t, re.IGNORECASE)
            if not m:
                continue
            raw = str(m.group(1) or "").strip()
            raw = raw[1:] if raw.lower().startswith("d") else raw
            if raw.isdigit():
                return raw
    return ""


def _rankear_deudas_servicio(cuenta_banco, monto, moneda, *textos):
    """Retorna candidatas de deuda Servicio rankeadas por match de descripción + monto exacto.

    Reglas duras:
    - Misma CuentaAsociada
    - Tipo Servicio
    - Estado activa/vencida
    - El monto del pendiente debe calzar EXACTO con lo pendiente de la deuda (±0.01 por redondeo)

    Priorización:
    - Mayor solapamiento entre descripción de la deuda y el contexto del pendiente
    - Vencimiento más cercano
    """
    cuenta_norm = normalizar_texto(cuenta_banco)
    if not cuenta_norm:
        return []

    try:
        monto_num = parsear_numero(monto)
        if monto_num <= 0:
            return []
    except Exception:
        return []

    contexto = normalizar_texto(" | ".join([str(t or "") for t in textos]))
    contexto_tokens = set(re.findall(r"[a-z0-9]{4,}", contexto))

    deudas = obtener_deudas_con_fila()
    candidatos = []
    for d in deudas:
        if normalizar_texto(d.get("Tipo", "")) != "servicio":
            continue
        if normalizar_texto(d.get("CuentaAsociada", "")) != cuenta_norm:
            continue

        estado = normalizar_texto(d.get("Estado", ""))
        if estado not in {"activa", "vencida"}:
            continue

        total = parsear_numero(d.get("MontoTotal", 0))
        pagado = parsear_numero(d.get("MontoPagado", 0))
        pendiente = round(total - pagado, 2)
        if pendiente <= 0:
            continue

        moneda_deuda = str(d.get("Moneda", "PEN")).upper()
        try:
            pago_en_moneda_deuda = round(convertir_moneda(monto_num, moneda, moneda_deuda), 2)
        except Exception:
            continue

        # Regla de negocio: en servicios el pago debe ser exacto.
        if abs(pago_en_moneda_deuda - pendiente) > 0.01:
            continue

        desc_norm = normalizar_texto(d.get("Descripcion", ""))
        desc_tokens = set(re.findall(r"[a-z0-9]{4,}", desc_norm))
        overlap = len(desc_tokens.intersection(contexto_tokens)) if desc_tokens and contexto_tokens else 0

        # Score principal por solapamiento semántico con la descripción en Airtable.
        score = overlap

        fecha_venc = parsear_fecha(d.get("FechaVencimiento"))
        fecha_ord = fecha_venc.date().toordinal() if fecha_venc else 9999999
        candidatos.append((score, fecha_ord, 0.0, d, pago_en_moneda_deuda, pendiente))

    candidatos.sort(key=lambda x: (-x[0], x[1]))
    return candidatos


def obtener_candidatas_deuda_servicio_para_pendiente(pendiente_obj, max_items=3):
    if not pendiente_obj:
        return []
    cuenta = str(pendiente_obj.get("Cuenta", "") or "").strip()
    monto = pendiente_obj.get("Monto", 0)
    moneda = str(pendiente_obj.get("Moneda", "PEN") or "PEN").upper()
    descripcion = str(pendiente_obj.get("Descripcion", "") or "")
    referencia = str(pendiente_obj.get("Referencia", "") or "")
    observacion = str(pendiente_obj.get("Observacion", "") or "")

    candidatos = _rankear_deudas_servicio(cuenta, monto, moneda, descripcion, referencia, observacion)
    salida = []
    for score, _, _, d, pago_conv, pendiente in candidatos[: max(1, int(max_items))]:
        salida.append({
            "id": str(d.get("ID", "")).strip(),
            "descripcion": str(d.get("Descripcion", "") or ""),
            "moneda": str(d.get("Moneda", "PEN") or "PEN").upper(),
            "pendiente": round(float(pendiente), 2),
            "pago_convertido": round(float(pago_conv), 2),
            "score": round(float(score), 2),
        })
    return salida


def _buscar_deuda_servicio_por_contexto(cuenta_banco, monto, moneda, *textos):
    """Intenta detectar automáticamente deuda de tipo Servicio a partir del contexto.

    Regla adicional anti-falsos-positivos:
    - Solo auto-confirma si hay al menos 1 token compartido entre
      contexto del pendiente y descripción de la deuda en Airtable (score >= 1).
    """
    candidatos = _rankear_deudas_servicio(cuenta_banco, monto, moneda, *textos)
    if not candidatos:
        return None

    top_score = candidatos[0][0]
    if top_score < 1:
        return None

    return candidatos[0][3]


def confirmar_movimiento_pendiente(pendiente_id, categoria_input, nota_extra=""):
    """Convierte un pendiente en transacción real y marca su resolución."""
    p = _buscar_pendiente_por_id(pendiente_id)
    if not p:
        raise ValueError(f"No existe pendiente '{pendiente_id}'.")

    if normalizar_texto(p.get("Estado", "")) != "pendiente":
        raise ValueError(f"El pendiente '{pendiente_id}' no está en estado Pendiente.")

    tipo = str(p.get("Tipo", "")).strip().capitalize()
    cuenta = str(p.get("Cuenta", "")).strip() or "Efectivo"
    monto = parsear_numero(p.get("Monto", 0))
    moneda = str(p.get("Moneda", "PEN")).upper()
    descripcion = str(p.get("Descripcion", "")).strip()
    referencia = str(p.get("Referencia", "")).strip()
    observacion = str(p.get("Observacion", "")).strip()

    nota = descripcion
    if referencia:
        nota = f"{nota} | Ref: {referencia}" if nota else f"Ref: {referencia}"
    if nota_extra:
        nota = f"{nota}. {nota_extra}" if nota else nota_extra

    texto_contexto = " | ".join([descripcion, referencia, observacion, nota_extra]).strip()
    texto_contexto_norm = normalizar_texto(texto_contexto)
    tx_id = None

    # Caso 1: usuario indica explícitamente el ID de deuda (ej. categoria "deuda:12").
    deuda_id_explicita = _extraer_deuda_id_desde_texto(categoria_input, nota_extra, texto_contexto)
    if not tx_id and deuda_id_explicita and es_cuenta_banco(cuenta):
        deuda_obj = obtener_deuda_por_id(deuda_id_explicita)
        if deuda_obj:
            pago_res = pagar_deuda(
                str(deuda_obj.get("ID", "")).strip(),
                monto,
                moneda,
                cuenta,
                nota=nota,
            )
            tx_id = pago_res.get("trans_id")
            tipo = "Gasto"
            categoria_input = "Deudas"

    # Caso 1.5: detección automática de pago de deuda de servicio desde cuenta banco.
    if not tx_id and es_cuenta_banco(cuenta):
        deuda_servicio = _buscar_deuda_servicio_por_contexto(
            cuenta,
            monto,
            moneda,
            descripcion,
            referencia,
            observacion,
            nota_extra,
            categoria_input,
        )
        if deuda_servicio:
            pago_res = pagar_deuda(
                str(deuda_servicio.get("ID", "")).strip(),
                monto,
                moneda,
                cuenta,
                nota=nota,
            )
            tx_id = pago_res.get("trans_id")
            tipo = "Gasto"
            categoria_input = "Deudas"

    # Caso 2: pago de tarjeta propia detectado por Gmail o por un pendiente manual.
    if not tx_id and ("pago_tarjeta_propia" in texto_contexto_norm or "pago de tarjeta propia" in texto_contexto_norm or "constancia de pago de tarjeta" in texto_contexto_norm):
        origen_match = re.search(r"(?:origen|desde)=([^|]+)", texto_contexto, re.IGNORECASE)
        destino_match = re.search(r"(?:destino|pagado a)=([^|]+)", texto_contexto, re.IGNORECASE)
        cuenta_origen = str((origen_match.group(1) if origen_match else "") or cuenta).strip()
        cuenta_destino = str((destino_match.group(1) if destino_match else "").strip())

        if not cuenta_destino:
            # Fallback: si el texto trae alguna cuenta crédito, usarla.
            cuenta_destino_detectada = detectar_cuenta_en_texto(texto_contexto)
            if cuenta_destino_detectada and es_cuenta_credito(cuenta_destino_detectada.get("Nombre", "")):
                cuenta_destino = cuenta_destino_detectada.get("Nombre", "")

        deuda_obj = obtener_deuda_activa_por_cuenta(cuenta_destino) if cuenta_destino else None
        if deuda_obj and cuenta_origen and es_cuenta_banco(cuenta_origen):
            pago_res = pagar_deuda(
                str(deuda_obj.get("ID", "")).strip(),
                monto,
                moneda,
                cuenta_origen,
                nota=nota,
            )
            tx_id = pago_res.get("trans_id")
            cuenta = cuenta_origen
            tipo = "Gasto"
            categoria_input = "Deudas"

    # Flujo tradicional: si el pendiente cayó como gasto sobre una tarjeta de crédito,
    # intentamos resolverlo como pago de deuda usando la cuenta asociada.
    if not tx_id and es_cuenta_credito(cuenta):
        desc_norm = normalizar_texto(f"{descripcion} {observacion}")
        if "pago" in desc_norm or "tarjeta" in desc_norm:
            deuda = obtener_deuda_activa_por_cuenta(cuenta)
            if deuda:
                source_account = None
                for suf in re.findall(r"(\d{4})", f"{descripcion} {observacion}"):
                    cand = detectar_cuenta_por_ultimos_digitos(suf)
                    if cand and es_cuenta_banco(cand.get("Nombre", "")):
                        source_account = cand.get("Nombre")
                        break
                if not source_account:
                    source_account = deuda.get("CuentaAsociada")
                if source_account and es_cuenta_banco(source_account):
                    pago_res = pagar_deuda(str(deuda.get("ID", "")).strip(), monto, moneda, source_account, nota)
                    tx_id = pago_res.get("trans_id")
                    cuenta = source_account
                    tipo = "Gasto"

    if not tx_id:
        tx_id = add_transaction(
            tipo=tipo,
            monto=monto,
            moneda=moneda,
            categoria_input=categoria_input,
            subcategoria="",
            cuenta=cuenta,
            metodo=_metodo_por_cuenta(cuenta),
            nota=nota,
        )

    row = p["_row"]
    ahora_iso = get_now().isoformat(timespec="seconds")

    # Evitar 422 por campos tipados (ej. Confianza:number) enviando solo campos necesarios.
    record = pend_ws._record_for_row(row)
    update_fields = {
        "Estado": "Confirmado",
        "TXID": tx_id,
        "FechaResolucion": ahora_iso,
    }
    if str(nota_extra).strip():
        update_fields["Observacion"] = str(nota_extra).strip()

    try:
        airtable_api.update_record("MovimientosPendientes", record["id"], update_fields)
    except Exception as e:
        err_txt = str(e)
        logger.error(f"Error actualizando pendiente {pendiente_id} con TXID ({tx_id}): {err_txt}")

        # Fallback anti-422: algunas bases tipan TXID como campo no-texto/relación.
        # En ese caso confirmamos el pendiente sin bloquear al usuario y dejamos traza.
        if "422" in err_txt:
            observacion_fallback = str(nota_extra or "").strip()
            marca_tx = f"TX generado: {tx_id}"
            observacion_fallback = f"{observacion_fallback} | {marca_tx}" if observacion_fallback else marca_tx
            update_fields_fallback = {
                "Estado": "Confirmado",
                "FechaResolucion": ahora_iso,
                "Observacion": observacion_fallback,
            }
            try:
                airtable_api.update_record("MovimientosPendientes", record["id"], update_fields_fallback)
            except Exception as e2:
                raise ValueError(
                    "No se pudo confirmar el pendiente en Airtable. "
                    f"Error original: {err_txt}. Error fallback: {e2}"
                )
        else:
            raise

    _cache_invalidate("pendientes_values")

    return {
        "pendiente_id": str(p.get("ID", pendiente_id)).strip(),
        "tx_id": tx_id,
        "tipo": tipo,
        "cuenta": cuenta,
        "monto": monto,
        "moneda": moneda,
    }


def descartar_movimiento_pendiente(pendiente_id, motivo=""):
    p = _buscar_pendiente_por_id(pendiente_id)
    if not p:
        raise ValueError(f"No existe pendiente '{pendiente_id}'.")

    if normalizar_texto(p.get("Estado", "")) != "pendiente":
        raise ValueError(f"El pendiente '{pendiente_id}' no está en estado Pendiente.")

    row = p["_row"]
    ahora_iso = get_now().isoformat(timespec="seconds")

    record = pend_ws._record_for_row(row)
    update_fields = {
        "Estado": "Descartado",
        "FechaResolucion": ahora_iso,
    }
    if str(motivo).strip():
        update_fields["Observacion"] = str(motivo).strip()
    airtable_api.update_record("MovimientosPendientes", record["id"], update_fields)
    _cache_invalidate("pendientes_values")
    return {"pendiente_id": str(p.get("ID", pendiente_id)).strip(), "motivo": motivo}


def sugerir_pendientes_por_diferencia(cuenta, diferencia_pen, max_items=5):
    """Retorna candidatos pendientes cercanos a la diferencia detectada."""
    cuenta_norm = normalizar_texto(cuenta)
    pendientes = listar_movimientos_pendientes(limit=200)
    if not pendientes:
        return []

    candidatos = []
    for p in pendientes:
        if normalizar_texto(p.get("Cuenta", "")) != cuenta_norm:
            continue

        monto = parsear_numero(p.get("Monto", 0))
        moneda = str(p.get("Moneda", "PEN")).upper()
        monto_pen = convertir_a_pen(monto, moneda)
        tipo = normalizar_texto(p.get("Tipo", ""))

        # Si falta dinero en hoja vs saldo real, suele faltar ingreso.
        # Si sobra dinero en hoja vs saldo real, suele faltar gasto.
        if diferencia_pen > 0 and tipo != "ingreso":
            continue
        if diferencia_pen < 0 and tipo != "gasto":
            continue

        score = abs(abs(diferencia_pen) - monto_pen)
        candidatos.append({
            "id": p.get("ID", ""),
            "tipo": p.get("Tipo", ""),
            "monto": monto,
            "moneda": moneda,
            "monto_pen": monto_pen,
            "descripcion": p.get("Descripcion", ""),
            "score": score,
        })

    candidatos.sort(key=lambda x: x["score"])
    return candidatos[: max(1, int(max_items))]


def conciliar_cuenta(cuenta, saldo_real, moneda_real="PEN"):
    """Compara saldo real con saldo hoja y propone pendientes cercanos a la diferencia."""
    cuenta_info = obtener_cuenta_por_nombre(cuenta)
    if not cuenta_info:
        raise ValueError(f"Cuenta '{cuenta}' no existe.")

    cuenta_nombre = cuenta_info["Nombre"]
    saldo_hoja_pen = obtener_saldo_actual_cuenta(cuenta_nombre)
    if saldo_hoja_pen is None:
        raise ValueError(f"No se pudo obtener saldo de la cuenta '{cuenta_nombre}'.")

    saldo_real_num = parsear_numero(saldo_real)
    saldo_real_pen = convertir_a_pen(saldo_real_num, moneda_real)
    diferencia_pen = round(saldo_real_pen - saldo_hoja_pen, 2)

    sugerencias = sugerir_pendientes_por_diferencia(cuenta_nombre, diferencia_pen, max_items=5)

    return {
        "cuenta": cuenta_nombre,
        "saldo_hoja_pen": round(saldo_hoja_pen, 2),
        "saldo_real_pen": round(saldo_real_pen, 2),
        "diferencia_pen": diferencia_pen,
        "sugerencias": sugerencias,
    }

# ---------- CATEGORÍAS Y SUBCATEGORÍAS ----------
def obtener_categorias(tipo=None):
    """Obtiene todas las categorías con sus subcategorías"""
    registros = _leer_records_cacheados(categorias_ws, "categorias_records")
    resultado = []
    for c in registros:
        nombre_original = c["Nombre"]
        nombre_norm = normalizar_texto(nombre_original)
        if tipo is None or c["Tipo"].lower() == tipo.lower():
            resultado.append({
                "original": nombre_original,
                "normalizado": nombre_norm,
                "tipo": c["Tipo"],
                "subcategorias": c.get("Subcategorías", "")
            })
    return resultado

def obtener_mapeo_subcategorias(tipo=None):
    """
    Retorna un diccionario: {subcategoria_normalizada: categoria_original}
    para todas las subcategorías definidas.
    """
    mapeo = {}
    categorias = obtener_categorias(tipo)
    for cat in categorias:
        subs = cat["subcategorias"]
        if subs and subs.strip():
            for sub in subs.split(";"):
                sub = sub.strip()
                if sub:
                    sub_norm = normalizar_texto(sub)
                    mapeo[sub_norm] = cat["original"]
    return mapeo

def resolver_categoria(input_text, tipo):
    """
    Dado un texto de entrada, determina si es categoría principal o subcategoría.
    Retorna una tupla: (categoria_original, subcategoria_original_o_vacia)
    Lanza ValueError si no encuentra coincidencia.
    """
    input_norm = normalizar_texto(input_text)
    
    # 1. Buscar como categoría principal
    categorias = obtener_categorias(tipo)
    for cat in categorias:
        if cat["normalizado"] == input_norm:
            return (cat["original"], "")
    
    # 2. Buscar como subcategoría
    mapeo_subs = obtener_mapeo_subcategorias(tipo)
    if input_norm in mapeo_subs:
        cat_original = mapeo_subs[input_norm]
        # El nombre original de la subcategoría lo recuperamos del mapeo inverso
        # pero podemos devolver el input_text original con capitalización adecuada
        return (cat_original, input_text.capitalize())
    
    # 3. No encontrado: sugerencias
    sugerencias = [c["original"] for c in categorias[:5]]
    raise ValueError(f"'{input_text}' no es categoría ni subcategoría válida. Sugerencias: {', '.join(sugerencias)}")

def validar_categoria(categoria_input, tipo):
    """Versión legacy que solo devuelve categoría principal (usada internamente)"""
    cat, _ = resolver_categoria(categoria_input, tipo)
    return cat

# ---------- CUENTAS ----------
def obtener_nombres_cuentas():
    try:
        registros = _leer_records_cacheados(cuentas_ws, "cuentas_records")
        return [c["Nombre"] for c in registros]
    except Exception as e:
        logger.error(f"Error obteniendo nombres de cuentas: {e}")
        return ["Efectivo"]


def _normalizar_digitos(texto):
    return re.sub(r"\D", "", str(texto or ""))


def _identificadores_cuenta(cuenta):
    """Recolecta posibles identificadores (nombre y números) para matching flexible."""
    ids = set()

    nombre = str(cuenta.get("Nombre", "")).strip()
    if nombre:
        ids.add(normalizar_texto(nombre))

    valor = str(cuenta.get("NumeroCuenta", "")).strip()
    if valor:
        ids.add(normalizar_texto(valor))
        digitos = _normalizar_digitos(valor)
        if digitos:
            ids.add(digitos)
            if len(digitos) >= 4:
                ids.add(digitos[-4:])

    return ids


def detectar_cuenta_por_ultimos_digitos(ultimos4):
    """Busca cuenta en hoja Cuentas por últimos 4 dígitos de cuenta/tarjeta."""
    suf = _normalizar_digitos(ultimos4)
    if len(suf) < 4:
        return None
    suf = suf[-4:]

    cuentas = _leer_records_cacheados(cuentas_ws, "cuentas_records")
    for i, c in enumerate(cuentas, start=2):
        ids = _identificadores_cuenta(c)
        for ident in ids:
            dig = _normalizar_digitos(ident)
            if len(dig) >= 4 and dig.endswith(suf):
                c["_row"] = i
                return c
    return None


def obtener_estado_gmail_push(clave=None, default=None):
    """Obtiene el estado persistido de Gmail Push como key/value."""
    valores = _leer_values_cacheados(gmail_estado_ws, "gmail_estado_values")
    if not valores or len(valores) <= 1:
        return default if clave else {}

    headers = valores[0]
    filas = [dict(zip(headers, f)) for f in valores[1:] if any(str(c).strip() for c in f)]
    estado = {}
    for fila in filas:
        k = str(fila.get("Clave", "")).strip()
        if k:
            estado[k] = str(fila.get("Valor", "")).strip()

    if clave is None:
        return estado
    return estado.get(clave, default)


def guardar_estado_gmail_push(**campos):
    """Crea o actualiza claves de estado para Gmail Push."""
    if not campos:
        return

    valores = _leer_values_cacheados(gmail_estado_ws, "gmail_estado_values")
    headers = valores[0] if valores else ["Clave", "Valor", "ActualizadoEn"]
    filas = [dict(zip(headers, f)) for f in valores[1:] if any(str(c).strip() for c in f)] if len(valores) > 1 else []
    indice = {str(f.get("Clave", "")).strip(): idx for idx, f in enumerate(filas, start=2)}
    # Airtable Date/DateTime acepta mejor formato ISO 8601 con zona horaria.
    ahora = get_now().isoformat(timespec="seconds")

    for clave, valor in campos.items():
        clave_txt = str(clave).strip()
        valor_txt = str(valor)
        row = indice.get(clave_txt)
        if row:
            gmail_estado_ws.update(f"B{row}:C{row}", [[valor_txt, ahora]], value_input_option="RAW")
        else:
            gmail_estado_ws.append_row([clave_txt, valor_txt, ahora], value_input_option="RAW")
    _cache_invalidate("gmail_estado_values")

def obtener_cuenta_por_nombre(nombre_input):
    """
    Busca una cuenta por nombre, ignorando tildes y mayúsculas.
    Retorna diccionario con datos de la cuenta y número de fila.
    """
    input_norm = normalizar_texto(nombre_input)
    cuentas = _leer_records_cacheados(cuentas_ws, "cuentas_records")
    for i, c in enumerate(cuentas, start=2):
        if normalizar_texto(c["Nombre"]) == input_norm:
            c["_row"] = i
            return c
    return None

def obtener_tipo_cuenta(nombre_input):
    """Retorna el tipo de cuenta (Efectivo/Banco/Crédito/Debito) para un nombre dado."""
    cuenta = obtener_cuenta_por_nombre(nombre_input)
    if not cuenta:
        return None
    return str(cuenta.get("Tipo", "")).strip()

def es_cuenta_credito(nombre_cuenta):
    tipo = normalizar_texto(obtener_tipo_cuenta(nombre_cuenta) or "")
    return tipo == "credito"

def es_cuenta_banco(nombre_cuenta):
    tipo = normalizar_texto(obtener_tipo_cuenta(nombre_cuenta) or "")
    return tipo == "banco"

def detectar_cuenta_en_texto(texto):
    """
    Detecta una cuenta mencionada dentro de un texto, ignorando tildes/mayúsculas.
    Prioriza nombres de cuenta más largos para soportar cuentas compuestas.
    """
    if not texto:
        return None

    texto_norm = normalizar_texto(texto)
    cuentas = _leer_records_cacheados(cuentas_ws, "cuentas_records")

    candidatos = []
    for i, c in enumerate(cuentas, start=2):
        nombre = str(c.get("Nombre", "")).strip()
        if not nombre:
            continue
        nombre_norm = normalizar_texto(nombre)
        candidatos.append((len(nombre_norm), nombre_norm, i, c))

    # Primero busca nombres más largos para evitar matches parciales incorrectos.
    candidatos.sort(reverse=True, key=lambda x: x[0])
    for _, nombre_norm, fila, cuenta in candidatos:
        patron = rf"(^|\s){re.escape(nombre_norm)}(\s|$)"
        if re.search(patron, texto_norm):
            cuenta["_row"] = fila
            return cuenta

    # Fallback por últimos 4 dígitos presentes en el texto.
    ultimos4 = re.findall(r"(?<!\d)(\d{4})(?!\d)", texto or "")
    for suf in ultimos4:
        cuenta = detectar_cuenta_por_ultimos_digitos(suf)
        if cuenta:
            return cuenta
    return None

# ---------- DEUDAS ----------
def obtener_deudas_con_fila():
    """Lee deudas de Airtable con FORMATTED_VALUE para evitar truncamiento de números."""
    try:
        # Usar función que lee con FORMATTED_VALUE y retorna dicts
        deudas = _leer_registros_formateado("Deudas")
        
        resultado = []
        for idx, d in enumerate(deudas, start=2):
            # Agregar _row para poder actualizar después
            d["_row"] = idx
            resultado.append(d)
        
        return resultado
    except Exception as e:
        logger.error(f"Error en obtener_deudas_con_fila: {e}")
        # Fallback al cache si falla la lectura directa
        deudas = _leer_records_cacheados(deudas_ws, "deudas_records")
        resultado = []
        for i, d in enumerate(deudas, start=2):
            d["_row"] = i
            resultado.append(d)
        return resultado

def sincronizar_estado_deudas(fecha_referencia=None):
    """Actualiza Estado según vencimiento y pendiente."""
    if fecha_referencia is None:
        fecha_referencia = get_now()

    for d in obtener_deudas_con_fila():
        row = d["_row"]
        estado_actual = str(d.get("Estado", "")).strip()
        estado_norm = normalizar_texto(estado_actual)
        monto_total = parsear_numero(d.get("MontoTotal", 0))
        monto_pagado = parsear_numero(d.get("MontoPagado", 0))
        pendiente = round(monto_total - monto_pagado, 2)

        fecha_venc = parsear_fecha(d.get("FechaVencimiento"))

        if pendiente <= 0:
            nuevo_estado = "Pagada"
        elif fecha_venc and fecha_venc.date() < fecha_referencia.date():
            nuevo_estado = "Vencida"
        else:
            nuevo_estado = "Activa"

        if normalizar_texto(nuevo_estado) != estado_norm:
            deudas_ws.update_cell(row, 8, nuevo_estado)

def obtener_deuda_activa_por_cuenta(nombre_cuenta, fecha_transaccion=None):
    """
    Busca deuda activa de tipo crédito vinculada a la cuenta y vigente para la fecha.
    Si hay varias, toma la de vencimiento más próximo.
    """
    if not nombre_cuenta:
        return None

    if fecha_transaccion is None:
        fecha_transaccion = get_now()

    cuenta_norm = normalizar_texto(nombre_cuenta)
    candidatas = []

    for d in obtener_deudas_con_fila():
        tipo = normalizar_texto(d.get("Tipo", ""))
        estado = normalizar_texto(d.get("Estado", ""))
        cuenta_asociada = normalizar_texto(d.get("CuentaAsociada", ""))
        if tipo != "credito":
            continue
        if cuenta_asociada != cuenta_norm:
            continue
        if estado != "activa":
            continue

        monto_total = parsear_numero(d.get("MontoTotal", 0))
        monto_pagado = parsear_numero(d.get("MontoPagado", 0))
        pendiente = round(monto_total - monto_pagado, 2)
        if pendiente <= 0:
            continue

        fecha_venc = parsear_fecha(d.get("FechaVencimiento"))
        if fecha_venc and fecha_venc.date() < fecha_transaccion.date():
            continue

        d["_fecha_venc"] = fecha_venc
        candidatas.append(d)

    if not candidatas:
        return None

    # Orden robusto ante mezcla de datetimes con/sin tz (ISO de Airtable vs datetime nativo)
    candidatas.sort(
        key=lambda x: (
            x.get("_fecha_venc") is None,
            (x.get("_fecha_venc").date().toordinal() if x.get("_fecha_venc") else 9999999),
        )
    )
    return candidatas[0]


def _obtener_periodo_por_fecha(fecha_dt, dia_corte=None):
    """Devuelve periodo 'YYYY-MM' al que pertenece una transacción según dia_corte.
    Si dia_corte es None, usa el mes de la fecha."""
    if fecha_dt is None:
        fecha_dt = get_now()
    if dia_corte is None:
        return fecha_dt.strftime("%Y-%m")
    try:
        dia_corte = int(dia_corte)
    except Exception:
        return fecha_dt.strftime("%Y-%m")

    if fecha_dt.day > dia_corte:
        # Pertenece al siguiente mes
        año = fecha_dt.year + (1 if fecha_dt.month == 12 else 0)
        mes = 1 if fecha_dt.month == 12 else fecha_dt.month + 1
    else:
        año = fecha_dt.year
        mes = fecha_dt.month
    return f"{año:04d}-{mes:02d}"


def _obtener_dia_corte_de_cuenta(nombre_cuenta):
    cuenta = obtener_cuenta_por_nombre(nombre_cuenta)
    if not cuenta:
        return None
    # Intentar varias variantes de nombre de columna
    for key in ("DíaCorte", "DiaCorte", "Día Corte", "Dia Corte", "DiaCorte"):
        val = cuenta.get(key)
        if val:
            try:
                return int(str(val).strip())
            except Exception:
                continue
    return None


def _buscar_deuda_por_periodo(nombre_cuenta, periodo):
    """Busca en Deudas una fila que coincida con CuentaAsociada y Periodo."""
    for d in obtener_deudas_con_fila():
        if normalizar_texto(d.get("CuentaAsociada", "")) != normalizar_texto(nombre_cuenta):
            continue
        if str(d.get("Periodo", "")).strip() == str(periodo):
            return d
    return None


def crear_deuda_ciclo(nombre_cuenta, periodo, fecha_venc=None, descripcion=None, tipo="credito", moneda="PEN"):
    """Crea una nueva fila en Deudas para el periodo indicado con montos iniciales 0."""
    next_id = _siguiente_id_deuda()
    deuda_id = str(next_id)
    descripcion = descripcion or f"Deuda {nombre_cuenta} {periodo}"
    # Construir un diccionario según headers de la hoja Deudas para mantener compatibilidad
    headers = deudas_ws.row_values(1)
    row_map = {h: "" for h in headers}
    # Valores comunes
    row_map[headers[0]] = deuda_id if headers else deuda_id
    # Buscar campos y asignar si existen
    def set_if_present(key, value):
        for h in headers:
            if normalizar_texto(h) == normalizar_texto(key):
                row_map[h] = value
                return True
        return False

    set_if_present("ID", deuda_id)
    set_if_present("Descripcion", descripcion)
    set_if_present("Tipo", tipo.capitalize())
    set_if_present("MontoTotal", 0.00)
    set_if_present("Moneda", moneda.upper())
    set_if_present("MontoPagado", 0.00)
    set_if_present("FechaVencimiento", fecha_venc.strftime("%d/%m/%Y") if fecha_venc else "")
    set_if_present("Estado", "Activa")
    set_if_present("CuentaAsociada", nombre_cuenta)
    set_if_present("Periodo", periodo)

    fila = [row_map.get(h, "") for h in headers]
    deudas_ws.append_row(fila, value_input_option="RAW")
    _cache_invalidate("deudas_records")
    logger.info("Crear deuda ciclo | id=%s cuenta=%s periodo=%s fecha_venc=%s", deuda_id, nombre_cuenta, periodo, fecha_venc)
    return deuda_id

    """Migra la hoja Deudas para asegurar columnas Periodo/FechaCorte y asigna periodo a filas existentes.
    También crea ciclos vacíos para el periodo actual si faltan para cuentas de crédito."""
    headers = deudas_ws.row_values(1)
    changed = False
    if "Periodo" not in headers:
        headers.append("Periodo")
        changed = True
    if "FechaCorte" not in headers:
        headers.append("FechaCorte")
        changed = True

    if changed:
        deudas_ws.update("1:1", [headers], value_input_option="RAW")
        logger.info("Migración: añadidas columnas Periodo/FechaCorte en Deudas")

    # Colocar periodo para filas existentes
    deudas = obtener_deudas_con_fila()
    headers = deudas_ws.row_values(1)
    try:
        col_periodo = headers.index("Periodo") + 1
    except ValueError:
        col_periodo = None
    try:
        col_fechacorte = headers.index("FechaCorte") + 1
    except ValueError:
        col_fechacorte = None

    updated = 0
    for d in deudas:
        row = d.get("_row")
        if not row:
            continue
        fecha_venc = parsear_fecha(d.get("FechaVencimiento"))
        periodo = None
        if fecha_venc:
            periodo = fecha_venc.strftime("%Y-%m")
            fecha_corte_str = fecha_venc.strftime("%d/%m/%Y")
        else:
            # intentar derivar periodo desde hoy y dia de corte de la cuenta
            dia_corte = _obtener_dia_corte_de_cuenta(d.get("CuentaAsociada", ""))
            periodo = _obtener_periodo_por_fecha(get_now(), dia_corte)
            fecha_corte_str = ""

        if col_periodo:
            deudas_ws.update_cell(row, col_periodo, periodo)
        if col_fechacorte:
            deudas_ws.update_cell(row, col_fechacorte, fecha_corte_str)
        updated += 1

    logger.info("Migración: asignados Periodo/FechaCorte a %d filas de Deudas", updated)

    # Crear ciclos vacíos para periodo actual en tarjetas de crédito si faltan
    cuentas = _leer_records_cacheados(cuentas_ws, "cuentas_records")
    created = 0
    for c in cuentas:
        tipo = normalizar_texto(c.get("Tipo", ""))
        if tipo != "credito":
            continue
        nombre = c.get("Nombre")
        dia_corte = _obtener_dia_corte_de_cuenta(nombre)
        periodo_actual = _obtener_periodo_por_fecha(get_now(), dia_corte)
        existe = _buscar_deuda_por_periodo(nombre, periodo_actual)
        if not existe:
            # intentar derivar fecha_venc desde DiaPago
            fecha_venc = None
            for key in ("DíaPago", "DiaPago", "Dia Pago"):
                val = c.get(key)
                if val:
                    try:
                        dp = int(str(val).strip())
                        año, mes = map(int, periodo_actual.split("-"))
                        fecha_venc = datetime(año, mes, min(dp, 28))
                    except Exception:
                        fecha_venc = None
            crear_deuda_ciclo(nombre, periodo_actual, fecha_venc=fecha_venc, descripcion=None, tipo="credito", moneda=c.get("Moneda", "PEN"))
            created += 1

    logger.info("Migración: creados %d ciclos vacíos para periodo actual", created)
    return {"asignadas": updated, "creadas": created}

def incrementar_deuda_por_gasto(nombre_cuenta, monto, moneda, fecha_transaccion=None):
    """Incrementa MontoTotal de la deuda activa asociada a una cuenta de crédito."""
    if fecha_transaccion is None:
        fecha_transaccion = get_now()

    # Determinar periodo según fecha_transaccion y dia de corte de la cuenta
    dia_corte = _obtener_dia_corte_de_cuenta(nombre_cuenta)
    periodo = _obtener_periodo_por_fecha(fecha_transaccion, dia_corte)

    # Buscar deuda por periodo
    deuda = _buscar_deuda_por_periodo(nombre_cuenta, periodo)
    if not deuda:
        # Si no existe deuda para el periodo, crearla (fecha_venc opcional)
        # Intentar derivar FechaVenc desde DiaPago de la cuenta
        cuenta_info = obtener_cuenta_por_nombre(nombre_cuenta)
        fecha_venc = None
        if cuenta_info:
            for key in ("DíaPago", "DiaPago", "Dia Pago", "Día Pago"):
                val = cuenta_info.get(key)
                if val:
                    try:
                        dp = int(str(val).strip())
                        # Construir fecha_venc en el mes correspondiente al periodo
                        año, mes = map(int, periodo.split("-"))
                        fecha_venc = datetime(año, mes, min(dp, 28))
                    except Exception:
                        fecha_venc = None
        nueva_id = crear_deuda_ciclo(nombre_cuenta, periodo, fecha_venc=fecha_venc, descripcion=None, tipo="credito", moneda="PEN")
        # Refrescar cache y obtener la deuda recién creada
        _cache_invalidate("deudas_records")
        deuda = _buscar_deuda_por_periodo(nombre_cuenta, periodo)
        if not deuda:
            logger.warning("No se pudo crear deuda para periodo %s cuenta %s", periodo, nombre_cuenta)
            return ""

    row = deuda["_row"]
    deuda_id = str(deuda.get("ID", "")).strip()
    moneda_deuda = str(deuda.get("Moneda", "PEN")).upper()
    monto_origen = parsear_numero(monto)
    monto_convertido = convertir_moneda(monto_origen, moneda, moneda_deuda)

    monto_total_actual = parsear_numero(deuda.get("MontoTotal", 0))
    nuevo_total = round(monto_total_actual + monto_convertido, 2)
    # Buscar columna MontoTotal por cabecera y actualizar la celda correcta
    # Asumimos que MontoTotal está en la columna D si se mantiene el esquema, pero
    # para mayor robustez, escribimos por celda calculando la letra mediante el header.
    headers = deudas_ws.row_values(1)
    col_idx = None
    for idx, h in enumerate(headers, start=1):
        if normalizar_texto(h) == normalizar_texto("MontoTotal"):
            col_idx = idx
            break
    if col_idx:
        deudas_ws.update_cell(row, col_idx, nuevo_total)
    else:
        # Fallback a D{row}
        deudas_ws.update(f"D{row}", [[nuevo_total]], value_input_option="RAW")

    _cache_invalidate("deudas_records")

    logger.info(
        "Deuda update | id=%s cuenta=%s periodo=%s fila=%s moneda_deuda=%s celda_raw='%s' "
        "monto_actual=%.2f gasto_origen=%.2f %s gasto_convertido=%.2f %s nuevo_total=%.2f",
        deuda_id,
        nombre_cuenta,
        periodo,
        row,
        moneda_deuda,
        deuda.get("MontoTotal", 0),
        monto_total_actual,
        monto_origen,
        (moneda or "PEN").upper(),
        monto_convertido,
        moneda_deuda,
        nuevo_total,
    )

    return deuda_id

def obtener_deuda_por_id(deuda_id):
    deuda_id_norm = str(deuda_id or "").strip()
    if not deuda_id_norm:
        return None

    for d in obtener_deudas_con_fila():
        if str(d.get("ID", "")).strip() == deuda_id_norm:
            return d
    return None

def _siguiente_id_deuda():
    return int(obtener_siguiente_id(deudas_ws, prefix=""))

def ajustar_monto_deuda(deuda_id, delta_monto, moneda_delta):
    """Ajusta MontoTotal de una deuda por ID. delta positivo suma, negativo resta."""
    deuda = obtener_deuda_por_id(deuda_id)
    if not deuda:
        logger.warning(f"No se encontró deuda ID '{deuda_id}' para ajuste.")
        return False

    row = deuda["_row"]
    moneda_deuda = str(deuda.get("Moneda", "PEN")).upper()
    delta_convertido = convertir_moneda(parsear_numero(delta_monto), moneda_delta, moneda_deuda)

    monto_total_actual = parsear_numero(deuda.get("MontoTotal", 0))
    nuevo_total = round(monto_total_actual + delta_convertido, 2)
    if nuevo_total < 0:
        nuevo_total = 0.0

    deudas_ws.update(f"D{row}", [[nuevo_total]], value_input_option="RAW")
    _cache_invalidate("deudas_records")
    logger.info(
        "Deuda ajuste | id=%s fila=%s actual=%.2f delta=%.2f %s convertido=%.2f %s nuevo=%.2f",
        deuda_id,
        row,
        monto_total_actual,
        parsear_numero(delta_monto),
        (moneda_delta or "PEN").upper(),
        delta_convertido,
        moneda_deuda,
        nuevo_total,
    )
    return True


def ajustar_pago_deuda(deuda_id, delta_pago, moneda_delta):
    """Ajusta MontoPagado de una deuda por ID. delta positivo suma, negativo resta."""
    deuda = obtener_deuda_por_id(deuda_id)
    if not deuda:
        logger.warning(f"No se encontró deuda ID '{deuda_id}' para ajuste de pago.")
        return False

    row = deuda["_row"]
    moneda_deuda = str(deuda.get("Moneda", "PEN")).upper()
    delta_convertido = convertir_moneda(parsear_numero(delta_pago), moneda_delta, moneda_deuda)

    monto_pagado_actual = parsear_numero(deuda.get("MontoPagado", 0))
    nuevo_pagado = round(monto_pagado_actual + delta_convertido, 2)
    if nuevo_pagado < 0:
        nuevo_pagado = 0.0

    headers = deudas_ws.row_values(1)
    col_idx = None
    for idx, h in enumerate(headers, start=1):
        if normalizar_texto(h) == normalizar_texto("MontoPagado"):
            col_idx = idx
            break

    if col_idx:
        deudas_ws.update_cell(row, col_idx, nuevo_pagado)
    else:
        deudas_ws.update(f"F{row}", [[nuevo_pagado]], value_input_option="RAW")

    _cache_invalidate("deudas_records")
    logger.info(
        "Pago deuda ajuste | id=%s fila=%s actual=%.2f delta=%.2f %s convertido=%.2f %s nuevo=%.2f",
        deuda_id,
        row,
        monto_pagado_actual,
        parsear_numero(delta_pago),
        (moneda_delta or "PEN").upper(),
        delta_convertido,
        moneda_deuda,
        nuevo_pagado,
    )
    sincronizar_estado_deudas()
    return True

def obtener_transaccion_por_id(trans_id):
    trans_id_norm = str(trans_id or "").strip().upper()
    if not trans_id_norm:
        return None

    transacciones = _leer_records_cacheados(trans_ws, "transacciones_records")
    for i, t in enumerate(transacciones, start=2):
        if str(t.get("ID", "")).strip().upper() == trans_id_norm:
            t["_row"] = i
            return t
    return None

def _aplicar_reversa_saldo(tipo, cuenta, monto, moneda):
    monto_pen = convertir_a_pen(parsear_numero(monto), moneda)
    if normalizar_texto(tipo) == "ingreso":
        return actualizar_saldo_cuenta(cuenta, "gasto", monto_pen)
    return actualizar_saldo_cuenta(cuenta, "ingreso", monto_pen)
    pend_ws.update(f"J{row}:N{row}", [["Confirmado", "", tx_id, ahora, nota_extra]], value_input_option="RAW")
def _aplicar_saldo(tipo, cuenta, monto, moneda):
    monto_pen = convertir_a_pen(parsear_numero(monto), moneda)
    return actualizar_saldo_cuenta(cuenta, tipo, monto_pen)

def eliminar_transaccion(trans_id):
    """Elimina una transacción y revierte su impacto en saldo/deuda."""
    trans = obtener_transaccion_por_id(trans_id)
    if not trans:
        raise ValueError(f"No existe la transacción '{trans_id}'.")

    row = trans["_row"]
    tipo = str(trans.get("Tipo", "")).strip()
    monto = parsear_numero(trans.get("Monto", 0))
    moneda = str(trans.get("Moneda", "PEN")).upper()
    cuenta = str(trans.get("Cuenta", "Efectivo")).strip() or "Efectivo"
    deuda_id = str(trans.get("DeudaID", "")).strip()

    es_pago_deuda = normalizar_texto(trans.get("Categoría", "")) == "deudas" and normalizar_texto(trans.get("Subcategoría", "")) == "pago" and deuda_id

    _aplicar_reversa_saldo(tipo, cuenta, monto, moneda)

    if es_pago_deuda:
        deuda = obtener_deuda_por_id(deuda_id)
        cuenta_asociada = deuda.get("CuentaAsociada", "") if deuda else ""
        deuda_moneda = str(deuda.get("Moneda", moneda)).upper() if deuda else moneda
        if cuenta_asociada:
            actualizar_saldo_cuenta(cuenta_asociada, "gasto", convertir_a_pen(monto, moneda))
        ajustar_pago_deuda(deuda_id, -monto, moneda)
    elif normalizar_texto(tipo) == "gasto" and deuda_id:
        ajustar_monto_deuda(deuda_id, -monto, moneda)

    trans_ws.delete_rows(row)
    _cache_invalidate("transacciones_records", "cuentas_records", "deudas_records")
    sincronizar_estado_deudas()

    return {
        "id": str(trans.get("ID", trans_id)),
        "tipo": tipo,
        "monto": monto,
        "moneda": moneda,
        "cuenta": cuenta,
    }

def editar_transaccion(trans_id, campo, nuevo_valor):
    """
    Edita un campo de una transacción y recalcula impactos en saldo/deuda.
    Campos soportados: monto, moneda, categoria, subcategoria, cuenta, metodo, nota, fecha.
    """
    trans = obtener_transaccion_por_id(trans_id)
    if not trans:
        raise ValueError(f"No existe la transacción '{trans_id}'.")

    row = trans["_row"]
    tipo = str(trans.get("Tipo", "")).strip().capitalize()
    campo_norm = normalizar_texto(campo)

    actual = {
        "id": str(trans.get("ID", "")).strip(),
        "fecha": str(trans.get("Fecha", "")).strip(),
        "tipo": tipo,
        "monto": parsear_numero(trans.get("Monto", 0)),
        "moneda": str(trans.get("Moneda", "PEN")).upper(),
        "categoria": str(trans.get("Categoría", "")).strip(),
        "subcategoria": str(trans.get("Subcategoría", "")).strip(),
        "cuenta": str(trans.get("Cuenta", "Efectivo")).strip() or "Efectivo",
        "metodo": str(trans.get("Método", "Efectivo")).strip() or "Efectivo",
        "nota": str(trans.get("Nota", "")).strip(),
        "deuda_id": str(trans.get("DeudaID", "")).strip(),
    }
    nuevo = actual.copy()

    if campo_norm == "monto":
        nuevo["monto"] = parsear_numero(nuevo_valor)
        if nuevo["monto"] <= 0:
            raise ValueError("El monto debe ser mayor a 0.")
    elif campo_norm == "moneda":
        moneda = str(nuevo_valor or "").strip().upper()
        if moneda not in ["PEN", "USD"]:
            raise ValueError("Moneda no válida. Usa PEN o USD.")
        nuevo["moneda"] = moneda
    elif campo_norm == "categoria":
        categoria, subcat = resolver_categoria(str(nuevo_valor).strip(), tipo)
        nuevo["categoria"] = categoria
        if subcat:
            nuevo["subcategoria"] = subcat
    elif campo_norm == "subcategoria":
        nuevo["subcategoria"] = str(nuevo_valor or "").strip()
    elif campo_norm == "cuenta":
        cuenta_info = obtener_cuenta_por_nombre(str(nuevo_valor).strip())
        if not cuenta_info:
            raise ValueError(f"Cuenta '{nuevo_valor}' no existe.")
        nuevo["cuenta"] = cuenta_info["Nombre"]
    elif campo_norm == "metodo":
        nuevo["metodo"] = str(nuevo_valor or "").strip() or "Efectivo"
    elif campo_norm == "nota":
        nuevo["nota"] = str(nuevo_valor or "")
    elif campo_norm == "fecha":
        fecha_dt = parsear_fecha(nuevo_valor)
        if not fecha_dt:
            raise ValueError("Fecha inválida. Usa DD/MM/AAAA o YYYY-MM-DD.")
        nuevo["fecha"] = fecha_dt.isoformat(timespec="seconds")
    else:
        raise ValueError("Campo no soportado. Usa monto, moneda, categoria, subcategoria, cuenta, metodo, nota o fecha.")

    # Revertir impacto anterior
    _aplicar_reversa_saldo(actual["tipo"], actual["cuenta"], actual["monto"], actual["moneda"])
    if normalizar_texto(actual["tipo"]) == "gasto" and actual["deuda_id"]:
        ajustar_monto_deuda(actual["deuda_id"], -actual["monto"], actual["moneda"])

    # Reaplicar impacto nuevo
    nuevo_deuda_id = ""
    fecha_nueva_dt = parsear_fecha(nuevo["fecha"]) or get_now()
    if normalizar_texto(nuevo["tipo"]) == "gasto" and es_cuenta_credito(nuevo["cuenta"]):
        nuevo_deuda_id = incrementar_deuda_por_gasto(
            nombre_cuenta=nuevo["cuenta"],
            monto=nuevo["monto"],
            moneda=nuevo["moneda"],
            fecha_transaccion=fecha_nueva_dt,
        )

    _aplicar_saldo(nuevo["tipo"], nuevo["cuenta"], nuevo["monto"], nuevo["moneda"])

    fila = [[
        nuevo["id"],
        nuevo["fecha"],
        nuevo["tipo"],
        round(float(nuevo["monto"]), 2),
        nuevo["moneda"],
        nuevo["categoria"],
        nuevo["subcategoria"],
        nuevo["cuenta"],
        nuevo["metodo"],
        nuevo["nota"],
        nuevo_deuda_id,
    ]]
    trans_ws.update(f"A{row}:K{row}", fila, value_input_option="RAW")
    _cache_invalidate("transacciones_records", "cuentas_records", "deudas_records")
    sincronizar_estado_deudas()

    return {
        "id": nuevo["id"],
        "campo": campo,
        "valor": str(nuevo_valor),
        "deuda_id": nuevo_deuda_id,
    }

def actualizar_saldo_cuenta(nombre_cuenta, tipo_transaccion, monto_pen):
    cuenta = obtener_cuenta_por_nombre(nombre_cuenta)
    if not cuenta:
        logger.warning(f"Cuenta '{nombre_cuenta}' no encontrada. No se actualizará saldo.")
        return False

    fila = cuenta["_row"]
    saldo_cache = parsear_numero(cuenta.get("SaldoActual", 0))
    saldo_actual = saldo_cache

    celda_saldo = _leer_celda_formateada("Cuentas", f"F{fila}")
    if celda_saldo is not None and str(celda_saldo).strip() != "":
        saldo_actual = parsear_numero(celda_saldo)

    tipo_norm = normalizar_texto(tipo_transaccion)
    tipo_cuenta = normalizar_texto(cuenta.get("Tipo", ""))

    # En cuentas de crédito el saldo representa deuda pendiente:
    # - gasto => sube la deuda
    # - ingreso => baja la deuda
    if tipo_cuenta == "credito":
        if tipo_norm == "ingreso":
            nuevo_saldo = saldo_actual - monto_pen
        elif tipo_norm == "gasto":
            nuevo_saldo = saldo_actual + monto_pen
        else:
            return False
    else:
        if tipo_norm == "ingreso":
            nuevo_saldo = saldo_actual + monto_pen
        elif tipo_norm == "gasto":
            nuevo_saldo = saldo_actual - monto_pen
        else:
            return False

    nuevo_saldo = round(nuevo_saldo, 2)
    # Registrar en log el detalle de la operación antes de escribir en Airtable
    logger.info(
        "Actualizar saldo | cuenta=%s fila=F%s tipo=%s monto=%.2f PEN inicial=%.2f final=%.2f cache=%.2f celda='%s'",
        nombre_cuenta,
        fila,
        tipo_transaccion,
        monto_pen,
        saldo_actual,
        nuevo_saldo,
        saldo_cache,
        celda_saldo,
    )

    cuentas_ws.update(f"F{fila}", [[nuevo_saldo]], value_input_option="RAW")
    _cache_invalidate("cuentas_records")
    logger.debug(f"Saldo de '{nombre_cuenta}' escrito en hoja: {saldo_actual} -> {nuevo_saldo}")
    return True

def obtener_saldo_actual_cuenta(nombre_cuenta):
    cuenta = obtener_cuenta_por_nombre(nombre_cuenta)
    if not cuenta:
        return None
    fila = cuenta.get("_row")
    if fila:
        try:
            # Usar FORMATTED_VALUE para obtener el texto tal como aparece en Airtable
            celda_saldo = cuentas_ws.acell(f"F{fila}", value_render_option="FORMATTED_VALUE").value
            if celda_saldo is not None and str(celda_saldo).strip() != "":
                return parsear_numero(celda_saldo)
        except Exception:
            # Fallback al valor cacheado si la lectura formateada falla
            pass

    return parsear_numero(cuenta.get("SaldoActual", 0))

# ---------- TRANSACCIONES ----------
def add_transaction(tipo, monto, moneda, categoria_input, subcategoria="", cuenta="Efectivo", metodo="Efectivo", nota="", fecha=None):
    sincronizar_estado_deudas()

    # Resolver categoría y subcategoría
    categoria_original, subcategoria_resuelta = resolver_categoria(categoria_input, tipo)
    # Si no se pasó subcategoría explícita, usar la resuelta (si existe)
    if not subcategoria and subcategoria_resuelta:
        subcategoria = subcategoria_resuelta
    
    monto_pen = convertir_a_pen(monto, moneda)
    next_id_num = obtener_siguiente_id(trans_ws)
    trans_id = f"TX{next_id_num:05d}"
    
    fecha_dt = parsear_fecha(fecha)
    if fecha_dt is None:
        fecha_dt = get_now()
    fecha = fecha_dt.isoformat(timespec="seconds")

    # Asegura que Monto viaje como número, no como texto.
    monto_num = round(float(monto), 2)

    cuenta_info = obtener_cuenta_por_nombre(cuenta)
    cuenta_final = cuenta_info["Nombre"] if cuenta_info else cuenta
    metodo = _metodo_compatible_airtable(metodo)

    deuda_id = ""
    if tipo.lower() == "gasto" and es_cuenta_credito(cuenta_final):
        deuda_id = incrementar_deuda_por_gasto(
            nombre_cuenta=cuenta_final,
            monto=monto_num,
            moneda=moneda,
            fecha_transaccion=fecha_dt,
        )

    nueva_fila = [
        trans_id,
        fecha,
        tipo.capitalize(),
        monto_num,
        moneda.upper(),
        categoria_original,
        subcategoria,
        cuenta_final,
        metodo,
        nota,
        deuda_id
    ]
    
    trans_ws.append_row(nueva_fila, value_input_option="RAW")
    _cache_invalidate("transacciones_records", "cuentas_records", "deudas_records")
    logger.info(f"Transacción {trans_id}: {tipo} {monto} {moneda} -> {categoria_original} / {subcategoria}")

    # Log detalle de saldo antes de aplicar la transacción
    try:
        saldo_inicial = obtener_saldo_actual_cuenta(cuenta_final)
        esperado = saldo_inicial + monto_pen if tipo.lower() == "ingreso" else saldo_inicial - monto_pen
        logger.info(
            "Aplicar transacción | trans_id=%s cuenta=%s tipo=%s monto=%.2f PEN saldo_inicial=%.2f saldo_esperado=%.2f",
            trans_id,
            cuenta_final,
            tipo,
            monto_pen,
            saldo_inicial or 0.0,
            esperado,
        )
    except Exception:
        logger.debug("No se pudo obtener saldo inicial para logging de transacción")

    actualizar_saldo_cuenta(cuenta_final, tipo, monto_pen)
    return trans_id

def pagar_deuda(deuda_id, monto, moneda_pago, cuenta_banco, nota=""):
    """
    Registra un pago de deuda usando una cuenta de tipo Banco.
    - Aumenta MontoPagado en Deudas
    - Descuenta saldo de la cuenta banco
    - Registra una transacción tipo Gasto con DeudaID
    """
    sincronizar_estado_deudas()

    deuda = obtener_deuda_por_id(deuda_id)
    if not deuda:
        raise ValueError(f"No existe la deuda ID '{deuda_id}'.")

    if not es_cuenta_banco(cuenta_banco):
        raise ValueError(f"La cuenta '{cuenta_banco}' no es de tipo Banco.")

    row_deuda = deuda["_row"]
    deuda_id_str = str(deuda.get("ID", "")).strip()
    descripcion = str(deuda.get("Descripcion", "")).strip() or f"Deuda {deuda_id_str}"
    moneda_deuda = str(deuda.get("Moneda", "PEN")).upper()
    fecha_venc_actual = parsear_fecha(deuda.get("FechaVencimiento"))

    monto_total = parsear_numero(deuda.get("MontoTotal", 0))
    monto_pagado = parsear_numero(deuda.get("MontoPagado", 0))
    pendiente = round(monto_total - monto_pagado, 2)

    estado_norm = normalizar_texto(deuda.get("Estado", ""))
    if pendiente <= 0 or estado_norm == "pagada":
        raise ValueError(
            f"La deuda '{deuda_id_str}' ya está pagada. No puedes registrar otro pago sobre el mismo ciclo."
        )
    if estado_norm not in {"activa", "vencida"}:
        raise ValueError(
            f"La deuda '{deuda_id_str}' está en estado '{deuda.get('Estado', '')}'. Solo se pueden pagar deudas activas o vencidas."
        )

    monto_pago_origen = parsear_numero(monto)
    if monto_pago_origen <= 0:
        raise ValueError("El monto de pago debe ser mayor a 0.")

    pago_en_moneda_deuda = round(convertir_moneda(monto_pago_origen, moneda_pago, moneda_deuda), 2)
    tipo_deuda_norm = normalizar_texto(deuda.get("Tipo", ""))

    if tipo_deuda_norm == "servicio":
        # Regla de negocio: servicios se pagan por monto exacto.
        if abs(pago_en_moneda_deuda - pendiente) > 0.01:
            raise ValueError(
                f"Para deudas de Servicio el pago debe ser exacto. "
                f"Pendiente actual: {moneda_deuda} {pendiente:,.2f}"
            )
    else:
        if pago_en_moneda_deuda > pendiente:
            raise ValueError(
                f"El pago excede la deuda pendiente. Pendiente actual: {moneda_deuda} {pendiente:,.2f}"
            )

    # Verificar saldo disponible en banco (se maneja en PEN en la hoja Cuentas).
    pago_en_pen = convertir_a_pen(monto_pago_origen, moneda_pago)
    saldo_banco = obtener_saldo_actual_cuenta(cuenta_banco)
    if saldo_banco is None:
        raise ValueError(f"No existe la cuenta '{cuenta_banco}'.")
    if saldo_banco < pago_en_pen:
        raise ValueError(
            f"Saldo insuficiente en {cuenta_banco}. Disponible PEN {saldo_banco:,.2f}, "
            f"requerido PEN {pago_en_pen:,.2f}."
        )

    # Actualizar MontoPagado en la deuda y reducir la deuda pendiente de la cuenta asociada.
    nuevo_pagado = round(monto_pagado + pago_en_moneda_deuda, 2)
    logger.info(
        "Pago deuda | deuda_id=%s fila=F%s pagado_actual=%.2f pago_registrado=%.2f pagado_nuevo=%.2f moneda=%s",
        deuda_id_str,
        row_deuda,
        monto_pagado,
        pago_en_moneda_deuda,
        nuevo_pagado,
        moneda_deuda,
    )
    deudas_ws.update(f"F{row_deuda}", [[nuevo_pagado]], value_input_option="RAW")
    _cache_invalidate("deudas_records")
    cuenta_asociada = str(deuda.get("CuentaAsociada", "")).strip()
    if cuenta_asociada:
        actualizar_saldo_cuenta(cuenta_asociada, "ingreso", pago_en_pen)

    # Avanzar vencimiento un mes en cada pago registrado.
    # Si el pago completa la deuda, marcamos la fila actual como Pagada y
    # creamos una nueva instancia si la deuda es recurrente (p.ej. Servicios).
    fecha_venc_nueva = avanzar_un_mes(fecha_venc_actual)
    pendiente_nuevo = round(monto_total - nuevo_pagado, 2)
    if pendiente_nuevo <= 0:
        # Marcar actual como Pagada
        logger.info("Marcar deuda pagada | deuda_id=%s fila=H%s", deuda_id_str, row_deuda)
        deudas_ws.update(f"H{row_deuda}", [["Pagada"]], value_input_option="RAW")
        # Determinar si la deuda debe recrearse como siguiente ciclo.
        tipo_norm = normalizar_texto(deuda.get("Tipo", ""))
        recurrente_flag = str(deuda.get("Recurrente", "")).strip().lower()
        es_recurrente = tipo_norm == "servicio" or recurrente_flag in ("si", "true", "1", "yes")
        nueva_deuda_id = None
        if es_recurrente:
            # Crear nueva fila de deuda para el siguiente ciclo
            next_id = _siguiente_id_deuda()
            nueva_deuda_id = str(next_id)
            nueva_fecha_venc = fecha_venc_nueva.strftime("%d/%m/%Y") if fecha_venc_nueva else ""
            # Para servicios recurrentes, prefijar el monto del siguiente ciclo con el monto anterior.
            if tipo_norm == "servicio" or recurrente_flag in ("si", "true", "1", "yes"):
                monto_inicial = round(float(monto_total), 2)
            else:
                monto_inicial = 0.00

            nueva_fila = [
                nueva_deuda_id,
                deuda.get("Descripcion", ""),
                deuda.get("Tipo", ""),
                monto_inicial,
                deuda.get("Moneda", "PEN"),
                0.00,
                nueva_fecha_venc,
                "Activa" if (fecha_venc_nueva and fecha_venc_nueva.date() <= get_now().date()) else "Programada",
                deuda.get("CuentaAsociada", ""),
            ]
            logger.info(
                "Crear nueva deuda recurrente | nueva_deuda_id=%s monto=%.2f moneda=%s cuenta_asociada=%s",
                nueva_deuda_id,
                monto_inicial,
                deuda.get("Moneda", "PEN"),
                deuda.get("CuentaAsociada", ""),
            )
            deudas_ws.append_row(nueva_fila, value_input_option="RAW")
            _cache_invalidate("deudas_records")
    # NOTE: no actualizar la fecha de vencimiento en pagos parciales.
    # El vencimiento del ciclo se mantiene hasta que el ciclo sea marcado como Pagada
    # y (si corresponde) se cree la nueva fila para el siguiente ciclo.

    # Registrar transacción del pago de deuda.
    trans_id = f"TX{obtener_siguiente_id(trans_ws):05d}"
    fecha = get_now().isoformat(timespec="seconds")
    nota_final = f"Pago deuda {deuda_id_str}: {descripcion}"
    if nota:
        nota_final = f"{nota_final}. {nota}"

    fila = [
        trans_id,
        fecha,
        "Gasto",
        round(float(monto_pago_origen), 2),
        (moneda_pago or "PEN").upper(),
        "Deudas",
        "Pago",
        cuenta_banco,
        "Transferencia",
        nota_final,
        deuda_id_str,
    ]
    logger.info(
        "Registrar transacción pago deuda | trans_id=%s cuenta=%s monto_registrado=%.2f moneda=%s deuda_id=%s",
        trans_id,
        cuenta_banco,
        round(float(monto_pago_origen), 2),
        (moneda_pago or "PEN").upper(),
        deuda_id_str,
    )
    trans_ws.append_row(fila, value_input_option="RAW")
    _cache_invalidate("transacciones_records", "cuentas_records", "deudas_records")

    # Descontar saldo del banco.
    actualizar_saldo_cuenta(cuenta_banco, "gasto", pago_en_pen)
    sincronizar_estado_deudas()

    pendiente_nuevo = round(monto_total - nuevo_pagado, 2)
    resultado = {
        "trans_id": trans_id,
        "deuda_id": deuda_id_str,
        "cuenta": cuenta_banco,
        "pagado": pago_en_moneda_deuda,
        "moneda_deuda": moneda_deuda,
        "pendiente": max(0.0, pendiente_nuevo),
        "vencimiento_anterior": fecha_venc_actual.strftime("%d/%m/%Y") if fecha_venc_actual else "",
        "vencimiento_nuevo": fecha_venc_nueva.strftime("%d/%m/%Y"),
    }
    if 'nueva_deuda_id' in locals() and nueva_deuda_id:
        resultado['nueva_deuda_id'] = nueva_deuda_id

    return resultado

# ---------- CONSULTAS PARA COMANDOS ----------
def obtener_resumen_cuentas():
    """Devuelve saldo de cada cuenta, total activos, total pasivos (créditos) y patrimonio neto"""
    cuentas = _leer_records_cacheados(cuentas_ws, "cuentas_records")
    resumen = []
    total_activos = 0.0
    total_pasivos = 0.0
    for i, c in enumerate(cuentas, start=2):
        # Leer SaldoActual directamente de la celda F con FORMATTED_VALUE para evitar truncamiento
        celda_saldo = cuentas_ws.acell(f"F{i}", value_render_option="FORMATTED_VALUE").value
        saldo = parsear_numero(celda_saldo if celda_saldo is not None else c.get("SaldoActual", 0))
        tipo = normalizar_texto(c.get("Tipo", ""))
        if tipo in ["efectivo", "banco", "ahorro"]:
            total_activos += saldo
        elif tipo == "credito":
            total_pasivos += saldo
        resumen.append({
            "nombre": c["Nombre"],
            "tipo": c["Tipo"],
            "saldo": saldo,
            "moneda": c["Moneda"]
        })
    patrimonio = total_activos - total_pasivos
    return {
        "cuentas": resumen,
        "total_activos": total_activos,
        "total_pasivos": total_pasivos,
        "patrimonio": patrimonio
    }

def obtener_balance_mes(mes=None, año=None):
    """Calcula ingresos, gastos y ahorro de un mes específico (por defecto mes actual)"""
    if mes is None or año is None:
        ahora = get_now()
        mes = ahora.month
        año = ahora.year

    # Leer valores con FORMATTED_VALUE para evitar truncamiento de montos
    # Rango: B2:E1000 = Fecha, Tipo, Monto, Moneda (sin ID)
    valores_formateados = _leer_rango_formateado("Transacciones", "B2:E1000")
    
    if not valores_formateados:
        logger.warning(f"No se encontraron valores en rango B2:E1000 de Transacciones")
        return {
            "mes": mes,
            "año": año,
            "ingresos": 0.0,
            "gastos": 0.0,
            "ahorro": 0.0,
        }

    logger.info(f"Leyendo {len(valores_formateados)} filas de Transacciones para {mes:02d}/{año}")
    
    ingresos = 0.0
    gastos = 0.0
    filas_procesadas = 0
    
    # Encabezados esperados: Fecha(B), Tipo(C), Monto(D), Moneda(E)
    for fila in valores_formateados:
        if not fila or len(fila) < 4:  # Mínimo: Fecha, Tipo, Monto, Moneda
            continue
            
        try:
            fecha = parsear_fecha(fila[0] if len(fila) > 0 else "")  # Columna B
            if not fecha:
                continue

            if fecha.year == año and fecha.month == mes:
                tipo = normalizar_texto(fila[1] if len(fila) > 1 else "")  # Columna C
                monto_str = fila[2] if len(fila) > 2 else "0"  # Columna D
                moneda = str(fila[3] if len(fila) > 3 else "PEN").upper()  # Columna E
                
                monto = parsear_numero(monto_str)
                monto_pen = convertir_a_pen(monto, moneda)

                if tipo == "ingreso":
                    ingresos += monto_pen
                    filas_procesadas += 1
                elif tipo == "gasto":
                    gastos += monto_pen
                    filas_procesadas += 1
        except (IndexError, ValueError) as e:
            logger.debug(f"Error al procesar fila de balance: {e}, fila: {fila}")
            continue

    logger.info(f"Balance {mes:02d}/{año}: {filas_procesadas} filas procesadas, Ingresos={ingresos}, Gastos={gastos}")
    
    ahorro = ingresos - gastos
    return {
        "mes": mes,
        "año": año,
        "ingresos": ingresos,
        "gastos": gastos,
        "ahorro": ahorro
    }

def obtener_gasto_por_categoria(categoria_input, mes=None, año=None):
    """Gasto acumulado en una categoría para un mes (por defecto actual)"""
    # Validar categoría y obtener nombre original
    categoria_original = validar_categoria(categoria_input, "Gasto")
    if mes is None or año is None:
        ahora = get_now()
        mes = ahora.month
        año = ahora.year

    # Leer valores con FORMATTED_VALUE para evitar truncamiento de montos
    # Rango: B2:F1000 = Fecha, Tipo, Monto, Moneda, Categoría (sin ID)
    valores_con_cat = _leer_rango_formateado("Transacciones", "B2:F1000")
    
    if not valores_con_cat:
        return {
            "categoria": categoria_original,
            "mes": mes,
            "año": año,
            "total": 0.0,
        }

    total = 0.0
    
    # Encabezados: Fecha(B), Tipo(C), Monto(D), Moneda(E), Categoría(F)
    for fila in valores_con_cat:
        if not fila or len(fila) < 5:
            continue
            
        try:
            tipo = normalizar_texto(fila[1] if len(fila) > 1 else "")  # Columna C
            if tipo != "gasto":
                continue

            categoria_registro = str(fila[4] if len(fila) > 4 else "").strip()  # Columna F
            if categoria_registro != categoria_original:
                continue

            fecha = parsear_fecha(fila[0] if len(fila) > 0 else "")  # Columna B
            if not fecha:
                continue

            if fecha.year == año and fecha.month == mes:
                monto_str = fila[2] if len(fila) > 2 else "0"  # Columna D
                moneda = str(fila[3] if len(fila) > 3 else "PEN").upper()  # Columna E
                monto = parsear_numero(monto_str)
                total += convertir_a_pen(monto, moneda)
        except (IndexError, ValueError):
            continue

    return {
        "categoria": categoria_original,
        "mes": mes,
        "año": año,
        "total": total
    }

def obtener_deudas_activas():
    """Lista deudas (tarjetas) con saldo pendiente > 0 o estado 'Activa'"""
    sincronizar_estado_deudas()
    # Usar obtener_deudas_con_fila() que lee con FORMATTED_VALUE
    deudas = obtener_deudas_con_fila()
    activas = []
    for d in deudas:
        if normalizar_texto(d.get("Estado", "")) != "activa":
            continue
        monto_total = parsear_numero(d.get("MontoTotal", 0))
        monto_pagado = parsear_numero(d.get("MontoPagado", 0))
        pendiente = monto_total - monto_pagado
        if pendiente > 0:
            activas.append({
                "id": str(d.get("ID", "")).strip(),
                "descripcion": d.get("Descripcion", ""),
                "pendiente": pendiente,
                "moneda": d.get("Moneda", "PEN"),
                "vencimiento": d.get("FechaVencimiento", ""),
                "cuenta": d.get("CuentaAsociada", "")
            })
    return activas

def obtener_recordatorios_deudas(dias_alerta=3, fecha_referencia=None):
    """Retorna deudas vencidas o por vencer dentro de `dias_alerta`."""
    if fecha_referencia is None:
        fecha_referencia = get_now()

    sincronizar_estado_deudas(fecha_referencia)
    recordatorios = []

    for d in obtener_deudas_con_fila():
        estado = normalizar_texto(d.get("Estado", ""))
        if estado not in ["activa", "vencida"]:
            continue

        monto_total = parsear_numero(d.get("MontoTotal", 0))
        monto_pagado = parsear_numero(d.get("MontoPagado", 0))
        pendiente = round(monto_total - monto_pagado, 2)
        if pendiente <= 0:
            continue

        fecha_venc = parsear_fecha(d.get("FechaVencimiento"))
        if not fecha_venc:
            continue

        dias_restantes = (fecha_venc.date() - fecha_referencia.date()).days
        if dias_restantes <= dias_alerta:
            recordatorios.append({
                "id": str(d.get("ID", "")).strip(),
                "descripcion": d.get("Descripcion", ""),
                "cuenta": d.get("CuentaAsociada", ""),
                "moneda": d.get("Moneda", "PEN"),
                "pendiente": pendiente,
                "vencimiento": fecha_venc.strftime("%d/%m/%Y"),
                "dias_restantes": dias_restantes,
                "estado": d.get("Estado", ""),
            })

    recordatorios.sort(key=lambda x: x["dias_restantes"])
    return recordatorios

def _valor_campo(registro, *keys, default=""):
    for key in keys:
        if key in registro:
            return registro.get(key)
    return default


def _siguiente_id_snapshot():
    next_num = obtener_siguiente_id(snap_ws, prefix="SH")
    return f"SH{int(next_num):05d}"


def generar_snapshot_saldos(origen="Manual", fecha=None):
    """Guarda una foto de saldos actuales por cuenta en SaldosHistoricos."""
    fecha_dt = parsear_fecha(fecha) if fecha else None
    if fecha_dt is None:
        fecha_dt = get_now()

    snapshot_id = _siguiente_id_snapshot()
    cuentas = _leer_records_cacheados(cuentas_ws, "cuentas_records")
    
    # Leer SaldoActual con FORMATTED_VALUE para evitar truncamiento
    saldos_formateados = _leer_rango_formateado("Cuentas", "F2:F100")
    saldos_dict = {}
    for idx, fila in enumerate(saldos_formateados):
        if fila:
            saldos_dict[idx + 2] = fila[0] if fila else "0"
    
    filas = []
    total_pen = 0.0

    for i, c in enumerate(cuentas, start=2):
        nombre = str(c.get("Nombre", "")).strip()
        tipo = str(c.get("Tipo", "")).strip()
        moneda = str(c.get("Moneda", "PEN")).strip().upper() or "PEN"

        # Usar valor formateado si está disponible, sino usar del diccionario
        saldo_valor = saldos_dict.get(i) or c.get("SaldoActual", 0)
        saldo = round(parsear_numero(saldo_valor), 2)
        
        try:
            saldo_pen = round(convertir_a_pen(saldo, moneda), 2)
        except ValueError:
            saldo_pen = saldo

        total_pen += saldo_pen
        filas.append(
            [
                snapshot_id,
                fecha_dt.isoformat(timespec="seconds"),
                nombre,
                tipo,
                moneda,
                saldo,
                saldo_pen,
                origen,
            ]
        )

    if filas:
        for fila in filas:
            snap_ws.append_row(fila, value_input_option="RAW")

    return {
        "snapshot_id": snapshot_id,
        "cuentas": len(filas),
        "total_pen": round(total_pen, 2),
        "fecha": fecha_dt.strftime("%Y-%m-%d %H:%M:%S"),
    }


def obtener_datos_reporte_mensual(mes=None, año=None):
    """
    Retorna métricas y agregados del mes para construir reportes visuales.
    Todos los cálculos monetarios se normalizan a PEN.
    """
    if mes is None or año is None:
        ahora = datetime.now()
        mes = ahora.month
        año = ahora.year

    # Leer con FORMATTED_VALUE para evitar truncamiento
    # Rango: B2:H1000 = Fecha, Tipo, Monto, Moneda, Categoría, Cuenta, Nota (sin ID)
    valores = _leer_rango_formateado("Transacciones", "B2:H1000")
    
    if not valores:
        return {
            "mes": mes,
            "año": año,
            "generado_en": now_str(),
            "kpis": {
                "ingresos": 0.0,
                "gastos": 0.0,
                "ahorro": 0.0,
                "total_transacciones": 0,
            },
            "categoria_top": None,
            "transaccion_mayor": None,
            "gastos_por_categoria": {},
            "uso_cuentas": {},
            "movimientos": [],
        }

    movimientos = []
    
    # Encabezados: Fecha(B), Tipo(C), Monto(D), Moneda(E), Categoría(F), Cuenta(G), Nota(H)
    for fila in valores:
        if not fila or len(fila) < 4:
            continue
            
        try:
            fecha_raw = fila[0] if len(fila) > 0 else ""  # Columna B
            fecha_dt = parsear_fecha(fecha_raw)
            if not fecha_dt:
                continue
            if fecha_dt.year != año or fecha_dt.month != mes:
                continue

            tipo = str(fila[1] if len(fila) > 1 else "").strip().capitalize()  # Columna C
            monto_str = fila[2] if len(fila) > 2 else "0"  # Columna D
            moneda = str(fila[3] if len(fila) > 3 else "PEN").upper()  # Columna E
            monto = parsear_numero(monto_str)
            monto_pen = convertir_a_pen(monto, moneda)

            categoria = str(fila[4] if len(fila) > 4 else "Sin categoría").strip() or "Sin categoría"  # Columna F
            cuenta = str(fila[5] if len(fila) > 5 else "Sin cuenta").strip() or "Sin cuenta"  # Columna G
            nota = str(fila[6] if len(fila) > 6 else "").strip()  # Columna H
            tx_id = fecha_dt.strftime("%Y%m%d") + "-" + tipo[:1]  # ID generado a partir de fecha y tipo

            movimientos.append({
                "id": tx_id,
                "fecha": fecha_dt,
                "tipo": tipo,
                "monto": monto,
                "moneda": moneda,
                "monto_pen": monto_pen,
                "categoria": categoria,
                "cuenta": cuenta,
                "nota": nota,
            })
        except (IndexError, ValueError):
            continue

    ingresos = sum(m["monto_pen"] for m in movimientos if normalizar_texto(m["tipo"]) == "ingreso")
    gastos = sum(m["monto_pen"] for m in movimientos if normalizar_texto(m["tipo"]) == "gasto")
    ahorro = ingresos - gastos
    total_transacciones = len(movimientos)

    gastos_por_categoria = {}
    uso_cuentas = {}
    for m in movimientos:
        if normalizar_texto(m["tipo"]) == "gasto":
            gastos_por_categoria[m["categoria"]] = gastos_por_categoria.get(m["categoria"], 0.0) + m["monto_pen"]

        if m["cuenta"] not in uso_cuentas:
            uso_cuentas[m["cuenta"]] = {"conteo": 0, "monto_pen": 0.0}
        uso_cuentas[m["cuenta"]]["conteo"] += 1
        uso_cuentas[m["cuenta"]]["monto_pen"] += m["monto_pen"]

    gastos_por_categoria = dict(
        sorted(gastos_por_categoria.items(), key=lambda x: x[1], reverse=True)
    )
    uso_cuentas = dict(
        sorted(uso_cuentas.items(), key=lambda x: x[1]["conteo"], reverse=True)
    )

    categoria_top = None
    if gastos_por_categoria:
        cat, val = next(iter(gastos_por_categoria.items()))
        categoria_top = {"categoria": cat, "monto_pen": val}

    transaccion_mayor = None
    if movimientos:
        tx = max(movimientos, key=lambda x: x["monto_pen"])
        transaccion_mayor = {
            "id": tx["id"],
            "fecha": tx["fecha"].strftime("%Y-%m-%d"),
            "tipo": tx["tipo"],
            "categoria": tx["categoria"],
            "cuenta": tx["cuenta"],
            "monto_pen": tx["monto_pen"],
        }

    return {
        "mes": mes,
        "año": año,
        "generado_en": now_str(),
        "kpis": {
            "ingresos": ingresos,
            "gastos": gastos,
            "ahorro": ahorro,
            "total_transacciones": total_transacciones,
        },
        "categoria_top": categoria_top,
        "transaccion_mayor": transaccion_mayor,
        "gastos_por_categoria": gastos_por_categoria,
        "uso_cuentas": uso_cuentas,
        "movimientos": movimientos,
    }