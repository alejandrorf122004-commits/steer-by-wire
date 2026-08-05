# Organizacion CAD

Esta carpeta contiene el diseno mecanico del sistema steer-by-wire.

## Estructura

- `vendor/`: modelos descargados de fabricantes o repositorios externos. No se
  modifican directamente.
- `parts/`: piezas disenadas para el proyecto, como soportes, ejes y carcazas.
- `assemblies/`: conjuntos que agrupan piezas propias y modelos de referencia.
- `drawings/`: planos acotados para fabricacion y documentacion.
- `exports/`: archivos derivados para impresion, corte o intercambio.

## Conjunto del volante

El conjunto principal se llama `steering-input-module` y puede contener:

- volante pequeno;
- eje;
- soporte del eje o rodamientos;
- portaiman;
- soporte del AS5600;
- tapa o proteccion;
- tornilleria y separadores.

## Convencion de nombres

Usar nombres estables y una revision al final:

```text
SBW-001_sensor-mount_v01
SBW-002_magnet-holder_v01
SBW-003_small-steering-wheel_v01
SBW-A01_steering-input-module_v01
```

El archivo nativo conserva la extension de la herramienta CAD. Los archivos
STEP, STL, DXF y PDF derivados se guardan en `exports/` o `drawings/`.

## Regla importante

Los archivos de `vendor/` son referencias geometricas. Si es necesario
corregirlos, se crea una copia en `parts/` con un nombre nuevo y se documenta
el cambio. Esto conserva el modelo original para comparar dimensiones.
