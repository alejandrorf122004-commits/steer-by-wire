# Evaluacion realista del cambio de hardware

## Pregunta

Vale la pena reemplazar la cadena cara de laboratorio:

`USB -> RS232 -> UIM2513 -> CAN`

por una placa HAT para Raspberry Pi que ofrezca `CAN` y, posiblemente, `RS485`.

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
2. evaluar el HAT como sustituto del enlace de laboratorio
3. documentar la decision final con una tabla comparativa

## Conclusion

El cambio vale la pena **solo si el HAT realmente entrega CAN utilizable** y
te permite hacer el banco mas barato, mas portable y mas facil de repetir.
