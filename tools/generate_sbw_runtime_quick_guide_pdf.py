from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pdf" / "SBW_runtime_guia_rapida_v01.pdf"


def add_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(18 * mm, 10 * mm, "Steer-by-wire - guia rapida de banco")
    canvas.drawRightString(192 * mm, 10 * mm, f"Pagina {doc.page}")
    canvas.restoreState()


def p(text: str, style):
    return Paragraph(text, style)


def code(text: str, styles):
    return Preformatted(text.strip(), styles["Code"])


def bullet(text: str, styles):
    return p(f"- {text}", styles["Body"])


def command_table(rows, styles):
    data = [[p("Parametro", styles["TableHead"]), p("Para que sirve", styles["TableHead"])]]
    for left, right in rows:
        data.append([p(left, styles["TableBody"]), p(right, styles["TableBody"])])
    table = Table(data, colWidths=[56 * mm, 112 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#22364a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#b8c2cc")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f7f9fb")),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    base = getSampleStyleSheet()
    styles = {
        "Title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#17212b"),
            spaceAfter=8,
        ),
        "H1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#17324d"),
            spaceBefore=10,
            spaceAfter=6,
        ),
        "H2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#17324d"),
            spaceBefore=8,
            spaceAfter=4,
        ),
        "Body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13,
            spaceAfter=4,
        ),
        "Small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#4b5563"),
            spaceAfter=3,
        ),
        "Code": ParagraphStyle(
            "Code",
            parent=base["Code"],
            fontName="Courier",
            fontSize=7.8,
            leading=9.5,
            backColor=colors.HexColor("#f0f3f6"),
            borderColor=colors.HexColor("#d0d7de"),
            borderWidth=0.4,
            borderPadding=5,
            leftIndent=0,
            rightIndent=0,
            spaceBefore=4,
            spaceAfter=7,
        ),
        "TableHead": ParagraphStyle(
            "TableHead",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.white,
        ),
        "TableBody": ParagraphStyle(
            "TableBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.2,
            leading=10.5,
        ),
    }

    story = []
    story.append(p("Guia rapida - Steer-by-wire Raspberry", styles["Title"]))
    story.append(
        p(
            "Resumen operativo para arrancar desde cero, setear el sensor AS5600, "
            "guardar centro y limites del motor, mover con flechas y correr el modo sensor-motor.",
            styles["Body"],
        )
    )
    story.append(
        p(
            "Usar solo en banco. Antes de mover motor confirma que el carro este levantado o sin carga peligrosa, "
            "que el driver pueda cortarse desde la fuente de 24 V y que el comando incluya --confirm BANCO_LIBRE.",
            styles["Small"],
        )
    )

    story.append(p("1. Entrar a la Raspberry", styles["H1"]))
    story.append(code("ssh cnvte11@raspberrypi.local\ncd ~/Documentos/steer-by-wire\nsource .venv/bin/activate", styles))
    story.append(
        p(
            "Para comandos que hablan con el motor por CAN se usa sudo .venv/bin/python. "
            "Para leer solo el sensor no hace falta sudo normalmente.",
            styles["Body"],
        )
    )

    story.append(p("2. Revisar I2C del AS5600", styles["H1"]))
    story.append(code("i2cdetect -y 1", styles))
    story.append(bullet("Debe aparecer 36. Si no aparece, el sensor no esta respondiendo por I2C.", styles))
    story.append(bullet("Con el bus libre, SDA-GND y SCL-GND deben estar cerca de 3.3 V.", styles))
    story.append(bullet("Si SDA queda cerca de 1.7 V al conectar el sensor, revisar pinout, JST, corto o sensor danado.", styles))

    story.append(p("3. Ver angulo del sensor en terminal", styles["H1"]))
    story.append(code("python3 tools/steer_by_wire_follow_runtime.py monitor --no-oled --terminal-hz 5 --duration 20", styles))
    story.append(
        p(
            "La salida muestra angle, raw, estado de iman y cero guardado. Si no tienes OLED conectada, "
            "--no-oled evita que el programa intente usarla.",
            styles["Body"],
        )
    )

    story.append(p("4. Setear cero del sensor", styles["H1"]))
    story.append(
        p(
            "Coloca la cabrilla exactamente en la posicion que quieres que sea 0 grados. "
            "Luego ejecuta:",
            styles["Body"],
        )
    )
    story.append(code("python3 tools/steer_by_wire_follow_runtime.py calibrate-zero --no-oled", styles))
    story.append(bullet("El cero queda guardado en .sbw_sensor_zero.json.", styles))
    story.append(bullet("No se pierde al apagar y prender la Raspberry.", styles))
    story.append(bullet("Si despues mueves la cabrilla antes de prender, el programa seguira usando el cero guardado, no tomara la nueva posicion como cero automaticamente.", styles))
    story.append(bullet("Para ignorar temporalmente ese cero, agrega --ignore-saved-zero al monitor o follow.", styles))

    story.append(p("5. Guardar centro y limites del motor", styles["H1"]))
    story.append(
        p(
            "Primero mueve el motor con keyboard-jog hasta la posicion deseada. Despues guarda cada punto:",
            styles["Body"],
        )
    )
    story.append(code("sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py save-center", styles))
    story.append(code("sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py save-right-limit", styles))
    story.append(code("sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py save-left-limit", styles))
    story.append(bullet("El archivo usado es .sbw_motor_limits.json.", styles))
    story.append(bullet("Centro = carro derecho. Right/left = topes mecanicos que no se deben pasar.", styles))
    story.append(bullet("Puedes revisar la posicion actual con print-position.", styles))
    story.append(code("sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py print-position", styles))

    story.append(PageBreak())
    story.append(p("6. Mover motor con flechas", styles["H1"]))
    story.append(
        p(
            "Este comando mueve el motor con flecha izquierda/derecha. Al soltar la flecha debe parar "
            "despues del release-timeout. Usa --ignore-motor-limits solo para pruebas de banco.",
            styles["Body"],
        )
    )
    story.append(
        code(
            """
sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py keyboard-jog \\
  --speed-rpm 1300 \\
  --release-timeout 0.50 \\
  --jog-refresh-s 0.1 \\
  --key-poll-s 0.02 \\
  --travel-pulses 2000000 \\
  --jog-acceleration-ms 10 \\
  --jog-deceleration-ms 10 \\
  --limit-check-s 0.02 \\
  --limit-tolerance-pulses 50 \\
  --jog-status-hz 5 \\
  --reverse-jog \\
  --allow-driver-enable \\
  --confirm BANCO_LIBRE
""",
            styles,
        )
    )
    story.append(p("Parametros importantes de keyboard-jog", styles["H2"]))
    story.append(
        command_table(
            [
                ("--speed-rpm", "Velocidad del motor en RPM. Si vibra o va por pasos, baja RPM o sube rampas AC/DC."),
                ("--release-timeout", "Tiempo para parar al soltar la flecha. Menor = para mas rapido; no bajar de 0.05 s."),
                ("--jog-refresh-s", "Cada cuanto refresca el comando mientras mantienes flecha. Menor = mas continuo; minimo validado 0.05 s."),
                ("--key-poll-s", "Cada cuanto lee teclado. 0.02 s funciona bien por SSH."),
                ("--travel-pulses", "Objetivo lejano por cada direccion cuando no se usan limites."),
                ("--jog-acceleration-ms / --jog-deceleration-ms", "Rampa del driver. 10 ms es minimo practico; si el motor suena feo, subir a 50-100 ms."),
                ("--reverse-jog", "Invierte flechas si izquierda/derecha quedan al reves."),
                ("--ignore-motor-limits", "Solo banco: permite mover sin respetar limites guardados."),
            ],
            styles,
        )
    )

    story.append(p("7. Programa sensor-motor: AS5600 siguiendo al motor", styles["H1"]))
    story.append(
        p(
            "Este modo lee el angulo del AS5600 y manda el motor al punto equivalente entre centro, limite izquierdo y limite derecho. "
            "Mapeo actual: 0 grados = centro, +90 grados = limite izquierdo, -90 grados = limite derecho.",
            styles["Body"],
        )
    )
    story.append(
        code(
            """
sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py follow \\
  --no-oled \\
  --continuous \\
  --use-saved-motor-limits \\
  --max-angle 90 \\
  --sensor-hz 50 \\
  --terminal-hz 5 \\
  --i2c-retries 5 \\
  --i2c-retry-delay 0.01 \\
  --follow-deadband-deg 5 \\
  --follow-alpha 0.15 \\
  --max-sensor-step 45 \\
  --max-sensor-outliers 10 \\
  --max-speed-rpm 950 \\
  --catchup-gain 8 \\
  --acceleration-ms 100 \\
  --deceleration-ms 100 \\
  --command-hz 20 \\
  --status-hz 5 \\
  --ignore-tracking-error \\
  --allow-driver-enable \\
  --confirm BANCO_LIBRE
""",
            styles,
        )
    )
    story.append(p("Parametros importantes de follow", styles["H2"]))
    story.append(
        command_table(
            [
                ("--use-saved-motor-limits", "Usa centro, limite derecho e izquierdo guardados en .sbw_motor_limits.json."),
                ("--max-angle 90", "Satura la entrada del volante entre -90 y +90 grados."),
                ("--follow-deadband-deg", "Zona muerta alrededor del centro para que no persiga ruido pequeno."),
                ("--follow-alpha", "Filtro del angulo. Menor = mas suave pero mas lento; mayor = mas rapido pero mas nervioso."),
                ("--max-speed-rpm", "Velocidad maxima del motor en RPM. Default actual: 950 RPM. Puedes editarlo al correr el comando."),
                ("--max-speed", "Compatibilidad: velocidad maxima en pulsos por segundo si alguna vez prefieres pps."),
                ("--catchup-gain", "Que tan agresivo corrige el error entre objetivo y motor."),
                ("--acceleration-ms / --deceleration-ms", "Rampas del driver. Si suena por pasos o pierde suavidad, subir estos valores."),
                ("--i2c-retries", "Reintentos si hay un error I2C momentaneo."),
                ("--ignore-tracking-error", "Solo banco: evita que aborte por error de seguimiento mientras se ajusta."),
                ("--reverse", "Agregar si el sensor manda el motor al lado contrario."),
            ],
            styles,
        )
    )

    story.append(p("8. Secuencia recomendada desde cero", styles["H1"]))
    for item in [
        "Conectar solo sensor y confirmar i2cdetect -y 1 con direccion 36.",
        "Correr monitor y verificar que angle cambie suave al girar la cabrilla.",
        "Poner cabrilla derecha y ejecutar calibrate-zero.",
        "Mover motor con keyboard-jog y guardar save-center.",
        "Mover al maximo derecho seguro y guardar save-right-limit.",
        "Mover al maximo izquierdo seguro y guardar save-left-limit.",
        "Correr keyboard-jog con limites para confirmar que no pasa los topes.",
        "Correr follow con --use-saved-motor-limits y empezar con velocidades moderadas.",
    ]:
        story.append(bullet(item, styles))

    story.append(p("9. Si algo falla", styles["H1"]))
    story.append(bullet("Si no aparece 36: problema electrico/I2C antes del programa.", styles))
    story.append(bullet("Si sale Errno 5: el bus I2C perdio comunicacion; revisar cables, GND, SDA/SCL y alimentacion.", styles))
    story.append(bullet("Si el motor va al lado contrario: agregar --reverse o quitarlo, segun el caso.", styles))
    story.append(bullet("Si el motor va por pasos: bajar velocidad, subir rampas AC/DC, o aumentar jog-refresh-s dentro del rango permitido.", styles))
    story.append(bullet("Para detener de emergencia: cortar la fuente de 24 V del driver.", styles))

    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)


if __name__ == "__main__":
    build()
    print(OUT)
