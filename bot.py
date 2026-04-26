import logging
import os
import tempfile
from datetime import datetime, time
from functools import wraps
import httpx
import tornado.web
from telegram import Update, InputFile, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from telegram.ext import _updater as ptb_updater
from telegram.ext._utils.webhookhandler import TelegramHandler
import config
from sheets_handler import (obtener_categorias,
    add_transaction, obtener_nombres_cuentas,
    obtener_resumen_cuentas, obtener_balance_mes,
    obtener_gasto_por_categoria, obtener_deudas_activas,
    detectar_cuenta_en_texto, obtener_tipo_cuenta,
    eliminar_transaccion, editar_transaccion, obtener_recordatorios_deudas,
    pagar_deuda, obtener_datos_reporte_mensual
)
from report_generator import generar_reporte_mensual_pdf
from voice_transcriber import transcribe_audio_file, VoiceTranscriptionError
from voice_interpreter import interpretar_transcripcion, validar_payload

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

VOICE_PENDING_KEY = "voice_pending_payload"
VOICE_EDITING_KEY = "voice_editing_mode"


class HealthHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_status(200)
        self.write("ok")


class RenderWebhookApp(tornado.web.Application):
    """Webhook app con endpoints de salud para plataformas como Render."""

    def __init__(self, webhook_path, bot, update_queue, secret_token=None):
        shared_objects = {
            "bot": bot,
            "update_queue": update_queue,
            "secret_token": secret_token,
        }
        handlers = [
            (r"/", HealthHandler),
            (r"/healthz/?", HealthHandler),
            (rf"{webhook_path}/?", TelegramHandler, shared_objects),
        ]
        super().__init__(handlers)

    def log_request(self, handler: tornado.web.RequestHandler) -> None:
        return

def restricted(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id != config.USER_ID:
            await update.message.reply_text("⛔ No estás autorizado para usar este bot.")
            return
        return await func(update, context)
    return wrapper

def metodo_por_tipo_cuenta(tipo_cuenta):
    tipo_norm = (tipo_cuenta or "").strip().lower()
    if tipo_norm in ["credito", "crédito"]:
        return "Tarjeta de Crédito"
    if tipo_norm in ["debito", "débito"]:
        return "Tarjeta de Débito"
    if tipo_norm == "banco":
        return "Transferencia"
    return "Efectivo"

@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 ¡Hola! Soy tu asistente financiero personal.\n"
        "Usa /ayuda para ver los comandos disponibles."
    )

@restricted
async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = """
📌 *Comandos disponibles:*

/gasto <monto> <categoría> <nota>
Ejemplo: `/gasto 25.50 Alimentacion almuerzo tarjeta AMEX`

/ingreso <monto> <categoría> <nota>
Ejemplo: `/ingreso 1500 Sueldo quincena BCP`

/resumen - Saldos de todas las cuentas y patrimonio neto
/mes <MM/AAAA> - Balance mensual (por defecto mes actual)
/reporte <MM/AAAA> - Exporta cierre mensual en PDF con gráficos
/categoria <nombre> - Gasto del mes en una categoría
/deudas - Lista de tarjetas de crédito con saldo pendiente
/pagar <deuda_id> <monto> <cuenta_banco> [nota]
Ejemplo: `/pagar 1 250 BCP pago quincena`

/recordatorios - Ver alertas de deudas por vencer (manual)
/editar <ID> <campo> <valor> - Edita una transacción
/eliminar <ID> - Elimina una transacción
/categorias - Listado de categorías
/help o /ayuda - Mostrar este mensaje

🎤 *Notas de voz (es-PE):*
- Envía una nota de voz con el comando en lenguaje natural.
- El bot transcribe, interpreta y te pedirá confirmar antes de registrar.
- Botones: Confirmar / Editar / Cancelar

💡 *Consejos:*
- Tildes y mayúsculas se ignoran.
- Para cuentas, escribe el nombre tal cual (BCP, AMEX, Efectivo).
- Puedes usar "USD": `/gasto 20 USD Comida`
"""
    await update.message.reply_text(mensaje, parse_mode="Markdown")


def _resumen_payload(payload):
    intent = payload.get("intent")
    periodo = None
    if payload.get("mes") and payload.get("anio"):
        try:
            periodo = f"{int(payload.get('mes')):02d}/{int(payload.get('anio'))}"
        except Exception:
            periodo = f"{payload.get('mes')}/{payload.get('anio')}"

    if intent == "pagar":
        return (
            f"🧠 Interpretación detectada:\n"
            f"• Acción: Pago de deuda\n"
            f"• Deuda ID: {payload.get('deuda_id', '—')}\n"
            f"• Monto: {payload.get('moneda', 'PEN')} {payload.get('monto', 0):.2f}\n"
            f"• Cuenta banco: {payload.get('cuenta', '—')}\n"
            f"\nTexto: {payload.get('raw_text', '')}"
        )

    if intent in {"reporte", "mes"}:
        return (
            f"🧠 Interpretación detectada:\n"
            f"• Acción: {'Reporte mensual' if intent == 'reporte' else 'Balance mensual'}\n"
            f"• Periodo: {periodo or '—'}\n"
            f"\nTexto: {payload.get('raw_text', '')}"
        )

    if intent == "resumen":
        return (
            f"🧠 Interpretación detectada:\n"
            f"• Acción: Resumen de cuentas\n"
            f"\nTexto: {payload.get('raw_text', '')}"
        )

    if intent == "deudas":
        return (
            f"🧠 Interpretación detectada:\n"
            f"• Acción: Ver deudas activas\n"
            f"\nTexto: {payload.get('raw_text', '')}"
        )

    if intent == "recordatorios":
        return (
            f"🧠 Interpretación detectada:\n"
            f"• Acción: Recordatorios de deudas\n"
            f"\nTexto: {payload.get('raw_text', '')}"
        )

    if intent == "categorias":
        return (
            f"🧠 Interpretación detectada:\n"
            f"• Acción: Listar categorías\n"
            f"\nTexto: {payload.get('raw_text', '')}"
        )

    if intent == "categoria":
        return (
            f"🧠 Interpretación detectada:\n"
            f"• Acción: Gasto por categoría\n"
            f"• Categoría: {payload.get('categoria', '—')}\n"
            f"• Periodo: {periodo or '—'}\n"
            f"\nTexto: {payload.get('raw_text', '')}"
        )

    if intent == "eliminar":
        return (
            f"🧠 Interpretación detectada:\n"
            f"• Acción: Eliminar transacción\n"
            f"• ID: {payload.get('trans_id', '—')}\n"
            f"\nTexto: {payload.get('raw_text', '')}"
        )

    if intent == "editar":
        return (
            f"🧠 Interpretación detectada:\n"
            f"• Acción: Editar transacción\n"
            f"• ID: {payload.get('trans_id', '—')}\n"
            f"• Campo: {payload.get('campo', '—')}\n"
            f"• Valor: {payload.get('valor', '—')}\n"
            f"\nTexto: {payload.get('raw_text', '')}"
        )

    accion = "Gasto" if intent == "gasto" else "Ingreso"
    return (
        f"🧠 Interpretación detectada:\n"
        f"• Acción: {accion}\n"
        f"• Monto: {payload.get('moneda', 'PEN')} {payload.get('monto', 0):.2f}\n"
        f"• Categoría: {payload.get('categoria', '—')}\n"
        f"• Cuenta: {payload.get('cuenta', '—')}\n"
        f"\nTexto: {payload.get('raw_text', '')}"
    )


def _keyboard_confirmacion_voz():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar", callback_data="voice:confirm")],
        [InlineKeyboardButton("✏️ Editar", callback_data="voice:edit")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="voice:cancel")],
    ])


async def _ejecutar_payload_voz(payload, update: Update):
    intent = payload.get("intent")

    if intent in {"resumen", "deudas", "recordatorios", "categorias"}:
        if intent == "resumen":
            data = obtener_resumen_cuentas()
            mensaje = "📊 *Resumen de Cuentas*\n\n"
            for c in data["cuentas"]:
                mensaje += f"• {c['nombre']} ({c['tipo']}): {c['moneda']} {c['saldo']:,.2f}\n"
            mensaje += f"\n💰 *Total Activos*: PEN {data['total_activos']:,.2f}\n"
            mensaje += f"💳 *Total Pasivos (Créditos)*: PEN {data['total_pasivos']:,.2f}\n"
            mensaje += f"📈 *Patrimonio Neto*: PEN {data['patrimonio']:,.2f}"
            await update.effective_message.reply_text(mensaje, parse_mode="Markdown")
            return

        if intent == "deudas":
            deudas_activas = obtener_deudas_activas()
            if not deudas_activas:
                await update.effective_message.reply_text("✅ No tienes deudas activas registradas.")
                return
            mensaje = "💳 *Deudas Activas*\n\n"
            for d in deudas_activas:
                mensaje += f"• {d['descripcion']}\n"
                mensaje += f"   Pendiente: {d['moneda']} {d['pendiente']:,.2f}\n"
                mensaje += f"   Vence: {d['vencimiento']}\n"
                if d['cuenta']:
                    mensaje += f"   Cuenta asociada: {d['cuenta']}\n"
                mensaje += "\n"
            await update.effective_message.reply_text(mensaje, parse_mode="Markdown")
            return

        if intent == "recordatorios":
            recordatorios = obtener_recordatorios_deudas(dias_alerta=7)
            if not recordatorios:
                await update.effective_message.reply_text("✅ No hay deudas por vencer en los próximos 7 días.")
                return
            lineas = ["⏰ *Recordatorios de Deudas (manual)*"]
            for r in recordatorios:
                if r["dias_restantes"] < 0:
                    estado = f"Vencida hace {abs(r['dias_restantes'])} día(s)"
                elif r["dias_restantes"] == 0:
                    estado = "Vence hoy"
                else:
                    estado = f"Vence en {r['dias_restantes']} día(s)"

                lineas.append(
                    f"\n• {r['descripcion']} ({r['cuenta']})\n"
                    f"  Pendiente: {r['moneda']} {r['pendiente']:,.2f}\n"
                    f"  Vencimiento: {r['vencimiento']} - {estado}"
                )

            await update.effective_message.reply_text("\n".join(lineas), parse_mode="Markdown")
            return

        if intent == "categorias":
            categorias = obtener_categorias()
            gastos = [c for c in categorias if c["tipo"].lower() == "gasto"]
            ingresos = [c for c in categorias if c["tipo"].lower() == "ingreso"]

            def formatear_lista(lista_cat):
                if not lista_cat:
                    return "• (ninguna)"
                lineas = []
                for cat in sorted(lista_cat, key=lambda x: x["original"]):
                    lineas.append(f"• {cat['original']}")
                    subs = cat.get("subcategorias", "")
                    if subs and subs.strip():
                        for sub in subs.split(";"):
                            sub = sub.strip()
                            if sub:
                                lineas.append(f"  - {sub}")
                return "\n".join(lineas)

            mensaje = "📂 *CATEGORÍAS DISPONIBLES*\n\n"
            mensaje += "📤 *Gastos:*\n"
            mensaje += formatear_lista(gastos)
            mensaje += "\n\n📥 *Ingresos:*\n"
            mensaje += formatear_lista(ingresos)
            await update.effective_message.reply_text(mensaje, parse_mode="Markdown")
            return

    if intent == "pagar":
        data = pagar_deuda(
            deuda_id=str(payload.get("deuda_id")).strip(),
            monto=float(payload.get("monto")),
            moneda_pago=payload.get("moneda", "PEN"),
            cuenta_banco=payload.get("cuenta", ""),
            nota=payload.get("raw_text", ""),
        )
        await update.effective_message.reply_text(
            f"✅ Pago de deuda registrado\n"
            f"🆔 Deuda: {data['deuda_id']}\n"
            f"💸 Pago: {data['moneda_deuda']} {data['pagado']:.2f}\n"
            f"🏦 Cuenta: {data['cuenta']}\n"
            f"📉 Pendiente: {data['moneda_deuda']} {data['pendiente']:.2f}\n"
            f"📅 Vencimiento anterior: {data.get('vencimiento_anterior', '—') or '—'}\n"
            f"📆 Nuevo vencimiento: {data.get('vencimiento_nuevo', '—')}\n"
            f"🧾 TX: {data['trans_id']}"
        )
        return

    if intent in {"reporte", "mes"}:
        mes = int(payload.get("mes"))
        anio = int(payload.get("anio"))
        if intent == "mes":
            data = obtener_balance_mes(mes, anio)
            mensaje = f"📅 *Balance {mes:02d}/{anio}*\n\n"
            mensaje += f"📥 Ingresos: PEN {data['ingresos']:,.2f}\n"
            mensaje += f"📤 Gastos: PEN {data['gastos']:,.2f}\n"
            mensaje += f"💵 Ahorro: PEN {data['ahorro']:,.2f}"
            await update.effective_message.reply_text(mensaje, parse_mode="Markdown")
            return

        datos = obtener_datos_reporte_mensual(mes, anio)
        if datos["kpis"]["total_transacciones"] == 0:
            await update.effective_message.reply_text(f"ℹ️ No hay transacciones para {mes:02d}/{anio}.")
            return
        pdf_buffer = generar_reporte_mensual_pdf(datos)
        filename = f"reporte_finanzas_{anio}_{mes:02d}.pdf"
        await update.effective_message.reply_document(
            document=InputFile(pdf_buffer, filename=filename),
            caption=f"📄 Cierre mensual {mes:02d}/{anio} generado con gráficos y KPIs.",
        )
        return

    if intent == "categoria":
        categoria = payload.get("categoria")
        mes = int(payload.get("mes"))
        anio = int(payload.get("anio"))
        data = obtener_gasto_por_categoria(categoria, mes, anio)
        mensaje = f"📊 *Gasto en {data['categoria']}*\n"
        mensaje += f"📅 {mes:02d}/{anio}: PEN {data['total']:,.2f}"
        await update.effective_message.reply_text(mensaje, parse_mode="Markdown")
        return

    if intent == "eliminar":
        data = eliminar_transaccion(str(payload.get("trans_id")).strip())
        await update.effective_message.reply_text(
            f"🗑️ Transacción eliminada\n"
            f"🆔 {data['id']}\n"
            f"📌 {data['tipo']} {data['moneda']} {data['monto']:.2f}\n"
            f"🏦 Cuenta: {data['cuenta']}"
        )
        return

    if intent == "editar":
        data = editar_transaccion(
            str(payload.get("trans_id")).strip(),
            str(payload.get("campo")).strip(),
            str(payload.get("valor")).strip(),
        )
        mensaje = (
            f"✏️ Transacción editada\n"
            f"🆔 {data['id']}\n"
            f"🔧 {data['campo']} -> {data['valor']}"
        )
        if data.get("deuda_id"):
            mensaje += f"\n💳 Deuda asociada: {data['deuda_id']}"
        await update.effective_message.reply_text(mensaje)
        return

    if intent == "ingreso":
        trans_id = add_transaction(
            "Ingreso",
            float(payload.get("monto")),
            payload.get("moneda", "PEN"),
            payload.get("categoria", ""),
            "",
            payload.get("cuenta", "Efectivo"),
            "Transferencia" if payload.get("cuenta", "Efectivo") != "Efectivo" else "Efectivo",
            payload.get("raw_text", ""),
        )
        await update.effective_message.reply_text(f"✅ Ingreso registrado. 🆔 {trans_id}")
        return

    # gasto por defecto
    cuenta = payload.get("cuenta", "Efectivo")
    tipo_cuenta = obtener_tipo_cuenta(cuenta)
    metodo = metodo_por_tipo_cuenta(tipo_cuenta)
    trans_id = add_transaction(
        "Gasto",
        float(payload.get("monto")),
        payload.get("moneda", "PEN"),
        payload.get("categoria", ""),
        "",
        cuenta,
        metodo,
        payload.get("raw_text", ""),
    )
    await update.effective_message.reply_text(f"✅ Gasto registrado. 🆔 {trans_id}")


async def _interpretar_y_confirmar(texto, update: Update, context: ContextTypes.DEFAULT_TYPE):
    cuentas = obtener_nombres_cuentas()
    categorias_gasto = obtener_categorias("Gasto")
    categorias_ingreso = obtener_categorias("Ingreso")

    payload = interpretar_transcripcion(
        texto=texto,
        cuentas=cuentas,
        categorias_gasto=categorias_gasto,
        categorias_ingreso=categorias_ingreso,
    )

    ok, msg = validar_payload(payload)
    if not ok:
        await update.effective_message.reply_text(
            f"⚠️ {msg}\n"
            f"Envíame una corrección en texto con más detalle."
        )
        context.user_data[VOICE_EDITING_KEY] = True
        return

    context.user_data[VOICE_PENDING_KEY] = payload
    context.user_data[VOICE_EDITING_KEY] = False

    await update.effective_message.reply_text(
        _resumen_payload(payload),
        reply_markup=_keyboard_confirmacion_voz(),
    )


@restricted
async def procesar_nota_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not config.VOICE_ENABLED:
        await update.message.reply_text("⚠️ El módulo de voz está desactivado.")
        return

    voice = update.message.voice or update.message.audio
    if not voice:
        await update.message.reply_text("⚠️ No pude leer el audio enviado.")
        return

    await update.message.reply_text("🎤 Recibido. Transcribiendo nota de voz...")

    try:
        tg_file = await context.bot.get_file(voice.file_id)
        tmp_path = None
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            await tg_file.download_to_drive(custom_path=tmp_path)
            texto = transcribe_audio_file(tmp_path, language=config.VOICE_LANGUAGE)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    logger.warning(f"No se pudo borrar el temporal de voz: {tmp_path}")

        await _interpretar_y_confirmar(texto, update, context)
    except VoiceTranscriptionError as e:
        await update.message.reply_text(f"❌ Error de transcripción: {e}")
    except Exception as e:
        logger.error(f"Error procesando nota de voz: {e}")
        await update.message.reply_text("❌ No pude procesar la nota de voz.")


@restricted
async def procesar_edicion_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get(VOICE_EDITING_KEY):
        return

    texto = (update.message.text or "").strip()
    if not texto:
        await update.message.reply_text("⚠️ Envíame un texto para editar la interpretación.")
        return

    await _interpretar_y_confirmar(texto, update, context)


@restricted
async def callbacks_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = (query.data or "").strip()
    payload = context.user_data.get(VOICE_PENDING_KEY)

    if action == "voice:cancel":
        context.user_data.pop(VOICE_PENDING_KEY, None)
        context.user_data[VOICE_EDITING_KEY] = False
        await query.edit_message_text("❌ Operación cancelada.")
        return

    if action == "voice:edit":
        context.user_data[VOICE_EDITING_KEY] = True
        await query.edit_message_text("✏️ Envíame el texto corregido para reinterpretarlo.")
        return

    if action == "voice:confirm":
        if not payload:
            await query.edit_message_text("⚠️ No hay una operación pendiente para confirmar.")
            return
        try:
            await _ejecutar_payload_voz(payload, update)
            await query.edit_message_text("✅ Confirmado y registrado.")
        except ValueError as e:
            await query.edit_message_text(f"❌ {e}")
        except Exception as e:
            logger.error(f"Error ejecutando payload de voz: {e}")
            await query.edit_message_text("❌ Error inesperado al ejecutar la operación.")
        finally:
            context.user_data.pop(VOICE_PENDING_KEY, None)
            context.user_data[VOICE_EDITING_KEY] = False

@restricted
async def procesar_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.replace("/gasto", "").strip()
    if not texto:
        await update.message.reply_text("⚠️ Uso: `/gasto <monto> <categoría> [nota]`", parse_mode="Markdown")
        return

    partes = texto.split()
    if len(partes) < 2:
        await update.message.reply_text("❌ Debes indicar al menos monto y categoría.")
        return

    try:
        monto_str = partes[0].replace(",", ".")
        moneda = "PEN"
        idx_categoria = 1

        # Soporta ambos formatos: "20USD ..." y "20 USD ..."
        if partes[0].upper().endswith("USD"):
            monto_str = partes[0][:-3].strip()
            moneda = "USD"
        elif len(partes) >= 3 and partes[1].upper() == "USD":
            moneda = "USD"
            idx_categoria = 2

        monto = float(monto_str)
    except ValueError:
        await update.message.reply_text("❌ Monto inválido.")
        return

    if len(partes) <= idx_categoria:
        await update.message.reply_text("❌ Debes indicar la categoría después del monto.")
        return

    categoria_input = partes[idx_categoria]
    nota = " ".join(partes[idx_categoria + 1:])

    # --- Detección de cuenta y método ---
    cuenta = "Efectivo"
    metodo = "Efectivo"

    # Obtener cuentas reales de la hoja
    try:
        nombres_cuentas = obtener_nombres_cuentas()
        logger.info(f"Cuentas disponibles: {nombres_cuentas}")
    except Exception as e:
        logger.error(f"Error obteniendo cuentas: {e}")
        nombres_cuentas = ["Efectivo"]

    # 1. Buscar explícitamente una cuenta en la nota (soporta nombres compuestos)
    cuenta_info = detectar_cuenta_en_texto(nota)
    if cuenta_info:
        cuenta = cuenta_info["Nombre"]
        metodo = metodo_por_tipo_cuenta(cuenta_info.get("Tipo"))
    else:
        # 2. Si no se detecta cuenta explícita, conservar fallback y derivar método por tipo real.
        tipo_cuenta = obtener_tipo_cuenta(cuenta)
        metodo = metodo_por_tipo_cuenta(tipo_cuenta)

    # Si después de todo la cuenta es "Efectivo" pero no existe en la hoja, advertir (pero no falla)
    if cuenta == "Efectivo" and "Efectivo" not in nombres_cuentas:
        logger.warning("Cuenta 'Efectivo' no está en la hoja Cuentas. Se usará pero no se actualizará saldo.")

    try:
        trans_id = add_transaction(
            tipo="Gasto",
            monto=monto,
            moneda=moneda,
            categoria_input=categoria_input,
            subcategoria="",
            cuenta=cuenta,
            metodo=metodo,
            nota=nota
        )
        await update.message.reply_text(
            f"✅ Gasto: {moneda} {monto:.2f}\n"
            f"📂 {categoria_input}\n"
            f"📝 {nota if nota else '—'}\n"
            f"💳 {cuenta} ({metodo})\n"
            f"🆔 {trans_id}"
        )
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
    except Exception as e:
        logger.error(f"Error gasto: {e}")
        await update.message.reply_text("❌ Error inesperado.")

@restricted
async def procesar_ingreso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.replace("/ingreso", "").strip()
    if not texto:
        await update.message.reply_text("⚠️ Uso: `/ingreso <monto> <categoría> [nota]`", parse_mode="Markdown")
        return

    partes = texto.split()
    if len(partes) < 2:
        await update.message.reply_text("❌ Debes indicar al menos monto y categoría.")
        return

    try:
        monto_str = partes[0].replace(",", ".")
        moneda = "PEN"
        idx_categoria = 1

        if partes[0].upper().endswith("USD"):
            monto_str = partes[0][:-3].strip()
            moneda = "USD"
        elif len(partes) >= 3 and partes[1].upper() == "USD":
            moneda = "USD"
            idx_categoria = 2

        monto = float(monto_str)
    except ValueError:
        await update.message.reply_text("❌ Monto inválido.")
        return

    if len(partes) <= idx_categoria:
        await update.message.reply_text("❌ Debes indicar la categoría después del monto.")
        return

    categoria = partes[idx_categoria]
    nota = " ".join(partes[idx_categoria + 1:])
    
    cuenta = "Efectivo"
    metodo = "Efectivo"
    try:
        nombres_cuentas = obtener_nombres_cuentas()
    except:
        nombres_cuentas = ["Efectivo"]
    cuenta_info = detectar_cuenta_en_texto(nota)
    if cuenta_info:
        cuenta = cuenta_info["Nombre"]
        metodo = metodo_por_tipo_cuenta(cuenta_info.get("Tipo"))
    else:
        tipo_cuenta = obtener_tipo_cuenta(cuenta)
        metodo = metodo_por_tipo_cuenta(tipo_cuenta)
    try:
        trans_id = add_transaction("Ingreso", monto, moneda, categoria, "", cuenta, metodo, nota)
        await update.message.reply_text(
            f"✅ Ingreso registrado: {moneda} {monto:.2f} en {categoria}\n"
            f"📝 {nota if nota else '—'}\n"
            f"🏦 Cuenta: {cuenta} ({metodo})\n"
            f"🆔 {trans_id}"
        )
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
    except Exception as e:
        logger.error(f"Error ingreso: {e}")
        await update.message.reply_text("❌ Error inesperado.")

@restricted
async def resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = obtener_resumen_cuentas()
    except Exception as e:
        await update.message.reply_text("❌ Error al obtener resumen.")
        logger.error(f"Error resumen: {e}")
        return
    mensaje = "📊 *Resumen de Cuentas*\n\n"
    for c in data["cuentas"]:
        mensaje += f"• {c['nombre']} ({c['tipo']}): {c['moneda']} {c['saldo']:,.2f}\n"
    mensaje += f"\n💰 *Total Activos*: PEN {data['total_activos']:,.2f}\n"
    mensaje += f"💳 *Total Pasivos (Créditos)*: PEN {data['total_pasivos']:,.2f}\n"
    mensaje += f"📈 *Patrimonio Neto*: PEN {data['patrimonio']:,.2f}"
    await update.message.reply_text(mensaje, parse_mode="Markdown")

@restricted
async def balance_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    mes = datetime.now().month
    año = datetime.now().year
    if args:
        try:
            partes = args[0].split("/")
            if len(partes) == 2:
                mes = int(partes[0])
                año = int(partes[1])
                if año < 100:
                    año += 2000
        except:
            pass
    try:
        data = obtener_balance_mes(mes, año)
    except Exception as e:
        await update.message.reply_text("❌ Error al calcular balance.")
        logger.error(f"Error balance: {e}")
        return
    mensaje = f"📅 *Balance {mes:02d}/{año}*\n\n"
    mensaje += f"📥 Ingresos: PEN {data['ingresos']:,.2f}\n"
    mensaje += f"📤 Gastos: PEN {data['gastos']:,.2f}\n"
    mensaje += f"💵 Ahorro: PEN {data['ahorro']:,.2f}"
    await update.message.reply_text(mensaje, parse_mode="Markdown")

@restricted
async def reporte_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    mes = datetime.now().month
    año = datetime.now().year

    if args:
        try:
            partes = args[0].split("/")
            if len(partes) == 2:
                mes = int(partes[0])
                año = int(partes[1])
                if año < 100:
                    año += 2000
        except Exception:
            await update.message.reply_text("⚠️ Formato inválido. Usa `/reporte MM/AAAA`", parse_mode="Markdown")
            return

    try:
        datos = obtener_datos_reporte_mensual(mes, año)
        if datos["kpis"]["total_transacciones"] == 0:
            await update.message.reply_text(f"ℹ️ No hay transacciones para {mes:02d}/{año}.")
            return

        pdf_buffer = generar_reporte_mensual_pdf(datos)
        filename = f"reporte_finanzas_{año}_{mes:02d}.pdf"
        await update.message.reply_document(
            document=InputFile(pdf_buffer, filename=filename),
            caption=f"📄 Cierre mensual {mes:02d}/{año} generado con gráficos y KPIs.",
        )
    except Exception as e:
        logger.error(f"Error generando reporte mensual: {e}")
        await update.message.reply_text("❌ Error al generar el reporte PDF.")

@restricted
async def gasto_categoria(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Uso: `/categoria <nombre>`", parse_mode="Markdown")
        return
    categoria = " ".join(context.args)
    try:
        data = obtener_gasto_por_categoria(categoria)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    except Exception as e:
        await update.message.reply_text("❌ Error al consultar categoría.")
        logger.error(f"Error categoria: {e}")
        return
    mensaje = f"📊 *Gasto en {data['categoria']}*\n"
    mensaje += f"📅 {data['mes']:02d}/{data['año']}: PEN {data['total']:,.2f}"
    await update.message.reply_text(mensaje, parse_mode="Markdown")

@restricted
async def deudas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        deudas_activas = obtener_deudas_activas()
    except Exception as e:
        await update.message.reply_text("❌ Error al obtener deudas.")
        logger.error(f"Error deudas: {e}")
        return
    if not deudas_activas:
        await update.message.reply_text("✅ No tienes deudas activas registradas.")
        return
    mensaje = "💳 *Deudas Activas*\n\n"
    for d in deudas_activas:
        mensaje += f"• {d['descripcion']}\n"
        mensaje += f"   Pendiente: {d['moneda']} {d['pendiente']:,.2f}\n"
        mensaje += f"   Vence: {d['vencimiento']}\n"
        if d['cuenta']:
            mensaje += f"   Cuenta asociada: {d['cuenta']}\n"
        mensaje += "\n"
    await update.message.reply_text(mensaje, parse_mode="Markdown")

@restricted
async def listar_categorias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        categorias = obtener_categorias()  # lista de dicts con original, tipo, subcategorias
    except Exception as e:
        await update.message.reply_text("❌ Error al obtener categorías.")
        logger.error(f"Error categorias: {e}")
        return

    # Separar por tipo y ordenar
    gastos = [c for c in categorias if c["tipo"].lower() == "gasto"]
    ingresos = [c for c in categorias if c["tipo"].lower() == "ingreso"]

    def formatear_lista(lista_cat):
        if not lista_cat:
            return "• (ninguna)"
        lineas = []
        for cat in sorted(lista_cat, key=lambda x: x["original"]):
            lineas.append(f"• {cat['original']}")
            # Agregar subcategorías si existen
            subs = cat.get("subcategorias", "")
            if subs and subs.strip():
                for sub in subs.split(";"):
                    sub = sub.strip()
                    if sub:
                        lineas.append(f"  - {sub}")
        return "\n".join(lineas)

    mensaje = "📂 *CATEGORÍAS DISPONIBLES*\n\n"
    mensaje += "📤 *Gastos:*\n"
    mensaje += formatear_lista(gastos)
    mensaje += "\n\n📥 *Ingresos:*\n"
    mensaje += formatear_lista(ingresos)

    await update.message.reply_text(mensaje, parse_mode="Markdown")

@restricted
async def eliminar_tx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Uso: `/eliminar <ID>`", parse_mode="Markdown")
        return

    trans_id = context.args[0].strip()
    try:
        data = eliminar_transaccion(trans_id)
        await update.message.reply_text(
            f"🗑️ Transacción eliminada\n"
            f"🆔 {data['id']}\n"
            f"📌 {data['tipo']} {data['moneda']} {data['monto']:.2f}\n"
            f"🏦 Cuenta: {data['cuenta']}"
        )
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
    except Exception as e:
        logger.error(f"Error eliminando transacción: {e}")
        await update.message.reply_text("❌ Error inesperado al eliminar transacción.")

@restricted
async def editar_tx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "⚠️ Uso: `/editar <ID> <campo> <valor>`\n"
            "Campos: monto, moneda, categoria, subcategoria, cuenta, metodo, nota, fecha",
            parse_mode="Markdown"
        )
        return

    trans_id = context.args[0].strip()
    campo = context.args[1].strip()
    valor = " ".join(context.args[2:]).strip()

    try:
        data = editar_transaccion(trans_id, campo, valor)
        mensaje = (
            f"✏️ Transacción editada\n"
            f"🆔 {data['id']}\n"
            f"🔧 {data['campo']} -> {data['valor']}"
        )
        if data.get("deuda_id"):
            mensaje += f"\n💳 Deuda asociada: {data['deuda_id']}"
        await update.message.reply_text(mensaje)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
    except Exception as e:
        logger.error(f"Error editando transacción: {e}")
        await update.message.reply_text("❌ Error inesperado al editar transacción.")

@restricted
async def pagar_deuda_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "⚠️ Uso: `/pagar <deuda_id> <monto> <cuenta_banco> [nota]`\n"
            "Ejemplo: `/pagar 1 250 BCP pago quincena`",
            parse_mode="Markdown"
        )
        return

    deuda_id = context.args[0].strip()
    try:
        monto = float(context.args[1].replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Monto inválido.")
        return

    cuenta_banco = context.args[2].strip()
    nota = " ".join(context.args[3:]).strip() if len(context.args) > 3 else ""

    try:
        data = pagar_deuda(
            deuda_id=deuda_id,
            monto=monto,
            moneda_pago="PEN",
            cuenta_banco=cuenta_banco,
            nota=nota,
        )
        await update.message.reply_text(
            f"✅ Pago de deuda registrado\n"
            f"🆔 Deuda: {data['deuda_id']}\n"
            f"💸 Pago: {data['moneda_deuda']} {data['pagado']:.2f}\n"
            f"🏦 Cuenta: {data['cuenta']}\n"
            f"📉 Pendiente: {data['moneda_deuda']} {data['pendiente']:.2f}\n"
            f"📅 Vencimiento anterior: {data.get('vencimiento_anterior', '—') or '—'}\n"
            f"📆 Nuevo vencimiento: {data.get('vencimiento_nuevo', '—')}\n"
            f"🧾 TX: {data['trans_id']}"
        )
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
    except Exception as e:
        logger.error(f"Error pagando deuda: {e}")
        await update.message.reply_text("❌ Error inesperado al registrar el pago de deuda.")

async def enviar_recordatorios_deuda(context: ContextTypes.DEFAULT_TYPE):
    try:
        recordatorios = obtener_recordatorios_deudas(dias_alerta=3)
    except Exception as e:
        logger.error(f"Error generando recordatorios de deuda: {e}")
        return

    if not recordatorios:
        return

    lineas = ["⏰ *Recordatorios de Deudas*"]
    for r in recordatorios:
        if r["dias_restantes"] < 0:
            estado = f"Vencida hace {abs(r['dias_restantes'])} día(s)"
        elif r["dias_restantes"] == 0:
            estado = "Vence hoy"
        else:
            estado = f"Vence en {r['dias_restantes']} día(s)"

        lineas.append(
            f"\n• {r['descripcion']} ({r['cuenta']})\n"
            f"  Pendiente: {r['moneda']} {r['pendiente']:,.2f}\n"
            f"  Vencimiento: {r['vencimiento']} - {estado}"
        )

    await context.bot.send_message(
        chat_id=config.USER_ID,
        text="\n".join(lineas),
        parse_mode="Markdown"
    )


async def enviar_keepalive(context: ContextTypes.DEFAULT_TYPE):
    """Ping periódico para evitar sleep en Render Free cuando está habilitado."""
    if not config.KEEPALIVE_ENABLED:
        return
    if not config.KEEPALIVE_URL:
        logger.warning("Keep-alive habilitado pero no hay WEBHOOK_URL/RENDER_EXTERNAL_URL configurado.")
        return

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(config.KEEPALIVE_URL)
        if 200 <= resp.status_code < 300:
            logger.info("Keep-alive ping | url=%s status=%s", config.KEEPALIVE_URL, resp.status_code)
        else:
            logger.warning("Keep-alive ping no exitoso | url=%s status=%s", config.KEEPALIVE_URL, resp.status_code)
    except Exception as e:
        logger.warning("Keep-alive ping falló | url=%s error=%s", config.KEEPALIVE_URL, e)

@restricted
async def recordatorios_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        recordatorios = obtener_recordatorios_deudas(dias_alerta=7)
    except Exception as e:
        logger.error(f"Error consultando recordatorios manuales: {e}")
        await update.message.reply_text("❌ Error al consultar recordatorios.")
        return

    if not recordatorios:
        await update.message.reply_text("✅ No hay deudas por vencer en los próximos 7 días.")
        return

    lineas = ["⏰ *Recordatorios de Deudas (manual)*"]
    for r in recordatorios:
        if r["dias_restantes"] < 0:
            estado = f"Vencida hace {abs(r['dias_restantes'])} día(s)"
        elif r["dias_restantes"] == 0:
            estado = "Vence hoy"
        else:
            estado = f"Vence en {r['dias_restantes']} día(s)"

        lineas.append(
            f"\n• {r['descripcion']} ({r['cuenta']})\n"
            f"  Pendiente: {r['moneda']} {r['pendiente']:,.2f}\n"
            f"  Vencimiento: {r['vencimiento']} - {estado}"
        )

    await update.message.reply_text("\n".join(lineas), parse_mode="Markdown")

def main():
    app = Application.builder().token(config.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", ayuda))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(CommandHandler("gasto", procesar_gasto))
    app.add_handler(CommandHandler("ingreso", procesar_ingreso))
    app.add_handler(CommandHandler("resumen", resumen))
    app.add_handler(CommandHandler("mes", balance_mes))
    app.add_handler(CommandHandler("reporte", reporte_mes))
    app.add_handler(CommandHandler("categoria", gasto_categoria))
    app.add_handler(CommandHandler("categorias", listar_categorias))
    app.add_handler(CommandHandler("deudas", deudas))
    app.add_handler(CommandHandler("pagar", pagar_deuda_cmd))
    app.add_handler(CommandHandler("pagar_deuda", pagar_deuda_cmd))
    app.add_handler(CommandHandler("recordatorios", recordatorios_cmd))
    app.add_handler(CommandHandler("editar", editar_tx))
    app.add_handler(CommandHandler("eliminar", eliminar_tx))
    app.add_handler(CallbackQueryHandler(callbacks_voz, pattern=r"^voice:"))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, procesar_nota_voz))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_edicion_voz))

    if app.job_queue is not None:
        app.job_queue.run_daily(enviar_recordatorios_deuda, time=time(hour=9, minute=0))
        app.job_queue.run_once(enviar_recordatorios_deuda, when=10)
        if config.BOT_MODE == "webhook" and config.KEEPALIVE_ENABLED:
            interval_seconds = max(60, int(config.KEEPALIVE_INTERVAL_MINUTES) * 60)
            app.job_queue.run_repeating(
                enviar_keepalive,
                interval=interval_seconds,
                first=30,
                name="keepalive_ping",
            )
            logger.info(
                "Keep-alive activo | cada %s min | url=%s",
                config.KEEPALIVE_INTERVAL_MINUTES,
                config.KEEPALIVE_URL,
            )
    else:
        logger.warning("JobQueue no disponible; recordatorios automáticos desactivados.")
    
    if config.BOT_MODE == "webhook":
        if not config.FULL_WEBHOOK_URL:
            raise ValueError(
                "BOT_MODE=webhook requiere WEBHOOK_URL o RENDER_EXTERNAL_URL configurado."
            )

        # Sustituye la app de webhook de PTB para responder 200 en / y /healthz.
        ptb_updater.WebhookAppClass = RenderWebhookApp

        logger.info(
            "Iniciando en modo webhook | port=%s path=%s url=%s",
            config.PORT,
            config.WEBHOOK_PATH,
            config.FULL_WEBHOOK_URL,
        )

        app.run_webhook(
            listen="0.0.0.0",
            port=config.PORT,
            url_path=config.WEBHOOK_PATH.lstrip("/"),
            webhook_url=config.FULL_WEBHOOK_URL,
            secret_token=config.WEBHOOK_SECRET_TOKEN,
            drop_pending_updates=True,
        )
    else:
        logger.info("Iniciando en modo polling.")
        app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()