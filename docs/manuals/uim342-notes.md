# Notas del manual UIM342

Estas notas resumen lo que si importa para el proyecto de steer-by-wire.

## Lo mas importante

- La familia `UIM342 / UIM342S / UIM342XS` es un controlador de motor con
  interfaz `CAN`.
- El manual confirma `CAN 2.0B` y bit rate configurable desde `125 Kbps` hasta
  `1 Mbps`.
- El controlador acepta tres tipos de direccionamiento: `Node ID`, `Group ID`
  y `Global ID`.
- El `Node ID` de fabrica es `5`.
- El controlador master usa `Producer ID = 4` cuando se habla por CAN directo.

## Comandos que mas nos sirven

- `MO` enciende o apaga el driver del motor.
- `BG` arranca el movimiento.
- `ST` detiene el movimiento.
- `JV` define velocidad en modo jog.
- `PR` define posicion relativa.
- `PA` define posicion absoluta.
- `SP` define la velocidad objetivo para posicion.
- `AC` y `DC` definen aceleracion y desaceleracion.

## Lo que cambia frente al gateway UIM2513

El manual distingue dos caminos:

1. `CAN directo` al UIM342
2. `RS232 / Ethernet gateway` con mensajes UI y CRC16

Si usamos el HAT `WVS-14882`, lo mas limpio es ir por `CAN directo` y dejar el
gateway solo como plan de respaldo.

## Detalles utiles para el software

- El intercambio CAN usa tramas extendidas de 29 bits.
- Para mandar instrucciones se calcula `SID` y `EID` a partir del `Consumer ID`
  y del `CW`.
- Para mover el motor en modo posicion se manda `PR` o `PA` y luego `BG`.
- El `DV[2]` devuelve velocidad deseada en `pulse/sec`.
- El `DV[3]` devuelve posicion relativa deseada en `pulse`.
- El `DV[4]` devuelve posicion absoluta deseada en `pulse`.

## Riesgos que conviene anotar

- El bitrate del bus debe coincidir con el banco real.
- La direccion positiva puede requerir inversion en `IC[1]`.
- Conviene probar primero con `MO`, `ST` y un `PR` pequeño antes de cualquier
  movimiento grande.
- Si el motor reporta alarmas de encoder o limite, hay que detener y revisar
  antes de seguir.
