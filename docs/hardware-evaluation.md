# Evaluacion realista del cambio de hardware

## Pregunta

Vale la pena reemplazar la cadena cara de laboratorio:

`USB -> RS232 -> UIM2513 -> CAN`

por una placa HAT para Raspberry Pi que ofrezca `CAN` y, posiblemente, `RS485`.

## Candidato actual

El candidato que acabamos de revisar es el `WVS-14882` de Sigma, basado en
`MCP2515` y pensado para Raspberry Pi. Su manual oficial indica:

- bus `CAN` sobre `SPI`
- soporte de `SocketCAN` en Linux
- activacion con `dtoverlay=mcp2515-can0`

Eso significa que **sí puede reemplazar la interfaz física** de acceso al bus
CAN, siempre que el bitrate y las tramas coincidan con el sistema del motor.

## Respuesta corta

**Si el HAT expone CAN real y estable en Linux, si vale la pena.**

**Si solo trae RS485, no reemplaza el enlace CAN del motor.**

## Criterio tecnico minimo

Para que el cambio tenga sentido, el HAT debe cumplir al menos esto:

- traer controlador + transceiver de `CAN`, no solo un puerto serie
- funcionar con `SocketCAN` o una capa Linux equivalente
- tener documentacion clara para enviar y recibir tramas
- permitir pruebas repetibles desde Python
- no obligarte a usar drivers opacos o cerrados

## Cuando si vale la pena

- si el objetivo es bajar costo por banco
- si quieres dejar un repositorio reproducible para otros
- si quieres evitar depender de un gateway dificil de conseguir
- si el HAT simplifica la integracion mecanica y electrica

## Cuando no vale la pena

- si solo da `RS485`
- si el soporte en Linux es frágil o poco documentado
- si el ahorro economico es pequeno frente al tiempo de integracion
- si el motor del laboratorio exige un protocolo que el HAT no resuelve

## Lectura honesta para portfolio

No conviene vender esto como una libreria universal para cualquier motor UIM.
Conviene presentarlo como un **banco reproducible de steer-by-wire** con una
arquitectura clara, mediciones, decisiones de hardware y pruebas.

Eso si tiene valor real en GitHub.

## Recomendacion

Mi recomendacion es:

1. mantener el repositorio publico con la parte de sensing, OLED, arquitectura y pruebas
2. instalar el HAT si ya lo tienes a mano, porque es la forma mas limpia de
   probar `SocketCAN` en la Pi
3. documentar la decision final con una tabla comparativa entre:
   - `USB-RS232 + UIM2513`
   - `WVS-14882 + CAN directo`

## Conclusion

El cambio vale la pena **solo si el HAT realmente entrega CAN utilizable** y
te permite hacer el banco mas barato, mas portable y mas facil de repetir.
