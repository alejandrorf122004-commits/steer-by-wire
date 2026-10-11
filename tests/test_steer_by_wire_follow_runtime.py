import importlib.util
import json
import argparse
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
MODULE_PATH = TOOLS_DIR / "steer_by_wire_follow_runtime.py"
SPEC = importlib.util.spec_from_file_location("steer_by_wire_follow_runtime", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AngleTests(unittest.TestCase):
    def test_unwraps_forward_across_zero(self):
        unwrap = MODULE.AngleUnwrapper()
        self.assertEqual(unwrap.update(359.0), 359.0)
        self.assertEqual(unwrap.update(1.0), 361.0)

    def test_unwraps_reverse_across_zero(self):
        unwrap = MODULE.AngleUnwrapper()
        self.assertEqual(unwrap.update(1.0), 1.0)
        self.assertEqual(unwrap.update(359.0), -1.0)

    def test_rejects_an_impossible_sensor_jump(self):
        unwrap = MODULE.AngleUnwrapper(max_step_deg=20.0)
        unwrap.update(10.0)
        with self.assertRaises(MODULE.TrackingError):
            unwrap.update(40.1)

    def test_holds_last_angle_during_isolated_sensor_outliers(self):
        unwrap = MODULE.AngleUnwrapper(max_step_deg=20.0, max_rejected_samples=2)
        self.assertEqual(unwrap.update(10.0), 10.0)
        self.assertEqual(unwrap.update(40.1), 10.0)
        self.assertEqual(unwrap.update(45.0), 10.0)
        self.assertEqual(unwrap.update(15.0), 15.0)

    def test_stops_after_repeated_sensor_outliers(self):
        unwrap = MODULE.AngleUnwrapper(max_step_deg=20.0, max_rejected_samples=2)
        unwrap.update(10.0)
        unwrap.update(40.1)
        unwrap.update(45.0)
        with self.assertRaises(MODULE.TrackingError):
            unwrap.update(50.0)

    def test_raw_angle_conversion(self):
        self.assertAlmostEqual(MODULE.raw_to_degrees(2048, 0.0), 180.0)

    def test_circular_zero_mean_handles_wraparound(self):
        self.assertAlmostEqual(MODULE.circular_mean_degrees([359.0, 0.0, 1.0]), 0.0)

    def test_saved_zero_makes_current_angle_zero(self):
        zero = MODULE.circular_mean_degrees([90.0, 90.0, 90.0])
        self.assertAlmostEqual(MODULE.raw_to_degrees(1024, zero), 0.0)

    def test_terminal_angle_is_signed_around_zero(self):
        self.assertAlmostEqual(MODULE.terminal_angle_degrees(358.0, 0.0), -2.0)
        self.assertAlmostEqual(MODULE.terminal_angle_degrees(2.0, 0.0), 2.0)

    def test_terminal_angle_snaps_near_zero(self):
        self.assertAlmostEqual(MODULE.terminal_angle_degrees(358.0, 2.5), 0.0)
        self.assertAlmostEqual(MODULE.terminal_angle_degrees(1.5, 2.5), 0.0)

    def test_decodes_as5600_magnet_status_bits(self):
        self.assertEqual(MODULE.decode_magnet_status(0x20), (True, False, False))
        self.assertEqual(MODULE.decode_magnet_status(0x10), (False, False, True))
        self.assertEqual(MODULE.decode_magnet_status(0x08), (False, True, False))


class PlannerTests(unittest.TestCase):
    def test_maps_ninety_degrees_to_quarter_output_revolution(self):
        planner = MODULE.TrackingPlanner(10.0, 1000, max_angle_deg=180.0)
        command = planner.command(100.0, 0.0, 1000)
        self.assertEqual(command.target_pulses, 41_000)
        self.assertEqual(command.steering_delta_deg, 90.0)

    def test_reverse_mapping_changes_motor_direction(self):
        planner = MODULE.TrackingPlanner(10.0, 1000, reverse=True, max_angle_deg=180.0)
        command = planner.command(100.0, 0.0, 1000)
        self.assertEqual(command.target_pulses, -39_000)

    def test_clamps_the_steering_excursion(self):
        planner = MODULE.TrackingPlanner(0.0, 0, max_angle_deg=30.0)
        command = planner.command(90.0, 0.0, 0)
        self.assertEqual(command.target_pulses, round(30.0 * MODULE.OUTPUT_PULSES_PER_DEGREE))
        self.assertTrue(command.limited)

    def test_unlimited_planner_does_not_clamp_angle(self):
        planner = MODULE.TrackingPlanner(0.0, 0, max_angle_deg=None)
        command = planner.command(360.0, 0.0, 0)
        self.assertEqual(command.target_pulses, MODULE.OUTPUT_PULSES_PER_REV)
        self.assertFalse(command.limited)

    def test_fast_wheel_requests_more_motor_speed(self):
        planner = MODULE.TrackingPlanner(0.0, 0, max_angle_deg=180.0, max_speed_pps=100_000)
        slow = planner.command(1.0, 1.0, 0)
        fast = planner.command(1.0, 20.0, 0)
        self.assertGreater(fast.speed_pps, slow.speed_pps)

    def test_low_pass_angle_filter_smooths_jump(self):
        angle_filter = MODULE.LowPassAngleFilter(alpha=0.25)

        self.assertEqual(angle_filter.update(0.0), 0.0)
        self.assertEqual(angle_filter.update(100.0), 25.0)

    def test_follow_deadband_holds_center(self):
        planner = MODULE.LimitTrackingPlanner(
            0.0,
            center_pulses=1_105_715,
            left_limit_pulses=1_155_358,
            right_limit_pulses=1_079_316,
            max_angle_deg=90.0,
            deadband_deg=5.0,
        )

        command = planner.command(4.0, 0.0, 1_105_715)

        self.assertEqual(command.target_pulses, 1_105_715)
        self.assertEqual(command.steering_delta_deg, 0.0)

    def test_limit_planner_maps_positive_ninety_to_left_limit(self):
        planner = MODULE.LimitTrackingPlanner(
            0.0,
            center_pulses=1_105_715,
            left_limit_pulses=1_155_358,
            right_limit_pulses=1_079_316,
            max_angle_deg=90.0,
        )

        self.assertEqual(planner.command(90.0, 0.0, 1_105_715).target_pulses, 1_155_358)
        self.assertEqual(planner.command(-90.0, 0.0, 1_105_715).target_pulses, 1_079_316)
        self.assertEqual(planner.command(0.0, 0.0, 1_105_715).target_pulses, 1_105_715)

    def test_limit_planner_clamps_beyond_ninety(self):
        planner = MODULE.LimitTrackingPlanner(
            0.0,
            center_pulses=1_105_715,
            left_limit_pulses=1_155_358,
            right_limit_pulses=1_079_316,
            max_angle_deg=90.0,
        )

        command = planner.command(120.0, 0.0, 1_105_715)
        self.assertEqual(command.target_pulses, 1_155_358)
        self.assertTrue(command.limited)

    def test_limit_planner_reverse_swaps_sensor_direction(self):
        planner = MODULE.LimitTrackingPlanner(
            0.0,
            center_pulses=1_105_715,
            left_limit_pulses=1_155_358,
            right_limit_pulses=1_079_316,
            reverse=True,
            max_angle_deg=90.0,
        )

        self.assertEqual(planner.command(90.0, 0.0, 1_105_715).target_pulses, 1_079_316)

    def test_target_deadband(self):
        self.assertFalse(MODULE.should_send_target(1000, 1079, 80))
        self.assertTrue(MODULE.should_send_target(1000, 1080, 80))

    def test_tracking_command_retries_one_timeout(self):
        class Reply:
            data = bytes([4]) + (1234).to_bytes(4, "little", signed=True)

        class FakeBus:
            def __init__(self):
                self.begin_calls = 0

            def request(self, *_args, **_kwargs):
                return Reply()

            def set_ptp_speed(self, speed_pps):
                self.speed_pps = speed_pps

            def begin_motion(self):
                self.begin_calls += 1
                if self.begin_calls == 1:
                    raise MODULE.UimTimeout("ACK perdido")

        bus = FakeBus()
        MODULE.send_tracking_command(bus, 1234, 6400)
        self.assertEqual(bus.begin_calls, 2)
        self.assertEqual(bus.speed_pps, 6400)

    def test_unsigned_motion_parameter_round_trip(self):
        class Reply:
            data = (100).to_bytes(4, "little")

        class FakeBus:
            def request(self, control_word, data, expected):
                self.call = (control_word, data, expected)
                return Reply()

        bus = FakeBus()
        MODULE.set_unsigned_parameter(bus, 0x99, 0x19, 100, "AC")
        self.assertEqual(bus.call, (0x99, (100).to_bytes(4, "little"), [0x19]))

    def test_ramp_parameter_allows_driver_minimum_rounding(self):
        class Reply:
            data = (MODULE.MIN_UIM_RAMP_MS).to_bytes(4, "little")

        class FakeBus:
            def request(self, control_word, data, expected):
                self.call = (control_word, data, expected)
                return Reply()

        bus = FakeBus()
        MODULE.set_unsigned_parameter(bus, 0x99, 0x19, 5, "AC")
        self.assertEqual(bus.call, (0x99, (5).to_bytes(4, "little"), [0x19]))

    def test_motor_rpm_conversion_matches_driver_pps(self):
        self.assertEqual(MODULE.motor_rpm_to_pps(60.0), 3200)
        self.assertAlmostEqual(MODULE.motor_pps_to_rpm(60_000), 1125.0)

    def test_keyboard_jog_speed_prefers_rpm(self):
        args = argparse.Namespace(speed_rpm=1125.0, speed_pps=3000)
        self.assertEqual(MODULE.effective_jog_speed_pps(args), 60_000)

    def test_follow_max_speed_defaults_to_950_rpm(self):
        args = argparse.Namespace(max_speed_rpm=950.0, max_speed=None)
        self.assertEqual(MODULE.effective_follow_max_speed_pps(args), round(950.0 * 3200 / 60.0))

    def test_follow_max_speed_pps_can_override_rpm(self):
        args = argparse.Namespace(max_speed_rpm=950.0, max_speed=60_000)
        self.assertEqual(MODULE.effective_follow_max_speed_pps(args), 60_000)

    def test_raw_angle_retry_recovers_from_i2c_error(self):
        class FakeSensor:
            def __init__(self):
                self.calls = 0

            def read_raw_angle(self):
                self.calls += 1
                if self.calls == 1:
                    raise OSError(5, "Input/output error")
                return 1234

        sensor = FakeSensor()
        self.assertEqual(MODULE.read_raw_angle_retry(sensor, retries=1, delay_s=0.0), 1234)
        self.assertEqual(sensor.calls, 2)

    def test_write_motor_limits_preserves_both_sides(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "limits.json"
            MODULE.write_motor_limit(path, "left", -123)
            MODULE.write_motor_limit(path, "right", 456)
            data = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(data["left_limit_pulses"], -123)
        self.assertEqual(data["right_limit_pulses"], 456)

    def test_write_motor_center_preserves_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "limits.json"
            MODULE.write_motor_limit(path, "left", -123)
            MODULE.write_motor_center(path, 10)
            data = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(data["left_limit_pulses"], -123)
        self.assertEqual(data["center_pulses"], 10)

    def test_read_motor_limits_orders_left_and_right(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "limits.json"
            MODULE.write_motor_limit(path, "left", 500)
            MODULE.write_motor_limit(path, "right", -100)

            limits = MODULE.read_motor_limits(path)

        self.assertEqual(limits, (-100, 500))

    def test_read_named_motor_limits_preserves_physical_sides(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "limits.json"
            MODULE.write_motor_limit(path, "left", 500)
            MODULE.write_motor_limit(path, "right", -100)

            limits = MODULE.read_named_motor_limits(path)

        self.assertEqual(limits, {"left": 500, "right": -100})

    def test_read_motor_calibration_requires_center_between_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "limits.json"
            MODULE.write_motor_limit(path, "left", 1_155_358)
            MODULE.write_motor_limit(path, "right", 1_079_316)
            MODULE.write_motor_center(path, 1_105_715)

            calibration = MODULE.read_motor_calibration(path)

        self.assertEqual(calibration, {"center": 1_105_715, "left": 1_155_358, "right": 1_079_316})

    def test_clamp_motor_target_respects_limits(self):
        self.assertEqual(MODULE.clamp_motor_target(600, -100, 500), 500)
        self.assertEqual(MODULE.clamp_motor_target(-200, -100, 500), -100)
        self.assertEqual(MODULE.clamp_motor_target(250, -100, 500), 250)

    def test_jog_limit_reached_when_moving_positive(self):
        self.assertFalse(MODULE.jog_limit_reached(450, 500, 1, 20))
        self.assertTrue(MODULE.jog_limit_reached(480, 500, 1, 20))
        self.assertTrue(MODULE.jog_limit_reached(520, 500, 1, 20))

    def test_jog_limit_reached_when_moving_negative(self):
        self.assertFalse(MODULE.jog_limit_reached(-450, -500, -1, 20))
        self.assertTrue(MODULE.jog_limit_reached(-480, -500, -1, 20))
        self.assertTrue(MODULE.jog_limit_reached(-520, -500, -1, 20))

    def test_direction_toward_target_uses_real_absolute_values(self):
        self.assertEqual(MODULE.direction_toward_target(1_105_715, 1_079_316), -1)
        self.assertEqual(MODULE.direction_toward_target(1_105_715, 1_155_358), 1)
        self.assertEqual(MODULE.direction_toward_target(1_155_358, 1_155_358), 0)

    def test_right_limit_can_be_lower_than_left_limit(self):
        actual_left = 1_155_358
        right_limit = 1_079_316
        direction = MODULE.direction_toward_target(actual_left, right_limit)

        self.assertEqual(direction, -1)
        self.assertFalse(MODULE.jog_limit_reached(actual_left, right_limit, direction, 50))

    def test_initial_position_allows_limit_tolerance(self):
        self.assertTrue(MODULE.position_within_limits(1_155_359, 1_052_634, 1_155_358, 50))
        self.assertFalse(MODULE.position_within_limits(1_155_459, 1_052_634, 1_155_358, 50))


if __name__ == "__main__":
    unittest.main()
