import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import calendar
import unicodedata
import re
import config
import logging
from gspread.exceptions import WorksheetNotFound

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

try:
    creds = Credentials.from_service_account_file(config.GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(config.SPREADSHEET_ID)
    logger.info("Conexión a Google Sheets exitosa.")
except Exception as e:
    logger.error(f"Error al conectar con Google Sheets: {e}")
    raise

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
    if (datetime.now() - timestamp).total_seconds() > _CACHE_TTL_SECONDS:
        _SHEET_CACHE.pop(key, None)
        return None
    return value


def _cache_set(key, value):
    _SHEET_CACHE[key] = (datetime.now(), value)
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

def parsear_fecha(valor):
    """Intenta parsear fechas en formatos frecuentes de la hoja."""
    if isinstance(valor, datetime):
        return valor

    txt = str(valor or "").strip()
    if not txt:
        return None

    formatos = [
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%d-%m-%Y",
        "%d/%m/%Y %H:%M:%S",
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
        fecha_base = datetime.now()

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
def obtener_siguiente_id(worksheet):
    try:
        col_a = worksheet.col_values(1)
        if len(col_a) <= 1:
            return 1
        ultimo_valor = col_a[-1]
        if ultimo_valor.startswith("TX"):
            num = int(ultimo_valor[2:])
            return num + 1
        else:
            return len(col_a)
    except Exception as e:
        logger.error(f"Error obteniendo siguiente ID: {e}")
        return len(worksheet.col_values(1))

def convertir_a_pen(monto, moneda):
    if moneda.upper() == "PEN":
        return monto
    elif moneda.upper() == "USD":
        return monto * config.EXCHANGE_RATE
    else:
        raise ValueError(f"Moneda no soportada: {moneda}")


def _metodo_por_cuenta(nombre_cuenta):
    tipo = normalizar_texto(obtener_tipo_cuenta(nombre_cuenta) or "")
    if tipo == "credito":
        return "Tarjeta de Crédito"
    if tipo == "debito":
        return "Tarjeta de Débito"
    if tipo == "banco":
        return "Transferencia"
    return "Efectivo"


def _siguiente_id_pendiente():
    try:
        col_a = pend_ws.col_values(1)
        if len(col_a) <= 1:
            return "MP00001"
        ultimo = str(col_a[-1]).strip().upper()
        if ultimo.startswith("MP"):
            return f"MP{int(ultimo[2:]) + 1:05d}"
        return f"MP{len(col_a):05d}"
    except Exception:
        return f"MP{len(pend_ws.col_values(1)):05d}"


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
    fila = [
        pend_id,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        fuente,
        cuenta_info["Nombre"],
        "Ingreso" if tipo_norm == "ingreso" else "Gasto",
        round(float(monto_num), 2),
        (moneda or "PEN").upper(),
        descripcion,
        referencia,
        "Pendiente",
        confianza,
        "",
        "",
        observacion,
    ]
    pend_ws.append_row(fila, value_input_option="RAW")
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

    nota = descripcion
    if referencia:
        nota = f"{nota} | Ref: {referencia}" if nota else f"Ref: {referencia}"
    if nota_extra:
        nota = f"{nota}. {nota_extra}" if nota else nota_extra
    # Si es un pago a tarjeta de crédito (pago de deuda), intentar usar pagar_deuda
    tx_id = None
    if es_cuenta_credito(cuenta):
        desc_norm = normalizar_texto(descripcion)
        if "pago" in desc_norm or "pago de tarjeta" in desc_norm or "pago tarjeta" in desc_norm:
            deuda = obtener_deuda_activa_por_cuenta(cuenta)
            if deuda:
                deuda_id = str(deuda.get("ID", "")).strip()
                # Intentar detectar la cuenta banco origen por últimos 4 dígitos en la descripción
                source_account = None
                for suf in re.findall(r"(\d{4})", descripcion or ""):
                    cand = detectar_cuenta_por_ultimos_digitos(suf)
                    if cand and es_cuenta_banco(cand.get("Nombre", "")):
                        source_account = cand.get("Nombre")
                        break
                # Si no se detectó, usar la cuenta asociada en la deuda
                if not source_account:
                    source_account = deuda.get("CuentaAsociada")
                if source_account and es_cuenta_banco(source_account):
                    try:
                        pago_res = pagar_deuda(deuda_id, monto, moneda, source_account, nota)
                        tx_id = pago_res.get("trans_id")
                    except Exception as e:
                        # Si falla el pago automático, caer al registro normal
                        logger.warning(f"No se pudo registrar pago de deuda automáticamente: {e}")

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
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pend_ws.update(f"J{row}:N{row}", [["Confirmado", "", tx_id, ahora, nota_extra]], value_input_option="RAW")
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
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pend_ws.update(f"J{row}:N{row}", [["Descartado", "", "", ahora, motivo]], value_input_option="RAW")
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
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
    deudas = _leer_records_cacheados(deudas_ws, "deudas_records")
    resultado = []
    for i, d in enumerate(deudas, start=2):
        d["_row"] = i
        resultado.append(d)
    return resultado

def sincronizar_estado_deudas(fecha_referencia=None):
    """Actualiza Estado según vencimiento y pendiente."""
    if fecha_referencia is None:
        fecha_referencia = datetime.now()

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
        fecha_transaccion = datetime.now()

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

    candidatas.sort(key=lambda x: x.get("_fecha_venc") or datetime.max)
    return candidatas[0]

def incrementar_deuda_por_gasto(nombre_cuenta, monto, moneda, fecha_transaccion=None):
    """Incrementa MontoTotal de la deuda activa asociada a una cuenta de crédito."""
    if fecha_transaccion is None:
        fecha_transaccion = datetime.now()

    deuda = obtener_deuda_activa_por_cuenta(nombre_cuenta, fecha_transaccion)
    if not deuda:
        return ""

    row = deuda["_row"]
    deuda_id = str(deuda.get("ID", "")).strip()
    moneda_deuda = str(deuda.get("Moneda", "PEN")).upper()
    monto_origen = parsear_numero(monto)
    monto_convertido = convertir_moneda(monto_origen, moneda, moneda_deuda)

    monto_total_actual = parsear_numero(deuda.get("MontoTotal", 0))
    nuevo_total = round(monto_total_actual + monto_convertido, 2)
    deudas_ws.update(f"D{row}", [[nuevo_total]], value_input_option="RAW")
    _cache_invalidate("deudas_records")

    logger.info(
        "Deuda update | id=%s cuenta=%s fila=%s moneda_deuda=%s celda_raw='%s' "
        "monto_actual=%.2f gasto_origen=%.2f %s gasto_convertido=%.2f %s nuevo_total=%.2f",
        deuda_id,
        nombre_cuenta,
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
    try:
        col_a = deudas_ws.col_values(1)
        if len(col_a) <= 1:
            return 1
        ultimo = str(col_a[-1]).strip()
        try:
            return int(ultimo) + 1
        except Exception:
            return len(col_a)
    except Exception:
        return len(deudas_ws.col_values(1))

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

    _aplicar_reversa_saldo(tipo, cuenta, monto, moneda)

    if normalizar_texto(tipo) == "gasto" and deuda_id:
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
        nuevo["fecha"] = fecha_dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        raise ValueError("Campo no soportado. Usa monto, moneda, categoria, subcategoria, cuenta, metodo, nota o fecha.")

    # Revertir impacto anterior
    _aplicar_reversa_saldo(actual["tipo"], actual["cuenta"], actual["monto"], actual["moneda"])
    if normalizar_texto(actual["tipo"]) == "gasto" and actual["deuda_id"]:
        ajustar_monto_deuda(actual["deuda_id"], -actual["monto"], actual["moneda"])

    # Reaplicar impacto nuevo
    nuevo_deuda_id = ""
    fecha_nueva_dt = parsear_fecha(nuevo["fecha"]) or datetime.now()
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
    saldo_actual = parsear_numero(cuenta.get("SaldoActual", 0))

    if tipo_transaccion.lower() == "ingreso":
        nuevo_saldo = saldo_actual + monto_pen
    elif tipo_transaccion.lower() == "gasto":
        nuevo_saldo = saldo_actual - monto_pen
    else:
        return False

    nuevo_saldo = round(nuevo_saldo, 2)
    cuentas_ws.update(f"F{fila}", [[nuevo_saldo]], value_input_option="RAW")
    _cache_invalidate("cuentas_records")
    logger.info(f"Saldo de '{nombre_cuenta}' actualizado: {saldo_actual} -> {nuevo_saldo}")
    return True

def obtener_saldo_actual_cuenta(nombre_cuenta):
    cuenta = obtener_cuenta_por_nombre(nombre_cuenta)
    if not cuenta:
        return None
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
        fecha_dt = datetime.now()
    fecha = fecha_dt.strftime("%Y-%m-%d %H:%M:%S")

    # Asegura que Monto viaje como número, no como texto.
    monto_num = round(float(monto), 2)

    cuenta_info = obtener_cuenta_por_nombre(cuenta)
    cuenta_final = cuenta_info["Nombre"] if cuenta_info else cuenta

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

    # Actualizar MontoPagado en la deuda.
    nuevo_pagado = round(monto_pagado + pago_en_moneda_deuda, 2)
    deudas_ws.update(f"F{row_deuda}", [[nuevo_pagado]], value_input_option="RAW")
    _cache_invalidate("deudas_records")

    # Avanzar vencimiento un mes en cada pago registrado.
    # Si el pago completa la deuda, marcamos la fila actual como Pagada y
    # creamos una nueva instancia si la deuda es recurrente (p.ej. Servicios).
    fecha_venc_nueva = avanzar_un_mes(fecha_venc_actual)
    pendiente_nuevo = round(monto_total - nuevo_pagado, 2)
    if pendiente_nuevo <= 0:
        # Marcar actual como Pagada
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
            nueva_fila = [
                nueva_deuda_id,
                deuda.get("Descripcion", ""),
                deuda.get("Tipo", ""),
                round(float(monto_total), 2),
                deuda.get("Moneda", "PEN"),
                0.00,
                nueva_fecha_venc,
                "Activa" if (fecha_venc_nueva and fecha_venc_nueva.date() <= datetime.now().date()) else "Programada",
                deuda.get("CuentaAsociada", ""),
            ]
            deudas_ws.append_row(nueva_fila, value_input_option="RAW")
            _cache_invalidate("deudas_records")
    else:
        # Si no se completó, actualizar la fecha de vencimiento si procede
        deudas_ws.update(f"G{row_deuda}", [[fecha_venc_nueva.strftime("%d/%m/%Y")]], value_input_option="RAW")
        _cache_invalidate("deudas_records")

    # Registrar transacción del pago de deuda.
    trans_id = f"TX{obtener_siguiente_id(trans_ws):05d}"
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
        saldo = parsear_numero(c.get("SaldoActual", 0))
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
        ahora = datetime.now()
        mes = ahora.month
        año = ahora.year

    valores = _leer_values_cacheados(trans_ws, "transacciones_values")
    if not valores or len(valores) <= 1:
        return {
            "mes": mes,
            "año": año,
            "ingresos": 0.0,
            "gastos": 0.0,
            "ahorro": 0.0,
        }

    headers = valores[0]
    transacciones = [dict(zip(headers, fila)) for fila in valores[1:] if any(str(c).strip() for c in fila)]

    ingresos = 0.0
    gastos = 0.0
    for t in transacciones:
        fecha = parsear_fecha(_valor_campo(t, "Fecha", default=""))
        if not fecha:
            continue

        if fecha.year == año and fecha.month == mes:
            monto = parsear_numero(_valor_campo(t, "Monto", default=0))
            moneda = str(_valor_campo(t, "Moneda", default="PEN")).upper()
            monto_pen = convertir_a_pen(monto, moneda)

            tipo = normalizar_texto(_valor_campo(t, "Tipo", default=""))
            if tipo == "ingreso":
                ingresos += monto_pen
            elif tipo == "gasto":
                gastos += monto_pen

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
        ahora = datetime.now()
        mes = ahora.month
        año = ahora.year

    valores = _leer_values_cacheados(trans_ws, "transacciones_values")
    if not valores or len(valores) <= 1:
        return {
            "categoria": categoria_original,
            "mes": mes,
            "año": año,
            "total": 0.0,
        }

    headers = valores[0]
    transacciones = [dict(zip(headers, fila)) for fila in valores[1:] if any(str(c).strip() for c in fila)]

    total = 0.0
    for t in transacciones:
        tipo = normalizar_texto(_valor_campo(t, "Tipo", default=""))
        if tipo != "gasto":
            continue

        categoria_registro = str(_valor_campo(t, "Categoría", "Categoria", default="")).strip()
        if categoria_registro != categoria_original:
            continue

        fecha = parsear_fecha(_valor_campo(t, "Fecha", default=""))
        if not fecha:
            continue

        if fecha.year == año and fecha.month == mes:
            monto = parsear_numero(_valor_campo(t, "Monto", default=0))
            moneda = str(_valor_campo(t, "Moneda", default="PEN")).upper()
            total += convertir_a_pen(monto, moneda)

    return {
        "categoria": categoria_original,
        "mes": mes,
        "año": año,
        "total": total
    }

def obtener_deudas_activas():
    """Lista deudas (tarjetas) con saldo pendiente > 0 o estado 'Activa'"""
    sincronizar_estado_deudas()
    deudas = _leer_records_cacheados(deudas_ws, "deudas_records")
    activas = []
    for i, d in enumerate(deudas, start=2):
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
        fecha_referencia = datetime.now()

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
    try:
        col_a = snap_ws.col_values(1)
        if len(col_a) <= 1:
            return "SH00001"
        ultimo = str(col_a[-1]).strip().upper()
        if ultimo.startswith("SH"):
            return f"SH{int(ultimo[2:]) + 1:05d}"
        return f"SH{len(col_a):05d}"
    except Exception:
        return f"SH{len(snap_ws.col_values(1)):05d}"


def generar_snapshot_saldos(origen="Manual", fecha=None):
    """Guarda una foto de saldos actuales por cuenta en SaldosHistoricos."""
    fecha_dt = parsear_fecha(fecha) if fecha else None
    if fecha_dt is None:
        fecha_dt = datetime.now()

    snapshot_id = _siguiente_id_snapshot()
    cuentas = _leer_records_cacheados(cuentas_ws, "cuentas_records")
    filas = []
    total_pen = 0.0

    for i, c in enumerate(cuentas, start=2):
        nombre = str(c.get("Nombre", "")).strip()
        tipo = str(c.get("Tipo", "")).strip()
        moneda = str(c.get("Moneda", "PEN")).strip().upper() or "PEN"

        saldo = round(parsear_numero(c.get("SaldoActual", 0)), 2)
        try:
            saldo_pen = round(convertir_a_pen(saldo, moneda), 2)
        except ValueError:
            saldo_pen = saldo

        total_pen += saldo_pen
        filas.append(
            [
                snapshot_id,
                fecha_dt.strftime("%Y-%m-%d %H:%M:%S"),
                nombre,
                tipo,
                moneda,
                saldo,
                saldo_pen,
                origen,
            ]
        )

    if filas:
        snap_ws.append_rows(filas, value_input_option="RAW")

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

    # Usar valores formateados para respetar configuración regional de la hoja.
    valores = _leer_values_cacheados(trans_ws, "transacciones_values")
    if not valores or len(valores) <= 1:
        return {
            "mes": mes,
            "año": año,
            "generado_en": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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

    headers = valores[0]
    transacciones = [dict(zip(headers, fila)) for fila in valores[1:] if any(str(c).strip() for c in fila)]
    movimientos = []

    for t in transacciones:
        fecha_raw = _valor_campo(t, "Fecha", default="")
        fecha_dt = parsear_fecha(fecha_raw)
        if not fecha_dt:
            continue
        if fecha_dt.year != año or fecha_dt.month != mes:
            continue

        tipo = str(_valor_campo(t, "Tipo", default="")).strip().capitalize()
        monto = parsear_numero(_valor_campo(t, "Monto", default=0))
        moneda = str(_valor_campo(t, "Moneda", default="PEN")).upper()
        monto_pen = convertir_a_pen(monto, moneda)

        categoria = str(_valor_campo(t, "Categoría", "Categoria", default="Sin categoría")).strip() or "Sin categoría"
        cuenta = str(_valor_campo(t, "Cuenta", default="Sin cuenta")).strip() or "Sin cuenta"
        nota = str(_valor_campo(t, "Nota", default="")).strip()
        tx_id = str(_valor_campo(t, "ID", default="")).strip()

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
        "generado_en": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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