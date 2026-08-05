# Evaluacion del HAT WVS-14882

## Conclusión corta

Si el objetivo es reducir costo y simplificar la cadena de actuacion, **sí vale la pena
instalarlo en la Raspberry Pi**. Este HAT expone **CAN real sobre MCP2515 por SPI**, con
transceptor CAN a bordo y soporte de `SocketCAN` en Linux segun el manual del fabricante.

Lo importante es entender que:

- **sí reemplaza** la parte de interfaz CAN entre la Pi y el bus
- **no reemplaza** el protocolo del motor
- **no convierte automáticamente** cualquier comando en movimiento

En otras palabras, el HAT te deja la Raspberry Pi hablando CAN de forma nativa; despues
todavia hay que usar el bitrate correcto y enviar los tramas que el motor o el gateway
esperan.

## Lo que confirma el manual oficial

- MCP2515 por SPI
- transceptor CAN SN65HVD230
- habilitacion por `dtoverlay=mcp2515-can0`
- interfaz `can0` en Linux
- uso de `SocketCAN`

## Recomendacion practica

Instalarlo ahora tiene sentido porque:

1. Reduce la dependencia de `USB-RS232 + UIM2513`.
2. Simplifica el cableado.
3. Deja la arquitectura mas portable para portfolio y tesis.
4. Te permite dejar listo el software de CAN en la Pi antes de tener el motor conectado.

## Pasos para ponerlo a funcionar

### 1. Apagar la Raspberry Pi

Antes de insertar el HAT:

```bash
sudo shutdown now
```

### 2. Montar el HAT

- Alinea el HAT con el conector GPIO de 40 pines.
- Inserta el modulo con la Pi apagada.
- Verifica que quede firme y sin pines corridos.

### 3. Habilitar SPI y el driver MCP2515

Edita el archivo de arranque de tu sistema:

- en sistemas nuevos suele ser `/boot/firmware/config.txt`
- en algunos sistemas sigue siendo `/boot/config.txt`

Agrega estas lineas:

```ini
dtparam=spi=on
dtoverlay=mcp2515-can0,oscillator=8000000,interrupt=25,spimaxfrequency=1000000
```

### 4. Reiniciar

```bash
sudo reboot
```

### 5. Verificar que aparezca `can0`

```bash
dmesg | grep -i '\(can\|spi\)'
ip link show can0
```

### 6. Instalar utilidades de prueba

```bash
sudo apt update
sudo apt install can-utils
```

### 7. Levantar la interfaz CAN

El bitrate debe coincidir con el bus del motor o del banco. Cuando lo confirmemos,
se levanta con un comando como:

```bash
sudo ip link set can0 up type can bitrate <BITRATE_CORRECTO>
```

### 8. Probar con `candump`

```bash
candump can0
```

### 9. Integrar el software

Despues se cambia el runtime del proyecto para que use:

- `SocketCAN` en vez de `/dev/ttyUSB*`
- un modulo Python que emita y reciba tramas CAN
- la misma logica de angulo, limites y seguridad que ya tenemos en la OLED

## Lo que sigue

Cuando el HAT este montado, el siguiente objetivo es:

1. confirmar que `can0` levanta sin errores
2. confirmar el bitrate del bus
3. capturar tramas del sistema
4. enviar una trama de prueba
5. adaptar el runtime del proyecto al nuevo enlace CAN

