import io
from datetime import datetime

from reportlab.graphics import renderPDF
from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas


def _fmt_pen(valor):
    return f"PEN {valor:,.2f}"


def _clip(texto, max_len=42):
    txt = str(texto or "")
    if len(txt) <= max_len:
        return txt
    return txt[: max_len - 1] + "..."


def _draw_balance_chart(c, x, y, w, h, ingresos, gastos, ahorro):
    d = Drawing(w, h)
    d.add(String(6, h - 12, "Balance mensual (PEN)", fontName="Helvetica-Bold", fontSize=10))

    bc = VerticalBarChart()
    bc.x = 45
    bc.y = 20
    bc.width = w - 65
    bc.height = h - 50
    bc.data = [[ingresos, gastos, ahorro]]
    bc.categoryAxis.categoryNames = ["Ingresos", "Gastos", "Ahorro"]
    bc.valueAxis.valueMin = 0
    bc.barWidth = 18
    bc.groupSpacing = 14
    bc.barSpacing = 8
    bc.bars[0].fillColor = colors.HexColor("#2e8b57")
    if len(bc.bars) > 1:
        bc.bars[1].fillColor = colors.HexColor("#c0392b")
    d.add(bc)

    # Colores por barra (workaround simple para 3 barras)
    # ReportLab aplica estilo por serie, así que añadimos una nota de color aquí.
    d.add(String(50, 5, "Verde: ingresos   Rojo: gastos   Azul: ahorro", fontSize=7, fillColor=colors.grey))

    renderPDF.draw(d, c, x, y)


def _draw_pie_categories(c, x, y, w, h, gastos_por_categoria):
    d = Drawing(w, h)
    d.add(String(6, h - 12, "Distribución de gastos por categoría", fontName="Helvetica-Bold", fontSize=10))

    if not gastos_por_categoria:
        d.add(String(10, h / 2, "No hay gastos para graficar", fontSize=10))
        renderPDF.draw(d, c, x, y)
        return

    top_items = list(gastos_por_categoria.items())[:6]
    resto = sum(v for _, v in list(gastos_por_categoria.items())[6:])
    if resto > 0:
        top_items.append(("Otros", resto))

    labels = [k for k, _ in top_items]
    values = [v for _, v in top_items]

    pie = Pie()
    pie.x = 20
    pie.y = 16
    pie.width = min(w - 130, 180)
    pie.height = min(h - 40, 160)
    pie.data = values
    pie.labels = labels
    pie.slices.strokeWidth = 0.3

    palette = [
        colors.HexColor("#1f77b4"), colors.HexColor("#ff7f0e"), colors.HexColor("#2ca02c"),
        colors.HexColor("#d62728"), colors.HexColor("#9467bd"), colors.HexColor("#8c564b"),
        colors.HexColor("#7f7f7f"),
    ]
    for i in range(len(values)):
        pie.slices[i].fillColor = palette[i % len(palette)]

    d.add(pie)

    # leyenda simplificada
    ly = h - 24
    for i, (lbl, val) in enumerate(top_items):
        if ly < 20:
            break
        d.add(String(w - 100, ly, f"{_clip(lbl, 14)}: {val:,.0f}", fontSize=7))
        ly -= 10

    renderPDF.draw(d, c, x, y)


def _draw_accounts_usage(c, x, y, w, h, uso_cuentas):
    d = Drawing(w, h)
    d.add(String(6, h - 12, "Cuentas con mayor uso (cantidad de transacciones)", fontName="Helvetica-Bold", fontSize=10))

    if not uso_cuentas:
        d.add(String(10, h / 2, "No hay transacciones para graficar", fontSize=10))
        renderPDF.draw(d, c, x, y)
        return

    top = list(uso_cuentas.items())[:8]
    labels = [k for k, _ in top]
    values = [v["conteo"] for _, v in top]

    hb = HorizontalBarChart()
    hb.x = 80
    hb.y = 20
    hb.width = w - 95
    hb.height = h - 45
    hb.data = [values[::-1]]
    hb.categoryAxis.categoryNames = labels[::-1]
    hb.categoryAxis.labels.boxAnchor = "e"
    hb.valueAxis.valueMin = 0
    hb.bars[0].fillColor = colors.HexColor("#5b7db1")
    d.add(hb)

    renderPDF.draw(d, c, x, y)


def generar_reporte_mensual_pdf(datos):
    """Genera un PDF en memoria con KPIs y gráficos del cierre mensual."""
    kpis = datos["kpis"]

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Página 1: portada ejecutiva
    c.setTitle(f"Reporte Finanzas {datos['mes']:02d}-{datos['año']}")
    c.setFillColor(colors.HexColor("#102a43"))
    c.rect(0, height - 8.2 * cm, width, 8.2 * cm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(2 * cm, height - 3.0 * cm, "Reporte Ejecutivo")
    c.setFont("Helvetica-Bold", 18)
    c.drawString(2 * cm, height - 4.1 * cm, f"Cierre Mensual {datos['mes']:02d}/{datos['año']}")
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, height - 5.2 * cm, f"Generado: {datos['generado_en']}")

    categoria_top = datos.get("categoria_top")
    trans_mayor = datos.get("transaccion_mayor")
    top_categoria_txt = "Sin datos"
    if categoria_top:
        top_categoria_txt = f"{categoria_top['categoria']} ({_fmt_pen(categoria_top['monto_pen'])})"

    top_tx_txt = "Sin datos"
    if trans_mayor:
        top_tx_txt = f"{trans_mayor['tipo']} {_fmt_pen(trans_mayor['monto_pen'])} en {trans_mayor['categoria']}"

    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(2 * cm, height - 9.6 * cm, "Resumen estratégico")
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, height - 10.3 * cm, f"• Ingresos del mes: {_fmt_pen(kpis['ingresos'])}")
    c.drawString(2 * cm, height - 10.9 * cm, f"• Gastos del mes: {_fmt_pen(kpis['gastos'])}")
    c.drawString(2 * cm, height - 11.5 * cm, f"• Ahorro del mes: {_fmt_pen(kpis['ahorro'])}")
    c.drawString(2 * cm, height - 12.1 * cm, f"• Categoría con mayor uso: {_clip(top_categoria_txt, 75)}")
    c.drawString(2 * cm, height - 12.7 * cm, f"• Transacción más alta: {_clip(top_tx_txt, 75)}")
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.grey)
    c.drawString(
        2 * cm,
        1.4 * cm,
        "Este documento resume los indicadores financieros del periodo y su distribución por comportamiento.",
    )
    c.showPage()

    # Página 2: KPIs y balance
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, height - 2 * cm, f"Cierre Mensual - {datos['mes']:02d}/{datos['año']}")
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.grey)
    c.drawString(2 * cm, height - 2.7 * cm, f"Generado: {datos['generado_en']}")
    c.setFillColor(colors.black)

    box_y = height - 4.4 * cm
    box_h = 1.6 * cm
    box_w = (width - 5 * cm) / 2

    tarjetas = [
        ("Ingreso total", _fmt_pen(kpis["ingresos"]), colors.HexColor("#e8f5e9"), colors.HexColor("#1b5e20")),
        ("Gasto total", _fmt_pen(kpis["gastos"]), colors.HexColor("#ffebee"), colors.HexColor("#b71c1c")),
        ("Ahorro total", _fmt_pen(kpis["ahorro"]), colors.HexColor("#e3f2fd"), colors.HexColor("#0d47a1")),
        ("Total transacciones", str(kpis["total_transacciones"]), colors.HexColor("#f3e5f5"), colors.HexColor("#4a148c")),
    ]

    for i, (label, value, fill_color, text_color) in enumerate(tarjetas):
        col = i % 2
        row = i // 2
        x = 2 * cm + col * (box_w + 1 * cm)
        y = box_y - row * (box_h + 0.6 * cm)
        c.setFillColor(fill_color)
        c.roundRect(x, y, box_w, box_h, 6, stroke=0, fill=1)
        c.setStrokeColor(colors.HexColor("#cfd8dc"))
        c.roundRect(x, y, box_w, box_h, 6, stroke=1, fill=0)
        c.setFillColor(text_color)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + 0.3 * cm, y + box_h - 0.55 * cm, label)
        c.setFont("Helvetica", 11)
        c.drawString(x + 0.3 * cm, y + 0.45 * cm, value)
        c.setFillColor(colors.black)

    y_text = box_y - 2 * (box_h + 0.6 * cm) - 0.4 * cm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(2 * cm, y_text, "Indicadores clave")
    y_text -= 0.55 * cm
    c.setFont("Helvetica", 10)

    if categoria_top:
        c.drawString(
            2 * cm,
            y_text,
            f"• Categoría con más gasto: {categoria_top['categoria']} ({_fmt_pen(categoria_top['monto_pen'])})",
        )
        y_text -= 0.45 * cm
    else:
        c.drawString(2 * cm, y_text, "• Categoría con más gasto: sin datos del mes")
        y_text -= 0.45 * cm

    if trans_mayor:
        c.drawString(
            2 * cm,
            y_text,
            f"• Transacción más alta: {trans_mayor['tipo']} {_fmt_pen(trans_mayor['monto_pen'])}",
        )
        y_text -= 0.45 * cm
        c.drawString(
            2 * cm,
            y_text,
            f"  ID {trans_mayor['id']} | {trans_mayor['categoria']} | {trans_mayor['cuenta']} | {trans_mayor['fecha']}",
        )
    else:
        c.drawString(2 * cm, y_text, "• Transacción más alta: sin datos del mes")

    _draw_balance_chart(c, 2 * cm, 2.1 * cm, 17 * cm, 7.6 * cm, kpis["ingresos"], kpis["gastos"], kpis["ahorro"])
    c.showPage()

    # Página 3: distribución por categorías y cuentas
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, height - 2 * cm, "Distribución y uso")
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.grey)
    c.drawString(2 * cm, height - 2.6 * cm, f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    c.setFillColor(colors.black)
    _draw_pie_categories(c, 1.6 * cm, height - 11.3 * cm, 18 * cm, 8.1 * cm, datos["gastos_por_categoria"])
    _draw_accounts_usage(c, 1.6 * cm, 2.1 * cm, 18 * cm, 8.1 * cm, datos["uso_cuentas"])
    c.showPage()

    # Página 4: Top 10 transacciones más altas
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, height - 2 * cm, "Top 10 transacciones más altas del mes")
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.grey)
    c.drawString(2 * cm, height - 2.6 * cm, f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    c.setFillColor(colors.black)

    movimientos = sorted(
        datos.get("movimientos", []),
        key=lambda x: x.get("monto_pen", 0),
        reverse=True,
    )[:10]

    headers = ["#", "ID", "Fecha", "Tipo", "Categoría", "Cuenta", "Monto (PEN)"]
    col_x = [2.0, 2.8, 4.2, 6.0, 8.0, 12.5, 16.2]
    y = height - 3.6 * cm

    c.setFont("Helvetica-Bold", 9)
    for i, htxt in enumerate(headers):
        c.drawString(col_x[i] * cm, y, htxt)
    y -= 0.35 * cm
    c.setStrokeColor(colors.HexColor("#cfd8dc"))
    c.line(2.0 * cm, y, 19.4 * cm, y)
    y -= 0.25 * cm

    c.setFont("Helvetica", 8.5)
    if not movimientos:
        c.drawString(2.0 * cm, y, "No hay transacciones para este periodo.")
    else:
        for idx, m in enumerate(movimientos, start=1):
            if y < 2.2 * cm:
                break
            fecha = m.get("fecha")
            fecha_txt = fecha.strftime("%Y-%m-%d") if hasattr(fecha, "strftime") else "-"
            c.drawString(col_x[0] * cm, y, str(idx))
            c.drawString(col_x[1] * cm, y, _clip(m.get("id") or "-", 10))
            c.drawString(col_x[2] * cm, y, fecha_txt)
            c.drawString(col_x[3] * cm, y, _clip(m.get("tipo"), 8))
            c.drawString(col_x[4] * cm, y, _clip(m.get("categoria"), 24))
            c.drawString(col_x[5] * cm, y, _clip(m.get("cuenta"), 16))
            c.drawRightString(19.2 * cm, y, f"{m.get('monto_pen', 0):,.2f}")
            y -= 0.48 * cm

    c.save()
    buffer.seek(0)
    return buffer
