from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "manual-as5600-rpi-zero-2w.pdf"

NAVY = colors.HexColor("#17324D")
TEAL = colors.HexColor("#2F7D77")
AMBER = colors.HexColor("#D89B28")
ORANGE = colors.HexColor("#C7772B")
RED = colors.HexColor("#D94841")
INK = colors.HexColor("#263642")
MUTED = colors.HexColor("#526878")
PAPER = colors.HexColor("#F4F0E8")
PALE = colors.HexColor("#EEF4F2")
WARN = colors.HexColor("#FFF7E5")
PURPLE = colors.HexColor("#5F5AA2")


class WiringDiagram(Flowable):
    def __init__(self, width: float = 178 * mm, height: float = 112 * mm):
        super().__init__()
        self.width = width
        self.height = height

    def draw_box(self, c, x, y, w, h, title, color, lines):
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor("#D5DDD9"))
        c.roundRect(x, y, w, h, 4 * mm, fill=1, stroke=1)
        c.setFillColor(color)
        c.roundRect(x, y + h - 13 * mm, w, 13 * mm, 4 * mm, fill=1, stroke=0)
        c.rect(x, y + h - 13 * mm, w, 5 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + 5 * mm, y + h - 9 * mm, title)
        c.setFillColor(INK)
        c.setFont("Courier-Bold", 7.7)
        line_y = y + h - 22 * mm
        for line in lines:
            c.drawString(x + 5 * mm, line_y, line)
            line_y -= 6.2 * mm

    def draw_wire(self, c, points, color, width=2.2):
        c.setStrokeColor(color)
        c.setLineWidth(width)
        c.setLineCap(1)
        path = c.beginPath()
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        c.drawPath(path)

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(PAPER)
        c.roundRect(0, 0, self.width, self.height, 4 * mm, fill=1, stroke=0)

        pi_x, pi_y, pi_w, pi_h = 5 * mm, 28 * mm, 48 * mm, 76 * mm
        as_x, as_y, as_w, as_h = 119 * mm, 62 * mm, 54 * mm, 45 * mm
        ad_x, ad_y, ad_w, ad_h = 119 * mm, 11 * mm, 54 * mm, 43 * mm
        oled_x, oled_y, oled_w, oled_h = 78 * mm, 5 * mm, 36 * mm, 43 * mm

        self.draw_box(
            c,
            pi_x,
            pi_y,
            pi_w,
            pi_h,
            "Raspberry Pi Zero 2 W",
            NAVY,
            ["1  3V3", "6  GND", "3  SDA / GPIO2", "5  SCL / GPIO3"],
        )
        self.draw_box(
            c,
            as_x,
            as_y,
            as_w,
            as_h,
            "AS5600",
            TEAL,
            ["VCC", "GND", "SDA", "SCL"],
        )
        self.draw_box(
            c,
            ad_x,
            ad_y,
            ad_w,
            ad_h,
            "ADS1115",
            ORANGE,
            ["VDD", "GND", "SDA", "SCL"],
        )
        self.draw_box(
            c,
            oled_x,
            oled_y,
            oled_w,
            oled_h,
            "OLED I2C",
            NAVY,
            ["VCC", "GND", "SDA", "SCL"],
        )

        pi_targets = [pi_y + 59 * mm, pi_y + 45 * mm, pi_y + 31 * mm, pi_y + 17 * mm]
        trunk_xs = [60 * mm, 64 * mm, 68 * mm, 72 * mm]
        as_targets = [as_y + 34 * mm, as_y + 28 * mm, as_y + 22 * mm, as_y + 16 * mm]
        ad_targets = [ad_y + 32 * mm, ad_y + 25 * mm, ad_y + 18 * mm, ad_y + 11 * mm]
        oled_targets = [oled_y + 21 * mm, oled_y + 15 * mm, oled_y + 9 * mm, oled_y + 3 * mm]
        rail_colors = [RED, INK, TEAL, AMBER]
        for pi_target, x, color, as_target, ad_target, oled_target in zip(
            pi_targets, trunk_xs, rail_colors, as_targets, ad_targets, oled_targets
        ):
            self.draw_wire(c, [(pi_x + pi_w, pi_target), (x, pi_target)], color)
            self.draw_wire(c, [(x, as_target), (x, min(ad_target, oled_target))], color)
            self.draw_wire(c, [(x, as_target), (as_x, as_target)], color)
            self.draw_wire(c, [(x, ad_target), (ad_x, ad_target)], color)
            self.draw_wire(c, [(x, oled_target), (oled_x, oled_target)], color)

        self.draw_wire(
            c,
            [
                (as_x + as_w, as_y + 7 * mm),
                (176 * mm, as_y + 7 * mm),
                (176 * mm, ad_y + 7 * mm),
                (ad_x + ad_w, ad_y + 7 * mm),
            ],
            PURPLE,
            2.7,
        )
        c.setFillColor(PURPLE)
        c.setFont("Helvetica-Bold", 7)
        c.drawRightString(as_x + as_w - 2 * mm, as_y + 9 * mm, "OUT")
        c.drawRightString(ad_x + ad_w - 2 * mm, ad_y + 9 * mm, "A0")

        c.setFillColor(WARN)
        c.setStrokeColor(AMBER)
        c.roundRect(5 * mm, 2 * mm, 48 * mm, 19 * mm, 3 * mm, fill=1, stroke=1)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 7.2)
        c.drawString(8 * mm, 14 * mm, "Trabajar a 3.3 V")
        c.setFont("Helvetica", 6.8)
        c.drawString(8 * mm, 9.5 * mm, "No conectar 5 V al bus")
        c.drawString(8 * mm, 5.5 * mm, "ni alimentar el motor aqui.")
        c.restoreState()


class MagnetDiagram(Flowable):
    def __init__(self, width: float = 178 * mm, height: float = 75 * mm):
        super().__init__()
        self.width = width
        self.height = height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(PAPER)
        c.roundRect(0, 0, self.width, self.height, 4 * mm, fill=1, stroke=0)

        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(43 * mm, 68 * mm, "Vista superior")
        c.drawCentredString(132 * mm, 68 * mm, "Vista lateral")

        c.setFillColor(TEAL)
        c.roundRect(14 * mm, 12 * mm, 58 * mm, 49 * mm, 4 * mm, fill=1, stroke=0)
        c.setFillColor(INK)
        c.roundRect(28 * mm, 22 * mm, 30 * mm, 29 * mm, 2 * mm, fill=1, stroke=0)
        c.setFillColor(RED)
        c.wedge(32 * mm, 25 * mm, 54 * mm, 47 * mm, 0, 180, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#4D6FA9"))
        c.wedge(32 * mm, 25 * mm, 54 * mm, 47 * mm, 180, 180, fill=1, stroke=0)
        c.setStrokeColor(AMBER)
        c.setLineWidth(1.2)
        c.setDash(3, 2)
        c.line(43 * mm, 19 * mm, 43 * mm, 54 * mm)
        c.line(25 * mm, 36 * mm, 61 * mm, 36 * mm)
        c.setDash()

        c.setFillColor(TEAL)
        c.roundRect(101 * mm, 14 * mm, 62 * mm, 7 * mm, 2 * mm, fill=1, stroke=0)
        c.setFillColor(INK)
        c.roundRect(122 * mm, 21 * mm, 20 * mm, 8 * mm, 1 * mm, fill=1, stroke=0)
        c.setFillColor(RED)
        c.roundRect(119 * mm, 46 * mm, 26 * mm, 10 * mm, 2 * mm, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#4D6FA9"))
        c.rect(132 * mm, 46 * mm, 13 * mm, 10 * mm, fill=1, stroke=0)
        c.setStrokeColor(AMBER)
        c.setLineWidth(1.2)
        c.setDash(3, 2)
        c.line(132 * mm, 10 * mm, 132 * mm, 61 * mm)
        c.setDash()
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7)
        c.drawString(146 * mm, 36 * mm, "0.5 a 3 mm")

        c.setFillColor(INK)
        c.setFont("Helvetica", 7)
        c.drawCentredString(43 * mm, 6 * mm, "Iman centrado sobre el chip")
        c.drawCentredString(132 * mm, 6 * mm, "Cara paralela, sin contacto")
        c.restoreState()


def table(data, widths, header=True, font_size=8):
    result = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B9C6C4")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
    ]
    if header:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    for row in range(1 if header else 0, len(data)):
        if row % 2 == 0:
            commands.append(("BACKGROUND", (0, row), (-1, row), PALE))
    result.setStyle(TableStyle(commands))
    return result


def p(text, style):
    return Paragraph(text, style)


def bullet(text, styles):
    return Paragraph(f"• {text}", styles["BulletBody"])


def add_page_number(canvas, doc):
    canvas.saveState()
    if doc.page > 1:
        canvas.setStrokeColor(colors.HexColor("#D5DDD9"))
        canvas.line(18 * mm, 13 * mm, 192 * mm, 13 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(18 * mm, 8 * mm, "Steer-by-wire | Manual AS5600")
        page_text = str(doc.page)
        canvas.drawRightString(192 * mm, 8 * mm, page_text)
    canvas.restoreState()


def build_styles():
    base = getSampleStyleSheet()
    styles = {
        "Title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=25,
            leading=29,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=7 * mm,
        ),
        "Subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=12,
            leading=17,
            textColor=MUTED,
            spaceAfter=8 * mm,
        ),
        "H1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=NAVY,
            spaceBefore=5 * mm,
            spaceAfter=3 * mm,
        ),
        "H2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=TEAL,
            spaceBefore=3 * mm,
            spaceAfter=2 * mm,
        ),
        "Body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=INK,
            spaceAfter=2.5 * mm,
        ),
        "BulletBody": ParagraphStyle(
            "BulletBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=12,
            leftIndent=5 * mm,
            firstLineIndent=-3.5 * mm,
            textColor=INK,
            spaceAfter=1.2 * mm,
        ),
        "Small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=MUTED,
        ),
        "Callout": ParagraphStyle(
            "Callout",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=13,
            textColor=INK,
            borderColor=AMBER,
            borderWidth=1,
            borderPadding=8,
            backColor=WARN,
            spaceBefore=2 * mm,
            spaceAfter=4 * mm,
        ),
        "Code": ParagraphStyle(
            "Code",
            parent=base["Code"],
            fontName="Courier",
            fontSize=8.3,
            leading=11,
            textColor=NAVY,
            borderColor=colors.HexColor("#D5DDD9"),
            borderWidth=0.5,
            borderPadding=7,
            backColor=PALE,
            spaceBefore=1 * mm,
            spaceAfter=3 * mm,
        ),
        "Center": ParagraphStyle(
            "Center",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
    }
    return styles


def build_pdf():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    styles = build_styles()
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=17 * mm,
        bottomMargin=18 * mm,
        title="Mini manual AS5600 con Raspberry Pi Zero 2 W",
        author="Proyecto Steer-by-wire",
        subject="Conexion AS5600, ADS1115 y OLED por I2C",
    )

    story = []
    story += [
        Spacer(1, 20 * mm),
        p("MINI MANUAL DE CONEXION", styles["Subtitle"]),
        p("AS5600 + ADS1115 + OLED<br/>con Raspberry Pi Zero 2 W", styles["Title"]),
        p(
            "Guia de pruebas de banco para el proyecto de direccion steer-by-wire. "
            "Incluye funcionamiento, pinout, alimentacion, cableado y limites de seguridad.",
            styles["Subtitle"],
        ),
        Spacer(1, 8 * mm),
        Table(
            [
                [p("<b>Version</b>", styles["Small"]), p("1.0 - 30 de julio de 2026", styles["Small"])],
                [p("<b>Estado</b>", styles["Small"]), p("Cableado previo a programacion", styles["Small"])],
                [p("<b>Alcance</b>", styles["Small"]), p("Sensor y visualizacion, sin actuador", styles["Small"])],
            ],
            colWidths=[38 * mm, 105 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), PALE),
                    ("BOX", (0, 0), (-1, -1), 0.7, TEAL),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#B9C6C4")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            ),
            hAlign="LEFT",
        ),
        Spacer(1, 15 * mm),
        p(
            "<b>ADVERTENCIA:</b> este montaje es para desarrollo y validacion en banco. "
            "No debe controlar un vehiculo en movimiento sin una arquitectura de seguridad "
            "independiente, parada de emergencia y pruebas documentadas.",
            styles["Callout"],
        ),
        Spacer(1, 20 * mm),
        p("Proyecto Steer-by-wire | Shell Eco-marathon", styles["Center"]),
        PageBreak(),
    ]

    story += [
        p("1. Respuesta corta", styles["H1"]),
        p(
            "El AS5600 puede entregar al mismo tiempo el angulo por <b>I2C</b> y por su "
            "salida <b>OUT analogica</b>. El ADS1115 convierte OUT a digital porque la "
            "Raspberry Pi no tiene entradas analogicas.",
            styles["Body"],
        ),
        p(
            "Las dos lecturas permiten detectar discrepancias, pero <b>no son redundancia "
            "independiente</b>: dependen del mismo AS5600, iman, eje y alimentacion.",
            styles["Callout"],
        ),
        p("2. Como funciona el AS5600", styles["H1"]),
        bullet("Un iman diametral gira centrado sobre el sensor.", styles),
        bullet("Los elementos Hall internos miden la direccion del campo magnetico.", styles),
        bullet("El chip calcula una posicion absoluta de 12 bits: 0 a 4095.", styles),
        bullet("I2C entrega el valor digital y OUT entrega voltaje analogico o PWM.", styles),
        p("angulo = lectura_i2c x 360 / 4096", styles["Code"]),
        p(
            "La resolucion teorica es 0.0879 grados por cuenta. La exactitud del conjunto "
            "sera menor por alineacion, iman, holguras, ruido y tolerancias.",
            styles["Body"],
        ),
        MagnetDiagram(),
        p("Limitacion de una vuelta", styles["H2"]),
        p(
            "El AS5600 representa una sola vuelta absoluta. Al cruzar 360 grados vuelve a "
            "cero. Si el volante gira mas de una vuelta, se necesita una relacion mecanica "
            "que comprima el recorrido, un sensor multivuelta o una segunda referencia "
            "absoluta. Contar vueltas por software puede perderse al reiniciar.",
            styles["Body"],
        ),
        PageBreak(),
    ]

    pin_rows = [
        ["Pin", "Funcion", "Uso propuesto"],
        ["VCC / VDD", "Alimentacion", "3.3 V de la Raspberry Pi"],
        ["GND", "Referencia comun", "GND de la Raspberry Pi"],
        ["SDA", "Datos I2C", "GPIO2, pin fisico 3"],
        ["SCL", "Reloj I2C", "GPIO3, pin fisico 5"],
        ["OUT", "Salida analogica o PWM", "A0 del ADS1115"],
        ["DIR", "Sentido del angulo", "GND para aumento horario"],
        ["PGO", "Programacion especial por OUT", "Sin conectar"],
    ]
    story += [
        p("3. Los siete pines del modulo AS5600", styles["H1"]),
        p(
            "El orden fisico cambia entre placas. Sigue siempre el nombre impreso y no "
            "cuentes pines desde un extremo.",
            styles["Body"],
        ),
        table(pin_rows, [30 * mm, 58 * mm, 82 * mm]),
        Spacer(1, 3 * mm),
        p(
            "<b>PGO, no GPO:</b> el nombre oficial es PGO. Si la serigrafia de tu placa "
            "dice GPO, confirma el modelo con una foto antes de energizar.",
            styles["Callout"],
        ),
        p("DIR", styles["H2"]),
        p(
            "Con DIR a GND, el valor aumenta al girar en sentido horario visto desde arriba. "
            "Con DIR a VCC aumenta en sentido antihorario. Para comenzar se fija a GND; no "
            "se deja flotando.",
            styles["Body"],
        ),
        p("PGO", styles["H2"]),
        p(
            "Se usa para una opcion especial de programacion permanente por el pin OUT. "
            "No lo necesitamos y debe quedar desconectado.",
            styles["Body"],
        ),
        p("OUT", styles["H2"]),
        p(
            "Por defecto es una salida analogica proporcional a VDD. Tambien puede "
            "configurarse como PWM. I2C puede leerse en cualquiera de los dos modos.",
            styles["Body"],
        ),
        p(
            "<b>No grabar OTP todavia.</b> Algunos comandos permanentes tienen una cantidad "
            "limitada de usos. Primero se probaran ajustes volatiles.",
            styles["Callout"],
        ),
        PageBreak(),
    ]

    story += [
        p("4. Diagrama de conexion", styles["H1"]),
        WiringDiagram(),
        Spacer(1, 3 * mm),
        p(
            "Los cuatro colores representan los buses compartidos: 3.3 V, GND, SDA y SCL. "
            "La linea morada es la lectura analogica independiente del bus I2C.",
            styles["Center"],
        ),
        p("Direcciones esperadas", styles["H2"]),
        table(
            [
                ["Dispositivo", "Direccion I2C"],
                ["AS5600", "0x36 fija"],
                ["ADS1115, ADDR a GND", "0x48"],
                ["OLED I2C comun", "0x3C o 0x3D"],
            ],
            [95 * mm, 55 * mm],
        ),
        PageBreak(),
    ]

    wire_rows = [
        ["Raspberry Pi Zero 2 W", "Destino"],
        ["Pin 1 - 3V3", "VCC AS5600 + VDD ADS1115 + VCC OLED"],
        ["Pin 6 - GND", "GND de los tres modulos + DIR del AS5600"],
        ["Pin 3 - GPIO2 / SDA1", "SDA de los tres modulos"],
        ["Pin 5 - GPIO3 / SCL1", "SCL de los tres modulos"],
        ["AS5600 OUT", "ADS1115 A0 / AIN0"],
    ]
    unused_rows = [
        ["Modulo", "Pin", "Estado"],
        ["AS5600", "PGO", "Sin conectar"],
        ["ADS1115", "A1, A2, A3", "Sin conectar por ahora"],
        ["ADS1115", "ALRT", "Sin conectar por ahora"],
        ["ADS1115", "ADDR", "GND o configuracion 0x48 de la placa"],
    ]
    story += [
        p("5. Cableado paso a paso", styles["H1"]),
        p(
            "<b>Haz todas las conexiones con la Raspberry Pi apagada y desconectada.</b>",
            styles["Body"],
        ),
        table(wire_rows, [60 * mm, 110 * mm]),
        p("Pines libres", styles["H2"]),
        table(unused_rows, [38 * mm, 40 * mm, 92 * mm]),
        p("Pantalla OLED", styles["H2"]),
        p(
            "La guia supone una OLED I2C de cuatro pines: GND, VCC, SCL y SDA. Si aparecen "
            "CS, DC, RES, D0 o D1, puede ser una version SPI y hay que verificar su modelo.",
            styles["Body"],
        ),
        p("6. Alimentacion a 3.3 V", styles["H1"]),
        p(
            "Los GPIO de la Raspberry Pi usan 3.3 V y no toleran 5 V. Las placas I2C suelen "
            "elevar SDA y SCL hacia su VCC, por lo que todos los modulos del bus se alimentan "
            "a 3.3 V en esta prueba.",
            styles["Body"],
        ),
        bullet("AS5600 a 3.3 V.", styles),
        bullet("ADS1115 a 3.3 V.", styles),
        bullet("OLED a 3.3 V si su placa confirma compatibilidad.", styles),
        bullet("Todas las tierras unidas.", styles),
        bullet("No agregar pull-ups externas al inicio.", styles),
        PageBreak(),
    ]

    power_rows = [
        ["Carga", "Consumo orientativo"],
        ["AS5600 en modo normal", "aprox. 6.5 mA"],
        ["ADS1115, solo chip", "aprox. 0.15 mA"],
        ["OLED pequena", "estimar 20 a 30 mA, depende del modelo"],
        ["Total perifericos", "aprox. 30 a 50 mA"],
    ]
    story += [
        p("7. Puede la Raspberry Pi alimentarlo todo", styles["H1"]),
        p(
            "Para pruebas de banco, normalmente si. Las placas genericas pueden consumir "
            "algo mas por LEDs o reguladores incorporados.",
            styles["Body"],
        ),
        table(power_rows, [85 * mm, 85 * mm]),
        Spacer(1, 3 * mm),
        p(
            "Alimenta la Raspberry Pi con una fuente estable de <b>5 V y 2 A</b>. Esto no "
            "significa que el motor pueda alimentarse desde la Pi.",
            styles["Callout"],
        ),
        p("En el vehiculo", styles["H2"]),
        bullet("Usar convertidor DC-DC regulado, fusible y proteccion de transitorios.", styles),
        bullet("Separar la potencia del motor de la alimentacion logica.", styles),
        bullet("Usar un controlador de motor adecuado; nunca conectar el motor a GPIO.", styles),
        p("8. Que aporta la doble lectura", styles["H1"]),
        p("<b>Puede detectar:</b>", styles["Body"]),
        bullet("Cable OUT cortado, ADS1115 bloqueado o canal analogico fijo.", styles),
        bullet("Diferencia excesiva entre la curva analogica y el valor I2C.", styles),
        bullet("Errores de configuracion o conversion del ADS1115.", styles),
        p("<b>No cubre por si sola:</b>", styles["Body"]),
        bullet("Iman suelto, descentrado, ausente o demasiado lejos.", styles),
        bullet("Falla comun del AS5600, alimentacion, montaje o Raspberry Pi.", styles),
        p(
            "Para redundancia real se recomiendan dos canales fisicamente independientes y "
            "una capa de control capaz de llevar el actuador a estado seguro si Linux falla.",
            styles["Callout"],
        ),
        PageBreak(),
    ]

    story += [
        p("9. Estrategia de lectura recomendada", styles["H1"]),
        bullet("Leer RAW ANGLE por I2C en 0x36.", styles),
        bullet("Supervisar MD, ML y MH en el registro STATUS.", styles),
        bullet("Leer A0 del ADS1115 con rango de +-4.096 V.", styles),
        bullet("Convertir y calibrar ambos canales en grados.", styles),
        bullet("Comparar usando diferencia angular circular en el salto 359/0.", styles),
        bullet("Ante discrepancia persistente: declarar falla, inhibir actuador y registrar.", styles),
        bullet("Mostrar angulo, iman y estado OK/FALLA en la OLED.", styles),
        p("10. Comprobacion al volver a encender", styles["H1"]),
        p("Habilitar I2C:", styles["Body"]),
        p("sudo raspi-config", styles["Code"]),
        p("Seleccionar Interface Options > I2C > Enable. Luego ejecutar:", styles["Body"]),
        p("i2cdetect -y 1", styles["Code"]),
        p(
            "Deben aparecer 0x36, 0x48 y 0x3C (o 0x3D). Si i2cdetect no existe, se instalara "
            "i2c-tools cuando la Raspberry Pi tenga acceso a Internet.",
            styles["Body"],
        ),
        p("11. Montaje del iman", styles["H1"]),
        bullet("Usar iman diametral, no axial.", styles),
        bullet("Mantener la cara paralela a la placa y el eje centrado.", styles),
        bullet("Separacion tipica: 0.5 a 3 mm, segun el iman.", styles),
        bullet("Con iman de 6 mm, descentramiento orientativo maximo de 0.25 mm.", styles),
        bullet("Retener el iman mecanicamente; no confiar solo en adhesivo.", styles),
        PageBreak(),
    ]

    checklist = [
        "Raspberry Pi apagada y desconectada.",
        "Etiquetas exactas verificadas en cada placa.",
        "Ningun cable de 5 V llega a SDA, SCL, OUT o A0.",
        "Los tres modulos reciben 3.3 V y comparten GND.",
        "OUT del AS5600 llega solamente a A0 del ADS1115.",
        "PGO queda sin conectar y DIR va a GND.",
        "No hay motor ni driver conectado en esta etapa.",
        "Iman diametral centrado, retenido y sin rozar el sensor.",
        "Se tomaron fotos del frente, reverso y cableado.",
    ]
    story += [
        p("12. Lista antes de energizar", styles["H1"]),
    ]
    for item in checklist:
        story.append(
            Table(
                [["[  ]", p(item, styles["Body"])]],
                colWidths=[12 * mm, 158 * mm],
                style=TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TEXTCOLOR", (0, 0), (0, 0), TEAL),
                        ("FONTNAME", (0, 0), (0, 0), "Courier-Bold"),
                        ("FONTSIZE", (0, 0), (0, 0), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ]
                ),
            )
        )
    story += [
        Spacer(1, 4 * mm),
        p(
            "<b>Pausa de seguridad:</b> antes de aplicar energia se necesitan fotos nitidas "
            "del frente y reverso del AS5600, ADS1115 y OLED. Asi se confirma el orden fisico, "
            "los reguladores y las resistencias pull-up de tus placas concretas.",
            styles["Callout"],
        ),
        p("13. Fuentes tecnicas", styles["H1"]),
        p(
            'Infineon/ams OSRAM: <link href="https://www.infineon.com/assets/row/public/'
            'documents/24/49/infineon-as5600-datasheet-en.pdf" color="#2F7D77">'
            "AS5600 datasheet</link>.",
            styles["Body"],
        ),
        p(
            'ams OSRAM: <link href="https://look.ams-osram.com/m/8a0660dd2b70f413/'
            'original/AS5600_UG000240_1-00.pdf" color="#2F7D77">'
            "manual de placa de siete pines</link>.",
            styles["Body"],
        ),
        p(
            'Texas Instruments: <link href="https://www.ti.com/lit/gpn/ads1115" '
            'color="#2F7D77">ADS1115 datasheet</link>.',
            styles["Body"],
        ),
        p(
            'Raspberry Pi: <link href="https://www.raspberrypi.com/documentation/'
            'computers/raspberry-pi.html" color="#2F7D77">GPIO y Zero 2 W</link>.',
            styles["Body"],
        ),
    ]

    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    print(OUTPUT)


if __name__ == "__main__":
    build_pdf()
