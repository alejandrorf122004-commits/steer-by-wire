import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "steer_by_wire_can_runtime.py"
SPEC = importlib.util.spec_from_file_location("steer_by_wire_can_runtime", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ProtocolTests(unittest.TestCase):
    def test_bench_full_turn_limits(self):
        self.assertEqual(MODULE.MAX_BENCH_PULSES, 160000)
        self.assertEqual(MODULE.MAX_BENCH_SPEED_PPS, 6400)

    def test_builds_node_13_protocol_parameter_query_id(self):
        self.assertEqual(MODULE.build_instruction_id(13, 0x81), 0x04680081)

    def test_decodes_node_13_protocol_parameter_reply(self):
        self.assertEqual(MODULE.parse_reply_id(0x0D080001), (13, 0x01))

    def test_signed_little_endian_values(self):
        self.assertEqual(MODULE.signed_le(bytes.fromhex("18 FC FF FF")), -1000)
        self.assertEqual(MODULE.signed_le(bytes.fromhex("9A F3 07 00")), 521114)

    def test_can_frame_round_trip(self):
        raw = MODULE.pack_can_frame(0x04680081, b"\x05")
        frame_id, data, is_error = MODULE.unpack_can_frame(raw)
        self.assertEqual(frame_id, 0x04680081)
        self.assertEqual(data, b"\x05")
        self.assertFalse(is_error)

    def test_relative_move_uses_the_per_command_position_counter(self):
        status = MODULE.MotionStatus(
            mode=1,
            driver_on=True,
            stopped=True,
            in_position=False,
            stall=False,
            locked=False,
            error=False,
            speed_pps=0,
            relative_position=100,
            absolute_position=521214,
        )
        self.assertTrue(MODULE.relative_move_complete(status, 100))
        self.assertFalse(MODULE.relative_move_complete(status, 521214))


if __name__ == "__main__":
    unittest.main()
