# Auditoría de respaldo — 2026-10-11

Se sincronizan los avances locales de Windows: runtime de seguimiento, pruebas,
documentación de transferencia, CAD, exportaciones STL y diseño PCB/Gerber.
Validación local: 47 pruebas de unittest aprobadas. No se ejecutó el hardware.
El archivo de sesión de Proteus (*.workspace) queda excluido por ser estado del editor.

## Pendiente: recuperar la copia de Raspberry Pi

El chat «Revisar chat de steer-by-wire» del 8 de octubre y
`estado-actual-sbw-profesor-claude.md` describen estos archivos, ausentes en Windows:

- `tools/as5600_steer_hold.py`
- `tools/as5600_steer.py`
- `tools/gamepad_steer.py`
- `run_steer.sh`

La conexión SSH a `raspberrypi.local` no pudo resolver el nombre durante esta
auditoría. Hace falta conectar la Raspberry y confirmar su dirección para leer
su estado Git, recuperar los archivos reales y comparar versiones. No reconstruir
estos programas únicamente a partir del chat. Revisar también calibraciones y
logs de esa máquina antes de afirmar que el respaldo del proyecto está completo.

## Evidencias futuras

Guardar cada sesión en `docs/evidence/AAAA-MM-DD/`, con un README que indique
objetivo, montaje, versión de código, parámetros, resultado y enlaces a fotos o
videos. Para videos grandes, usar almacenamiento externo y registrar el enlace.
