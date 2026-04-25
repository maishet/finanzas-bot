import io
import os
import tempfile
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
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


def _crear_grafico_balances(path, ingresos, gastos, ahorro):
    labels = ["Ingresos", "Gastos", "Ahorro"]
    values = [ingresos, gastos, ahorro]
    colors_bars = ["#2e8b57", "#c0392b", "#1f4e79"]

    fig, ax = plt.subplots(figsize=(7.8, 3.8))
    bars = ax.bar(labels, values, color=colors_bars)
    ax.set_title("Balance mensual (PEN)")
    ax.grid(axis="y", linestyle="--", alpha=0.35)

    for bar in bars:
        height = bar.get_height()
        ax.annotate(
            f"{height:,.2f}",
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _crear_grafico_categorias(path, gastos_por_categoria):
    if not gastos_por_categoria:
        fig, ax = plt.subplots(figsize=(7.8, 3.8))
        ax.text(0.5, 0.5, "No hay gastos para graficar", ha="center", va="center")
        ax.axis("off")
        fig.tight_layout()
        fig.savefig(path, dpi=160)
        plt.close(fig)
        return

    top_items = list(gastos_por_categoria.items())[:6]
    resto = sum(v for _, v in list(gastos_por_categoria.items())[6:])
    if resto > 0:
        top_items.append(("Otros", resto))

    labels = [k for k, _ in top_items]
    values = [v for _, v in top_items]

    fig, ax = plt.subplots(figsize=(7.8, 3.8))
    wedges, texts, autotexts = ax.pie(
        values,
        labels=labels,
        autopct="%1.1f%%",
        startangle=90,
        pctdistance=0.8,
        textprops={"fontsize": 8},
    )
    ax.set_title("Distribución de gastos por categoría")
    ax.axis("equal")

    for t in autotexts:
        t.set_fontsize(8)

    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _crear_grafico_cuentas(path, uso_cuentas):
    if not uso_cuentas:
        fig, ax = plt.subplots(figsize=(7.8, 3.8))
        ax.text(0.5, 0.5, "No hay transacciones para graficar", ha="center", va="center")
        ax.axis("off")
        fig.tight_layout()
        fig.savefig(path, dpi=160)
        plt.close(fig)
        return

    top = list(uso_cuentas.items())[:8]
    labels = [k for k, _ in top]
    values = [v["conteo"] for _, v in top]

    fig, ax = plt.subplots(figsize=(7.8, 3.8))
    bars = ax.barh(labels[::-1], values[::-1], color="#5b7db1")
    ax.set_title("Cuentas con mayor uso (cantidad de transacciones)")
    ax.grid(axis="x", linestyle="--", alpha=0.35)

    for bar in bars:
        width = bar.get_width()
        ax.annotate(
            f"{int(width)}",
            xy=(width, bar.get_y() + bar.get_height() / 2),
            xytext=(4, 0),
            textcoords="offset points",
            ha="left",
            va="center",
            fontsize=8,
        )

    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def generar_reporte_mensual_pdf(datos):
    """Genera un PDF en memoria con KPIs y gráficos del cierre mensual."""
    with tempfile.TemporaryDirectory() as tmpdir:
        chart_balance = os.path.join(tmpdir, "balance.png")
        chart_categorias = os.path.join(tmpdir, "categorias.png")
        chart_cuentas = os.path.join(tmpdir, "cuentas.png")

        kpis = datos["kpis"]
        _crear_grafico_balances(chart_balance, kpis["ingresos"], kpis["gastos"], kpis["ahorro"])
        _crear_grafico_categorias(chart_categorias, datos["gastos_por_categoria"])
        _crear_grafico_cuentas(chart_cuentas, datos["uso_cuentas"])

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
            top_tx_txt = (
                f"{trans_mayor['tipo']} {_fmt_pen(trans_mayor['monto_pen'])} "
                f"en {trans_mayor['categoria']}"
            )

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

        categoria_top = datos.get("categoria_top")
        trans_mayor = datos.get("transaccion_mayor")
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
            y_text -= 0.45 * cm
        else:
            c.drawString(2 * cm, y_text, "• Transacción más alta: sin datos del mes")
            y_text -= 0.45 * cm

        c.drawImage(chart_balance, 2 * cm, 2.2 * cm, width=17 * cm, height=7.5 * cm, preserveAspectRatio=True)
        c.showPage()

        # Página 3: distribución por categorías y cuentas
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, height - 2 * cm, "Distribución y uso")
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.grey)
        c.drawString(2 * cm, height - 2.6 * cm, f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        c.setFillColor(colors.black)

        c.drawImage(chart_categorias, 1.6 * cm, height - 11.2 * cm, width=18 * cm, height=8.0 * cm, preserveAspectRatio=True)
        c.drawImage(chart_cuentas, 1.6 * cm, 2.2 * cm, width=18 * cm, height=8.0 * cm, preserveAspectRatio=True)

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
        for i, h in enumerate(headers):
            c.drawString(col_x[i] * cm, y, h)
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
