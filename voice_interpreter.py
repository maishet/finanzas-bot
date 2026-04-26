import re
import unicodedata
from datetime import datetime


STOPWORDS = {
    "de",
    "del",
    "la",
    "el",
    "los",
    "las",
    "por",
    "para",
    "con",
    "en",
    "y",
    "un",
    "una",
    "al",
    "mi",
    "mis",
    "su",
    "sus",
    "que",
    "se",
    "me",
    "te",
    "a",
}

MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "setiembre": 9,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

INTENT_PATTERNS = {
    "resumen": [
        "como voy",
        "como estoy",
        "como van mis cuentas",
        "estado de cuentas",
        "muestrame el resumen",
        "ver resumen",
        "balance general",
        "patrimonio neto",
        "total de cuentas",
    ],
    "reporte": [
        "cierre mensual",
        "cierre del mes",
        "genera el reporte",
        "generar reporte",
        "exportar pdf",
        "descargar reporte",
        "informe mensual",
        "saca el reporte",
    ],
    "mes": [
        "balance mensual",
        "balance del mes",
        "cuanto gaste",
        "cuanto gasté",
        "que gaste",
        "que gasté",
        "cuanto ingrese",
        "cuanto ingresé",
        "gastos del mes",
        "ingresos del mes",
    ],
    "categoria": [
        "gasto en",
        "gastos en",
        "por categoria",
        "por categoría",
        "en la categoria",
        "en la categoría",
        "cuanto gaste en",
        "cuanto gasté en",
    ],
    "deudas": [
        "que debo",
        "que deudas tengo",
        "mis deudas",
        "deudas activas",
        "cuanto debo",
        "lo pendiente",
    ],
    "recordatorios": [
        "que vence pronto",
        "que vence hoy",
        "cuando vence",
        "vencen mis deudas",
        "alertas de deuda",
        "recordatorios",
    ],
    "categorias": [
        "listar categorias",
        "listar categorías",
        "ver categorias",
        "ver categorías",
        "mostrar categorias",
        "mostrar categorías",
        "que categorias hay",
    ],
    "pagar": [
        "pagar deuda",
        "abonar deuda",
        "hacer un pago",
        "pagar la tarjeta",
        "abonar a la tarjeta",
        "pagar cuota",
        "cancelar deuda",
    ],
    "editar": [
        "editar transaccion",
        "editar transacción",
        "modificar transaccion",
        "modificar transacción",
        "corregir transaccion",
        "corregir transacción",
        "cambiar el monto",
    ],
    "eliminar": [
        "eliminar transaccion",
        "eliminar transacción",
        "borrar transaccion",
        "borrar transacción",
        "quitar transaccion",
        "quitar transacción",
    ],
}


def normalizar_texto(texto):
    if not texto:
        return ""
    txt = texto.lower().strip()
    txt = unicodedata.normalize("NFD", txt)
    txt = txt.encode("ascii", "ignore").decode("utf-8")
    return txt


def clasificar_intencion(texto_norm):
    """Clasificador simple de intención (fallback asistido)."""
    scores = {
        "reporte": 0,
        "resumen": 0,
        "mes": 0,
        "categoria": 0,
        "deudas": 0,
        "recordatorios": 0,
        "pagar": 0,
        "ingreso": 0,
        "gasto": 0,
        "eliminar": 0,
        "editar": 0,
        "categorias": 0,
    }

    for intent, frases in INTENT_PATTERNS.items():
        for frase in frases:
            if frase in texto_norm:
                scores[intent] += 6

    kw_reporte = ["reporte", "pdf", "exporta", "exportar", "cierre mensual", "informe"]
    kw_resumen = ["resumen", "saldos", "patrimonio", "cuentas", "como voy", "como estoy"]
    kw_mes = ["mes", "balance", "gastos del mes", "ingresos del mes", "cuanto gaste", "cuanto ingrese"]
    kw_categoria = ["categoria", "categoría", "por categoria", "por categoría", "gasto en", "gastos en"]
    kw_deudas = ["deudas", "deuda", "pendiente", "tarjetas", "que debo", "cuanto debo"]
    kw_recordatorios = ["recordatorios", "recordatorio", "vencen", "vencimiento", "vence pronto", "vence hoy"]
    kw_eliminar = ["eliminar", "borra", "borrar", "elimina", "quitar"]
    kw_editar = ["editar", "edita", "corrige", "modifica", "cambiar el monto"]
    kw_categorias = ["categorias", "categorías", "lista de categorias", "lista de categorías", "ver categorias"]
    kw_pagar = ["pagar", "paga", "abonar", "abono", "deuda", "cuota", "tarjeta"]
    kw_ingreso = ["ingreso", "ingrese", "cobre", "deposito", "depositaron", "me pagaron", "sueldo", "venta", "me abonaron"]
    kw_gasto = ["gasto", "gaste", "compre", "pague", "consumo", "consumi", "almuerzo", "comida", "mercado", "gaste en"]

    for kw in kw_reporte:
        if kw in texto_norm:
            scores["reporte"] += 3
    for kw in kw_resumen:
        if kw in texto_norm:
            scores["resumen"] += 3
    for kw in kw_mes:
        if kw in texto_norm:
            scores["mes"] += 3
    for kw in kw_categoria:
        if kw in texto_norm:
            scores["categoria"] += 3
    for kw in kw_deudas:
        if kw in texto_norm:
            scores["deudas"] += 3
    for kw in kw_recordatorios:
        if kw in texto_norm:
            scores["recordatorios"] += 3
    for kw in kw_eliminar:
        if kw in texto_norm:
            scores["eliminar"] += 3
    for kw in kw_editar:
        if kw in texto_norm:
            scores["editar"] += 3
    for kw in kw_categorias:
        if kw in texto_norm:
            scores["categorias"] += 3

    for kw in kw_pagar:
        if kw in texto_norm:
            scores["pagar"] += 2
    for kw in kw_ingreso:
        if kw in texto_norm:
            scores["ingreso"] += 2
    for kw in kw_gasto:
        if kw in texto_norm:
            scores["gasto"] += 2

    # Sesgos suaves para frases comunes.
    if "deuda" in texto_norm and "pagar" in texto_norm:
        scores["pagar"] += 2
    if any(frase in texto_norm for frase in ["como voy", "como estoy", "estado de cuentas"]):
        scores["resumen"] += 4
    if any(frase in texto_norm for frase in ["cuanto gaste", "que gaste", "cuanto ingrese", "que ingrese"]):
        scores["mes"] += 4
    if any(frase in texto_norm for frase in ["que debo", "cuanto debo", "mis deudas"]):
        scores["deudas"] += 4
    if any(frase in texto_norm for frase in ["vence pronto", "vence hoy", "cuando vence"]):
        scores["recordatorios"] += 4
    if "me pagaron" in texto_norm:
        scores["ingreso"] += 3

    orden = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not orden:
        return "gasto"
    if orden[0][1] == 0:
        if any(frase in texto_norm for frase in ["como voy", "como estoy", "estado de cuentas"]):
            return "resumen"
        if any(frase in texto_norm for frase in ["que debo", "cuanto debo", "mis deudas"]):
            return "deudas"
        if any(frase in texto_norm for frase in ["cuanto gaste", "que gaste", "cuanto ingrese", "que ingrese"]):
            return "mes"
        if any(frase in texto_norm for frase in ["vence pronto", "vence hoy", "cuando vence"]):
            return "recordatorios"
        return "gasto"
    if len(orden) > 1 and orden[0][1] == orden[1][1]:
        if orden[0][0] in ["reporte", "resumen", "mes", "categoria", "deudas", "recordatorios", "categorias", "pagar", "editar", "eliminar"]:
            return orden[0][0]
    return orden[0][0]


def extraer_monto_moneda(texto_norm):
    moneda = "PEN"
    if any(k in texto_norm for k in ["usd", "dolar", "dolares", "dólar", "dólares"]):
        moneda = "USD"

    match = re.search(r"(-?\d+[\.,]?\d*)", texto_norm)
    if not match:
        return None, moneda

    monto_str = match.group(1).replace(",", ".")
    try:
        return float(monto_str), moneda
    except ValueError:
        return None, moneda


def detectar_cuenta(texto_norm, cuentas):
    """Busca cuenta por coincidencia textual completa, priorizando nombres largos."""
    if not cuentas:
        return None

    ordenadas = sorted(cuentas, key=lambda x: len(normalizar_texto(x)), reverse=True)
    for cuenta in ordenadas:
        c_norm = normalizar_texto(cuenta)
        patron = rf"(^|\s){re.escape(c_norm)}(\s|$)"
        if re.search(patron, texto_norm):
            return cuenta
    return None


def detectar_categoria(texto_norm, categorias):
    if not categorias:
        return None

    # categorias puede ser lista de dicts o lista de strings
    nombres = []
    for c in categorias:
        if isinstance(c, dict):
            nombre = str(c.get("original") or c.get("Nombre") or "").strip()
            if nombre:
                nombres.append(nombre)
        else:
            nombres.append(str(c).strip())

    nombres = [n for n in nombres if n]
    nombres = sorted(nombres, key=lambda x: len(normalizar_texto(x)), reverse=True)

    for nombre in nombres:
        n_norm = normalizar_texto(nombre)
        patron = rf"(^|\s){re.escape(n_norm)}(\s|$)"
        if re.search(patron, texto_norm):
            return nombre
    return None


def extraer_periodo(texto_norm):
    hoy = datetime.now()
    if "mes pasado" in texto_norm or "mes anterior" in texto_norm:
        if hoy.month == 1:
            return 12, hoy.year - 1
        return hoy.month - 1, hoy.year
    if "este mes" in texto_norm or "mes actual" in texto_norm or "del mes" in texto_norm:
        return hoy.month, hoy.year

    m = re.search(r"\b(0?[1-9]|1[0-2])\s*[/-]\s*(\d{2,4})\b", texto_norm)
    if m:
        mes = int(m.group(1))
        año = int(m.group(2))
        if año < 100:
            año += 2000
        return mes, año

    for nombre_mes, numero_mes in MESES.items():
        if nombre_mes in texto_norm:
            if "pasado" in texto_norm or "anterior" in texto_norm:
                if hoy.month == 1:
                    return 12, hoy.year - 1
                return hoy.month - 1, hoy.year
            return numero_mes, hoy.year

    return hoy.month, hoy.year


def extraer_id_transaccion_o_deuda(texto_norm):
    m = re.search(r"\b(?:id\s*)?(\d{1,6})\b", texto_norm)
    return m.group(1) if m else None


def _fallback_categoria_por_tokens(texto_norm, cuentas, keywords):
    tokens = re.findall(r"[a-zA-Z0-9]+", texto_norm)
    cuentas_norm = {normalizar_texto(c) for c in cuentas}
    keywords_norm = {normalizar_texto(k) for k in keywords}

    for tok in tokens:
        if tok in STOPWORDS:
            continue
        if tok in cuentas_norm:
            continue
        if tok in keywords_norm:
            continue
        if re.fullmatch(r"\d+[\.,]?\d*", tok):
            continue
        return tok.capitalize()
    return None


def interpretar_transcripcion(texto, cuentas, categorias_gasto, categorias_ingreso):
    """Devuelve payload de comando interno listo para confirmar/ejecutar."""
    texto = (texto or "").strip()
    texto_norm = normalizar_texto(texto)

    intencion = clasificar_intencion(texto_norm)
    monto, moneda = extraer_monto_moneda(texto_norm)
    cuenta = detectar_cuenta(texto_norm, cuentas) or "Efectivo"

    payload = {
        "intent": intencion,
        "raw_text": texto,
    }

    if intencion in {"resumen", "deudas", "recordatorios", "categorias"}:
        payload.update({"cuenta": cuenta})
        return payload

    if intencion in {"reporte", "mes"}:
        mes, año = extraer_periodo(texto_norm)
        payload.update({"mes": mes, "anio": año})
        return payload

    if intencion == "categoria":
        categoria = detectar_categoria(texto_norm, categorias_gasto) or _fallback_categoria_por_tokens(
            texto_norm,
            cuentas,
            keywords=["categoria", "categoria", "gasto", "del mes"],
        )
        payload.update({"categoria": categoria, "mes": extraer_periodo(texto_norm)[0], "anio": extraer_periodo(texto_norm)[1]})
        return payload

    if intencion == "pagar":
        deuda_id = None
        m_deuda = re.search(r"deuda\s*(id\s*)?(\d+)", texto_norm)
        if m_deuda:
            deuda_id = m_deuda.group(2)
        else:
            deuda_id = extraer_id_transaccion_o_deuda(texto_norm)

        payload.update({
            "deuda_id": deuda_id,
            "monto": monto,
            "moneda": moneda,
            "cuenta": cuenta,
            "nota": texto,
        })
        return payload

    if intencion in {"editar", "eliminar"}:
        trans_id = extraer_id_transaccion_o_deuda(texto_norm)
        campo = None
        valor = None
        if intencion == "editar":
            campo_match = re.search(r"\b(monto|moneda|categoria|subcategoria|cuenta|metodo|nota|fecha)\b", texto_norm)
            if campo_match:
                campo = campo_match.group(1)
            if campo:
                resto = texto_norm.split(campo, 1)[-1].strip()
                valor = resto.lstrip("=:- ").strip() or None

        payload.update({
            "trans_id": trans_id,
            "campo": campo,
            "valor": valor,
        })
        return payload

    if intencion == "ingreso":
        categoria = detectar_categoria(texto_norm, categorias_ingreso)
        if not categoria:
            categoria = _fallback_categoria_por_tokens(
                texto_norm,
                cuentas,
                keywords=["ingreso", "sueldo", "deposito", "depositaron", "cobre", "me pagaron"],
            )

        payload.update({
            "monto": monto,
            "moneda": moneda,
            "categoria": categoria,
            "cuenta": cuenta,
            "nota": texto,
        })
        return payload

    # gasto por defecto
    categoria = detectar_categoria(texto_norm, categorias_gasto)
    if not categoria:
        categoria = _fallback_categoria_por_tokens(
            texto_norm,
            cuentas,
            keywords=["gasto", "gaste", "compre", "pague", "consumo", "consumi", "tarjeta"],
        )

    payload.update({
        "monto": monto,
        "moneda": moneda,
        "categoria": categoria,
        "cuenta": cuenta,
        "nota": texto,
    })
    return payload


def validar_payload(payload):
    intent = payload.get("intent")
    if intent in {"resumen", "deudas", "recordatorios", "categorias"}:
        return True, ""

    if intent in {"reporte", "mes"}:
        if not payload.get("mes") or not payload.get("anio"):
            return False, "No pude identificar el mes y el año."
        return True, ""

    if intent == "categoria":
        if not payload.get("categoria"):
            return False, "No pude identificar la categoría."
        if not payload.get("mes") or not payload.get("anio"):
            return False, "No pude identificar el mes y el año."
        return True, ""

    if intent == "pagar":
        if not payload.get("deuda_id"):
            return False, "No pude identificar el ID de la deuda."
        if not payload.get("monto") or payload.get("monto") <= 0:
            return False, "No pude identificar un monto válido para el pago."
        if not payload.get("cuenta") or payload.get("cuenta") == "Efectivo":
            return False, "Para pagar deuda necesito una cuenta de tipo Banco (ej. BCP)."
        return True, ""

    if intent == "eliminar":
        if not payload.get("trans_id"):
            return False, "No pude identificar el ID de la transacción."
        return True, ""

    if intent == "editar":
        if not payload.get("trans_id"):
            return False, "No pude identificar el ID de la transacción."
        if not payload.get("campo"):
            return False, "No pude identificar el campo a editar."
        if payload.get("valor") in [None, ""]:
            return False, "No pude identificar el nuevo valor."
        return True, ""

    if not payload.get("monto") or payload.get("monto") <= 0:
        return False, "No pude identificar un monto válido."
    if not payload.get("categoria"):
        return False, "No pude identificar la categoría."

    return True, ""
