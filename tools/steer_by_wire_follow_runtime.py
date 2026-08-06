#!/usr/bin/env python3
"""Low-latency AS5600, OLED and direct-CAN steering follower.

This runtime is independent from the validated one-shot CAN and legacy RS232
programs. ``monitor`` never touches CAN. ``follow`` requires explicit bench
confirmation and always sends ST before closing the CAN interface.
"""

from __future__ import annotations

import argparse
import math
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from steer_by_wire_can_runtime import (  # noqa: E402
    BENCH_CONFIRMATION,
    CanError,
    MotionStatus,
    Uim342Can,
    UimTimeout,
    configure_interface,
    format_status,
    signed_le,
    stop_interface,
    unsigned_le,
)

I2C_BUS = 1
AS5600_ADDR = 0x36
AS5600_COUNTS = 4096
MOTOR_PULSES_PER_REV = 3200
GEAR_RATIO = 50
OUTPUT_PULSES_PER_REV = MOTOR_PULSES_PER_REV * GEAR_RATIO
OUTPUT_PULSES_PER_DEGREE = OUTPUT_PULSES_PER_REV / 360.0
MAX_UIM_SPEED_PPS = 160_000


class TrackingError(RuntimeError):
    pass


def normalize_angle(angle_deg: float) -> float:
    return angle_deg % 360.0


def shortest_angle_delta(current_deg: float, previous_deg: float) -> float:
    return ((current_deg - previous_deg + 180.0) % 360.0) - 180.0


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


class AngleUnwrapper:
    def __init__(self, max_step_deg: float = 30.0, max_rejected_samples: int = 0) -> None:
        if not 0.0 < max_step_deg < 180.0:
            raise ValueError("max_step_deg debe estar entre 0 y 180 grados.")
        if max_rejected_samples < 0:
            raise ValueError("max_rejected_samples no puede ser negativo.")
        self.max_step_deg = max_step_deg
        self.max_rejected_samples = max_rejected_samples
        self._last_wrapped: float | None = None
        self._unwrapped: float | None = None
        self._rejected_samples = 0

    def update(self, wrapped_deg: float) -> float:
        wrapped = normalize_angle(wrapped_deg)
        if self._last_wrapped is None:
            self._last_wrapped = wrapped
            self._unwrapped = wrapped
            return wrapped

        delta = shortest_angle_delta(wrapped, self._last_wrapped)
        if abs(delta) > self.max_step_deg:
            self._rejected_samples += 1
            if self._rejected_samples > self.max_rejected_samples:
                raise TrackingError(
                    f"AS5600 inestable: {self._rejected_samples} saltos consecutivos; "
                    f"ultimo salto={delta:+.2f} grados."
                )
            assert self._unwrapped is not None
            return self._unwrapped
        assert self._unwrapped is not None
        self._rejected_samples = 0
        self._unwrapped += delta
        self._last_wrapped = wrapped
        return self._unwrapped


class VelocityEstimator:
    def __init__(self, alpha: float = 0.4) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha debe estar entre 0 y 1.")
        self.alpha = alpha
        self._last_angle: float | None = None
        self._last_time: float | None = None
        self._velocity = 0.0

    def update(self, angle_deg: float, now: float) -> float:
        if self._last_angle is None or self._last_time is None:
            self._last_angle = angle_deg
            self._last_time = now
            return 0.0

        dt = now - self._last_time
        if dt <= 0.0:
            return self._velocity
        raw_velocity = (angle_deg - self._last_angle) / dt
        self._velocity += self.alpha * (raw_velocity - self._velocity)
        self._last_angle = angle_deg
        self._last_time = now
        return self._velocity


@dataclass(frozen=True)
class TrackingCommand:
    target_pulses: int
    speed_pps: int
    steering_delta_deg: float
    limited: bool


class TrackingPlanner:
    def __init__(
        self,
        sensor_zero_deg: float,
        motor_zero_pulses: int,
        *,
        gain: float = 1.0,
        reverse: bool = False,
        max_angle_deg: float | None = 90.0,
        min_speed_pps: int = 400,
        max_speed_pps: int = 32_000,
        catchup_gain: float = 3.0,
    ) -> None:
        if gain <= 0.0:
            raise ValueError("gain debe ser positivo.")
        if max_angle_deg is not None and max_angle_deg <= 0.0:
            raise ValueError("max_angle_deg debe ser positivo.")
        if not 1 <= min_speed_pps <= max_speed_pps <= MAX_UIM_SPEED_PPS:
            raise ValueError("Limites de velocidad invalidos.")
        self.sensor_zero_deg = sensor_zero_deg
        self.motor_zero_pulses = motor_zero_pulses
        self.gain = gain
        self.direction = -1.0 if reverse else 1.0
        self.max_angle_deg = max_angle_deg
        self.min_speed_pps = min_speed_pps
        self.max_speed_pps = max_speed_pps
        self.catchup_gain = catchup_gain

    def command(self, sensor_unwrapped_deg: float, velocity_deg_s: float, motor_position: int) -> TrackingCommand:
        requested_delta = (sensor_unwrapped_deg - self.sensor_zero_deg) * self.gain * self.direction
        if self.max_angle_deg is None:
            steering_delta = requested_delta
            limited = False
        else:
            steering_delta = clamp(requested_delta, -self.max_angle_deg, self.max_angle_deg)
            limited = not math.isclose(requested_delta, steering_delta, abs_tol=1e-9)
        target = self.motor_zero_pulses + round(steering_delta * OUTPUT_PULSES_PER_DEGREE)
        if not -(2**31) <= target < 2**31:
            raise TrackingError("El objetivo excede el rango de posicion de 32 bits del UIM342.")
        error_pulses = abs(target - motor_position)
        feedforward = abs(velocity_deg_s * self.gain) * OUTPUT_PULSES_PER_DEGREE
        requested_speed = feedforward + self.catchup_gain * error_pulses
        speed = round(clamp(requested_speed, self.min_speed_pps, self.max_speed_pps))
        return TrackingCommand(target, speed, steering_delta, limited)


def should_send_target(last_target: int, new_target: int, deadband_pulses: int) -> bool:
    return abs(new_target - last_target) >= deadband_pulses


def set_absolute_position(bus: Uim342Can, pulses: int) -> None:
    reply = bus.request(0xA0, int(pulses).to_bytes(4, "little", signed=True), [0x2E])
    if len(reply.data) != 5 or reply.data[0] != 4 or signed_le(reply.data[1:5]) != pulses:
        raise CanError(f"ACK PA inesperado: {reply.data.hex(' ')}")


def send_tracking_command(bus: Uim342Can, target_pulses: int, speed_pps: int, retries: int = 1) -> None:
    for attempt in range(retries + 1):
        try:
            set_absolute_position(bus, target_pulses)
            bus.set_ptp_speed(speed_pps)
            bus.begin_motion()
            return
        except UimTimeout:
            if attempt >= retries:
                raise
            time.sleep(0.005)


def get_unsigned_parameter(bus: Uim342Can, request_cw: int, reply_cw: int, label: str) -> int:
    data = bus.get_simple(request_cw, reply_cw)
    if len(data) != 4:
        raise CanError(f"Respuesta {label} invalida: {data.hex(' ')}")
    return unsigned_le(data)


def set_unsigned_parameter(
    bus: Uim342Can,
    request_cw: int,
    reply_cw: int,
    value: int,
    label: str,
) -> None:
    encoded = int(value).to_bytes(4, "little", signed=False)
    reply = bus.request(request_cw, encoded, [reply_cw])
    if len(reply.data) != 4 or unsigned_le(reply.data) != value:
        raise CanError(f"ACK {label} inesperado: {reply.data.hex(' ')}")


def motor_status_is_safe(status: MotionStatus) -> bool:
    return not (status.stall or status.locked or status.error)


def raw_to_degrees(raw_angle: int, offset_deg: float) -> float:
    return normalize_angle(raw_angle * 360.0 / AS5600_COUNTS - offset_deg)


def decode_magnet_status(status_register: int) -> tuple[bool, bool, bool]:
    detected = bool(status_register & 0x20)
    too_weak = bool(status_register & 0x10)
    too_strong = bool(status_register & 0x08)
    return detected, too_strong, too_weak


class OledWorker:
    def __init__(self, bus_number: int, update_hz: float) -> None:
        self.bus_number = bus_number
        self.period_s = 1.0 / update_hz
        self._angle = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: BaseException | None = None

    def publish(self, angle_deg: float) -> None:
        with self._lock:
            self._angle = normalize_angle(angle_deg)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="oled-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        try:
            from smbus2 import SMBus
            from oled_compass import OLEDCompass, SSD1306

            with SMBus(self.bus_number) as oled_bus:
                display = SSD1306(oled_bus)
                display.init()
                compass = OLEDCompass(display)
                while not self._stop.is_set():
                    with self._lock:
                        angle = self._angle
                    compass.show_angle(angle)
                    self._stop.wait(self.period_s)
        except BaseException as exc:  # Thread errors must reach the control loop.
            self.error = exc


def load_sensor(bus_number: int) -> tuple[Any, Any]:
    try:
        from smbus2 import SMBus
        from oled_compass import AS5600
    except ImportError as exc:
        raise TrackingError("Faltan smbus2/Pillow. Activa el entorno virtual de la Raspberry Pi.") from exc
    bus = SMBus(bus_number)
    return bus, AS5600(bus, AS5600_ADDR)


def read_magnet_status(sensor: Any) -> tuple[bool, bool, bool]:
    value = sensor.bus.read_byte_data(sensor.addr, 0x0B)
    return decode_magnet_status(value)


def start_oled(args: argparse.Namespace) -> OledWorker | None:
    if args.no_oled:
        return None
    worker = OledWorker(args.i2c_bus, args.oled_hz)
    worker.start()
    return worker


def run_monitor(args: argparse.Namespace) -> int:
    bus, sensor = load_sensor(args.i2c_bus)
    oled = start_oled(args)
    period_s = 1.0 / args.sensor_hz
    start = time.monotonic()
    next_tick = start
    next_report = start
    next_status = start
    samples = 0
    minimum = 360.0
    maximum = 0.0
    magnet = (False, False, False)
    try:
        while time.monotonic() - start < args.duration:
            now = time.monotonic()
            raw = sensor.read_raw_angle()
            angle = raw_to_degrees(raw, args.offset)
            samples += 1
            minimum = min(minimum, angle)
            maximum = max(maximum, angle)
            if oled is not None:
                oled.publish(angle)
                if oled.error is not None:
                    raise TrackingError(f"Fallo la OLED: {oled.error}")
            if now >= next_status:
                magnet = read_magnet_status(sensor)
                next_status = now + 0.2
            if now >= next_report:
                print(
                    f"AS5600 angle={angle:7.2f} raw={raw:4d} "
                    f"magnet={magnet[0]} strong={magnet[1]} weak={magnet[2]}"
                )
                next_report = now + 0.5
            next_tick += period_s
            time.sleep(max(0.0, next_tick - time.monotonic()))
    finally:
        if oled is not None:
            oled.stop()
        bus.close()
    elapsed = max(time.monotonic() - start, 1e-9)
    print(f"Monitor OK: samples={samples} rate={samples / elapsed:.1f}Hz range={minimum:.2f}..{maximum:.2f}deg")
    return 0


def run_follow(args: argparse.Namespace) -> int:
    if args.confirm != BENCH_CONFIRMATION:
        raise TrackingError(f"Movimiento bloqueado: --confirm debe ser {BENCH_CONFIRMATION}.")

    bus_i2c, sensor = load_sensor(args.i2c_bus)
    oled = start_oled(args)
    can_configured = False
    enabled_here = False
    stopped = False
    original_acceleration: int | None = None
    original_deceleration: int | None = None
    stop_requested = threading.Event()
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def request_stop(_signum: int, _frame: Any) -> None:
        stop_requested.set()

    signal.signal(signal.SIGTERM, request_stop)
    try:
        configure_interface(args.interface, args.bitrate)
        can_configured = True
        with Uim342Can(args.interface, args.node_id, args.can_timeout) as motor:
            initial_status = motor.get_motion_status()
            if not motor_status_is_safe(initial_status):
                raise TrackingError(f"Estado inicial inseguro: {format_status(initial_status)}")
            if not initial_status.stopped or initial_status.speed_pps != 0:
                motor.stop_motion()
                time.sleep(0.1)
                initial_status = motor.get_motion_status()
            if not initial_status.stopped or initial_status.speed_pps != 0:
                raise TrackingError("El motor no confirmo parada antes de iniciar seguimiento.")

            if not motor.get_motor_enabled():
                if not args.allow_driver_enable:
                    raise TrackingError("El driver esta OFF; falta --allow-driver-enable.")
                motor.set_motor_enabled(True)
                enabled_here = True

            time_units = unsigned_le(motor.get_indexed(0x86, 0x06, 4))
            if time_units != 1:
                raise TrackingError("IC[4] no esta configurado en unidades de tiempo.")
            original_acceleration = get_unsigned_parameter(motor, 0x99, 0x19, "AC")
            original_deceleration = get_unsigned_parameter(motor, 0x9A, 0x1A, "DC")
            set_unsigned_parameter(motor, 0x99, 0x19, args.acceleration_ms, "AC")
            set_unsigned_parameter(motor, 0x9A, 0x1A, args.deceleration_ms, "DC")

            initial_raw = sensor.read_raw_angle()
            initial_angle = raw_to_degrees(initial_raw, args.offset)
            unwrapper = AngleUnwrapper(args.max_sensor_step, args.max_sensor_outliers)
            initial_unwrapped = unwrapper.update(initial_angle)
            velocity = VelocityEstimator(args.velocity_alpha)
            velocity.update(initial_unwrapped, time.monotonic())
            planner = TrackingPlanner(
                initial_unwrapped,
                initial_status.absolute_position,
                gain=args.gain,
                reverse=args.reverse,
                max_angle_deg=None if args.unlimited_angle else args.max_angle,
                min_speed_pps=args.min_speed,
                max_speed_pps=args.max_speed,
                catchup_gain=args.catchup_gain,
            )

            period_s = 1.0 / args.sensor_hz
            status_period_s = 1.0 / args.status_hz
            command_period_s = 1.0 / args.command_hz
            start = time.monotonic()
            next_tick = start
            next_status = start
            next_command = start
            next_report = start
            next_magnet = start
            last_target = initial_status.absolute_position
            latest_status = initial_status
            tracking_fault_since: float | None = None
            oled_warning_reported = False

            angle_limit = "unlimited" if args.unlimited_angle else f"+/-{args.max_angle:.1f}deg"
            print(
                f"FOLLOW activo: sensor_zero={initial_angle:.2f}deg "
                f"motor_zero={initial_status.absolute_position} pulses "
                f"max_angle={angle_limit} max_speed={args.max_speed}pps "
                f"AC={args.acceleration_ms}ms DC={args.deceleration_ms}ms"
            )

            while not stop_requested.is_set() and (
                args.continuous or time.monotonic() - start < args.duration
            ):
                now = time.monotonic()
                raw = sensor.read_raw_angle()
                angle = raw_to_degrees(raw, args.offset)
                unwrapped = unwrapper.update(angle)
                filtered_angle = normalize_angle(unwrapped)
                wheel_velocity = velocity.update(unwrapped, now)
                if oled is not None:
                    oled.publish(filtered_angle)
                    if oled.error is not None and not oled_warning_reported:
                        print(f"ADVERTENCIA OLED deshabilitada: {oled.error}", file=sys.stderr)
                        oled_warning_reported = True

                if now >= next_magnet:
                    detected, too_strong, too_weak = read_magnet_status(sensor)
                    if not args.allow_invalid_magnet and (not detected or too_strong or too_weak):
                        raise TrackingError(
                            f"Estado de iman invalido: detected={detected} strong={too_strong} weak={too_weak}"
                        )
                    next_magnet = now + 0.2

                command = planner.command(unwrapped, wheel_velocity, latest_status.absolute_position)
                if (
                    now >= next_command
                    and should_send_target(last_target, command.target_pulses, args.command_deadband)
                ):
                    send_tracking_command(motor, command.target_pulses, command.speed_pps)
                    last_target = command.target_pulses
                    next_command = time.monotonic() + command_period_s

                if now >= next_status:
                    latest_status = motor.get_motion_status()
                    if not motor_status_is_safe(latest_status):
                        raise TrackingError(f"Fallo del motor: {format_status(latest_status)}")
                    error_pulses = abs(last_target - latest_status.absolute_position)
                    if error_pulses > args.max_tracking_error:
                        tracking_fault_since = tracking_fault_since or now
                        if now - tracking_fault_since >= args.tracking_error_time:
                            raise TrackingError(f"Error de seguimiento excesivo: {error_pulses} pulsos.")
                    else:
                        tracking_fault_since = None
                    next_status = now + status_period_s

                if now >= next_report:
                    error = last_target - latest_status.absolute_position
                    print(
                        f"wheel={filtered_angle:7.2f}deg delta={command.steering_delta_deg:+7.2f}deg "
                        f"velocity={wheel_velocity:+7.1f}deg/s target={last_target} "
                        f"motor={latest_status.absolute_position} error={error:+d} "
                        f"speed_cmd={command.speed_pps}pps limited={command.limited}"
                    )
                    next_report = now + 0.25

                next_tick += period_s
                remaining = next_tick - time.monotonic()
                if remaining > 0.0:
                    time.sleep(remaining)
                else:
                    next_tick = time.monotonic()

            motor.stop_motion()
            stopped = True
            time.sleep(0.1)
            final_status = motor.get_motion_status()
            print("FOLLOW terminado:", format_status(final_status))
            if not final_status.stopped or final_status.speed_pps != 0 or not motor_status_is_safe(final_status):
                raise TrackingError("No se confirmo una parada limpia al finalizar.")
    finally:
        if can_configured and not stopped:
            try:
                with Uim342Can(args.interface, args.node_id, args.can_timeout) as emergency_motor:
                    emergency_motor.stop_motion()
            except BaseException as exc:
                print(f"ADVERTENCIA: ST no confirmado ({exc}). Corta los 24 V.", file=sys.stderr)
        if can_configured and original_acceleration is not None and original_deceleration is not None:
            try:
                with Uim342Can(args.interface, args.node_id, args.can_timeout) as motor:
                    set_unsigned_parameter(motor, 0x99, 0x19, original_acceleration, "AC")
                    set_unsigned_parameter(motor, 0x9A, 0x1A, original_deceleration, "DC")
            except BaseException as exc:
                print(f"ADVERTENCIA: no se pudieron restaurar AC/DC ({exc}).", file=sys.stderr)
        if can_configured and enabled_here:
            try:
                with Uim342Can(args.interface, args.node_id, args.can_timeout) as motor:
                    motor.set_motor_enabled(False)
            except BaseException as exc:
                print(f"ADVERTENCIA: no se pudo apagar el driver ({exc}).", file=sys.stderr)
        if can_configured:
            stop_interface(args.interface)
        if oled is not None:
            oled.stop()
        bus_i2c.close()
        signal.signal(signal.SIGTERM, previous_sigterm)
    return 0


def add_i2c_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--i2c-bus", type=int, default=I2C_BUS)
    parser.add_argument("--offset", type=float, default=0.0)
    parser.add_argument("--sensor-hz", type=float, default=100.0)
    parser.add_argument("--oled-hz", type=float, default=10.0)
    parser.add_argument("--no-oled", action="store_true")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AS5600/OLED/UIM342 direct-CAN steering follower.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    monitor = subparsers.add_parser("monitor", help="Prueba AS5600 y OLED sin tocar el motor.")
    add_i2c_arguments(monitor)
    monitor.add_argument("--duration", type=float, default=10.0)

    follow = subparsers.add_parser("follow", help="Seguimiento de banco AS5600 -> UIM342.")
    add_i2c_arguments(follow)
    follow.add_argument("--interface", default="can0")
    follow.add_argument("--bitrate", type=int, default=500_000)
    follow.add_argument("--node-id", type=int, default=13)
    follow.add_argument("--can-timeout", type=float, default=0.35)
    follow.add_argument("--duration", type=float, default=15.0)
    follow.add_argument("--continuous", action="store_true", help="Ejecuta hasta SIGTERM o Ctrl+C.")
    follow.add_argument("--gain", type=float, default=1.0)
    follow.add_argument("--reverse", action="store_true")
    follow.add_argument("--max-angle", type=float, default=90.0)
    follow.add_argument("--unlimited-angle", action="store_true")
    follow.add_argument("--min-speed", type=int, default=400)
    follow.add_argument("--max-speed", type=int, default=32_000)
    follow.add_argument("--catchup-gain", type=float, default=3.0)
    follow.add_argument("--acceleration-ms", type=int, default=100)
    follow.add_argument("--deceleration-ms", type=int, default=100)
    follow.add_argument("--command-deadband", type=int, default=80)
    follow.add_argument("--command-hz", type=float, default=25.0)
    follow.add_argument("--status-hz", type=float, default=10.0)
    follow.add_argument("--max-sensor-step", type=float, default=30.0)
    follow.add_argument("--max-sensor-outliers", type=int, default=3)
    follow.add_argument("--velocity-alpha", type=float, default=0.4)
    follow.add_argument("--max-tracking-error", type=int, default=20_000)
    follow.add_argument("--tracking-error-time", type=float, default=0.75)
    follow.add_argument(
        "--allow-invalid-magnet",
        action="store_true",
        help="Solo banco: permite seguimiento aunque el AS5600 reporte campo magnetico invalido.",
    )
    follow.add_argument("--allow-driver-enable", action="store_true")
    follow.add_argument("--confirm", required=True)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not getattr(args, "continuous", False) and args.duration <= 0.0:
        raise TrackingError("duration debe ser positivo.")
    if args.sensor_hz <= 0.0 or args.sensor_hz > 200.0:
        raise TrackingError("sensor-hz debe estar entre 0 y 200.")
    if args.oled_hz <= 0.0 or args.oled_hz > 20.0:
        raise TrackingError("oled-hz debe estar entre 0 y 20.")
    if args.command == "follow":
        if args.status_hz <= 0.0 or args.status_hz > args.sensor_hz:
            raise TrackingError("status-hz debe ser positivo y no superar sensor-hz.")
        if args.command_hz <= 0.0 or args.command_hz > 50.0:
            raise TrackingError("command-hz debe estar entre 0 y 50.")
        if args.command_deadband < 1:
            raise TrackingError("command-deadband debe ser al menos 1 pulso.")
        if args.max_tracking_error < 1 or args.tracking_error_time <= 0.0:
            raise TrackingError("Proteccion de error de seguimiento invalida.")
        if not 0 <= args.max_sensor_outliers <= 20:
            raise TrackingError("max-sensor-outliers debe estar entre 0 y 20.")
        if not 1 <= args.acceleration_ms <= 60_000 or not 1 <= args.deceleration_ms <= 60_000:
            raise TrackingError("AC/DC deben estar entre 1 y 60000 ms.")


def main() -> int:
    args = parse_args()
    validate_args(args)
    if args.command == "monitor":
        return run_monitor(args)
    return run_follow(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit("Interrumpido. Si el eje se mueve, corta los 24 V.")
    except (CanError, OSError, TrackingError) as exc:
        raise SystemExit(f"ERROR: {exc}")
