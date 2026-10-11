# Estado actual steer-by-wire - AS5600 + motor UIM342

Fecha: 2026-10-08  
Proyecto en Raspberry: `~/Documentos/steer-by-wire`

## Contexto

El sistema ya funciona con dos entradas:

- `gamepad_steer.py`: control Bluetooth/gamepad. Funciona bien y fluido.
- AS5600: funciona, pero se estaba sintiendo con lag, saltos o microparadas.

El motor, driver UIM342, CAN y limites parecen estar bien porque con el control Bluetooth responde correctamente.

## Hardware y calibraciones actuales

Sensor:

- AS5600 por I2C.
- Direccion I2C esperada: `0x36`.
- Comando para revisar:

```bash
i2cdetect -y 1
```

Calibracion guardada:

```bash
.sbw_sensor_zero.json
.sbw_motor_limits.json
```

Valores vistos en la RPi:

```text
center_pulses = 1105715
left_limit_pulses = 1155358
right_limit_pulses = 1052634
zero_offset_deg = 125.68359375000006
```

## Diagnostico realizado

Se probo el AS5600 sin mover motor durante movimiento lento y rapido del volante:

```text
errors = 0
jumps_gt_12deg = 0
bad_magnet_samples = 0
angle aprox: -93 deg a +94 deg
```

Conclusion: el AS5600 no parece perder I2C ni saltar cuando se mueve. El problema principal no era comunicacion I2C.

Con el programa anterior `as5600_steer.py`, el target cambiaba mucho por pequenas variaciones del sensor. Eso hacia que el driver recibiera muchos objetivos pequenos y pareciera trabarse o reiniciar rampas. En algunos logs se vio:

```text
wheel cerca de centro
target cerca de centro
motor muy lejos
err > 40000 pulsos
speed muy baja o movimiento incompleto
```

## Programa nuevo creado

Se creo un programa nuevo, separado del anterior:

```bash
tools/as5600_steer_hold.py
```

Tambien se agrego al launcher:

```bash
bash run_steer.sh as5600hold ...
```

No reemplaza:

```bash
tools/as5600_steer.py
tools/gamepad_steer.py
tools/steer_by_wire_follow_runtime.py
```

## Que hace el programa nuevo

`as5600_steer_hold.py` intenta comportarse mas parecido al control Bluetooth:

- Lee el AS5600 rapido.
- Calcula el target entre centro y limites.
- No manda microcomandos todo el tiempo.
- Mantiene el target si el motor esta lejos.
- Cambia target si el nuevo objetivo ayuda a volver o si el motor ya esta cerca.
- Reenvia el target si el motor queda parado lejos.
- Agrega `--max-target-step` para no mandar saltos grandes de target de una sola vez.

El parametro nuevo importante:

```bash
--max-target-step
```

Controla cuanto puede cambiar el target por comando.

- Menor = mas suave, pero mas lento.
- Mayor = mas rapido, pero puede ir por saltos.

## Comando recomendado actual

Arrancar:

```bash
cd ~/Documentos/steer-by-wire
bash run_steer.sh as5600hold start --speed-pps 60000 --angle-alpha 0.40 --deadband-deg 1.0 --command-deadband 120 --max-target-step 4000 --retarget-error 2500 --improvement-pulses 1200 --accel-ms 100 --decel-ms 100
```

Ver log:

```bash
bash run_steer.sh as5600hold tail
```

Parar:

```bash
bash run_steer.sh as5600hold stop
```

## Ajustes sugeridos

Si va por saltos:

```bash
--max-target-step 2500
--accel-ms 120 --decel-ms 120
```

Si va muy lento:

```bash
--max-target-step 6000
--speed-pps 70000
```

Si queda nervioso cerca del centro:

```bash
--deadband-deg 1.5
--command-deadband 180
```

Si queda lento para reaccionar:

```bash
--angle-alpha 0.50
```

Si va al lado contrario:

```bash
agregar --reverse
```

## Comandos utiles

Recalibrar cero del sensor:

```bash
python3 tools/steer_by_wire_follow_runtime.py calibrate-zero --no-oled
```

Ver sensor:

```bash
python3 tools/steer_by_wire_follow_runtime.py monitor --no-oled --terminal-hz 5 --duration 10
```

Ver posicion motor:

```bash
sudo .venv/bin/python tools/steer_by_wire_follow_runtime.py print-position
```

Reiniciar CAN:

```bash
sudo ip link set can0 down 2>/dev/null
sudo ip link set can0 type can bitrate 500000 restart-ms 100
sudo ip link set can0 up
```

## Pendiente principal

El sistema ya mejoro con `as5600hold`, pero todavia falta afinar suavidad vs rapidez. El mejor camino parece seguir ajustando:

```text
max-target-step
angle-alpha
command-deadband
accel/decel
speed-pps
```

La causa mas probable ya no es el sensor ni el motor, sino la forma en que se actualizan los targets del motor desde el AS5600.
