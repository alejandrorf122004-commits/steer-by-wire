#!/usr/bin/env python3
"""Steer-by-wire bench runtime for AS5600 + OLED + motor gateway.

This script keeps the OLED arrow and angle display working while adding a
motor-command layer prepared for the UIM2513 RS232-to-CAN gateway.

Current bench architecture:

    AS5600 -> Raspberry Pi Zero 2 -> OLED
    AS5600 -> Raspberry Pi Zero 2 -> RS232/UIM2513 -> CAN -> UIM4247CM

The exact serial frame used by the UIM2513 still depends on the professor's
gateway configuration, so the motor layer is parameterized by command template.
That lets the software, wiring, and safety flow stay ready for tomorrow's test.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from smbus2 import SMBus

try:
    import serial  # type: ignore
except ImportError:  # pragma: no cover - optional dependency on the Pi
    serial = None

WIDTH = 128
HEIGHT = 64
PAGES = HEIGHT // 8
I2C_BUS = 1
I2C_ADDR = 0x3C
AS5600_ADDR = 0x36
AS5600_STATUS_REG = 0x0B
AS5600_RAW_ANGLE_REG = 0x0C


def normalize_angle(angle_deg: float) -> float:
    return angle_deg % 360.0


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class CompassGeometry:
    center_x: int = 64
    center_y: int = 22
    needle_length: int = 24
    head_length: int = 10
    shaft_width: int = 6


@dataclass(frozen=True)
class AS5600Reading:
    raw_angle: int
    angle_deg: float
    magnet_detected: bool
    magnet_too_strong: bool
    magnet_too_weak: bool


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            ]
        )

    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


class SSD1306:
    def __init__(self, bus: SMBus, width: int = WIDTH, height: int = HEIGHT, addr: int = I2C_ADDR) -> None:
        self.bus = bus
        self.width = width
        self.height = height
        self.addr = addr

    def _cmds(self, *cmds: int) -> None:
        self.bus.write_i2c_block_data(self.addr, 0x00, list(cmds))

    def _data(self, data: list[int]) -> None:
        for start in range(0, len(data), 16):
            self.bus.write_i2c_block_data(self.addr, 0x40, data[start : start + 16])

    def init(self) -> None:
        self._cmds(
            0xAE,
            0x20, 0x00,
            0xB0,
            0xC8,
            0x00,
            0x10,
            0x40,
            0x81, 0xCF,
            0xA1,
            0xA6,
            0xA8, 0x3F,
            0xA4,
            0xD3, 0x00,
            0xD5, 0x80,
            0xD9, 0xF1,
            0xDA, 0x12,
            0xDB, 0x40,
            0x8D, 0x14,
            0xAF,
        )

    def show(self, image: Image.Image) -> None:
        if image.mode != "1":
            image = image.convert("1")
        if image.size != (self.width, self.height):
            image = image.resize((self.width, self.height))

        buf = [0x00] * (self.width * self.height // 8)
        pixels = image.load()
        index = 0
        for page in range(PAGES):
            for x in range(self.width):
                byte = 0
                for bit in range(8):
                    y = page * 8 + bit
                    if pixels[x, y] != 0:
                        byte |= 1 << bit
                buf[index] = byte
                index += 1

        self._cmds(0x21, 0x00, self.width - 1, 0x22, 0x00, PAGES - 1)
        self._data(buf)

    def clear(self) -> None:
        self.show(Image.new("1", (self.width, self.height), 0))


class AS5600:
    def __init__(self, bus: SMBus, addr: int = AS5600_ADDR) -> None:
        self.bus = bus
        self.addr = addr

    def read_status(self) -> tuple[bool, bool, bool]:
        value = self.bus.read_byte_data(self.addr, AS5600_STATUS_REG)
        magnet_detected = bool(value & 0x20)
        magnet_too_strong = bool(value & 0x10)
        magnet_too_weak = bool(value & 0x08)
        return magnet_detected, magnet_too_strong, magnet_too_weak

    def read_raw_angle(self) -> int:
        high, low = self.bus.read_i2c_block_data(self.addr, AS5600_RAW_ANGLE_REG, 2)
        return ((high & 0x0F) << 8) | low

    def read(self, offset_deg: float = 0.0) -> AS5600Reading:
        raw_angle = self.read_raw_angle()
        angle_deg = normalize_angle(raw_angle * 360.0 / 4096.0 - offset_deg)
        magnet_detected, magnet_too_strong, magnet_too_weak = self.read_status()
        return AS5600Reading(
            raw_angle=raw_angle,
            angle_deg=angle_deg,
            magnet_detected=magnet_detected,
            magnet_too_strong=magnet_too_strong,
            magnet_too_weak=magnet_too_weak,
        )


class OLEDCompass:
    def __init__(self, display: SSD1306) -> None:
        self.display = display
        self.font_big = load_font(20, bold=True)
        self.geo = CompassGeometry()
        self._filtered_angle: float | None = None
        self._display_angle: float | None = None

    def _polar(self, angle_deg: float, radius: float) -> tuple[float, float]:
        rad = math.radians(angle_deg - 90.0)
        x = self.geo.center_x + radius * math.cos(rad)
        y = self.geo.center_y + radius * math.sin(rad)
        return x, y

    def _draw_needle(self, draw: ImageDraw.ImageDraw, angle_deg: float) -> None:
        tip_x, tip_y = self._polar(angle_deg, self.geo.needle_length)
        left_base_x, left_base_y = self._polar(angle_deg + 155.0, 9)
        right_base_x, right_base_y = self._polar(angle_deg - 155.0, 9)
        tail_left_x, tail_left_y = self._polar(angle_deg + 180.0 + 25.0, 5)
        tail_right_x, tail_right_y = self._polar(angle_deg + 180.0 - 25.0, 5)

        draw.polygon(
            [
                (tip_x, tip_y),
                (left_base_x, left_base_y),
                (tail_left_x, tail_left_y),
                (tail_right_x, tail_right_y),
                (right_base_x, right_base_y),
            ],
            outline=1,
            fill=1,
        )

        center_x, center_y = self._polar(angle_deg + 180.0, 2)
        draw.ellipse((center_x - 1, center_y - 1, center_x + 1, center_y + 1), outline=1, fill=1)

    def render(self, angle_deg: float) -> Image.Image:
        angle_deg = normalize_angle(angle_deg)
        image = Image.new("1", (WIDTH, HEIGHT), 0)
        draw = ImageDraw.Draw(image)

        draw.rounded_rectangle((0, 0, WIDTH - 1, HEIGHT - 1), radius=4, outline=1)
        self._draw_needle(draw, angle_deg)
        draw.text((18, 45), f"{angle_deg:6.1f}°", font=self.font_big, fill=1)
        return image

    def show_angle(self, angle_deg: float) -> None:
        self.display.show(self.render(angle_deg))

    def _adaptive_alpha(self, delta_deg: float) -> float:
        delta_deg = abs(delta_deg)
        if delta_deg >= 20.0:
            return 0.85
        if delta_deg >= 8.0:
            return 0.60
        if delta_deg >= 3.0:
            return 0.35
        return 0.20

    def live_display(self, sensor: AS5600, offset_deg: float, delay_s: float) -> float:
        reading = sensor.read(offset_deg=offset_deg)
        current = normalize_angle(reading.angle_deg)
        if self._display_angle is None:
            self._display_angle = current
        else:
            delta = ((current - self._display_angle + 180.0) % 360.0) - 180.0
            alpha = self._adaptive_alpha(delta)
            if abs(delta) < 0.4:
                self._display_angle = current
            else:
                self._display_angle = normalize_angle(self._display_angle + alpha * delta)

        self._filtered_angle = self._display_angle
        self.show_angle(self._display_angle)
        time.sleep(delay_s)
        return reading.angle_deg


class MotorGateway:
    def send_target(self, target_deg: float) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass


class NullMotorGateway(MotorGateway):
    def __init__(self, dry_run: bool = True) -> None:
        self.dry_run = dry_run

    def send_target(self, target_deg: float) -> None:
        if self.dry_run:
            print(f"[motor] target={target_deg:.2f} deg", file=sys.stderr)

    def stop(self) -> None:
        if self.dry_run:
            print("[motor] stop", file=sys.stderr)


class SerialMotorGateway(MotorGateway):
    def __init__(
        self,
        port: str,
        baudrate: int,
        motor_id: int,
        target_template: str,
        stop_template: str,
        enable_template: str | None = None,
        timeout_s: float = 1.0,
    ) -> None:
        if serial is None:
            raise RuntimeError("pyserial no esta instalado. Ejecuta: pip install pyserial")

        self._serial = serial.Serial(port=port, baudrate=baudrate, timeout=timeout_s, write_timeout=timeout_s)
        self._motor_id = motor_id
        self._target_template = target_template
        self._stop_template = stop_template
        self._enable_template = enable_template

    def _write(self, payload: str) -> None:
        if not payload.endswith(("\n", "\r")):
            payload += "\n"
        self._serial.write(payload.encode("ascii", errors="ignore"))
        self._serial.flush()

    def enable(self) -> None:
        if self._enable_template:
            self._write(self._enable_template.format(motor_id=self._motor_id))

    def send_target(self, target_deg: float) -> None:
        self._write(self._target_template.format(target_deg=target_deg, motor_id=self._motor_id))

    def stop(self) -> None:
        self._write(self._stop_template.format(motor_id=self._motor_id))

    def close(self) -> None:
        self._serial.close()


@dataclass
class MotorMapper:
    gain: float = 1.0
    offset_deg: float = 0.0
    minimum: float | None = None
    maximum: float | None = None
    reverse: bool = False

    def map(self, sensor_angle_deg: float) -> float:
        angle = sensor_angle_deg - self.offset_deg
        if self.reverse:
            angle = -angle
        angle *= self.gain

        if self.minimum is not None and self.maximum is not None:
            angle = clamp(angle, self.minimum, self.maximum)
            return angle

        return normalize_angle(angle)


def build_motor_gateway(args: argparse.Namespace) -> MotorGateway:
    if not args.motor_port:
        return NullMotorGateway(dry_run=True)

    if args.motor_dry_run:
        return NullMotorGateway(dry_run=True)

    gateway = SerialMotorGateway(
        port=args.motor_port,
        baudrate=args.motor_baud,
        motor_id=args.motor_id,
        target_template=args.motor_template,
        stop_template=args.motor_stop_template,
        enable_template=args.motor_enable_template,
    )
    gateway.enable()
    return gateway


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Steer-by-wire bench runtime for the AS5600, OLED and motor gateway.")
    parser.add_argument("--angle", type=float, help="Show one angle in degrees and hold it on screen.")
    parser.add_argument("--offset", type=float, default=0.0, help="Subtract this calibration offset before display.")
    parser.add_argument("--hold", type=float, default=4.0, help="Seconds to hold a single-angle screen.")
    parser.add_argument("--demo", action="store_true", help="Run a short demo sweep of angles.")
    parser.add_argument("--repeat", action="store_true", help="Repeat the demo sweep forever.")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between demo frames.")
    parser.add_argument("--live-delay", type=float, default=0.05, help="Delay between live sensor updates.")

    parser.add_argument("--motor-port", help="Serial port for the UIM2513 gateway, for example /dev/ttyUSB0.")
    parser.add_argument("--motor-baud", type=int, default=52600, help="Baud rate for the UIM2513 serial link.")
    parser.add_argument("--motor-id", type=int, default=3, help="Motor CAN ID used by the gateway commands.")
    parser.add_argument(
        "--motor-template",
        default="ID {motor_id} TARGET {target_deg:.2f}",
        help="Serial command template sent for each motor target.",
    )
    parser.add_argument(
        "--motor-stop-template",
        default="ID {motor_id} STOP",
        help="Serial command template used when the control loop faults or exits.",
    )
    parser.add_argument(
        "--motor-enable-template",
        default=None,
        help="Optional command sent once at startup to enable the gateway or motor.",
    )
    parser.add_argument("--motor-dry-run", action="store_true", help="Print motor commands instead of sending them.")
    parser.add_argument("--motor-gain", type=float, default=1.0, help="Scale applied to the sensor angle before sending it.")
    parser.add_argument("--motor-offset", type=float, default=0.0, help="Offset applied to the sensor angle before motor mapping.")
    parser.add_argument("--motor-min", type=float, default=None, help="Minimum target angle before clamping.")
    parser.add_argument("--motor-max", type=float, default=None, help="Maximum target angle before clamping.")
    parser.add_argument("--motor-reverse", action="store_true", help="Invert motor direction before sending.")
    parser.add_argument(
        "--motor-deadband",
        type=float,
        default=0.25,
        help="Minimum target change required before sending a new motor command.",
    )
    return parser.parse_args()


def run_live(compass: OLEDCompass, sensor: AS5600, motor: MotorGateway, mapper: MotorMapper, offset_deg: float, delay_s: float, motor_deadband: float) -> None:
    last_target: float | None = None
    try:
        while True:
            try:
                sensor_angle = compass.live_display(sensor, offset_deg=offset_deg, delay_s=delay_s)
                target = mapper.map(sensor_angle)
                if last_target is None or abs(((target - last_target + 180.0) % 360.0) - 180.0) >= motor_deadband:
                    motor.send_target(target)
                    last_target = target
            except OSError:
                compass.show_angle(0.0)
                motor.stop()
                time.sleep(max(delay_s, 0.1))
    finally:
        motor.stop()
        motor.close()


def main() -> None:
    args = parse_args()
    mapper = MotorMapper(
        gain=args.motor_gain,
        offset_deg=args.motor_offset,
        minimum=args.motor_min,
        maximum=args.motor_max,
        reverse=args.motor_reverse,
    )

    with SMBus(I2C_BUS) as bus:
        display = SSD1306(bus)
        display.init()
        compass = OLEDCompass(display)
        motor = build_motor_gateway(args)

        if args.angle is not None:
            angle = args.angle - args.offset
            compass.show_angle(angle)
            if args.motor_port and not args.motor_dry_run:
                motor.send_target(mapper.map(angle))
            time.sleep(args.hold)
            motor.stop()
            motor.close()
            return

        if args.demo:
            demo_angles = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330]
            for angle in demo_angles:
                compass.show_angle(angle)
                if args.motor_port:
                    motor.send_target(mapper.map(angle))
                time.sleep(args.delay)
            if not args.repeat:
                motor.stop()
                motor.close()
                return
            while True:
                for angle in demo_angles:
                    compass.show_angle(angle)
                    if args.motor_port:
                        motor.send_target(mapper.map(angle))
                    time.sleep(args.delay)

        sensor = AS5600(bus)
        run_live(
            compass=compass,
            sensor=sensor,
            motor=motor,
            mapper=mapper,
            offset_deg=args.offset,
            delay_s=args.live_delay,
            motor_deadband=args.motor_deadband,
        )


if __name__ == "__main__":
    main()
