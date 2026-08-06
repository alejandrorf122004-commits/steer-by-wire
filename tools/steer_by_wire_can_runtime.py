#!/usr/bin/env python3
"""Direct SocketCAN runtime for the UIM342 bench actuator.

This file is independent from the legacy UIM2513/RS232 runtime. Its default
operations are read-only. Motion requires explicit bench confirmation and is
limited to a small relative displacement.
"""

from __future__ import annotations

import argparse
import os
import socket
import struct
import subprocess
import time
from dataclasses import dataclass
from typing import Iterable

CAN_EFF_FLAG = 0x80000000
CAN_EFF_MASK = 0x1FFFFFFF
CAN_ERR_FLAG = 0x20000000
CAN_FRAME_FMT = "=IB3x8s"
CAN_FRAME_SIZE = struct.calcsize(CAN_FRAME_FMT)

DEFAULT_INTERFACE = "can0"
DEFAULT_BITRATE = 500_000
DEFAULT_NODE_ID = 13
MAX_BENCH_PULSES = 160000
MAX_BENCH_SPEED_PPS = 6400
BENCH_CONFIRMATION = "BANCO_LIBRE"


class CanError(RuntimeError):
    pass


class UimTimeout(CanError):
    pass


@dataclass(frozen=True)
class UimReply:
    frame_id: int
    producer_id: int
    control_word: int
    data: bytes


@dataclass(frozen=True)
class MotionStatus:
    mode: int
    driver_on: bool
    stopped: bool
    in_position: bool
    stall: bool
    locked: bool
    error: bool
    speed_pps: int
    relative_position: int
    absolute_position: int


def run_checked(command: list[str]) -> None:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CanError(f"Fallo el comando {' '.join(command)}: {detail}")


def configure_interface(interface: str, bitrate: int) -> None:
    if os.geteuid() != 0:
        raise CanError("Ejecuta el programa con sudo para configurar can0.")
    subprocess.run(["ip", "link", "set", interface, "down"], check=False)
    run_checked(["ip", "link", "set", interface, "type", "can", "bitrate", str(bitrate), "restart-ms", "0"])
    run_checked(["ip", "link", "set", interface, "up"])


def stop_interface(interface: str) -> None:
    if os.geteuid() == 0:
        subprocess.run(["ip", "link", "set", interface, "down"], check=False)


def build_instruction_id(consumer_id: int, control_word: int) -> int:
    if not 0 <= consumer_id <= 127:
        raise ValueError("El Node ID debe estar entre 0 y 127.")
    sid = ((consumer_id << 1) & 0x003F) | 0x0100
    eid = (((consumer_id << 1) & 0x00C0) << 8) | (control_word & 0xFF)
    return (sid << 18) | eid


def parse_reply_id(frame_id: int) -> tuple[int, int]:
    sid = (frame_id >> 18) & 0x07FF
    eid = frame_id & 0x03FFFF
    producer_id = ((eid >> 11) & 0x0060) | ((sid >> 6) & 0x001F)
    control_word = eid & 0x00FF
    return producer_id, control_word


def pack_can_frame(frame_id: int, data: bytes) -> bytes:
    if len(data) > 8:
        raise ValueError("CAN clasico admite maximo 8 bytes.")
    return struct.pack(CAN_FRAME_FMT, frame_id | CAN_EFF_FLAG, len(data), data.ljust(8, b"\x00"))


def unpack_can_frame(raw: bytes) -> tuple[int, bytes, bool]:
    if len(raw) != CAN_FRAME_SIZE:
        raise CanError(f"Frame CAN incompleto: {len(raw)} bytes.")
    can_id, dlc, payload = struct.unpack(CAN_FRAME_FMT, raw)
    return can_id & CAN_EFF_MASK, payload[:dlc], bool(can_id & CAN_ERR_FLAG)


def signed_le(data: bytes) -> int:
    return int.from_bytes(data, byteorder="little", signed=True)


def unsigned_le(data: bytes) -> int:
    return int.from_bytes(data, byteorder="little", signed=False)


class Uim342Can:
    def __init__(self, interface: str, node_id: int, timeout_s: float = 0.35) -> None:
        self.interface = interface
        self.node_id = node_id
        self.timeout_s = timeout_s
        self.sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self.sock.bind((interface,))

    def close(self) -> None:
        self.sock.close()

    def __enter__(self) -> "Uim342Can":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def request(
        self,
        control_word: int,
        data: bytes = b"",
        expected_control_words: Iterable[int] | None = None,
    ) -> UimReply:
        expected = set(expected_control_words or [control_word & 0x7F])
        frame_id = build_instruction_id(self.node_id, control_word)
        self.sock.send(pack_can_frame(frame_id, data))
        deadline = time.monotonic() + self.timeout_s

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UimTimeout(
                    f"Sin ACK del nodo {self.node_id} para CW 0x{control_word:02X}."
                )
            self.sock.settimeout(remaining)
            try:
                raw = self.sock.recv(CAN_FRAME_SIZE)
            except socket.timeout as exc:
                raise UimTimeout(
                    f"Sin ACK del nodo {self.node_id} para CW 0x{control_word:02X}."
                ) from exc

            received_id, received_data, is_error = unpack_can_frame(raw)
            if is_error:
                raise CanError(f"SocketCAN recibio un frame de error: 0x{received_id:08X}")
            producer_id, reply_cw = parse_reply_id(received_id)
            if producer_id == self.node_id and reply_cw in expected:
                return UimReply(received_id, producer_id, reply_cw, received_data)

    def get_indexed(self, request_cw: int, reply_cw: int, index: int) -> bytes:
        reply = self.request(request_cw, bytes([index]), [reply_cw])
        if not reply.data or reply.data[0] != index:
            raise CanError(f"ACK inesperado para indice {index}: {reply.data.hex(' ')}")
        return reply.data[1:]

    def get_simple(self, request_cw: int, reply_cw: int) -> bytes:
        return self.request(request_cw, b"", [reply_cw]).data

    def get_motor_enabled(self) -> bool:
        data = self.get_simple(0x95, 0x15)
        if len(data) != 1:
            raise CanError(f"Respuesta MO invalida: {data.hex(' ')}")
        return data[0] == 1

    def get_motion_status(self) -> MotionStatus:
        ms0 = self.get_indexed(0x91, 0x11, 0)
        ms1 = self.get_indexed(0x91, 0x11, 1)
        if len(ms0) != 7 or len(ms1) != 7:
            raise CanError("Respuesta MS incompleta.")

        flags_1 = ms0[0]
        flags_2 = ms0[1]
        return MotionStatus(
            mode=flags_1 & 0x03,
            driver_on=bool(flags_1 & 0x04),
            stopped=bool(flags_2 & 0x01),
            in_position=bool(flags_2 & 0x02),
            stall=bool(flags_2 & 0x08),
            locked=bool(flags_2 & 0x20),
            error=bool(flags_2 & 0x80),
            speed_pps=signed_le(ms1[0:3]),
            relative_position=signed_le(ms0[3:7]),
            absolute_position=signed_le(ms1[3:7]),
        )

    def stop_motion(self) -> None:
        self.request(0x97, b"", [0x17])

    def set_motor_enabled(self, enabled: bool) -> None:
        self.request(0x95, bytes([1 if enabled else 0]), [0x15])

    def set_relative_position(self, pulses: int) -> None:
        reply = self.request(0x9F, int(pulses).to_bytes(4, "little", signed=True), [0x2E])
        if len(reply.data) != 5 or reply.data[0] != 3 or signed_le(reply.data[1:5]) != pulses:
            raise CanError(f"ACK PR inesperado: {reply.data.hex(' ')}")

    def set_ptp_speed(self, speed_pps: int) -> None:
        reply = self.request(0x9E, int(speed_pps).to_bytes(4, "little", signed=True), [0x2E])
        if len(reply.data) != 5 or reply.data[0] != 2 or signed_le(reply.data[1:5]) != speed_pps:
            raise CanError(f"ACK SP inesperado: {reply.data.hex(' ')}")

    def begin_motion(self) -> None:
        self.request(0x96, b"", [0x16])


def format_status(status: MotionStatus) -> str:
    return (
        f"driver={'ON' if status.driver_on else 'OFF'} "
        f"stopped={status.stopped} in_position={status.in_position} "
        f"stall={status.stall} locked={status.locked} error={status.error} "
        f"speed={status.speed_pps}pps relative={status.relative_position} "
        f"absolute={status.absolute_position}"
    )


def relative_move_complete(status: MotionStatus, commanded_pulses: int, tolerance: int = 5) -> bool:
    return status.stopped and abs(status.relative_position - commanded_pulses) <= tolerance


def diagnose(bus: Uim342Can) -> None:
    ic = {i: unsigned_le(bus.get_indexed(0x86, 0x06, i)) for i in [0, 1, 4, 6, 7, 8]}
    mt = {i: unsigned_le(bus.get_indexed(0x90, 0x10, i)) for i in [0, 1, 2, 3, 5]}
    qe = {i: unsigned_le(bus.get_indexed(0xBD, 0x3D, i)) for i in [0, 1, 3, 4]}
    motion = {
        "AC": unsigned_le(bus.get_simple(0x99, 0x19)),
        "DC": unsigned_le(bus.get_simple(0x9A, 0x1A)),
        "SS": unsigned_le(bus.get_simple(0x9B, 0x1B)),
        "SD": unsigned_le(bus.get_simple(0x9C, 0x1C)),
    }
    limits = {i: signed_le(bus.get_indexed(0xAC, 0x2C, i)) for i in [0, 1, 2, 3, 4]}
    limits[6] = unsigned_le(bus.get_indexed(0xAC, 0x2C, 6))
    limits[7] = unsigned_le(bus.get_indexed(0xAC, 0x2C, 7))
    status = bus.get_motion_status()

    print(f"Nodo: {bus.node_id}")
    print(f"IC: auto_enable={ic[0]} positive_direction={ic[1]} ac_dc_time_units={ic[4]}")
    print(f"IC: closed_loop={ic[6]} software_limits={ic[7]} brake_logic={ic[8]}")
    print(f"MT: microsteps={mt[0]} current={mt[1] / 10:.1f}A idle={mt[2]}% enable_delay={mt[3]}ms brake={mt[5]}")
    print(f"QE: LPR={qe[0]} stall_tolerance={qe[1]} battery={qe[3] / 1000:.3f}V CPR={qe[4]}")
    print(f"Motion: AC={motion['AC']} DC={motion['DC']} SS={motion['SS']} SD={motion['SD']}")
    print(
        "Limits: max_speed={} lower_work={} upper_work={} lower_bump={} upper_bump={} max_error={} max_accel={}".format(
            limits[0], limits[1], limits[2], limits[3], limits[4], limits[6], limits[7]
        )
    )
    print("Status:", format_status(status))


def show_status(bus: Uim342Can) -> None:
    print(format_status(bus.get_motion_status()))


def move_relative(bus: Uim342Can, pulses: int, speed_pps: int, timeout_s: float, allow_enable: bool) -> None:
    if abs(pulses) > MAX_BENCH_PULSES:
        raise CanError(f"Limite de banco: |pulses| debe ser <= {MAX_BENCH_PULSES}.")
    if not 1 <= speed_pps <= MAX_BENCH_SPEED_PPS:
        raise CanError(f"Limite de banco: speed debe estar entre 1 y {MAX_BENCH_SPEED_PPS} pps.")

    initial = bus.get_motion_status()
    print("Antes:", format_status(initial))
    if initial.stall or initial.locked or initial.error:
        raise CanError("El motor reporta stall, bloqueo o error. No se permite movimiento.")
    if not initial.stopped or initial.speed_pps != 0:
        bus.stop_motion()
        time.sleep(0.1)
        initial = bus.get_motion_status()
        if not initial.stopped or initial.speed_pps != 0:
            raise CanError("El motor no confirmo parada antes de la prueba.")

    enabled_here = False
    if not bus.get_motor_enabled():
        if not allow_enable:
            raise CanError("El driver esta OFF. Usa --allow-driver-enable solo con el banco despejado.")
        bus.set_motor_enabled(True)
        enabled_here = True

    started = False
    try:
        bus.set_relative_position(pulses)
        bus.set_ptp_speed(speed_pps)
        bus.begin_motion()
        started = True
        deadline = time.monotonic() + timeout_s
        last = initial
        while time.monotonic() < deadline:
            time.sleep(0.03)
            last = bus.get_motion_status()
            if last.stall or last.locked or last.error:
                raise CanError("El motor reporto un fallo durante el movimiento.")
            if relative_move_complete(last, pulses):
                print("Despues:", format_status(last))
                return
        raise CanError(f"Timeout de movimiento. Ultimo estado: {format_status(last)}")
    finally:
        if started:
            try:
                bus.stop_motion()
            except CanError:
                print("ADVERTENCIA: no se pudo confirmar ST. Corta los 24 V.")
        if enabled_here:
            try:
                bus.set_motor_enabled(False)
            except CanError:
                print("ADVERTENCIA: no se pudo apagar el driver. Corta los 24 V.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Runtime CAN directo y seguro para UIM342 en banco.")
    parser.add_argument("--interface", default=DEFAULT_INTERFACE)
    parser.add_argument("--bitrate", type=int, default=DEFAULT_BITRATE)
    parser.add_argument("--node-id", type=int, default=DEFAULT_NODE_ID)
    parser.add_argument("--timeout", type=float, default=0.35, help="Timeout de cada ACK CAN.")
    parser.add_argument("--keep-can-up", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("diagnose", help="Lee configuracion y estado sin mover.")
    subparsers.add_parser("status", help="Lee el estado actual sin mover.")
    subparsers.add_parser("stop", help="Envia ST y verifica parada.")

    move = subparsers.add_parser("move-relative", help="Movimiento relativo limitado para banco.")
    move.add_argument("--pulses", type=int, default=100)
    move.add_argument("--speed", type=int, default=400)
    move.add_argument("--motion-timeout", type=float, default=3.0)
    move.add_argument("--allow-driver-enable", action="store_true")
    move.add_argument("--confirm", required=True, help=f"Debe ser exactamente {BENCH_CONFIRMATION}.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "move-relative" and args.confirm != BENCH_CONFIRMATION:
        raise SystemExit(f"Movimiento bloqueado: --confirm debe ser {BENCH_CONFIRMATION}.")

    configure_interface(args.interface, args.bitrate)
    try:
        with Uim342Can(args.interface, args.node_id, args.timeout) as bus:
            if args.command == "diagnose":
                diagnose(bus)
            elif args.command == "status":
                show_status(bus)
            elif args.command == "stop":
                bus.stop_motion()
                time.sleep(0.1)
                show_status(bus)
            elif args.command == "move-relative":
                print("Banco despejado requerido. Ten acceso inmediato al corte de 24 V.")
                move_relative(bus, args.pulses, args.speed, args.motion_timeout, args.allow_driver_enable)
    finally:
        if not args.keep_can_up:
            stop_interface(args.interface)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit("Interrumpido por el usuario. Si el eje se mueve, corta los 24 V.")
    except CanError as exc:
        raise SystemExit(f"ERROR: {exc}")
