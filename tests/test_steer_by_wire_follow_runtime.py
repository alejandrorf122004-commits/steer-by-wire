import importlib.util
import sys
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


if __name__ == "__main__":
    unittest.main()
