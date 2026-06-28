import io
from datetime import datetime

from reportlab.graphics import renderPDF
from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


PAGE_W, PAGE_H = A4
LEFT = 1.8 * cm
RIGHT = PAGE_W - 1.8 * cm
CONTENT_W = RIGHT - LEFT

COLOR_PRIMARY = colors.HexColor("#0F172A")
COLOR_SUBTLE = colors.HexColor("#64748B")
COLOR_BORDER = colors.HexColor("#E2E8F0")
COLOR_BG_SOFT = colors.HexColor("#F8FAFC")
COLOR_INCOME = colors.HexColor("#16A34A")
COLOR_EXPENSE = colors.HexColor("#DC2626")
COLOR_SAVING = colors.HexColor("#2563EB")


def _fmt_pen(valor):
    return f"PEN {float(valor or 0):,.2f}"


def _clip(texto, max_len=36):
    txt = str(texto or "").strip()
    if len(txt) <= max_len:
        return txt
    return txt[: max_len - 1] + "…"


def _draw_footer(c, page_num):
    c.setStrokeColor(COLOR_BORDER)
    c.line(LEFT, 1.4 * cm, RIGHT, 1.4 * cm)
    c.setFillColor(COLOR_SUBTLE)
    c.setFont("Helvetica", 8)
    c.drawString(LEFT, 0.95 * cm, "Reporte financiero mensual")
    c.drawRightString(RIGHT, 0.95 * cm, f"Página {page_num}")


def _draw_title(c, title, subtitle=""):
    c.setFillColor(COLOR_PRIMARY)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(LEFT, PAGE_H - 2.0 * cm, title)
    if subtitle:
        c.setFillColor(COLOR_SUBTLE)
        c.setFont("Helvetica", 9.5)
        c.drawString(LEFT, PAGE_H - 2.6 * cm, subtitle)


def _build_resumen_natural(kpis, categoria_top=None):
    ingresos = float(kpis.get("ingresos", 0) or 0)
    gastos = float(kpis.get("gastos", 0) or 0)
    ahorro = float(kpis.get("ahorro", 0) or 0)

    if ingresos <= 0 and gastos <= 0:
        estado = "sin movimientos relevantes"
        lectura = "No se registraron ingresos ni gastos en el periodo."
    elif ahorro > 0:
        estado = "saludable"
        ratio = (ahorro / ingresos * 100) if ingresos > 0 else 0
        lectura = f"Tus ingresos superaron tus gastos. Ahorraste aproximadamente {ratio:.1f}% de tus ingresos."
    elif abs(ahorro) < 0.01:
        estado = "en equilibrio"
        lectura = "Tus ingresos y gastos quedaron prácticamente iguales este mes."
    else:
        deficit = abs(ahorro)
        ratio = (deficit / ingresos * 100) if ingresos > 0 else 0
        estado = "en alerta"
        lectura = (
            f"Tus gastos fueron mayores que tus ingresos por {_fmt_pen(deficit)}"
            + (f" ({ratio:.1f}% de tus ingresos)." if ingresos > 0 else ".")
        )

    if categoria_top:
        lectura += f" La categoría con mayor gasto fue {_clip(categoria_top.get('categoria', ''), 28)}."

    return estado, lectura


def _draw_semaforo_financiero(c, x, y, w, h, estado):
    estado_norm = str(estado or "").lower().strip()
    color = colors.HexColor("#94A3B8")
    titulo = "⚪ Semáforo financiero: Sin datos"
    recomendacion = "No hay suficiente información para evaluar tendencia."

    if estado_norm == "saludable":
        color = colors.HexColor("#16A34A")
        titulo = "🟢 Semáforo financiero: Saludable"
        recomendacion = "Mantén este ritmo y considera separar ahorro automático."
    elif estado_norm == "en equilibrio":
        color = colors.HexColor("#F59E0B")
        titulo = "🟡 Semáforo financiero: En equilibrio"
        recomendacion = "Estás al límite. Reducir un gasto fijo mejoraría tu margen."
    elif estado_norm == "en alerta":
        color = colors.HexColor("#DC2626")
        titulo = "🔴 Semáforo financiero: En alerta"
        recomendacion = "Prioriza recortar gastos variables y revisar pagos recurrentes."

    c.setFillColor(colors.white)
    c.roundRect(x, y, w, h, 8, stroke=0, fill=1)
    c.setStrokeColor(COLOR_BORDER)
    c.roundRect(x, y, w, h, 8, stroke=1, fill=0)

    c.setFillColor(color)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x + 0.35 * cm, y + h - 0.6 * cm, titulo)

    _draw_wrapped_line(
        c,
        recomendacion,
        x + 0.35 * cm,
        y + h - 1.15 * cm,
        w - 0.7 * cm,
        font="Helvetica",
        size=9.2,
        color=COLOR_SUBTLE,
        leading=11,
    )


def _estado_desde_kpi(kpi):
    ingresos = float(kpi.get("ingresos", 0) or 0)
    ahorro = float(kpi.get("ahorro", 0) or 0)
    gastos = float(kpi.get("gastos", 0) or 0)
    if ingresos <= 0 and gastos <= 0:
        return "sin movimientos relevantes"
    if ahorro > 0:
        return "saludable"
    if abs(ahorro) < 0.01:
        return "en equilibrio"
    return "en alerta"


def _emoji_estado(estado):
    estado = str(estado or "").lower().strip()
    if estado == "saludable":
        return "🟢"
    if estado == "en equilibrio":
        return "🟡"
    if estado == "en alerta":
        return "🔴"
    return "⚪"


def _draw_wrapped_line(c, text, x, y, max_width, font="Helvetica", size=10, color=colors.black, leading=13):
    c.setFont(font, size)
    c.setFillColor(color)
    words = str(text or "").split()
    if not words:
        return y - leading
    line = ""
    for w in words:
        candidate = (line + " " + w).strip()
        if stringWidth(candidate, font, size) <= max_width:
            line = candidate
        else:
            c.drawString(x, y, line)
            y -= leading
            line = w
    if line:
        c.drawString(x, y, line)
        y -= leading
    return y


def _draw_kpi_card(c, x, y, w, h, label, value, bg, fg):
    c.setFillColor(bg)
    c.roundRect(x, y, w, h, 8, stroke=0, fill=1)
    c.setStrokeColor(COLOR_BORDER)
    c.roundRect(x, y, w, h, 8, stroke=1, fill=0)
    c.setFillColor(fg)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x + 0.35 * cm, y + h - 0.55 * cm, label)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x + 0.35 * cm, y + 0.45 * cm, value)


def _draw_balance_chart(c, x, y, w, h, ingresos, gastos, ahorro):
    d = Drawing(w, h)
    d.add(String(6, h - 13, "Balance mensual (PEN)", fontName="Helvetica-Bold", fontSize=10))

    bc = VerticalBarChart()
    bc.x = 38
    bc.y = 28
    bc.width = w - 56
    bc.height = h - 52
    bc.data = [[max(0, ingresos)], [max(0, gastos)], [max(0, ahorro)]]
    bc.categoryAxis.categoryNames = ["Ingresos", "Gastos", "Ahorro"]
    bc.valueAxis.valueMin = 0
    bc.barWidth = 24
    bc.groupSpacing = 15
    bc.barSpacing = 9
    bc.valueAxis.labels.fontSize = 7
    bc.categoryAxis.labels.fontSize = 8
    bc.bars[0].fillColor = COLOR_INCOME
    bc.bars[1].fillColor = COLOR_EXPENSE
    bc.bars[2].fillColor = COLOR_SAVING
    d.add(bc)

    d.add(String(38, 8, "Verde: ingresos  •  Rojo: gastos  •  Azul: ahorro", fontSize=7, fillColor=COLOR_SUBTLE))
    renderPDF.draw(d, c, x, y)


def _draw_pie_categories(c, x, y, w, h, gastos_por_categoria):
    d = Drawing(w, h)
    d.add(String(6, h - 12, "Distribución de gastos por categoría", fontName="Helvetica-Bold", fontSize=10))

    if not gastos_por_categoria:
        d.add(String(10, h / 2, "No hay gastos para graficar", fontSize=10))
        renderPDF.draw(d, c, x, y)
        return

    items = sorted(gastos_por_categoria.items(), key=lambda kv: kv[1], reverse=True)
    top_items = items[:7]
    resto = sum(v for _, v in items[7:])
    if resto > 0:
        top_items.append(("Otros", resto))

    labels = [_clip(k, 16) for k, _ in top_items]
    values = [float(v or 0) for _, v in top_items]
    total = sum(values) or 1

    pie = Pie()
    pie.x = 10
    pie.y = 14
    pie.width = min(w - 135, 170)
    pie.height = min(h - 35, 150)
    pie.data = values
    pie.labels = [""] * len(values)
    pie.slices.strokeWidth = 0.3

    palette = [
        colors.HexColor("#2563EB"), colors.HexColor("#F97316"), colors.HexColor("#16A34A"),
        colors.HexColor("#DC2626"), colors.HexColor("#7C3AED"), colors.HexColor("#0891B2"),
        colors.HexColor("#A16207"), colors.HexColor("#64748B"),
    ]
    for i in range(len(values)):
        pie.slices[i].fillColor = palette[i % len(palette)]
    d.add(pie)

    ly = h - 24
    for i, (lbl, val) in enumerate(zip(labels, values)):
        if ly < 14:
            break
        pct = (val / total) * 100
        d.add(Rect(w - 115, ly - 4, 5, 5, fillColor=palette[i % len(palette)], strokeColor=palette[i % len(palette)]))
        d.add(String(w - 106, ly - 1, f"{lbl}: {_fmt_pen(val)} ({pct:.1f}%)", fontSize=7))
        ly -= 10

    renderPDF.draw(d, c, x, y)


def _draw_accounts_usage(c, x, y, w, h, uso_cuentas, titulo="Cuentas con mayor uso (número de transacciones)"):
    d = Drawing(w, h)
    d.add(String(6, h - 12, titulo, fontName="Helvetica-Bold", fontSize=10))

    if not uso_cuentas:
        d.add(String(10, h / 2, "No hay transacciones para graficar", fontSize=10))
        renderPDF.draw(d, c, x, y)
        return

    top = sorted(uso_cuentas.items(), key=lambda kv: kv[1].get("conteo", 0), reverse=True)[:8]
    labels = [_clip(k, 18) for k, _ in top]
    values = [int(v.get("conteo", 0)) for _, v in top]

    hb = HorizontalBarChart()
    hb.x = 78
    hb.y = 20
    hb.width = w - 92
    hb.height = h - 44
    hb.data = [values[::-1]]
    hb.categoryAxis.categoryNames = labels[::-1]
    hb.categoryAxis.labels.boxAnchor = "e"
    hb.categoryAxis.labels.fontSize = 7.5
    hb.valueAxis.valueMin = 0
    hb.valueAxis.labels.fontSize = 7
    hb.bars[0].fillColor = colors.HexColor("#4F46E5")
    d.add(hb)

    renderPDF.draw(d, c, x, y)


def _draw_transactions_table(c, movimientos, x, y_top, w, row_h=0.52 * cm):
    headers = ["#", "ID", "Fecha", "Tipo", "Categoría", "Cuenta", "Monto (PEN)"]
    col_w = [0.8 * cm, 1.5 * cm, 2.0 * cm, 1.7 * cm, 5.0 * cm, 3.6 * cm, 2.6 * cm]

    c.setFillColor(COLOR_BG_SOFT)
    c.rect(x, y_top - row_h, w, row_h, stroke=0, fill=1)
    c.setStrokeColor(COLOR_BORDER)
    c.rect(x, y_top - row_h, w, row_h, stroke=1, fill=0)

    c.setFont("Helvetica-Bold", 8.5)
    cx = x + 0.12 * cm
    for i, htxt in enumerate(headers):
        if i == len(headers) - 1:
            c.drawRightString(x + sum(col_w) - 0.12 * cm, y_top - 0.35 * cm, htxt)
        else:
            c.drawString(cx, y_top - 0.35 * cm, htxt)
        cx += col_w[i]

    y = y_top - row_h
    c.setFont("Helvetica", 8.3)

    if not movimientos:
        c.drawString(x + 0.15 * cm, y - 0.35 * cm, "No hay transacciones para este periodo.")
        return y - row_h

    for idx, m in enumerate(movimientos[:10], start=1):
        y -= row_h
        if idx % 2 == 0:
            c.setFillColor(colors.HexColor("#FAFAFA"))
            c.rect(x, y, w, row_h, stroke=0, fill=1)
        c.setStrokeColor(COLOR_BORDER)
        c.rect(x, y, w, row_h, stroke=1, fill=0)

        fecha = m.get("fecha")
        fecha_txt = fecha.strftime("%Y-%m-%d") if hasattr(fecha, "strftime") else "-"

        row = [
            str(idx),
            _clip(m.get("id") or "-", 8),
            fecha_txt,
            _clip(m.get("tipo"), 8),
            _clip(m.get("categoria"), 28),
            _clip(m.get("cuenta"), 18),
            f"{float(m.get('monto_pen', 0)):,.2f}",
        ]

        cx = x + 0.12 * cm
        for i, txt in enumerate(row):
            c.setFillColor(COLOR_PRIMARY if i != 3 else (COLOR_EXPENSE if str(m.get("tipo", "")).lower() == "gasto" else COLOR_INCOME))
            if i == len(row) - 1:
                c.drawRightString(x + sum(col_w) - 0.12 * cm, y + 0.17 * cm, txt)
            else:
                c.drawString(cx, y + 0.17 * cm, txt)
            cx += col_w[i]

    return y


def _draw_segmento_detalle(c, x, y, w, titulo, detalle):
    c.setFillColor(COLOR_PRIMARY)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(x, y, titulo)
    y -= 0.4 * cm
    c.setFont("Helvetica", 8.2)
    c.setFillColor(COLOR_SUBTLE)

    if not detalle:
        c.drawString(x, y, "Sin movimientos en este segmento.")
        return y - 0.35 * cm

    items = sorted(detalle.items(), key=lambda kv: kv[1].get("total_transacciones", 0), reverse=True)
    for nombre, v in items[:4]:
        linea = (
            f"• {_clip(nombre, 18)} | Tx: {int(v.get('total_transacciones', 0))} | "
            f"Ing: {_fmt_pen(v.get('ingresos', 0))} | Gas: {_fmt_pen(v.get('gastos', 0))} | "
            f"Neto: {_fmt_pen(v.get('ahorro', 0))}"
        )
        y = _draw_wrapped_line(c, linea, x, y, w, size=8.0, color=COLOR_SUBTLE, leading=10)
        y -= 0.03 * cm
    return y


def _draw_comparativo_cuentas(c, x, y, w, h, items):
    d = Drawing(w, h)
    d.add(String(6, h - 12, "Comparativo de cuentas por monto neto (PEN)", fontName="Helvetica-Bold", fontSize=10))

    if not items:
        d.add(String(10, h / 2, "No hay datos para comparar cuentas.", fontSize=10))
        renderPDF.draw(d, c, x, y)
        return

    top = sorted(items, key=lambda z: abs(z.get("neto", 0)), reverse=True)[:10]
    labels = [_clip(f"{it.get('cuenta','')} ({it.get('grupo','')})", 24) for it in top][::-1]
    values = [float(it.get("neto", 0)) for it in top][::-1]

    hb = HorizontalBarChart()
    hb.x = 130
    hb.y = 18
    hb.width = w - 145
    hb.height = h - 42
    hb.data = [values]
    hb.categoryAxis.categoryNames = labels
    hb.categoryAxis.labels.boxAnchor = "e"
    hb.categoryAxis.labels.fontSize = 7
    hb.valueAxis.labels.fontSize = 7
    hb.bars[0].fillColor = colors.HexColor("#0EA5E9")
    d.add(hb)

    renderPDF.draw(d, c, x, y)


def _draw_rank_table_comparativo(c, x, y_top, w, items, row_h=0.46 * cm):
    headers = ["#", "Cuenta", "Tipo", "Tx", "Ingresos", "Gastos", "Neto"]
    col_w = [0.7 * cm, 4.4 * cm, 1.8 * cm, 1.1 * cm, 2.5 * cm, 2.5 * cm, 2.4 * cm]

    c.setFillColor(COLOR_BG_SOFT)
    c.rect(x, y_top - row_h, w, row_h, stroke=0, fill=1)
    c.setStrokeColor(COLOR_BORDER)
    c.rect(x, y_top - row_h, w, row_h, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 8.2)

    cx = x + 0.1 * cm
    for i, htxt in enumerate(headers):
        if i >= 4:
            c.drawRightString(cx + col_w[i] - 0.1 * cm, y_top - 0.32 * cm, htxt)
        else:
            c.drawString(cx, y_top - 0.32 * cm, htxt)
        cx += col_w[i]

    y = y_top - row_h
    c.setFont("Helvetica", 8.0)

    if not items:
        c.drawString(x + 0.12 * cm, y - 0.3 * cm, "Sin datos de cuentas para este periodo.")
        return

    for idx, it in enumerate(items[:14], start=1):
        y -= row_h
        if y < 1.9 * cm:
            break
        if idx % 2 == 0:
            c.setFillColor(colors.HexColor("#FAFAFA"))
            c.rect(x, y, w, row_h, stroke=0, fill=1)
        c.setStrokeColor(COLOR_BORDER)
        c.rect(x, y, w, row_h, stroke=1, fill=0)

        row = [
            str(idx),
            _clip(it.get("cuenta"), 26),
            "Banco" if it.get("grupo") == "banco" else "Crédito",
            str(int(it.get("tx", 0))),
            _fmt_pen(it.get("ingresos", 0)).replace("PEN ", ""),
            _fmt_pen(it.get("gastos", 0)).replace("PEN ", ""),
            _fmt_pen(it.get("neto", 0)).replace("PEN ", ""),
        ]

        cx = x + 0.1 * cm
        for i, txt in enumerate(row):
            c.setFillColor(COLOR_PRIMARY)
            if i >= 4:
                c.drawRightString(cx + col_w[i] - 0.1 * cm, y + 0.14 * cm, txt)
            else:
                c.drawString(cx, y + 0.14 * cm, txt)
            cx += col_w[i]


def generar_reporte_mensual_pdf(datos):
    """Genera un PDF en memoria con KPIs y gráficos del cierre mensual."""
    kpis = datos["kpis"]

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    # Página 1: portada
    c.setTitle(f"Reporte Finanzas {datos['mes']:02d}-{datos['año']}")
    c.setFillColor(COLOR_PRIMARY)
    c.rect(0, PAGE_H - 8.5 * cm, PAGE_W, 8.5 * cm, stroke=0, fill=1)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 23)
    c.drawString(LEFT, PAGE_H - 3.0 * cm, "Reporte Financiero")
    c.setFont("Helvetica-Bold", 17)
    c.drawString(LEFT, PAGE_H - 4.1 * cm, f"Cierre mensual {datos['mes']:02d}/{datos['año']}")
    c.setFont("Helvetica", 10)
    c.drawString(LEFT, PAGE_H - 5.2 * cm, f"Generado: {datos['generado_en']}")

    categoria_top = datos.get("categoria_top")
    trans_mayor = datos.get("transaccion_mayor")
    top_categoria_txt = "Sin datos"
    if categoria_top:
        top_categoria_txt = f"{categoria_top['categoria']} ({_fmt_pen(categoria_top['monto_pen'])})"

    top_tx_txt = "Sin datos"
    if trans_mayor:
        top_tx_txt = f"{trans_mayor['tipo']} {_fmt_pen(trans_mayor['monto_pen'])} en {trans_mayor['categoria']}"

    estado_financiero, resumen_natural = _build_resumen_natural(kpis, categoria_top)

    y = PAGE_H - 9.7 * cm
    c.setFillColor(COLOR_PRIMARY)
    c.setFont("Helvetica-Bold", 11.5)
    c.drawString(LEFT, y, "Resumen ejecutivo")
    y -= 0.8 * cm
    y = _draw_wrapped_line(c, f"• Ingresos del mes: {_fmt_pen(kpis['ingresos'])}", LEFT, y, CONTENT_W, size=10)
    y = _draw_wrapped_line(c, f"• Gastos del mes: {_fmt_pen(kpis['gastos'])}", LEFT, y, CONTENT_W, size=10)
    y = _draw_wrapped_line(c, f"• Ahorro del mes: {_fmt_pen(kpis['ahorro'])}", LEFT, y, CONTENT_W, size=10)
    y = _draw_wrapped_line(c, f"• Categoría con mayor gasto: {_clip(top_categoria_txt, 90)}", LEFT, y, CONTENT_W, size=10)
    y = _draw_wrapped_line(c, f"• Transacción más alta: {_clip(top_tx_txt, 90)}", LEFT, y, CONTENT_W, size=10)

    c.setFillColor(COLOR_PRIMARY)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(LEFT, y - 0.35 * cm, "Lectura en lenguaje simple")
    _draw_wrapped_line(
        c,
        f"• {resumen_natural}",
        LEFT,
        y - 0.95 * cm,
        CONTENT_W,
        size=9.8,
        color=COLOR_SUBTLE,
        leading=12,
    )

    _draw_semaforo_financiero(c, LEFT, 2.35 * cm, CONTENT_W, 2.6 * cm, estado_financiero)
    _draw_footer(c, 1)
    c.showPage()

    # Página 2: KPIs + balance
    _draw_title(c, f"Cierre mensual - {datos['mes']:02d}/{datos['año']}", f"Generado: {datos['generado_en']}")

    box_y = PAGE_H - 5.0 * cm
    box_h = 1.75 * cm
    box_w = (CONTENT_W - 0.8 * cm) / 2

    cards = [
        ("Ingreso total", _fmt_pen(kpis["ingresos"]), colors.HexColor("#ECFDF3"), colors.HexColor("#166534")),
        ("Gasto total", _fmt_pen(kpis["gastos"]), colors.HexColor("#FEF2F2"), colors.HexColor("#991B1B")),
        ("Ahorro total", _fmt_pen(kpis["ahorro"]), colors.HexColor("#EFF6FF"), colors.HexColor("#1E3A8A")),
        ("Transacciones", str(kpis["total_transacciones"]), colors.HexColor("#F5F3FF"), colors.HexColor("#5B21B6")),
    ]

    for i, (label, value, bg, fg) in enumerate(cards):
        col = i % 2
        row = i // 2
        x = LEFT + col * (box_w + 0.8 * cm)
        y = box_y - row * (box_h + 0.45 * cm)
        _draw_kpi_card(c, x, y, box_w, box_h, label, value, bg, fg)

    y_txt = box_y - 2 * (box_h + 0.45 * cm) - 0.2 * cm
    c.setFillColor(COLOR_PRIMARY)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(LEFT, y_txt, "Detalles destacados")
    y_txt -= 0.6 * cm

    if categoria_top:
        y_txt = _draw_wrapped_line(
            c,
            f"• Categoría con más gasto: {_clip(categoria_top['categoria'], 55)} ({_fmt_pen(categoria_top['monto_pen'])})",
            LEFT,
            y_txt,
            CONTENT_W,
            size=9.6,
        )
    else:
        y_txt = _draw_wrapped_line(c, "• Categoría con más gasto: sin datos", LEFT, y_txt, CONTENT_W, size=9.6)

    if trans_mayor:
        y_txt = _draw_wrapped_line(
            c,
            f"• Transacción más alta: {_clip(trans_mayor['tipo'], 12)} {_fmt_pen(trans_mayor['monto_pen'])} | "
            f"{_clip(trans_mayor['categoria'], 32)} | {_clip(trans_mayor['cuenta'], 18)} | {trans_mayor['fecha']}",
            LEFT,
            y_txt,
            CONTENT_W,
            size=9.6,
        )
    else:
        y_txt = _draw_wrapped_line(c, "• Transacción más alta: sin datos", LEFT, y_txt, CONTENT_W, size=9.6)

    # Resumen por tipo de cuenta
    segmentos = datos.get("segmentos", {})
    banco = segmentos.get("banco", {"ingresos": 0.0, "gastos": 0.0, "ahorro": 0.0, "total_transacciones": 0})
    crédito = segmentos.get("crédito", {"ingresos": 0.0, "gastos": 0.0, "ahorro": 0.0, "total_transacciones": 0})

    y_seg = y_txt - 0.15 * cm
    c.setFillColor(COLOR_PRIMARY)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(LEFT, y_seg, "Vista separada por tipo de cuenta")

    card_w = (CONTENT_W - 0.6 * cm) / 2
    card_h = 2.35 * cm
    y_card = y_seg - card_h - 0.18 * cm

    for i, (titulo, seg) in enumerate((("Banco", banco), ("Crédito", crédito))):
        x_card = LEFT + i * (card_w + 0.6 * cm)
        estado_seg = _estado_desde_kpi(seg)
        c.setFillColor(colors.white)
        c.roundRect(x_card, y_card, card_w, card_h, 8, stroke=0, fill=1)
        c.setStrokeColor(COLOR_BORDER)
        c.roundRect(x_card, y_card, card_w, card_h, 8, stroke=1, fill=0)
        c.setFillColor(COLOR_PRIMARY)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x_card + 0.25 * cm, y_card + card_h - 0.5 * cm, f"{titulo} {_emoji_estado(estado_seg)}")
        c.setFont("Helvetica", 8.6)
        c.setFillColor(COLOR_SUBTLE)
        c.drawString(x_card + 0.25 * cm, y_card + card_h - 0.95 * cm, f"Ingresos: {_fmt_pen(seg.get('ingresos', 0))}")
        c.drawString(x_card + 0.25 * cm, y_card + card_h - 1.35 * cm, f"Gastos: {_fmt_pen(seg.get('gastos', 0))}")
        c.drawString(x_card + 0.25 * cm, y_card + card_h - 1.75 * cm, f"Ahorro neto: {_fmt_pen(seg.get('ahorro', 0))}")
        c.drawString(x_card + 0.25 * cm, y_card + card_h - 2.15 * cm, f"Transacciones: {int(seg.get('total_transacciones', 0))}")

    _draw_balance_chart(c, LEFT, 1.9 * cm, CONTENT_W, 4.8 * cm, kpis["ingresos"], kpis["gastos"], kpis["ahorro"])
    _draw_footer(c, 2)
    c.showPage()

    # Página 3: distribución
    _draw_title(c, "Distribución y uso", f"Generado: {datos['generado_en']}")
    _draw_pie_categories(c, LEFT, PAGE_H - 10.6 * cm, CONTENT_W, 6.9 * cm, datos.get("gastos_por_categoria", {}))

    segmentos_detalle = datos.get("segmentos_detalle", {})
    banco_detalle = segmentos_detalle.get("banco", {})
    credito_detalle = segmentos_detalle.get("crédito", {})

    uso_banco = {k: {"conteo": v.get("total_transacciones", 0), "monto_pen": v.get("gastos", 0)} for k, v in banco_detalle.items()}
    uso_credito = {k: {"conteo": v.get("total_transacciones", 0), "monto_pen": v.get("gastos", 0)} for k, v in credito_detalle.items()}

    col_w = (CONTENT_W - 0.6 * cm) / 2
    _draw_accounts_usage(c, LEFT, 2.4 * cm, col_w, 5.3 * cm, uso_banco, "Uso de cuentas Banco")
    _draw_accounts_usage(c, LEFT + col_w + 0.6 * cm, 2.4 * cm, col_w, 5.3 * cm, uso_credito, "Uso de cuentas Crédito")

    _draw_segmento_detalle(c, LEFT, 8.15 * cm, col_w, "Detalle Banco", banco_detalle)
    _draw_segmento_detalle(c, LEFT + col_w + 0.6 * cm, 8.15 * cm, col_w, "Detalle Crédito", credito_detalle)

    _draw_footer(c, 3)
    c.showPage()

    # Página 4: top transacciones
    _draw_title(c, "Top 10 transacciones más altas", f"Generado: {datos['generado_en']}")
    movimientos = sorted(datos.get("movimientos", []), key=lambda x: x.get("monto_pen", 0), reverse=True)
    _draw_transactions_table(c, movimientos, LEFT, PAGE_H - 3.3 * cm, CONTENT_W)
    _draw_footer(c, 4)
    c.showPage()

    # Página 5: comparativo detallado de cuentas Banco vs Crédito
    _draw_title(c, "Comparativo entre cuentas", f"Generado: {datos['generado_en']}")
    segmentos_detalle = datos.get("segmentos_detalle", {})
    comparativo_items = []
    for grupo_key, detalle in (("banco", segmentos_detalle.get("banco", {})), ("crédito", segmentos_detalle.get("crédito", {}))):
        for cuenta, vals in detalle.items():
            comparativo_items.append({
                "grupo": grupo_key,
                "cuenta": cuenta,
                "tx": int(vals.get("total_transacciones", 0)),
                "ingresos": float(vals.get("ingresos", 0) or 0),
                "gastos": float(vals.get("gastos", 0) or 0),
                "neto": float(vals.get("ahorro", 0) or 0),
            })

    _draw_comparativo_cuentas(c, LEFT, PAGE_H - 11.2 * cm, CONTENT_W, 7.4 * cm, comparativo_items)
    _draw_rank_table_comparativo(c, LEFT, 10.8 * cm, CONTENT_W, sorted(comparativo_items, key=lambda z: abs(z.get("neto", 0)), reverse=True))
    _draw_footer(c, 5)

    c.save()
    buffer.seek(0)
    return buffer
