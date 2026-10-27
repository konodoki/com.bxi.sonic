"""BXI lifecycle tests: actual controller/packet builder; ROS and parent mocked.

Run: python3 -m unittest discover -s tools/gripper_native -p test_exit.py
No device, CAN, ROS launch or robot commands.
"""
import importlib
from pathlib import Path
from threading import RLock
from types import ModuleType, SimpleNamespace as NS
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
DISABLE = bytes.fromhex('fffffffffffffffd')


class Packet:
    def __init__(self):
        self.bus = 0
        self.frame = NS(can_id=0, flags=0, len=0, data=[0]*64)


class Parent:
    def on_exit(self, ctx):
        pass

    def on_unbind(self, ctx):
        self._gripper_publisher = None


class ExitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        name = '_bxi_exit_test'
        pkg = ModuleType(name)
        pkg.__path__ = [str(ROOT)]
        state = ModuleType(name+'.state')
        state.SonicTeleopState = Parent
        comm = ModuleType('communication')
        comm.msg = ModuleType('communication.msg')
        comm.msg.CANFDPacket = Packet
        cls.modules = patch.dict(sys.modules, {name: pkg, name+'.state': state,
            'communication': comm, 'communication.msg': comm.msg})
        cls.modules.start()
        cls.d = importlib.import_module(name+'.bxi_demo')

    @classmethod
    def tearDownClass(cls):
        cls.modules.stop()

    def setUp(self):
        self.s = object.__new__(self.d.BxiDemoState)
        self.s._demo_lock = RLock()
        self.s._left_bus, self.s._right_bus = 5, 6
        self.s._gripper_publisher = Mock()
        self.pub = self.s._gripper_publisher
        self.s._motion_log = Mock()
        self.s._native = Mock()
        self.s.hardware_gripper = True
        self.s._gripper_session_active = self.s._gripper_armed = True
        self.s._gripper_motion_ready = self.s._gripper_calibrated = True
        self.s._sides = {b: self.d.Side(phase='control', enabled_at=10., handle=b)
                         for b in (5, 6)}
        self.ctx = Mock()

    def packets(self):
        return [c.args[0] for c in self.pub.publish.call_args_list]

    def assert_disabled(self, buses=(5, 6)):
        self.assertEqual([(p.bus, p.frame.can_id, p.frame.flags, bytes(p.frame.data[:8]))
                          for p in self.packets()],
                         [(b, 1, 5, DISABLE) for _ in range(3) for b in buses])
        self.assertFalse(self.s._gripper_session_active)
        self.assertFalse(self.s._gripper_armed)
        self.ctx.request_state.assert_not_called()

    def test_all_exit_targets_disable_without_close_or_new_body_request(self):
        for target, forced in [('normal', False), ('pd_brake', True), ('zero_torque', True)]:
            with self.subTest(target=target):
                self.setUp()
                self.assertTrue(self.s.prepare_exit(self.ctx, 'com.bxi.basic_actions/'+target,
                                                   trigger='test', force=forced))
                self.assertFalse(self.packets())  # preparation can still be cancelled
                self.s.on_exit(self.ctx)
                self.assert_disabled()
                self.s._update_gripper(self.ctx, .005)
                self.s.on_exit(self.ctx)
                self.s.on_unbind(self.ctx)
                self.assert_disabled()  # no commands after exit, no duplicate teardown

    def test_opening_and_waiting_for_first_feedback_also_disable(self):
        for phase in ('opening', 'wait_feedback', 'fault'):
            with self.subTest(phase=phase):
                self.setUp()
                for side in self.s._sides.values():
                    side.phase, side.handle = phase, None
                self.s.on_exit(self.ctx)
                self.assert_disabled()

    def test_unbind_disables_before_publisher_destroyed(self):
        self.s.on_unbind(self.ctx)
        self.assert_disabled()
        self.assertIsNone(self.s._gripper_publisher)

    def test_does_not_disable_a_side_never_enabled(self):
        self.s._sides[6] = self.d.Side()
        self.s.on_exit(self.ctx)
        self.assert_disabled((5,))

    def test_never_entered_state_sends_nothing(self):
        self.s._sides = {}
        self.s.on_unbind(self.ctx)
        self.assertFalse(self.packets())

    def test_failed_bus_still_attempts_other_bus_and_logs_failure(self):
        def publish(packet):
            if packet.bus == 5:
                raise OSError('CAN5 publisher failed')
        self.pub.publish.side_effect = publish
        self.s.on_exit(self.ctx)
        self.assert_disabled()  # records attempts, not physical delivery
        failed = [c for c in self.s._motion_log.call_args_list
                  if c.args[2]['event'] == 'disable_send_failed']
        self.assertEqual(len(failed), 3)
        self.assertTrue(all(c.args[0] == 'warning' for c in failed))

    def test_stop_before_free_and_repeated_end_is_inert(self):
        native = self.s._native
        native.lib.demo_free.side_effect = lambda handle: self.assert_disabled()
        self.s._end_demo()
        self.assertEqual(native.lib.demo_free.call_count, 2)
        native.close.assert_called_once()
        self.s._end_demo()
        self.assert_disabled()


if __name__ == '__main__':
    unittest.main()
