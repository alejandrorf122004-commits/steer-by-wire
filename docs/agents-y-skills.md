# Agentes y skills recomendados

## Agentes

### Coordinador

- Integra todos los resultados
- Mantiene prioridades y orden
- Evita que mecánica, control y tesis se contradigan

### Requisitos y arquitectura

- Convierte la idea en requisitos
- Define bloques del sistema
- Identifica supuestos abiertos

### Mecanica

- Revisa acoples, soportes y torque
- Verifica la integracion del motor con la caja de direccion

### Control y software

- Diseña lectura del encoder
- Define el lazo de control y los estados del sistema
- Revisa tiempos, limites y watchdogs

### Integracion CAN/RS232

- Define el enlace entre Raspberry Pi y UIM2513
- Traduce comandos de alto nivel a mensajes de movimiento
- Verifica respuesta, tasa de actualizacion y parada segura

### Seguridad y validacion

- Analiza riesgos y fallos
- Define pruebas de banco y de vehiculo

### Documentacion y tesis

- Mantiene el documento en LaTeX
- Convierte decisiones tecnicas en texto de tesis

## Skills

### `steer-by-wire-system-design`

- Arquitectura
- Requisitos
- Interfaces

### `steer-by-wire-control`

- Sensorizacion
- Lazo de control
- Ejecucion en tiempo de ciclo

### `steer-by-wire-safety-validation`

- Riesgos
- Fallos
- Matriz de pruebas

### `steer-by-wire-thesis-latex`

- Estructura de tesis
- Capitulos
- Referencias y figuras

### `export-cad-to-stl`

- Convierte piezas `.SLDPRT` a STL mediante SolidWorks
- Exporta en milimetros, binario y resolucion fina
- Verifica la estructura y los triangulos del STL
- Conserva intactos los archivos CAD editables

## Regla practica

Si una tarea toca mas de una de estas areas, primero se escribe la decision en `docs/` y despues se traduce a LaTeX.
