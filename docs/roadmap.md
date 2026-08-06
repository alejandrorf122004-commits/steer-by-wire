# Roadmap

## Completado en banco

- [x] Lectura del AS5600 por I2C.
- [x] Visualizacion de angulo y flecha en OLED.
- [x] Inicializacion del HAT MCP2515 como `can0`.
- [x] Identificacion del bitrate CAN de `500 kbit/s`.
- [x] Comunicacion con UIM342 mediante el nodo `13`.
- [x] Movimiento relativo limitado y verificado.
- [x] Seguimiento continuo del sensor con el motor.
- [x] Parada ante fallos CAN, motor inseguro y lecturas incoherentes.
- [x] Evidencia en video de la cadena completa.

## Siguiente iteracion

- [ ] Redisenar el soporte para mantener centrado y axial el iman.
- [ ] Verificar el estado magnetico durante una vuelta completa.
- [ ] Registrar sensor, objetivo, posicion real, velocidad y tiempos en CSV.
- [ ] Agregar marcas visuales de alto contraste para analizar video cuadro a cuadro.
- [ ] Medir latencia extremo a extremo y error de seguimiento.
- [ ] Ajustar la respuesta a baja velocidad despues de estabilizar el sensor.
- [ ] Incorporar un sensor independiente en la salida mecanica.

## Seguridad y arquitectura

- [ ] Instalar paro de emergencia fisico que corte la potencia del actuador.
- [ ] Definir topes mecanicos y limites de software calibrados.
- [ ] Implementar watchdog independiente de la Raspberry Pi.
- [ ] Comparar Raspberry Pi con un microcontrolador para el lazo determinista.
- [ ] Crear una matriz de fallos y pruebas de inyeccion de fallos.

## Integracion futura

- [ ] Disenar la PCB cuando los conectores e interfaces queden congelados.
- [ ] Integrar el actuador con la caja de direccion en banco.
- [ ] Validar bajo carga antes de cualquier instalacion en el vehiculo.
- [ ] Actualizar los capitulos de metodologia, control y validacion en LaTeX.
