import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import unicodedata
import re
import config
import logging

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

    # Caso típico LATAM: 1.234,56
    if "," in txt and "." in txt and txt.rfind(",") > txt.rfind("."):
        txt = txt.replace(".", "").replace(",", ".")
    # Solo coma: 123,45
    elif "," in txt and "." not in txt:
        txt = txt.replace(",", ".")

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

# ---------- CATEGORÍAS Y SUBCATEGORÍAS ----------
def obtener_categorias(tipo=None):
    """Obtiene todas las categorías con sus subcategorías"""
    registros = categorias_ws.get_all_records()
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
        registros = cuentas_ws.get_all_records()
        return [c["Nombre"] for c in registros]
    except Exception as e:
        logger.error(f"Error obteniendo nombres de cuentas: {e}")
        return ["Efectivo"]

def obtener_cuenta_por_nombre(nombre_input):
    """
    Busca una cuenta por nombre, ignorando tildes y mayúsculas.
    Retorna diccionario con datos de la cuenta y número de fila.
    """
    input_norm = normalizar_texto(nombre_input)
    cuentas = cuentas_ws.get_all_records()
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
    cuentas = cuentas_ws.get_all_records()

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
    return None

# ---------- DEUDAS ----------
def obtener_deudas_con_fila():
    deudas = deudas_ws.get_all_records()
    resultado = []
    for i, d in enumerate(deudas, start=2):
        d["_row"] = i
        d["MontoTotal"] = deudas_ws.acell(f"D{i}", value_render_option="FORMATTED_VALUE").value
        d["MontoPagado"] = deudas_ws.acell(f"F{i}", value_render_option="FORMATTED_VALUE").value
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

    # Leer el valor formateado directamente de la celda para evitar ambigüedades regionales.
    celda_monto_total = deudas_ws.acell(f"D{row}", value_render_option="FORMATTED_VALUE").value
    monto_total_actual = parsear_numero(celda_monto_total if celda_monto_total is not None else deuda.get("MontoTotal", 0))
    nuevo_total = round(monto_total_actual + monto_convertido, 2)
    deudas_ws.update(f"D{row}", [[nuevo_total]], value_input_option="RAW")

    logger.info(
        "Deuda update | id=%s cuenta=%s fila=%s moneda_deuda=%s celda_raw='%s' "
        "monto_actual=%.2f gasto_origen=%.2f %s gasto_convertido=%.2f %s nuevo_total=%.2f",
        deuda_id,
        nombre_cuenta,
        row,
        moneda_deuda,
        celda_monto_total,
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

def ajustar_monto_deuda(deuda_id, delta_monto, moneda_delta):
    """Ajusta MontoTotal de una deuda por ID. delta positivo suma, negativo resta."""
    deuda = obtener_deuda_por_id(deuda_id)
    if not deuda:
        logger.warning(f"No se encontró deuda ID '{deuda_id}' para ajuste.")
        return False

    row = deuda["_row"]
    moneda_deuda = str(deuda.get("Moneda", "PEN")).upper()
    delta_convertido = convertir_moneda(parsear_numero(delta_monto), moneda_delta, moneda_deuda)

    celda_monto_total = deudas_ws.acell(f"D{row}", value_render_option="FORMATTED_VALUE").value
    monto_total_actual = parsear_numero(celda_monto_total if celda_monto_total is not None else deuda.get("MontoTotal", 0))
    nuevo_total = round(monto_total_actual + delta_convertido, 2)
    if nuevo_total < 0:
        nuevo_total = 0.0

    deudas_ws.update(f"D{row}", [[nuevo_total]], value_input_option="RAW")
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

    transacciones = trans_ws.get_all_records()
    for i, t in enumerate(transacciones, start=2):
        if str(t.get("ID", "")).strip().upper() == trans_id_norm:
            t["_row"] = i
            t["Monto"] = trans_ws.acell(f"D{i}", value_render_option="FORMATTED_VALUE").value
            return t
    return None

def _aplicar_reversa_saldo(tipo, cuenta, monto, moneda):
    monto_pen = convertir_a_pen(parsear_numero(monto), moneda)
    if normalizar_texto(tipo) == "ingreso":
        return actualizar_saldo_cuenta(cuenta, "gasto", monto_pen)
    return actualizar_saldo_cuenta(cuenta, "ingreso", monto_pen)

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
    celda_saldo = cuentas_ws.acell(f"E{fila}", value_render_option="FORMATTED_VALUE").value
    saldo_actual = parsear_numero(celda_saldo if celda_saldo is not None else cuenta.get("SaldoActual", 0))

    if tipo_transaccion.lower() == "ingreso":
        nuevo_saldo = saldo_actual + monto_pen
    elif tipo_transaccion.lower() == "gasto":
        nuevo_saldo = saldo_actual - monto_pen
    else:
        return False

    nuevo_saldo = round(nuevo_saldo, 2)
    cuentas_ws.update(f"E{fila}", [[nuevo_saldo]], value_input_option="RAW")
    logger.info(f"Saldo de '{nombre_cuenta}' actualizado: {saldo_actual} -> {nuevo_saldo}")
    return True

def obtener_saldo_actual_cuenta(nombre_cuenta):
    cuenta = obtener_cuenta_por_nombre(nombre_cuenta)
    if not cuenta:
        return None
    fila = cuenta["_row"]
    celda_saldo = cuentas_ws.acell(f"E{fila}", value_render_option="FORMATTED_VALUE").value
    return parsear_numero(celda_saldo if celda_saldo is not None else cuenta.get("SaldoActual", 0))

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

    celda_total = deudas_ws.acell(f"D{row_deuda}", value_render_option="FORMATTED_VALUE").value
    celda_pagado = deudas_ws.acell(f"F{row_deuda}", value_render_option="FORMATTED_VALUE").value
    monto_total = parsear_numero(celda_total if celda_total is not None else deuda.get("MontoTotal", 0))
    monto_pagado = parsear_numero(celda_pagado if celda_pagado is not None else deuda.get("MontoPagado", 0))
    pendiente = round(monto_total - monto_pagado, 2)

    if pendiente <= 0:
        raise ValueError(f"La deuda '{deuda_id_str}' no tiene saldo pendiente.")

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

    # Descontar saldo del banco.
    actualizar_saldo_cuenta(cuenta_banco, "gasto", pago_en_pen)
    sincronizar_estado_deudas()

    pendiente_nuevo = round(monto_total - nuevo_pagado, 2)
    return {
        "trans_id": trans_id,
        "deuda_id": deuda_id_str,
        "cuenta": cuenta_banco,
        "pagado": pago_en_moneda_deuda,
        "moneda_deuda": moneda_deuda,
        "pendiente": max(0.0, pendiente_nuevo),
    }

# ---------- CONSULTAS PARA COMANDOS ----------
def obtener_resumen_cuentas():
    """Devuelve saldo de cada cuenta, total activos, total pasivos (créditos) y patrimonio neto"""
    cuentas = cuentas_ws.get_all_records()
    resumen = []
    total_activos = 0.0
    total_pasivos = 0.0
    for i, c in enumerate(cuentas, start=2):
        saldo_celda = cuentas_ws.acell(f"E{i}", value_render_option="FORMATTED_VALUE").value
        saldo = parsear_numero(saldo_celda if saldo_celda is not None else c.get("SaldoActual", 0))
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
    transacciones = trans_ws.get_all_records()
    ingresos = 0.0
    gastos = 0.0
    for t in transacciones:
        fecha_str = t["Fecha"]
        try:
            fecha = datetime.strptime(fecha_str.split()[0], "%Y-%m-%d")
        except:
            continue
        if fecha.year == año and fecha.month == mes:
            monto = parsear_numero(t.get("Monto", 0))
            moneda = t["Moneda"]
            monto_pen = convertir_a_pen(monto, moneda)
            if t["Tipo"].lower() == "ingreso":
                ingresos += monto_pen
            elif t["Tipo"].lower() == "gasto":
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
    transacciones = trans_ws.get_all_records()
    total = 0.0
    for t in transacciones:
        if t["Tipo"].lower() != "gasto":
            continue
        if t["Categoría"] != categoria_original:
            continue
        fecha_str = t["Fecha"]
        try:
            fecha = datetime.strptime(fecha_str.split()[0], "%Y-%m-%d")
        except:
            continue
        if fecha.year == año and fecha.month == mes:
            monto = parsear_numero(t.get("Monto", 0))
            moneda = t["Moneda"]
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
    deudas = deudas_ws.get_all_records()
    activas = []
    for i, d in enumerate(deudas, start=2):
        if normalizar_texto(d.get("Estado", "")) != "activa":
            continue
        monto_total_cell = deudas_ws.acell(f"D{i}", value_render_option="FORMATTED_VALUE").value
        monto_pagado_cell = deudas_ws.acell(f"F{i}", value_render_option="FORMATTED_VALUE").value
        monto_total = parsear_numero(monto_total_cell if monto_total_cell is not None else d.get("MontoTotal", 0))
        monto_pagado = parsear_numero(monto_pagado_cell if monto_pagado_cell is not None else d.get("MontoPagado", 0))
        pendiente = monto_total - monto_pagado
        if pendiente > 0:
            activas.append({
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