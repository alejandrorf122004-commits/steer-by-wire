# Probe del HAT WVS-14882

Este archivo resume el primer paso para migrar el banco desde el camino
`UIM2513 + RS232` hacia `CAN directo` en Raspberry Pi.

## Objetivo

Antes de tocar el runtime que ya funciona con el gateway de laboratorio, hay
que validar el HAT por separado:

1. que la Raspberry cree `can0`
2. que el bitrate sea el correcto
3. que se puedan ver y enviar tramas CAN desde Linux

## Script nuevo

El script nuevo vive en:

- [tools/hat_can_probe.py](../tools/hat_can_probe.py)

No modifica el runtime actual del motor.

## Uso recomendado

Primero levantar la interfaz y verificar estado:

```bash
sudo python3 tools/hat_can_probe.py --bring-up --interface can0 --bitrate 500000
```

Luego monitorear tramas:

```bash
sudo python3 tools/hat_can_probe.py --monitor --interface can0
```

Y, si hace falta, mandar una trama de prueba:

```bash
sudo python3 tools/hat_can_probe.py --send-id 0x123 --send-data "11 22 33"
```

## Qué significa éxito

- `ip link show can0` muestra la interfaz `UP`
- el monitor imprime tramas sin errores
- una trama de prueba sale por el bus

## Siguiente paso

Cuando el HAT esté validado, entonces sí se crea un runtime nuevo para el motor
usando `SocketCAN`, sin tocar el flujo legado de `UIM2513`.
