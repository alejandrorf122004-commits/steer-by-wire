# Seguimiento directo AS5600-CAN-UIM342

## Objetivo

Este runtime conecta la lectura del volante de banco con el controlador UIM342
sin utilizar el gateway UIM2513 ni el adaptador USB-RS232. La Raspberry Pi usa
SocketCAN y un HAT basado en MCP2515.

## Configuracion validada

| Elemento | Configuracion |
| --- | --- |
| Computador | Raspberry Pi Zero 2 W |
| Sensor de entrada | AS5600 por I2C, direccion `0x36` |
| Pantalla | OLED SSD1306 por I2C, direccion `0x3C` |
| Interfaz CAN | WVS-14882, MCP2515, oscilador de 12 MHz |
| Bus CAN | `can0`, `500 kbit/s` |
| Controlador | UIM342, nodo `13` |
| Motor | UIM4247CM con reduccion 50:1 |
| Resolucion usada | 160000 pulsos por vuelta de salida |

## Flujo del runtime

1. Configura `can0` y verifica que el motor este detenido.
2. Lee el cero inicial del AS5600 y la posicion absoluta del UIM342.
3. Convierte el desplazamiento angular en pulsos absolutos.
4. Calcula una velocidad usando velocidad del volante y error de seguimiento.
5. Envia posicion, velocidad e inicio de movimiento por CAN.
6. Consulta periodicamente el estado y la posicion interna del motor.
7. Actualiza la OLED en un hilo separado para no bloquear el control.
8. Envia parada y restaura los parametros temporales al finalizar.

## Protecciones implementadas

- Confirmacion explicita `BANCO_LIBRE` antes de seguir el sensor.
- Comprobacion de estado inicial detenido.
- Limite de velocidad del UIM342.
- Deteccion de `stall`, bloqueo y error reportados por el motor.
- Limite temporal de error de seguimiento.
- Rechazo de saltos aislados del AS5600 sin cambiar el objetivo del motor.
- Parada si las lecturas incoherentes del sensor son consecutivas.
- Parada ante `SIGTERM`, `Ctrl+C` o excepcion CAN.

## Parametros de la prueba del 5 de agosto

| Parametro | Valor |
| --- | ---: |
| Frecuencia del sensor | 100 Hz |
| Frecuencia maxima de comandos | 25 Hz |
| Frecuencia de estado del motor | 10 Hz |
| Velocidad maxima | 160000 pulsos/s |
| Aceleracion y desaceleracion temporales | 100 ms |
| Umbral de envio | 40 pulsos |
| Salto maximo por lectura | 60 grados |
| Lecturas anomalas consecutivas permitidas | 5 |
| Error de seguimiento de banco | 80000 pulsos durante 2 s |

## Resultados observados

- El motor sigue de forma fluida los movimientos medios del volante.
- La velocidad aumenta cuando el volante se gira rapidamente.
- Los cambios bruscos pueden separar o inclinar el iman en el soporte actual.
- Una perdida de lectura sostenida produce parada controlada.
- En movimientos minimos la OLED puede cambiar antes de que el motor se mueva.

El ultimo punto coincide con la cuantizacion actual. El AS5600 tiene 4096
posiciones por vuelta y la salida usa 160000 pulsos por vuelta:

```text
160000 / 4096 = 39.06 pulsos por cuenta del AS5600
```

El umbral actual es 40 pulsos. Reducirlo inmediatamente haria al motor mas
sensible al ruido del soporte debil. Primero se debe estabilizar el iman y
despues comparar un umbral menor, histeresis o acumulacion de error.

## Criterio para la siguiente fase

No se debe instalar este montaje en el vehiculo. La siguiente fase empieza
cuando el AS5600 mantiene deteccion magnetica valida durante una vuelta completa
sin depender de presion manual. En ese punto se habilitara telemetria CSV y se
medira la latencia real antes de ajustar el control.
