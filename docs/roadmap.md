# Roadmap inicial

## Fase 1: Definicion

- Requisitos funcionales
- Requisitos de seguridad
- Restricciones mecanicas y electricas
- Criterios de exito
- Evaluacion del HAT RS485/CAN frente al enlace de laboratorio

## Fase 2: Diseno

- Bloque general del sistema
- Integracion Raspberry Pi -> UIM2513 -> CAN
- Acople del motor a la caja de direccion
- Lectura del AS5600
- Estrategia de control y seguridad
- Abstraccion de hardware para poder cambiar el enlace serie/CAN sin rehacer todo

## Fase 3: Prototipo de banco

- Integracion del encoder
- Integracion del gateway UIM2513
- Integracion del actuador
- Pruebas sin vehiculo
- Registro de comportamiento
- Evidencia fotografica y video para portfolio

## Fase 4: Validacion en vehiculo

- Pruebas de movimiento limitado
- Observacion de fallos
- Ajuste de limites y parametros

## Fase 5: Documento

- Capitulos de metodologia
- Capitulos de diseno
- Resultados y validacion
- Conclusiones
- Version publica del repositorio con README y guias de reproduccion
