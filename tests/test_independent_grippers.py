from __future__ import annotations

import importlib
from pathlib import Path
import sys
from threading import Lock
import types
import unittest
from unittest.mock import patch


MOD_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "_sonic_independent_gripper_test"


def _install_import_stubs() -> None:
    communication = types.ModuleType("communication")
    communication_msg = types.ModuleType("communication.msg")
    communication_msg.CANFDPacket = type("CANFDPacket", (), {})
    communication.msg = communication_msg
    sys.modules.setdefault("communication", communication)
    sys.modules.setdefault("communication.msg", communication_msg)

    rclpy = types.ModuleType("rclpy")
    rclpy_qos = types.ModuleType("rclpy.qos")
    rclpy_qos.QoSProfile = type(
        "QoSProfile",
        (),
        {"__init__": lambda self, *args, **kwargs: None},
    )
    rclpy.qos = rclpy_qos
    sys.modules.setdefault("rclpy", rclpy)
    sys.modules.setdefault("rclpy.qos", rclpy_qos)

    std_msgs = types.ModuleType("std_msgs")
    std_msgs_msg = types.ModuleType("std_msgs.msg")
    std_msgs_msg.Float32 = type("Float32", (), {})
    std_msgs.msg = std_msgs_msg
    sys.modules.setdefault("std_msgs", std_msgs)
    sys.modules.setdefault("std_msgs.msg", std_msgs_msg)


_install_import_stubs()
package = types.ModuleType(PACKAGE_NAME)
package.__path__ = [str(MOD_ROOT)]
sys.modules.setdefault(PACKAGE_NAME, package)
state_module = importlib.import_module(f"{PACKAGE_NAME}.state")
gripper_module = importlib.import_module(f"{PACKAGE_NAME}.gripper")


class _Logger:
    def __init__(self) -> None:
        self.infos: list[str] = []
        self.errors: list[str] = []

    def info(self, message: str) -> None:
        self.infos.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)


class _Calibrator:
    def __init__(
        self,
        phase,
        *,
        target: float | None,
        ready: bool = False,
        fail_on_update: bool = False,
    ) -> None:
        self.phase = phase
        self.target = target
        self.ready = ready
        self.failed = False
        self.failure_reason = None
        self.closed_position = -0.5 if ready else None
        self.open_position = 0.5 if ready else None
        self.fail_on_update = fail_on_update
        self.updates: list[object] = []

    def update(self, feedback, now: float, dt: float):
        self.updates.append(feedback)
        if self.fail_on_update:
            self.failed = True
            self.phase = gripper_module.CalibrationPhase.FAILED
            self.failure_reason = "motor is offline"
        return self.target


def _state(left: _Calibrator, right: _Calibrator):
    result = object.__new__(state_module.SonicTeleopState)
    result.hardware_gripper = True
    result._gripper_session_active = True
    result._gripper_armed = True
    result._left_bus = 5
    result._right_bus = 6
    result._gripper_calibrators = {5: left, 6: right}
    result._gripper_feedback_lock = Lock()
    result._gripper_feedback = {5: object()}
    result._gripper_ready_buses = set()
    result._gripper_faulted_buses = set()
    result._gripper_calibration_kp = 5.0
    result._gripper_calibration_kd = 0.5
    result._left_trigger = 0.25
    result._right_trigger = 0.75
    result._logger = _Logger()
    result._log_gripper_phase_change = lambda bus, calibrator: None
    return result


class IndependentGripperTest(unittest.TestCase):
    def test_missing_right_feedback_does_not_block_left_calibration(self):
        left = _Calibrator(
            gripper_module.CalibrationPhase.SEEKING_OPEN,
            target=0.25,
        )
        right = _Calibrator(
            gripper_module.CalibrationPhase.WAITING_FEEDBACK,
            target=None,
        )
        state = _state(left, right)
        published: list[tuple[int, float]] = []
        state._publish_gripper_target = (
            lambda bus, target, **kwargs: published.append((bus, target))
        )

        with patch.object(state_module.time, "monotonic", return_value=0.1):
            state._update_gripper(0.02)

        self.assertEqual(published, [(5, 0.25)])
        self.assertEqual(len(left.updates), 1)
        self.assertEqual(len(right.updates), 1)
        self.assertIsNone(right.updates[0])

    def test_right_failure_disables_only_right_and_left_remains_usable(self):
        left = _Calibrator(
            gripper_module.CalibrationPhase.READY,
            target=0.5,
            ready=True,
        )
        right = _Calibrator(
            gripper_module.CalibrationPhase.WAITING_FEEDBACK,
            target=None,
            fail_on_update=True,
        )
        state = _state(left, right)
        disabled: list[int] = []
        controlled: list[tuple[int, float]] = []
        state._disable_gripper = disabled.append
        state._publish_gripper = (
            lambda bus, trigger: controlled.append((bus, trigger))
        )
        state._refresh_gripper_enable = lambda now: None

        with patch.object(state_module.time, "monotonic", return_value=0.1):
            state._update_gripper(0.02)

        self.assertEqual(disabled, [6])
        self.assertEqual(controlled, [(5, 0.25)])
        self.assertEqual(state._gripper_faulted_buses, {6})
        self.assertEqual(state._gripper_ready_buses, {5})

    def test_ready_gripper_still_detects_runtime_feedback_timeout(self):
        settings = gripper_module.CalibrationSettings(
            response_timeout_s=0.2,
            feedback_timeout_s=0.1,
        )
        calibrator = gripper_module.GripperCalibrator("left", settings)
        calibrator.phase = gripper_module.CalibrationPhase.READY
        calibrator.target_position = 0.5
        feedback = gripper_module.MotorFeedback(
            motor_id=1,
            position=0.5,
            velocity=0.0,
            torque=0.0,
            mos_temperature_c=30,
            motor_temperature_c=31,
            received_at=0.0,
        )

        calibrator.update(feedback, 0.11, 0.02)

        self.assertTrue(calibrator.failed)
        self.assertIn("feedback timed out", calibrator.failure_reason or "")


if __name__ == "__main__":
    unittest.main()
