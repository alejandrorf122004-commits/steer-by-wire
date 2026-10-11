#!/usr/bin/env python3
"""Low-latency AS5600, OLED and direct-CAN steering follower.

This runtime is independent from the validated one-shot CAN and legacy RS232
programs. ``monitor`` never touches CAN. ``follow`` requires explicit bench
confirmation and always sends ST before closing the CAN interface.
"""

from __future__ import annotations

import argparse
import json
import math
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = TOOLS_DIR.parent
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
MIN_UIM_RAMP_MS = 10
DEFAULT_ZERO_FILE = PROJECT_DIR / ".sbw_sensor_zero.json"
DEFAULT_LIMITS_FILE = PROJECT_DIR / ".sbw_motor_limits.json"


class TrackingError(RuntimeError):
    pass


def normalize_angle(angle_deg: float) -> float:
    normalized = angle_deg % 360.0
    if math.isclose(normalized, 0.0, abs_tol=1e-9) or math.isclose(normalized, 360.0, abs_tol=1e-9):
        return 0.0
    return normalized


def shortest_angle_delta(current_deg: float, previous_deg: float) -> float:
    return ((current_deg - previous_deg + 180.0) % 360.0) - 180.0


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def motor_rpm_to_pps(rpm: float) -> int:
    return round(rpm * MOTOR_PULSES_PER_REV / 60.0)


def motor_pps_to_rpm(pps: int) -> float:
    return pps * 60.0 / MOTOR_PULSES_PER_REV


def output_rpm_from_motor_pps(pps: int) -> float:
    return motor_pps_to_rpm(pps) / GEAR_RATIO


def effective_jog_speed_pps(args: argparse.Namespace) -> int:
    if args.speed_rpm is not None:
        return motor_rpm_to_pps(args.speed_rpm)
    if args.speed_pps is not None:
        return args.speed_pps
    return motor_rpm_to_pps(60.0)


def effective_follow_max_speed_pps(args: argparse.Namespace) -> int:
    if args.max_speed is not None:
        return args.max_speed
    if args.max_speed_rpm is not None:
        return motor_rpm_to_pps(args.max_speed_rpm)
    return motor_rpm_to_pps(950.0)


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


class LowPassAngleFilter:
    def __init__(self, alpha: float = 1.0) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha debe estar entre 0 y 1.")
        self.alpha = alpha
        self._value: float | None = None

    def update(self, value: float) -> float:
        if self._value is None:
            self._value = value
        else:
            self._value += self.alpha * (value - self._value)
        return self._value


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
        deadband_deg: float = 0.0,
    ) -> None:
        if gain <= 0.0:
            raise ValueError("gain debe ser positivo.")
        if max_angle_deg is not None and max_angle_deg <= 0.0:
            raise ValueError("max_angle_deg debe ser positivo.")
        if not 1 <= min_speed_pps <= max_speed_pps <= MAX_UIM_SPEED_PPS:
            raise ValueError("Limites de velocidad invalidos.")
        if deadband_deg < 0.0:
            raise ValueError("deadband_deg no puede ser negativo.")
        self.sensor_zero_deg = sensor_zero_deg
        self.motor_zero_pulses = motor_zero_pulses
        self.gain = gain
        self.direction = -1.0 if reverse else 1.0
        self.max_angle_deg = max_angle_deg
        self.min_speed_pps = min_speed_pps
        self.max_speed_pps = max_speed_pps
        self.catchup_gain = catchup_gain
        self.deadband_deg = deadband_deg

    def command(self, sensor_unwrapped_deg: float, velocity_deg_s: float, motor_position: int) -> TrackingCommand:
        requested_delta = (sensor_unwrapped_deg - self.sensor_zero_deg) * self.gain * self.direction
        if abs(requested_delta) <= self.deadband_deg:
            requested_delta = 0.0
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


class LimitTrackingPlanner:
    def __init__(
        self,
        sensor_zero_deg: float,
        *,
        center_pulses: int,
        left_limit_pulses: int,
        right_limit_pulses: int,
        gain: float = 1.0,
        reverse: bool = False,
        max_angle_deg: float = 90.0,
        min_speed_pps: int = 400,
        max_speed_pps: int = 32_000,
        catchup_gain: float = 3.0,
        deadband_deg: float = 0.0,
    ) -> None:
        if gain <= 0.0:
            raise ValueError("gain debe ser positivo.")
        if max_angle_deg <= 0.0:
            raise ValueError("max_angle_deg debe ser positivo.")
        if not 1 <= min_speed_pps <= max_speed_pps <= MAX_UIM_SPEED_PPS:
            raise ValueError("Limites de velocidad invalidos.")
        if deadband_deg < 0.0:
            raise ValueError("deadband_deg no puede ser negativo.")
        if left_limit_pulses == right_limit_pulses:
            raise ValueError("Los limites izquierdo y derecho no pueden ser iguales.")
        lower = min(left_limit_pulses, right_limit_pulses)
        upper = max(left_limit_pulses, right_limit_pulses)
        if not lower <= center_pulses <= upper:
            raise ValueError("El centro debe estar entre los limites izquierdo y derecho.")
        self.sensor_zero_deg = sensor_zero_deg
        self.center_pulses = center_pulses
        self.left_limit_pulses = left_limit_pulses
        self.right_limit_pulses = right_limit_pulses
        self.gain = gain
        self.direction = -1.0 if reverse else 1.0
        self.max_angle_deg = max_angle_deg
        self.min_speed_pps = min_speed_pps
        self.max_speed_pps = max_speed_pps
        self.catchup_gain = catchup_gain
        self.deadband_deg = deadband_deg

    def command(self, sensor_unwrapped_deg: float, velocity_deg_s: float, motor_position: int) -> TrackingCommand:
        requested_delta = (sensor_unwrapped_deg - self.sensor_zero_deg) * self.gain * self.direction
        if abs(requested_delta) <= self.deadband_deg:
            requested_delta = 0.0
        steering_delta = clamp(requested_delta, -self.max_angle_deg, self.max_angle_deg)
        limited = not math.isclose(requested_delta, steering_delta, abs_tol=1e-9)
        if steering_delta >= 0.0:
            ratio = steering_delta / self.max_angle_deg
            target = self.center_pulses + round((self.left_limit_pulses - self.center_pulses) * ratio)
        else:
            ratio = abs(steering_delta) / self.max_angle_deg
            target = self.center_pulses + round((self.right_limit_pulses - self.center_pulses) * ratio)
        if not -(2**31) <= target < 2**31:
            raise TrackingError("El objetivo excede el rango de posicion de 32 bits del UIM342.")
        error_pulses = abs(target - motor_position)
        span_per_deg = max(
            abs(self.left_limit_pulses - self.center_pulses),
            abs(self.right_limit_pulses - self.center_pulses),
        ) / self.max_angle_deg
        feedforward = abs(velocity_deg_s * self.gain) * span_per_deg
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
    if len(reply.data) != 4:
        raise CanError(f"ACK {label} inesperado: {reply.data.hex(' ')}")
    acknowledged = unsigned_le(reply.data)
    if acknowledged != value:
        if label in {"AC", "DC"} and value < MIN_UIM_RAMP_MS and acknowledged == MIN_UIM_RAMP_MS:
            print(
                f"ADVERTENCIA: {label}={value}ms no fue aceptado; "
                f"el driver uso {acknowledged}ms.",
                file=sys.stderr,
            )
            return
        raise CanError(f"ACK {label} inesperado: {reply.data.hex(' ')}")


def motor_status_is_safe(status: MotionStatus) -> bool:
    return not (status.stall or status.locked or status.error)


def raw_to_degrees(raw_angle: int, offset_deg: float) -> float:
    return normalize_angle(raw_angle * 360.0 / AS5600_COUNTS - offset_deg)


def signed_angle_degrees(angle_deg: float) -> float:
    angle = normalize_angle(angle_deg)
    if angle > 180.0:
        return angle - 360.0
    return angle


def terminal_angle_degrees(angle_deg: float, zero_deadband_deg: float) -> float:
    angle = signed_angle_degrees(angle_deg)
    if abs(angle) <= zero_deadband_deg:
        return 0.0
    return angle


def circular_mean_degrees(angles_deg: list[float]) -> float:
    if not angles_deg:
        raise TrackingError("No hay muestras para calcular el cero.")
    sin_sum = sum(math.sin(math.radians(angle)) for angle in angles_deg)
    cos_sum = sum(math.cos(math.radians(angle)) for angle in angles_deg)
    return normalize_angle(math.degrees(math.atan2(sin_sum, cos_sum)))


def read_saved_zero(path: Path) -> float | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return float(data["zero_offset_deg"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise TrackingError(f"No se pudo leer el cero guardado en {path}: {exc}") from exc


def write_saved_zero(path: Path, *, zero_offset_deg: float, samples: int, bus_number: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "sensor": "AS5600",
        "zero_offset_deg": normalize_angle(zero_offset_deg),
        "samples": samples,
        "i2c_bus": bus_number,
        "created_unix": time.time(),
    }
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def write_motor_limit(path: Path, side: str, absolute_position: int) -> None:
    if side not in {"left", "right"}:
        raise TrackingError("El lado del limite debe ser left o right.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TrackingError(f"No se pudo leer el archivo de limites {path}: {exc}") from exc
    else:
        payload = {"version": 1, "motor": "UIM342"}
    payload[f"{side}_limit_pulses"] = int(absolute_position)
    payload["updated_unix"] = time.time()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def write_motor_center(path: Path, absolute_position: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TrackingError(f"No se pudo leer el archivo de limites {path}: {exc}") from exc
    else:
        payload = {"version": 1, "motor": "UIM342"}
    payload["center_pulses"] = int(absolute_position)
    payload["updated_unix"] = time.time()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def read_motor_limits(path: Path) -> tuple[int, int]:
    if not path.exists():
        raise TrackingError(f"No existe el archivo de limites {path}. Guarda primero left y right.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        left = int(payload["left_limit_pulses"])
        right = int(payload["right_limit_pulses"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TrackingError(f"Limites de motor invalidos en {path}: {exc}") from exc
    lower = min(left, right)
    upper = max(left, right)
    if lower == upper:
        raise TrackingError("Los limites izquierdo y derecho no pueden ser iguales.")
    return lower, upper


def read_named_motor_limits(path: Path) -> dict[str, int]:
    if not path.exists():
        raise TrackingError(f"No existe el archivo de limites {path}. Guarda primero left y right.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        left = int(payload["left_limit_pulses"])
        right = int(payload["right_limit_pulses"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TrackingError(f"Limites de motor invalidos en {path}: {exc}") from exc
    if left == right:
        raise TrackingError("Los limites izquierdo y derecho no pueden ser iguales.")
    return {"left": left, "right": right}


def read_motor_calibration(path: Path) -> dict[str, int]:
    if not path.exists():
        raise TrackingError(f"No existe el archivo de limites {path}. Guarda primero centro, left y right.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        center = int(payload["center_pulses"])
        left = int(payload["left_limit_pulses"])
        right = int(payload["right_limit_pulses"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TrackingError(f"Calibracion de motor invalida en {path}: {exc}") from exc
    if left == right:
        raise TrackingError("Los limites izquierdo y derecho no pueden ser iguales.")
    lower = min(left, right)
    upper = max(left, right)
    if not lower <= center <= upper:
        raise TrackingError(f"Centro {center} no esta entre limites {lower} y {upper}.")
    return {"center": center, "left": left, "right": right}


def clamp_motor_target(target: int, lower_limit: int, upper_limit: int) -> int:
    return round(clamp(target, lower_limit, upper_limit))


def jog_limit_reached(actual: int, target: int, direction: int, tolerance_pulses: int) -> bool:
    if direction > 0:
        return actual >= target - tolerance_pulses
    return actual <= target + tolerance_pulses


def position_within_limits(actual: int, lower_limit: int, upper_limit: int, tolerance_pulses: int) -> bool:
    return lower_limit - tolerance_pulses <= actual <= upper_limit + tolerance_pulses


def direction_toward_target(actual: int, target: int) -> int:
    if target > actual:
        return 1
    if target < actual:
        return -1
    return 0


def effective_offset(args: argparse.Namespace) -> float:
    saved_zero = None if args.ignore_saved_zero else read_saved_zero(Path(args.zero_file))
    return normalize_angle(args.offset + (saved_zero or 0.0))


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


def read_raw_angle_retry(sensor: Any, retries: int, delay_s: float) -> int:
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return int(sensor.read_raw_angle())
        except OSError as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(delay_s)
    raise TrackingError(f"Fallo I2C leyendo AS5600 tras {retries + 1} intentos: {last_error}") from last_error


def read_magnet_status_retry(sensor: Any, retries: int, delay_s: float) -> tuple[bool, bool, bool]:
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return read_magnet_status(sensor)
        except OSError as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(delay_s)
    raise TrackingError(f"Fallo I2C leyendo estado de iman tras {retries + 1} intentos: {last_error}") from last_error


def start_oled(args: argparse.Namespace) -> OledWorker | None:
    if args.no_oled:
        return None
    worker = OledWorker(args.i2c_bus, args.oled_hz)
    worker.start()
    return worker


def run_calibrate_zero(args: argparse.Namespace) -> int:
    bus, sensor = load_sensor(args.i2c_bus)
    period_s = 1.0 / args.sensor_hz
    samples: list[float] = []
    try:
        for _index in range(args.samples):
            raw = read_raw_angle_retry(sensor, args.i2c_retries, args.i2c_retry_delay)
            samples.append(raw_to_degrees(raw, args.offset))
            time.sleep(period_s)
        detected, too_strong, too_weak = read_magnet_status_retry(sensor, args.i2c_retries, args.i2c_retry_delay)
    finally:
        bus.close()

    zero = circular_mean_degrees(samples)
    write_saved_zero(Path(args.zero_file), zero_offset_deg=zero, samples=len(samples), bus_number=args.i2c_bus)
    print(
        f"Cero guardado: offset={zero:.2f}deg file={args.zero_file} "
        f"magnet={detected} strong={too_strong} weak={too_weak}"
    )
    print("Desde ahora esa posicion se mostrara como 0.00deg en monitor y follow.")
    return 0


def run_monitor(args: argparse.Namespace) -> int:
    bus, sensor = load_sensor(args.i2c_bus)
    oled = start_oled(args)
    offset_deg = effective_offset(args)
    saved_zero = read_saved_zero(Path(args.zero_file)) if not args.ignore_saved_zero else None
    period_s = 1.0 / args.sensor_hz
    start = time.monotonic()
    next_tick = start
    next_report = start
    next_status = start
    samples = 0
    minimum = 180.0
    maximum = -180.0
    magnet = (False, False, False)
    oled_warning_reported = False
    try:
        while time.monotonic() - start < args.duration:
            now = time.monotonic()
            raw = read_raw_angle_retry(sensor, args.i2c_retries, args.i2c_retry_delay)
            angle = raw_to_degrees(raw, offset_deg)
            terminal_angle = terminal_angle_degrees(angle, args.zero_deadband)
            samples += 1
            minimum = min(minimum, terminal_angle)
            maximum = max(maximum, terminal_angle)
            if oled is not None:
                oled.publish(angle)
                if oled.error is not None and not oled_warning_reported:
                    print(f"ADVERTENCIA OLED deshabilitada: {oled.error}", file=sys.stderr)
                    oled_warning_reported = True
            if now >= next_status:
                magnet = read_magnet_status_retry(sensor, args.i2c_retries, args.i2c_retry_delay)
                next_status = now + 0.2
            if now >= next_report:
                print(
                    f"AS5600 angle={terminal_angle:+7.2f} raw={raw:4d} "
                    f"magnet={magnet[0]} strong={magnet[1]} weak={magnet[2]} "
                    f"zero={'none' if saved_zero is None else f'{saved_zero:.2f}deg'}"
                )
                next_report = now + 1.0 / args.terminal_hz
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
    offset_deg = effective_offset(args)
    saved_zero = read_saved_zero(Path(args.zero_file)) if not args.ignore_saved_zero else None
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

            initial_raw = read_raw_angle_retry(sensor, args.i2c_retries, args.i2c_retry_delay)
            initial_angle = raw_to_degrees(initial_raw, offset_deg)
            unwrapper = AngleUnwrapper(args.max_sensor_step, args.max_sensor_outliers)
            initial_unwrapped = unwrapper.update(initial_angle)
            angle_filter = LowPassAngleFilter(args.follow_alpha)
            filtered_unwrapped = angle_filter.update(initial_unwrapped)
            velocity = VelocityEstimator(args.velocity_alpha)
            velocity.update(filtered_unwrapped, time.monotonic())
            if args.use_saved_motor_limits:
                if args.unlimited_angle:
                    raise TrackingError("No uses --unlimited-angle con --use-saved-motor-limits.")
                motor_calibration = read_motor_calibration(Path(args.limits_file))
                max_speed_pps = effective_follow_max_speed_pps(args)
                planner = LimitTrackingPlanner(
                    initial_unwrapped,
                    center_pulses=motor_calibration["center"],
                    left_limit_pulses=motor_calibration["left"],
                    right_limit_pulses=motor_calibration["right"],
                    gain=args.gain,
                    reverse=args.reverse,
                    max_angle_deg=args.max_angle,
                    min_speed_pps=args.min_speed,
                    max_speed_pps=max_speed_pps,
                    catchup_gain=args.catchup_gain,
                    deadband_deg=args.follow_deadband_deg,
                )
                motor_zero_label = (
                    f"center={motor_calibration['center']} "
                    f"left(+{args.max_angle:.0f})={motor_calibration['left']} "
                    f"right(-{args.max_angle:.0f})={motor_calibration['right']}"
                )
            else:
                max_speed_pps = effective_follow_max_speed_pps(args)
                planner = TrackingPlanner(
                    initial_unwrapped,
                    initial_status.absolute_position,
                    gain=args.gain,
                    reverse=args.reverse,
                    max_angle_deg=None if args.unlimited_angle else args.max_angle,
                    min_speed_pps=args.min_speed,
                    max_speed_pps=max_speed_pps,
                    catchup_gain=args.catchup_gain,
                    deadband_deg=args.follow_deadband_deg,
                )
                motor_zero_label = f"motor_zero={initial_status.absolute_position} pulses"

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
            magnet_warning_reported = False

            angle_limit = "unlimited" if args.unlimited_angle else f"+/-{args.max_angle:.1f}deg"
            print(
                f"FOLLOW activo: sensor_zero={initial_angle:.2f}deg "
                f"{motor_zero_label} "
                f"max_angle={angle_limit} "
                f"max_speed={motor_pps_to_rpm(max_speed_pps):.1f}RPM motor "
                f"({max_speed_pps}pps, salida={output_rpm_from_motor_pps(max_speed_pps):.2f}RPM) "
                f"AC={args.acceleration_ms}ms DC={args.deceleration_ms}ms "
                f"terminal={args.terminal_hz:.1f}Hz oled={'off' if args.no_oled else 'on'} "
                f"zero={'none' if saved_zero is None else f'{saved_zero:.2f}deg'}"
            )

            while not stop_requested.is_set() and (
                args.continuous or time.monotonic() - start < args.duration
            ):
                now = time.monotonic()
                raw = read_raw_angle_retry(sensor, args.i2c_retries, args.i2c_retry_delay)
                angle = raw_to_degrees(raw, offset_deg)
                unwrapped = unwrapper.update(angle)
                filtered_unwrapped = angle_filter.update(unwrapped)
                filtered_angle = normalize_angle(filtered_unwrapped)
                terminal_angle = terminal_angle_degrees(filtered_unwrapped, args.zero_deadband)
                wheel_velocity = velocity.update(filtered_unwrapped, now)
                if oled is not None:
                    oled.publish(filtered_angle)
                    if oled.error is not None and not oled_warning_reported:
                        print(f"ADVERTENCIA OLED deshabilitada: {oled.error}", file=sys.stderr)
                        oled_warning_reported = True

                if now >= next_magnet:
                    detected, too_strong, too_weak = read_magnet_status_retry(
                        sensor,
                        args.i2c_retries,
                        args.i2c_retry_delay,
                    )
                    if (not detected or too_strong or too_weak) and not magnet_warning_reported:
                        print(
                            "ADVERTENCIA: estado de iman invalido; follow continua "
                            f"detected={detected} strong={too_strong} weak={too_weak}",
                            file=sys.stderr,
                        )
                        magnet_warning_reported = True
                    next_magnet = now + 0.2

                command = planner.command(filtered_unwrapped, wheel_velocity, latest_status.absolute_position)
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
                    if error_pulses > args.max_tracking_error and not args.ignore_tracking_error:
                        tracking_fault_since = tracking_fault_since or now
                        if now - tracking_fault_since >= args.tracking_error_time:
                            raise TrackingError(f"Error de seguimiento excesivo: {error_pulses} pulsos.")
                    else:
                        tracking_fault_since = None
                    next_status = now + status_period_s

                if now >= next_report:
                    error = last_target - latest_status.absolute_position
                    print(
                        f"wheel={terminal_angle:+7.2f}deg delta={command.steering_delta_deg:+7.2f}deg "
                        f"velocity={wheel_velocity:+7.1f}deg/s target={last_target} "
                        f"motor={latest_status.absolute_position} error={error:+d} "
                        f"speed_cmd={command.speed_pps}pps limited={command.limited}"
                    )
                    next_report = now + 1.0 / args.terminal_hz

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


def read_keyboard_key(timeout_s: float = 0.1) -> str | None:
    import select

    ready, _, _ = select.select([sys.stdin], [], [], timeout_s)
    if not ready:
        return None
    char = sys.stdin.read(1)
    if char == "\x1b":
        if not select.select([sys.stdin], [], [], 0.08)[0]:
            return "escape"
        second = sys.stdin.read(1)
        if second != "[" or not select.select([sys.stdin], [], [], 0.08)[0]:
            return "escape"
        third = sys.stdin.read(1)
        return {"C": "right", "D": "left"}.get(third, "escape")
    return {
        " ": "stop",
        "s": "stop",
        "S": "stop",
        "q": "quit",
        "Q": "quit",
        "p": "status",
        "P": "status",
    }.get(char)


def print_jog_help(
    speed_pps: int,
    status_hz: float,
    hold_timeout_s: float,
    travel_pulses: int,
    refresh_s: float,
    acceleration_ms: int,
    deceleration_ms: int,
    reversed_jog: bool,
    limits: tuple[int, int] | None,
) -> None:
    print("", flush=True)
    print("Keyboard jog activo", flush=True)
    print("-------------------", flush=True)
    print(
        f"Mantener flecha izquierda/derecha: mover a {motor_pps_to_rpm(speed_pps):.1f} RPM motor "
        f"({speed_pps} pps, salida={output_rpm_from_motor_pps(speed_pps):.2f} RPM)",
        flush=True,
    )
    print(f"Soltar flecha: parar tras {hold_timeout_s:.2f} s sin repeticion de tecla", flush=True)
    print(f"Refresco de comando mientras mantienes flecha: {refresh_s:.2f} s", flush=True)
    print(f"Rampa del driver: AC={acceleration_ms}ms DC={deceleration_ms}ms", flush=True)
    print(f"Direccion de flechas: {'invertida' if reversed_jog else 'normal'}", flush=True)
    if limits is None:
        print("Limites: DESACTIVADOS", flush=True)
    else:
        print(f"Limites activos: {limits[0]}..{limits[1]} pulsos", flush=True)
    print(f"Telemetria: {status_hz:.1f} Hz", flush=True)
    print("ESPACIO o s: parar ahora", flush=True)
    print("p: imprimir estado", flush=True)
    print("q: salir con parada controlada", flush=True)
    print(f"Objetivo lejano por direccion: {travel_pulses} pulsos desde la posicion actual", flush=True)
    print("", flush=True)


def run_print_position(args: argparse.Namespace) -> int:
    configure_interface(args.interface, args.bitrate)
    try:
        with Uim342Can(args.interface, args.node_id, args.can_timeout) as motor:
            status = motor.get_motion_status()
            print(f"ABSOLUTE_PULSES={status.absolute_position}", flush=True)
            print(format_status(status), flush=True)
    finally:
        stop_interface(args.interface)
    return 0


def run_save_center(args: argparse.Namespace) -> int:
    configure_interface(args.interface, args.bitrate)
    try:
        with Uim342Can(args.interface, args.node_id, args.can_timeout) as motor:
            status = motor.get_motion_status()
            if not motor_status_is_safe(status):
                raise TrackingError(f"Estado inseguro; no guardo centro: {format_status(status)}")
            if not status.stopped or status.speed_pps != 0:
                raise TrackingError(f"El motor debe estar detenido para guardar centro: {format_status(status)}")
            write_motor_center(Path(args.limits_file), status.absolute_position)
            print(f"CENTER_PULSES={status.absolute_position}", flush=True)
            print(f"Centro guardado en {args.limits_file}", flush=True)
            print(format_status(status), flush=True)
    finally:
        stop_interface(args.interface)
    return 0


def run_save_motor_limit(args: argparse.Namespace, side: str) -> int:
    configure_interface(args.interface, args.bitrate)
    try:
        with Uim342Can(args.interface, args.node_id, args.can_timeout) as motor:
            status = motor.get_motion_status()
            if not motor_status_is_safe(status):
                raise TrackingError(f"Estado inseguro; no guardo limite: {format_status(status)}")
            if not status.stopped or status.speed_pps != 0:
                raise TrackingError(f"El motor debe estar detenido para guardar limite: {format_status(status)}")
            write_motor_limit(Path(args.limits_file), side, status.absolute_position)
            print(f"{side.upper()}_LIMIT_PULSES={status.absolute_position}", flush=True)
            print(f"Limite {side} guardado en {args.limits_file}", flush=True)
            print(format_status(status), flush=True)
    finally:
        stop_interface(args.interface)
    return 0


def run_keyboard_jog(args: argparse.Namespace) -> int:
    import termios
    import tty

    if args.confirm != BENCH_CONFIRMATION:
        raise TrackingError(f"Movimiento bloqueado: --confirm debe ser {BENCH_CONFIRMATION}.")
    if not sys.stdin.isatty():
        raise TrackingError("keyboard-jog necesita una terminal interactiva SSH.")

    speed_pps = effective_jog_speed_pps(args)
    can_configured = False
    enabled_here = False
    original_acceleration: int | None = None
    original_deceleration: int | None = None
    original_settings = termios.tcgetattr(sys.stdin.fileno())
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
                raise TrackingError("El motor no confirmo parada antes de iniciar keyboard-jog.")

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
            set_unsigned_parameter(motor, 0x99, 0x19, args.jog_acceleration_ms, "AC")
            set_unsigned_parameter(motor, 0x9A, 0x1A, args.jog_deceleration_ms, "DC")

            named_limits = None if args.ignore_motor_limits else read_named_motor_limits(Path(args.limits_file))
            limits = None if named_limits is None else (
                min(named_limits["left"], named_limits["right"]),
                max(named_limits["left"], named_limits["right"]),
            )
            target = initial_status.absolute_position
            active_direction: int | None = None
            last_arrow_at: float | None = None
            last_command_at = 0.0
            latest_status = initial_status
            print_jog_help(
                speed_pps,
                args.jog_status_hz,
                args.release_timeout,
                args.travel_pulses,
                args.jog_refresh_s,
                args.jog_acceleration_ms,
                args.jog_deceleration_ms,
                args.reverse_jog,
                limits,
            )
            print("Estado inicial:", format_status(initial_status), flush=True)
            if limits is not None and not position_within_limits(
                initial_status.absolute_position,
                limits[0],
                limits[1],
                args.limit_tolerance_pulses,
            ):
                raise TrackingError(
                    f"Posicion inicial fuera de limites: {initial_status.absolute_position} "
                    f"no esta entre {limits[0]} y {limits[1]} "
                    f"(tolerancia={args.limit_tolerance_pulses})."
                )

            status_period_s = 1.0 / args.jog_status_hz
            next_status_report = time.monotonic()
            next_limit_check = time.monotonic()
            tty.setcbreak(sys.stdin.fileno())
            while True:
                now = time.monotonic()
                key = read_keyboard_key(args.key_poll_s)
                if active_direction is not None and named_limits is not None and now >= next_limit_check:
                    latest_status = motor.get_motion_status()
                    if not motor_status_is_safe(latest_status):
                        raise TrackingError(f"Fallo del motor: {format_status(latest_status)}")
                    if jog_limit_reached(
                        latest_status.absolute_position,
                        target,
                        active_direction,
                        args.limit_tolerance_pulses,
                    ):
                        motor.stop_motion()
                        time.sleep(0.02)
                        latest_status = motor.get_motion_status()
                        target = latest_status.absolute_position
                        active_direction = None
                        last_arrow_at = None
                        print("LIMIT watchdog stop:", format_status(latest_status), flush=True)
                    next_limit_check = now + args.limit_check_s
                if (
                    active_direction is not None
                    and last_arrow_at is not None
                    and now - last_arrow_at >= args.release_timeout
                ):
                    motor.stop_motion()
                    time.sleep(0.02)
                    latest_status = motor.get_motion_status()
                    target = latest_status.absolute_position
                    active_direction = None
                    last_arrow_at = None
                    print("AUTO-STOP release:", format_status(latest_status), flush=True)
                if now >= next_status_report:
                    latest_status = motor.get_motion_status()
                    if not motor_status_is_safe(latest_status):
                        raise TrackingError(f"Fallo del motor: {format_status(latest_status)}")
                    print(
                        f"JOG absolute={latest_status.absolute_position} target={target} "
                        f"error={target - latest_status.absolute_position:+d} speed={latest_status.speed_pps}pps "
                        f"stopped={latest_status.stopped} in_position={latest_status.in_position} "
                        f"driver={'ON' if latest_status.driver_on else 'OFF'}",
                        flush=True,
                    )
                    next_status_report = now + status_period_s

                if key is None:
                    continue
                if key == "quit":
                    motor.stop_motion()
                    time.sleep(0.05)
                    print("Salida:", format_status(motor.get_motion_status()), flush=True)
                    break
                if key == "stop":
                    motor.stop_motion()
                    time.sleep(0.05)
                    latest_status = motor.get_motion_status()
                    target = latest_status.absolute_position
                    active_direction = None
                    last_arrow_at = None
                    print("STOP:", format_status(latest_status), flush=True)
                    continue
                if key == "status":
                    latest_status = motor.get_motion_status()
                    print("Status:", format_status(latest_status), flush=True)
                    continue
                if key in {"left", "right"}:
                    physical_side = key
                    if args.reverse_jog:
                        physical_side = "left" if key == "right" else "right"
                    now = time.monotonic()
                    last_arrow_at = now
                    latest_status = motor.get_motion_status()
                    if not motor_status_is_safe(latest_status):
                        raise TrackingError(f"Fallo del motor: {format_status(latest_status)}")
                    if named_limits is None:
                        direction = -1 if physical_side == "left" else 1
                        target = latest_status.absolute_position + direction * args.travel_pulses
                    else:
                        target = named_limits[physical_side]
                        direction = direction_toward_target(latest_status.absolute_position, target)
                    if direction == 0:
                        motor.stop_motion()
                        active_direction = None
                        last_arrow_at = None
                        print(
                            f"LIMIT {physical_side} reached: actual={latest_status.absolute_position} "
                            f"target={target} limits={limits[0]}..{limits[1]}",
                            flush=True,
                        )
                        continue
                    if active_direction != direction or now - last_command_at >= args.jog_refresh_s:
                        latest_status = motor.get_motion_status()
                        if not motor_status_is_safe(latest_status):
                            raise TrackingError(f"Fallo del motor: {format_status(latest_status)}")
                        if named_limits is not None and jog_limit_reached(
                            latest_status.absolute_position,
                            target,
                            direction,
                            args.limit_tolerance_pulses,
                        ):
                            motor.stop_motion()
                            active_direction = None
                            last_arrow_at = None
                            print(
                                f"LIMIT {physical_side} reached: actual={latest_status.absolute_position} "
                                f"target={target} limits={limits[0]}..{limits[1]}",
                                flush=True,
                            )
                            continue
                        send_tracking_command(motor, target, speed_pps)
                        active_direction = direction
                        last_command_at = now
                        next_limit_check = now
                        print(
                            f"{key}: RUN target={target} actual={latest_status.absolute_position} "
                            f"error={target - latest_status.absolute_position:+d}",
                            flush=True,
                        )
                    next_status_report = time.monotonic()
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, original_settings)
        if can_configured:
            try:
                with Uim342Can(args.interface, args.node_id, args.can_timeout) as motor:
                    motor.stop_motion()
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
    return 0


def add_i2c_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--i2c-bus", type=int, default=I2C_BUS)
    parser.add_argument("--offset", type=float, default=0.0)
    parser.add_argument("--zero-file", default=str(DEFAULT_ZERO_FILE))
    parser.add_argument("--ignore-saved-zero", action="store_true")
    parser.add_argument("--sensor-hz", type=float, default=100.0)
    parser.add_argument("--oled-hz", type=float, default=10.0)
    parser.add_argument("--terminal-hz", type=float, default=4.0)
    parser.add_argument("--zero-deadband", type=float, default=2.0)
    parser.add_argument("--i2c-retries", type=int, default=3)
    parser.add_argument("--i2c-retry-delay", type=float, default=0.005)
    parser.add_argument("--no-oled", action="store_true", help="No intenta usar la OLED; imprime el angulo en terminal.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AS5600/OLED/UIM342 direct-CAN steering follower.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    monitor = subparsers.add_parser("monitor", help="Prueba AS5600 y OLED sin tocar el motor.")
    add_i2c_arguments(monitor)
    monitor.add_argument("--duration", type=float, default=10.0)

    zero = subparsers.add_parser("calibrate-zero", help="Guarda la posicion actual del AS5600 como cero persistente.")
    add_i2c_arguments(zero)
    zero.add_argument("--samples", type=int, default=50)

    jog = subparsers.add_parser("keyboard-jog", help="Mueve el motor con flechas y guarda limites mecanicos.")
    jog.add_argument("--interface", default="can0")
    jog.add_argument("--bitrate", type=int, default=500_000)
    jog.add_argument("--node-id", type=int, default=13)
    jog.add_argument("--can-timeout", type=float, default=0.35)
    jog.add_argument("--speed-rpm", type=float, default=None, help="Velocidad del motor en RPM.")
    jog.add_argument("--speed-pps", type=int, default=None, help="Compatibilidad: velocidad en pulsos por segundo.")
    jog.add_argument("--jog-status-hz", type=float, default=2.0)
    jog.add_argument("--release-timeout", type=float, default=0.35)
    jog.add_argument("--jog-refresh-s", type=float, default=0.1)
    jog.add_argument("--key-poll-s", type=float, default=0.02)
    jog.add_argument("--travel-pulses", type=int, default=80_000)
    jog.add_argument("--jog-acceleration-ms", type=int, default=20)
    jog.add_argument("--jog-deceleration-ms", type=int, default=20)
    jog.add_argument("--limits-file", default=str(DEFAULT_LIMITS_FILE))
    jog.add_argument("--limit-tolerance-pulses", type=int, default=20)
    jog.add_argument("--limit-check-s", type=float, default=0.02)
    jog.add_argument("--ignore-motor-limits", action="store_true")
    jog.add_argument("--reverse-jog", action="store_true")
    jog.add_argument("--allow-driver-enable", action="store_true")
    jog.add_argument("--confirm", required=True)

    position = subparsers.add_parser("print-position", help="Imprime una sola vez la posicion absoluta del motor.")
    position.add_argument("--interface", default="can0")
    position.add_argument("--bitrate", type=int, default=500_000)
    position.add_argument("--node-id", type=int, default=13)
    position.add_argument("--can-timeout", type=float, default=0.35)

    center = subparsers.add_parser("save-center", help="Guarda la posicion absoluta actual como centro de direccion.")
    center.add_argument("--interface", default="can0")
    center.add_argument("--bitrate", type=int, default=500_000)
    center.add_argument("--node-id", type=int, default=13)
    center.add_argument("--can-timeout", type=float, default=0.35)
    center.add_argument("--limits-file", default=str(DEFAULT_LIMITS_FILE))

    right_limit = subparsers.add_parser("save-right-limit", help="Guarda la posicion absoluta actual como limite derecho.")
    right_limit.add_argument("--interface", default="can0")
    right_limit.add_argument("--bitrate", type=int, default=500_000)
    right_limit.add_argument("--node-id", type=int, default=13)
    right_limit.add_argument("--can-timeout", type=float, default=0.35)
    right_limit.add_argument("--limits-file", default=str(DEFAULT_LIMITS_FILE))

    left_limit = subparsers.add_parser("save-left-limit", help="Guarda la posicion absoluta actual como limite izquierdo.")
    left_limit.add_argument("--interface", default="can0")
    left_limit.add_argument("--bitrate", type=int, default=500_000)
    left_limit.add_argument("--node-id", type=int, default=13)
    left_limit.add_argument("--can-timeout", type=float, default=0.35)
    left_limit.add_argument("--limits-file", default=str(DEFAULT_LIMITS_FILE))

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
    follow.add_argument("--use-saved-motor-limits", action="store_true")
    follow.add_argument("--limits-file", default=str(DEFAULT_LIMITS_FILE))
    follow.add_argument("--min-speed", type=int, default=400)
    follow.add_argument("--max-speed-rpm", type=float, default=950.0, help="Velocidad maxima del motor en RPM.")
    follow.add_argument("--max-speed", type=int, default=None, help="Compatibilidad: velocidad maxima en pulsos por segundo.")
    follow.add_argument("--catchup-gain", type=float, default=3.0)
    follow.add_argument("--acceleration-ms", type=int, default=100)
    follow.add_argument("--deceleration-ms", type=int, default=100)
    follow.add_argument("--command-deadband", type=int, default=80)
    follow.add_argument("--follow-deadband-deg", type=float, default=3.0)
    follow.add_argument("--command-hz", type=float, default=25.0)
    follow.add_argument("--status-hz", type=float, default=10.0)
    follow.add_argument("--max-sensor-step", type=float, default=30.0)
    follow.add_argument("--max-sensor-outliers", type=int, default=3)
    follow.add_argument("--follow-alpha", type=float, default=0.25)
    follow.add_argument("--velocity-alpha", type=float, default=0.4)
    follow.add_argument("--max-tracking-error", type=int, default=20_000)
    follow.add_argument("--tracking-error-time", type=float, default=0.75)
    follow.add_argument("--ignore-tracking-error", action="store_true")
    follow.add_argument(
        "--allow-invalid-magnet",
        action="store_true",
        help="Solo banco: permite seguimiento aunque el AS5600 reporte campo magnetico invalido.",
    )
    follow.add_argument("--allow-driver-enable", action="store_true")
    follow.add_argument("--confirm", required=True)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if hasattr(args, "duration") and not getattr(args, "continuous", False) and args.duration <= 0.0:
        raise TrackingError("duration debe ser positivo.")
    if hasattr(args, "sensor_hz") and (args.sensor_hz <= 0.0 or args.sensor_hz > 200.0):
        raise TrackingError("sensor-hz debe estar entre 0 y 200.")
    if hasattr(args, "oled_hz") and (args.oled_hz <= 0.0 or args.oled_hz > 20.0):
        raise TrackingError("oled-hz debe estar entre 0 y 20.")
    if hasattr(args, "terminal_hz") and (args.terminal_hz <= 0.0 or args.terminal_hz > 50.0):
        raise TrackingError("terminal-hz debe estar entre 0 y 50.")
    if hasattr(args, "zero_deadband") and not 0.0 <= args.zero_deadband <= 20.0:
        raise TrackingError("zero-deadband debe estar entre 0 y 20 grados.")
    if hasattr(args, "i2c_retries") and not 0 <= args.i2c_retries <= 20:
        raise TrackingError("i2c-retries debe estar entre 0 y 20.")
    if hasattr(args, "i2c_retry_delay") and not 0.0 <= args.i2c_retry_delay <= 0.5:
        raise TrackingError("i2c-retry-delay debe estar entre 0 y 0.5 segundos.")
    if args.command == "calibrate-zero" and not 1 <= args.samples <= 1000:
        raise TrackingError("samples debe estar entre 1 y 1000.")
    if args.command == "keyboard-jog":
        speed_pps = effective_jog_speed_pps(args)
        if not 1 <= speed_pps <= MAX_UIM_SPEED_PPS:
            raise TrackingError(
                f"speed-rpm/speed-pps equivale a {speed_pps} pps; debe estar entre 1 y {MAX_UIM_SPEED_PPS}."
            )
        if not 0.2 <= args.jog_status_hz <= 20.0:
            raise TrackingError("jog-status-hz debe estar entre 0.2 y 20.")
        if not 0.05 <= args.release_timeout <= 2.0:
            raise TrackingError("release-timeout debe estar entre 0.05 y 2.0 segundos.")
        if not 0.05 <= args.jog_refresh_s <= 2.0:
            raise TrackingError("jog-refresh-s debe estar entre 0.05 y 2.0 segundos.")
        if not 0.005 <= args.key_poll_s <= 0.2:
            raise TrackingError("key-poll-s debe estar entre 0.005 y 0.2 segundos.")
        if not 1 <= args.travel_pulses <= 2_000_000:
            raise TrackingError("travel-pulses debe estar entre 1 y 2000000.")
        if not 1 <= args.jog_acceleration_ms <= 60_000 or not 1 <= args.jog_deceleration_ms <= 60_000:
            raise TrackingError("jog-acceleration-ms/jog-deceleration-ms deben estar entre 1 y 60000 ms.")
        if not 0 <= args.limit_tolerance_pulses <= 10_000:
            raise TrackingError("limit-tolerance-pulses debe estar entre 0 y 10000.")
        if not 0.005 <= args.limit_check_s <= 0.5:
            raise TrackingError("limit-check-s debe estar entre 0.005 y 0.5 segundos.")
    if args.command == "follow":
        max_speed_pps = effective_follow_max_speed_pps(args)
        if not 1 <= max_speed_pps <= MAX_UIM_SPEED_PPS:
            raise TrackingError(
                f"max-speed-rpm/max-speed equivale a {max_speed_pps} pps; "
                f"debe estar entre 1 y {MAX_UIM_SPEED_PPS}."
            )
        if args.min_speed > max_speed_pps:
            raise TrackingError("min-speed no puede ser mayor que la velocidad maxima.")
        if args.status_hz <= 0.0 or args.status_hz > args.sensor_hz:
            raise TrackingError("status-hz debe ser positivo y no superar sensor-hz.")
        if args.command_hz <= 0.0 or args.command_hz > 50.0:
            raise TrackingError("command-hz debe estar entre 0 y 50.")
        if args.command_deadband < 1:
            raise TrackingError("command-deadband debe ser al menos 1 pulso.")
        if not 0.0 <= args.follow_deadband_deg <= args.max_angle:
            raise TrackingError("follow-deadband-deg debe estar entre 0 y max-angle.")
        if not 0.0 < args.follow_alpha <= 1.0:
            raise TrackingError("follow-alpha debe estar entre 0 y 1.")
        if args.max_tracking_error < 1 or args.tracking_error_time <= 0.0:
            raise TrackingError("Proteccion de error de seguimiento invalida.")
        if not 0 <= args.max_sensor_outliers <= 20:
            raise TrackingError("max-sensor-outliers debe estar entre 0 y 20.")
        if not MIN_UIM_RAMP_MS <= args.acceleration_ms <= 60_000 or not MIN_UIM_RAMP_MS <= args.deceleration_ms <= 60_000:
            raise TrackingError(f"AC/DC deben estar entre {MIN_UIM_RAMP_MS} y 60000 ms.")


def main() -> int:
    args = parse_args()
    validate_args(args)
    if args.command == "calibrate-zero":
        return run_calibrate_zero(args)
    if args.command == "monitor":
        return run_monitor(args)
    if args.command == "keyboard-jog":
        return run_keyboard_jog(args)
    if args.command == "print-position":
        return run_print_position(args)
    if args.command == "save-center":
        return run_save_center(args)
    if args.command == "save-right-limit":
        return run_save_motor_limit(args, "right")
    if args.command == "save-left-limit":
        return run_save_motor_limit(args, "left")
    return run_follow(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit("Interrumpido. Si el eje se mueve, corta los 24 V.")
    except (CanError, OSError, TrackingError) as exc:
        raise SystemExit(f"ERROR: {exc}")
