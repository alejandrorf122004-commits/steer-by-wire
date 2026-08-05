#!/usr/bin/env python3
"""Probe and monitor the WVS-14882 CAN HAT without touching the UIM2513 runtime.

Use this script first to verify that:

- the HAT is detected as ``can0``
- the bitrate matches the bus you want to use
- CAN frames can be transmitted and received from Linux

It does not implement motor control. It is only a probe and bring-up tool.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import struct
import subprocess
import sys
import time
from dataclasses import dataclass

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_SFF_MASK = 0x000007FF
CAN_EFF_MASK = 0x1FFFFFFF
CAN_FRAME_FMT = "=IB3x8s"
CAN_FRAME_SIZE = struct.calcsize(CAN_FRAME_FMT)


@dataclass(frozen=True)
class ParsedFrame:
    can_id: int
    dlc: int
    data: bytes

    @property
    def is_extended(self) -> bool:
        return bool(self.can_id & CAN_EFF_FLAG)

    @property
    def is_rtr(self) -> bool:
        return bool(self.can_id & CAN_RTR_FLAG)

    @property
    def is_error(self) -> bool:
        return bool(self.can_id & CAN_ERR_FLAG)

    @property
    def frame_id(self) -> int:
        if self.is_extended:
            return self.can_id & CAN_EFF_MASK
        return self.can_id & CAN_SFF_MASK

    @property
    def data_hex(self) -> str:
        return " ".join(f"{byte:02X}" for byte in self.data[: self.dlc])


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def show_interface(interface: str) -> None:
    result = run_command(["ip", "link", "show", interface])
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode != 0:
        raise SystemExit(f"Interface {interface!r} no existe o no se puede leer.")


def bring_up(interface: str, bitrate: int) -> None:
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise SystemExit("Ejecuta este script con sudo para poder levantar can0.")

    result = run_command(["ip", "link", "set", interface, "up", "type", "can", "bitrate", str(bitrate)])
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode != 0:
        raise SystemExit(f"No se pudo levantar {interface} con bitrate {bitrate}.")


def parse_data_bytes(raw: str) -> bytes:
    tokens = [token for token in re.split(r"[\s,;:-]+", raw.strip()) if token]
    if not tokens:
        return b""
    values: list[int] = []
    for token in tokens:
        values.append(int(token, 16))
    if len(values) > 8:
        raise ValueError("CAN clasico solo permite hasta 8 bytes de datos.")
    return bytes(values)


def build_frame(can_id: int, data: bytes, *, extended: bool = False, rtr: bool = False, error: bool = False) -> bytes:
    flags = 0
    if extended:
        flags |= CAN_EFF_FLAG
    if rtr:
        flags |= CAN_RTR_FLAG
    if error:
        flags |= CAN_ERR_FLAG

    payload = data[:8].ljust(8, b"\x00")
    return struct.pack(CAN_FRAME_FMT, can_id | flags, len(data[:8]), payload)


def parse_can_id(raw: str) -> int:
    return int(raw, 0)


def open_can_socket(interface: str) -> socket.socket:
    sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    sock.bind((interface,))
    sock.settimeout(1.0)
    return sock


def recv_frame(sock: socket.socket) -> ParsedFrame:
    raw = sock.recv(CAN_FRAME_SIZE)
    if len(raw) != CAN_FRAME_SIZE:
        raise ValueError(f"Frame CAN incompleto: {len(raw)} bytes.")
    can_id, dlc, data = struct.unpack(CAN_FRAME_FMT, raw)
    return ParsedFrame(can_id=can_id, dlc=dlc, data=data)


def format_frame(frame: ParsedFrame) -> str:
    flags = []
    if frame.is_extended:
        flags.append("EFF")
    if frame.is_rtr:
        flags.append("RTR")
    if frame.is_error:
        flags.append("ERR")
    flags_text = ",".join(flags) if flags else "STD"
    return f"id=0x{frame.frame_id:X} dlc={frame.dlc} data=[{frame.data_hex}] flags={flags_text}"


def monitor(sock: socket.socket, duration_s: float | None) -> None:
    start = time.time()
    try:
        while True:
            if duration_s is not None and (time.time() - start) >= duration_s:
                return
            try:
                frame = recv_frame(sock)
            except socket.timeout:
                continue
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] {format_frame(frame)}")
    except KeyboardInterrupt:
        print("\nMonitor detenido por el usuario.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe y monitor de CAN para el HAT WVS-14882.")
    parser.add_argument("--interface", default="can0", help="Interfaz CAN a usar.")
    parser.add_argument("--bitrate", type=int, default=500000, help="Bitrate para levantar la interfaz.")
    parser.add_argument("--bring-up", action="store_true", help="Levanta la interfaz CAN antes de probar.")
    parser.add_argument("--monitor", action="store_true", help="Escucha y muestra tramas CAN recibidas.")
    parser.add_argument("--duration", type=float, default=None, help="Tiempo de monitoreo en segundos.")
    parser.add_argument("--send-id", type=str, default=None, help="ID CAN para enviar un frame de prueba. Ej: 0x123")
    parser.add_argument("--send-data", type=str, default="", help="Datos hex separados por espacio o coma. Ej: '11 22 33'")
    parser.add_argument("--extended", action="store_true", help="Usa identificador CAN extendido.")
    parser.add_argument("--rtr", action="store_true", help="Marca el frame como RTR.")
    parser.add_argument("--error", action="store_true", help="Marca el frame como error CAN.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.bring_up:
        bring_up(args.interface, args.bitrate)

    show_interface(args.interface)

    sock = None
    if args.monitor or args.send_id is not None:
        sock = open_can_socket(args.interface)

    if args.send_id is not None:
        if sock is None:
            raise SystemExit("No se pudo abrir el socket CAN para enviar.")
        can_id = parse_can_id(args.send_id)
        data = parse_data_bytes(args.send_data)
        frame = build_frame(can_id, data, extended=args.extended, rtr=args.rtr, error=args.error)
        sock.send(frame)
        sent_can_id = can_id | (CAN_EFF_FLAG if args.extended else 0)
        sent_frame = ParsedFrame(can_id=sent_can_id, dlc=len(data), data=data.ljust(8, b"\x00"))
        print(f"Frame enviado: {format_frame(sent_frame)}")

    if args.monitor:
        if sock is None:
            raise SystemExit("No se pudo abrir el socket CAN para monitorear.")
        monitor(sock, args.duration)

    if sock is not None:
        sock.close()


if __name__ == "__main__":
    main()
