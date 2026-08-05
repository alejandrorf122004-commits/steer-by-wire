# Steer-by-Wire Portfolio

Repositorio de portfolio y banco de pruebas para una direccion steer-by-wire
basada en Raspberry Pi, sensor AS5600, OLED de banco y actuador UIM.

## Resumen

El proyecto documenta:

- la lectura del volante con `AS5600`
- la visualizacion en `OLED SSD1306`
- el lazo de software en `Raspberry Pi Zero 2`
- la integracion con el actuador por `RS232`/`CAN`
- la evolucion del hardware de banco y las decisiones de arquitectura

## Estado actual

Hay dos niveles de integracion:

- **Banco de sensing**: `AS5600` + `OLED` ya funcionando
- **Banco de actuacion**: ruta serial/CAN en evaluacion con el hardware del laboratorio

## Pregunta de hardware abierta

Se esta evaluando reemplazar la cadena `USB-RS232 + RS232-CAN gateway` por una
placa HAT para Raspberry Pi con interfaz `CAN` real y, si aplica, `RS485`.
La decision final depende de que el HAT exponga `CAN` utilizable en Linux
(`SocketCAN`) y no solo un puerto `RS485`.

## Documentacion principal

- [docs/README.md](docs/README.md) indice general de la documentacion
- [docs/hardware-evaluation.md](docs/hardware-evaluation.md) criterio realista para decidir el cambio de hardware
- [docs/arquitectura-uim2513-rs232-can.md](docs/arquitectura-uim2513-rs232-can.md) arquitectura del enlace actual
- [docs/manual-as5600-rpi-zero-2w.md](docs/manual-as5600-rpi-zero-2w.md) manual de banco para sensor y OLED
- [docs/repo-assets.md](docs/repo-assets.md) lista de fotos, videos y capturas utiles para portfolio

## Software util

- `tools/oled_compass.py` monitor de flecha para la OLED
- `tools/steer_by_wire_runtime.py` runtime de banco para sensor, OLED y capa de actuacion

## Estructura

- `docs/` decisiones, arquitectura, validacion y notas tecnicas
- `hardware/` CAD, piezas y ensambles mecanicos
- `output/` artefactos exportados, como PDF o STL
- `thesis-latex/` version academica en LaTeX
- `tools/` scripts de banco y utilidades de control

## Lo que faltaria para que el repo quede fuerte

1. Confirmar el HAT exacto y su interfaz real de `CAN`.
2. Guardar fotos limpias del banco y del cableado final.
3. Grabar un video corto del sensor moviendo la flecha en la OLED.
4. Documentar el flujo motor/hardware con comandos de prueba reproducibles.
5. Publicar un README final con una demo funcional y una seccion de riesgos.
