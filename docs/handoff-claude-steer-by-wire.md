# Handoff para trabajar el steer-by-wire en Claude

Fecha de corte: 2026-09-25  
Repositorio local: `C:\Users\Admin\Desktop\PORTFOLIO\Steer-by-wire`  
Raspberry Pi: usuario `cnvte11`, host habitual `raspberrypi.local`  
Ruta en Raspberry: `~/Documentos/steer-by-wire`

## Prompt corto para pegar en Claude

Estoy trabajando en un prototipo de banco steer-by-wire. Usa Raspberry Pi Zero 2 W, AS5600 por I2C, MCP2515 CAN HAT, controlador UIM342 nodo 13 y motor UIM4247CM con reduccion 50:1. Lee todo este archivo primero. El archivo principal actual es `tools/steer_by_wire_follow_runtime.py`. Necesito ayuda para estabilizar el modo `follow`: mapear AS5600 a limites guardados del motor, filtrar ruido del sensor, evitar fallas falsas de iman, y ajustar velocidad/seguimiento sin perder seguridad de banco. No propongas cambios sin explicar que archivo tocar y que comando probar en la Raspberry.

## Resumen del sistema

Cadena actual:

```text
AS5600 -> I2C -> Raspberry Pi Zero 2 W -> SocketCAN/can0 -> MCP2515 HAT -> UIM342 -> UIM4247CM
```

Hardware principal:

- Sensor de volante: `AS5600`, I2C direccion `0x36`.
- Raspberry Pi Zero 2 W.
- HAT CAN basado en MCP2515, interfaz `can0`, bitrate `500000`.
- Driver/controlador: `UIM342`, nodo CAN `13`.
- Motor: `UIM4247CM`.
- Reduccion usada en software: `50:1`.
- Pulsos de motor por vuelta interna: `3200`.
- Pulsos por vuelta de salida: `3200 * 50 = 160000`.

Estado actual:

- `keyboard-jog` con flechas funciona y respeta limites guardados.
- `follow` ya une AS5600 con motor, pero todavia esta en ajuste porque la lectura del AS5600 salta/mete ruido.
- El sensor ha mostrado errores I2C intermitentes `[Errno 5] Input/output error`.
- El estado de iman invalido ya NO debe parar el `follow`; solo debe advertir.
- Para banco se agrego `--ignore-tracking-error` para que no aborte por error de seguimiento mientras se ajusta.

## Archivos importantes

### Runtime principal

```text
tools/steer_by_wire_follow_runtime.py
```

Este es el archivo mas importante ahora. Contiene:

- `monitor`: leer AS5600 sin mover motor.
- `calibrate-zero`: guardar cero persistente del AS5600.
- `keyboard-jog`: mover motor con flechas.
- `print-position`: imprimir posicion absoluta del motor.
- `save-center`: guardar centro del motor.
- `save-right-limit`: guardar limite derecho.
- `save-left-limit`: guardar limite izquierdo.
- `follow`: seguimiento AS5600 -> motor.

Cambios relevantes ya implementados:

- Cero persistente del AS5600 en `.sbw_sensor_zero.json`.
- Limites persistentes del motor en `.sbw_motor_limits.json`.
- `keyboard-jog` acepta `--speed-rpm`.
- `keyboard-jog` respeta limites por lado fisico, aunque derecha sea menor que izquierda.
- `keyboard-jog` tiene watchdog de limites.
- `follow` tiene `--use-saved-motor-limits`.
- `follow` mapea:
  - `0 deg` -> centro guardado.
  - `+90 deg` -> limite izquierdo guardado.
  - `-90 deg` -> limite derecho guardado.
- `follow` tiene filtro `--follow-alpha`.
- `follow` tiene zona muerta `--follow-deadband-deg`.
- `follow` tiene retries I2C: `--i2c-retries`, `--i2c-retry-delay`.
- `follow` ya no debe abortar por iman invalido.
- `follow` puede no abortar por tracking error con `--ignore-tracking-error`.

### CAN/UIM342

```text
tools/steer_by_wire_can_runtime.py
```

Contiene la capa CAN base:

- Configuracion de `can0`.
- Clase `Uim342Can`.
- Lectura de estado del motor.
- Escritura de posicion absoluta.
- Escritura de velocidad.
- Habilitar/deshabilitar driver.

### Sensor/OLED

```text
tools/oled_compass.py
```

Contiene clases relacionadas con:

- `AS5600`.
- OLED SSD1306.

El proyecto ahora corre sin OLED usando `--no-oled`.

### Pruebas

```text
tests/test_steer_by_wire_follow_runtime.py
tests/test_steer_by_wire_can_runtime.py
```

Ultima corrida local conocida del test principal:

```text
Ran 39 tests OK
```

Comando local:

```powershell
python -m unittest tests.test_steer_by_wire_follow_runtime
```

### PDF de guia rapida

```text
output/pdf/SBW_runtime_guia_rapida_v01.pdf
```

PDF actualizado con comandos de banco, limites, RPM, tolerancias, errores comunes.

### PCB

```text
hardware/pcb/SBW-PCB-001_as5600-rpi-power-interface/design/SBW-PCB-001_as5600-rpi-power-interface_v01.pdsprj
hardware/pcb/SBW-PCB-001_as5600-rpi-power-interface/gerber/v01 - CADCAM.ZIP
```

Nota importante de PCB:

- Hubo problema de I2C porque `SDA` tenia continuidad con `GND`.
- Al quitar la PCB, `i2cdetect` volvio a la normalidad.
- Se debe revisar siempre continuidad antes de conectar:

```text
SDA - GND  NO debe pitar
SCL - GND  NO debe pitar
SDA - SCL  NO debe pitar
3V3 - GND  NO debe pitar
```

## Comandos de transferencia Windows -> Raspberry

Cuando se modifica `tools/steer_by_wire_follow_runtime.py` en Windows, copiarlo a la Raspberry:

```powershell
scp C:\Users\Admin\Desktop\PORTFOLIO\Steer-by-wire\tools\steer_by_wire_follow_runtime.py cnvte11@raspberrypi.local:~/Documentos/steer-by-wire/tools/
```

Si `raspberrypi.local` falla, usar IP de la Raspberry:

```powershell
scp C:\Users\Admin\Desktop\PORTFOLIO\Steer-by-wire\tools\steer_by_wire_follow_runtime.py cnvte11@<IP_RPI>:~/Documentos/steer-by-wire/tools/
```

## Arranque basico en Raspberry

```bash
cd ~/Documentos/steer-by-wire
source .venv/bin/activate
```

Para comandos que tocan CAN/motor:

```bash
sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py ...
```

Para comandos solo de sensor:

```bash
python3 tools/steer_by_wire_follow_runtime.py ...
```

## Ver I2C

```bash
i2cdetect -y 1
```

Resultado esperado con AS5600:

```text
36
```

Si salen casi todas las direcciones (`08 09 0a ... 77`), normalmente hay corto o bus mal conectado. En nuestro caso paso por SDA a GND en la PCB.

## Conexion AS5600

AS5600 por I2C:

```text
VCC -> 3V3 Raspberry
GND -> GND Raspberry
SDA -> GPIO2, pin fisico 3
SCL -> GPIO3, pin fisico 5
DIR -> GND recomendado
OUT -> no usado
PGO -> no usado
```

DIR:

- Recomendado: `DIR -> GND`.
- No dejar flotando.
- Si se quiere flexibilidad en PCB: jumper `3V3 - DIR - GND`.

Capacitor:

- `100 nF` entre `3V3` y `GND`, cerca del sensor/conector.
- Va en paralelo, no en serie.

## Archivos persistentes en Raspberry

Estos archivos viven en la raiz del repo en la Raspberry:

```text
~/Documentos/steer-by-wire/.sbw_sensor_zero.json
~/Documentos/steer-by-wire/.sbw_motor_limits.json
```

`.sbw_sensor_zero.json`:

- Guarda el cero del AS5600.
- Si la Raspberry se apaga, el cero no se pierde.

`.sbw_motor_limits.json`:

- Guarda centro del motor.
- Guarda limite derecho.
- Guarda limite izquierdo.

Valores absolutos reportados por el estudiante en una prueba:

```text
derecho   = 1079316
centro    = 1105715
izquierdo = 1155358
```

En otra prueba aparecio limite bajo:

```text
derecho o minimo = 1052634
izquierdo/maximo = 1155358
```

Ojo: derecha puede ser menor que izquierda. El codigo ya debe manejar eso.

## Comandos del sensor

### Monitor sin OLED

```bash
python3 tools/steer_by_wire_follow_runtime.py monitor --no-oled --terminal-hz 5 --duration 30
```

Salida esperada:

```text
AS5600 angle= +4.74 raw=2647 magnet=True strong=False weak=False zero=227.90deg
```

Interpretacion:

- `magnet=True`: detecta iman.
- `strong=False`: no esta demasiado fuerte.
- `weak=False`: no esta demasiado debil.
- Si la lectura salta mucho quieto, revisar alineacion iman/sensor, soldaduras, cables, ruido I2C.

### Calibrar cero del AS5600

Poner la cabrilla en posicion fisica de cero y correr:

```bash
python3 tools/steer_by_wire_follow_runtime.py calibrate-zero --no-oled
```

Esto guarda `.sbw_sensor_zero.json`.

## Comandos del motor sin sensor

### Ver posicion absoluta

```bash
sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py print-position
```

### Guardar centro

Poner mecanicamente la direccion en centro/carro derecho y correr:

```bash
sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py save-center
```

### Guardar limite derecho

Mover con flechas hasta el tope derecho y correr:

```bash
sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py save-right-limit
```

### Guardar limite izquierdo

Mover con flechas hasta el tope izquierdo y correr:

```bash
sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py save-left-limit
```

## Mover motor con flechas

### Con limites activos

Usar despues de guardar centro, derecha e izquierda. Importante: NO usar `--ignore-motor-limits`.

```bash
sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py keyboard-jog \
  --speed-rpm 1300 \
  --release-timeout 0.50 \
  --jog-refresh-s 0.1 \
  --key-poll-s 0.02 \
  --travel-pulses 2000000 \
  --jog-acceleration-ms 10 \
  --jog-deceleration-ms 10 \
  --limit-check-s 0.02 \
  --limit-tolerance-pulses 50 \
  --jog-status-hz 5 \
  --reverse-jog \
  --allow-driver-enable \
  --confirm BANCO_LIBRE
```

Teclas:

```text
flecha izquierda/derecha -> mover
ESPACIO o s             -> stop inmediato
p                       -> imprimir estado
q                       -> salir con parada controlada
```

Parametros clave:

- `--speed-rpm`: velocidad del motor en RPM. `1300 RPM` equivale a `69333 pps`.
- `--release-timeout`: si se corta mientras mantienes flecha, subir a `0.70`. Si tarda al soltar, bajar a `0.35`.
- `--jog-acceleration-ms` y `--jog-deceleration-ms`: rampas del driver. Minimo real observado `10 ms`.
- `--limit-tolerance-pulses 50`: evita bloquear por 1 o pocos pulsos fuera del limite.

### Sin limites

Solo para video o reposicionamiento controlado. El motor puede pasar los topes guardados.

```bash
sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py keyboard-jog \
  --speed-rpm 1300 \
  --release-timeout 0.50 \
  --jog-refresh-s 0.1 \
  --key-poll-s 0.02 \
  --travel-pulses 2000000 \
  --jog-acceleration-ms 10 \
  --jog-deceleration-ms 10 \
  --jog-status-hz 5 \
  --reverse-jog \
  --ignore-motor-limits \
  --allow-driver-enable \
  --confirm BANCO_LIBRE
```

## Follow: AS5600 controla motor

Objetivo actual:

```text
AS5600 0 grados   -> centro guardado
AS5600 +90 grados -> limite izquierdo guardado
AS5600 -90 grados -> limite derecho guardado
```

Comando mas reciente recomendado para pruebas de banco:

```bash
sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py follow \
  --no-oled \
  --continuous \
  --use-saved-motor-limits \
  --max-angle 90 \
  --sensor-hz 50 \
  --terminal-hz 5 \
  --i2c-retries 5 \
  --i2c-retry-delay 0.01 \
  --follow-deadband-deg 5 \
  --follow-alpha 0.15 \
  --max-sensor-step 45 \
  --max-sensor-outliers 10 \
  --max-speed 60000 \
  --catchup-gain 8 \
  --acceleration-ms 100 \
  --deceleration-ms 100 \
  --command-hz 20 \
  --status-hz 5 \
  --ignore-tracking-error \
  --allow-driver-enable \
  --confirm BANCO_LIBRE
```

Si el motor va al lado contrario:

```bash
--reverse
```

Agregar `--reverse` dentro del comando `follow`.

## Interpretar salida del follow

Ejemplo:

```text
wheel=-96.94deg delta=-90.00deg velocity=-240.1deg/s target=1057610 motor=1062904 error=-5294 speed_cmd=32000pps limited=True
```

Campos:

- `wheel`: angulo del AS5600 relativo al cero.
- `delta`: angulo usado por el control despues de limite `max-angle`.
- `velocity`: velocidad estimada del volante.
- `target`: posicion absoluta objetivo del motor.
- `motor`: posicion absoluta actual del motor.
- `error`: `target - motor`.
- `speed_cmd`: velocidad enviada al UIM342.
- `limited=True`: el sensor pidio mas de `max-angle`, y se recorto a `+/-90`.

En la ultima prueba se vio que el motor si llegaba al tope por momentos:

```text
target=1052634 motor=1052633 error=+1
```

Pero luego el sensor salto de cerca de `-100 deg` a `-7 deg`, cambiando el objetivo hacia el centro. Esto indica ruido/saltos de AS5600 o mecanica del iman.

## Problemas conocidos y diagnostico

### `i2cdetect` muestra todas las direcciones

Sintoma:

```text
08 09 0a 0b ... 77
```

Causa probable:

- SDA/SCL en corto.
- SDA a GND.
- PCB mal conectada.

Caso real:

- Con sensor quitado seguia mal.
- Con PCB quitada se arreglo.
- Se midio continuidad `SDA-GND`.

Accion:

- No conectar PCB hasta corregir corto.
- Medir continuidad en PCB desconectada.

### AS5600 salta quieto

Sintoma:

```text
AS5600 angle= +4.74
AS5600 angle= +12.22
AS5600 angle= -2.81
```

Aunque `magnet=True strong=False weak=False`, la lectura no esta estable.

Revisar:

- Iman centrado.
- Distancia iman-AS5600.
- Rigidez del soporte.
- Soldaduras en SDA/SCL/GND/3V3.
- Ruido o falsos contactos de PCB.

### `ERROR: [Errno 5] Input/output error`

Error I2C. Se agregaron retries:

```bash
--i2c-retries 5 --i2c-retry-delay 0.01
```

Pero si persiste, es hardware/cableado/PCB.

### `Estado de iman invalido`

Antes abortaba. Ahora debe solo advertir y continuar.

### `Error de seguimiento excesivo`

Antes abortaba si el motor no seguia suficientemente. Para banco se puede ignorar:

```bash
--ignore-tracking-error
```

No usar eso como solucion final para vehiculo; es solo para banco.

### ACK AC inesperado `0a 00 00 00`

Paso al intentar rampas de `5 ms`:

```bash
--jog-acceleration-ms 5
--jog-deceleration-ms 5
```

`0a` hexadecimal = `10`. El driver redondea/minimo real `10 ms`.

Recomendacion:

```bash
--jog-acceleration-ms 10 --jog-deceleration-ms 10
```

Para `follow`:

```bash
--acceleration-ms 100 --deceleration-ms 100
```

## Parametros importantes del follow

- `--use-saved-motor-limits`: usa `.sbw_motor_limits.json`.
- `--max-angle 90`: mapea `+/-90 deg` a topes.
- `--reverse`: invierte sentido sensor->motor.
- `--follow-alpha`: filtro suave del angulo usado para control.
  - Mas bajo = mas suave, menos saltos, mas lento.
  - Ejemplo: `0.15`.
  - Mas alto = responde mas rapido, persigue ruido.
- `--follow-deadband-deg`: zona muerta alrededor del centro.
  - Ejemplo: `5`.
- `--max-speed`: velocidad maxima del motor en pps.
  - `60000` pps aprox `1125 RPM` motor.
- `--catchup-gain`: cuanto acelera por error de seguimiento.
  - Subir para perseguir mas fuerte.
  - Ejemplo actual: `8`.
- `--command-hz`: frecuencia maxima de envio de objetivos.
  - Ejemplo actual: `20`.
- `--max-sensor-step`: salto maximo permitido por lectura.
  - Ejemplo actual: `45`.
- `--max-sensor-outliers`: saltos consecutivos permitidos antes de abortar.
  - Ejemplo actual: `10`.
- `--ignore-tracking-error`: banco solamente.

## Que revisar si el motor no llega al tope

1. Confirmar que los limites guardados son correctos:

```bash
cat .sbw_motor_limits.json
```

2. Confirmar que `follow` usa:

```bash
--use-saved-motor-limits --max-angle 90
```

3. Mirar salida:

```text
delta=-90.00deg target=<limite derecho>
```

Si `delta` llega a `-90` y `target` es el limite derecho, el mapeo esta bien.

4. Si `motor` llega cerca de `target`, el motor esta cumpliendo.

5. Si luego el `target` cambia de golpe hacia centro aunque la cabrilla este sostenida, el problema es lectura del AS5600.

6. Para estabilizar:

```bash
--follow-alpha 0.10
--follow-deadband-deg 8
--sensor-hz 30
```

7. Para hacerlo seguir mas fuerte:

```bash
--max-speed 80000
--catchup-gain 12
```

Subir con cuidado.

## Seguridad

Esto es banco, no vehiculo.

Reglas:

- Siempre tener corte fisico de 24 V.
- No meter manos en mecanismo con driver energizado.
- Usar `--confirm BANCO_LIBRE`.
- No usar `--ignore-motor-limits` salvo reposicionamiento/video.
- `--ignore-tracking-error` es solo para pruebas, no para validacion.
- La Raspberry Pi no es controlador de seguridad en tiempo real.

## Estado Git/local

Hay cambios locales no necesariamente commiteados. Estado visto:

```text
 M README.md
 M docs/direct-can-follow-runtime.md
 M tests/test_steer_by_wire_follow_runtime.py
 M tools/steer_by_wire_follow_runtime.py
 ?? hardware/pcb/
 ?? varios archivos CAD/STL nuevos
```

Si Claude o el profesor van a editar, primero revisar:

```bash
git status --short
git diff -- tools/steer_by_wire_follow_runtime.py
```

No hacer `git reset --hard`.

## Rutas CAD/PCB

CAD:

```text
hardware/cad/
hardware/cad/parts/
hardware/cad/assemblies/
hardware/cad/exports/stl/
```

PCB:

```text
hardware/pcb/SBW-PCB-001_as5600-rpi-power-interface/
hardware/pcb/SBW-PCB-001_as5600-rpi-power-interface/design/
hardware/pcb/SBW-PCB-001_as5600-rpi-power-interface/gerber/
```

Archivo Proteus:

```text
hardware/pcb/SBW-PCB-001_as5600-rpi-power-interface/design/SBW-PCB-001_as5600-rpi-power-interface_v01.pdsprj
```

Gerber:

```text
hardware/pcb/SBW-PCB-001_as5600-rpi-power-interface/gerber/v01 - CADCAM.ZIP
```

## Siguiente tarea recomendada para Claude/profesor

1. Revisar `tools/steer_by_wire_follow_runtime.py`.
2. Confirmar que `follow` no aborta por iman invalido.
3. Confirmar que `--ignore-tracking-error` funciona.
4. En Raspberry, correr monitor y cuantificar estabilidad AS5600 quieto:

```bash
python3 tools/steer_by_wire_follow_runtime.py monitor --no-oled --terminal-hz 5 --duration 30
```

5. Si el AS5600 sigue saltando mas de 3-5 grados quieto, solucionar mecanica/PCB antes de seguir afinando control.
6. Si el sensor se estabiliza, bajar filtro:

```bash
--follow-alpha 0.25
--follow-deadband-deg 3
```

7. Ajustar seguimiento:

```bash
--max-speed 60000 a 80000
--catchup-gain 8 a 12
--acceleration-ms 100
--deceleration-ms 100
```

## Comando final de referencia para continuar

```bash
cd ~/Documentos/steer-by-wire
source .venv/bin/activate

sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py follow \
  --no-oled \
  --continuous \
  --use-saved-motor-limits \
  --max-angle 90 \
  --sensor-hz 50 \
  --terminal-hz 5 \
  --i2c-retries 5 \
  --i2c-retry-delay 0.01 \
  --follow-deadband-deg 5 \
  --follow-alpha 0.15 \
  --max-sensor-step 45 \
  --max-sensor-outliers 10 \
  --max-speed 60000 \
  --catchup-gain 8 \
  --acceleration-ms 100 \
  --deceleration-ms 100 \
  --command-hz 20 \
  --status-hz 5 \
  --ignore-tracking-error \
  --allow-driver-enable \
  --confirm BANCO_LIBRE
```

Si va al lado contrario:

```bash
--reverse
```

