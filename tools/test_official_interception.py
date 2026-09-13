"""Verify the relative-input adapter without sending desktop input."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import pipa_bird


class OfficialInterceptionTest(unittest.TestCase):
    def driver(self, attached=True, succeeded=True):
        device = Mock()
        device.get_HWID.return_value = "mouse" if attached else ""
        context = SimpleNamespace(mouse=10, devices={10: device}, send=Mock())
        context.send.return_value = SimpleNamespace(succeeded=succeeded)
        return SimpleNamespace(inputs=SimpleNamespace(_g_context=context), auto_capture_devices=Mock())

    def test_signed_relative_stroke_uses_attached_mouse(self):
        driver = self.driver()
        with patch.object(pipa_bird, "_relative_mouse", return_value=driver):
            self.assertTrue(pipa_bird._relative_move(-120, 80))
        device, stroke = driver.inputs._g_context.send.call_args.args
        self.assertEqual((device, stroke.flags, stroke.x, stroke.y), (10, 0, -120, 80))
        driver.auto_capture_devices.assert_called_once_with(keyboard=False, mouse=True)

    def test_empty_slot_does_not_receive_input(self):
        driver = self.driver(attached=False)
        with patch.object(pipa_bird, "_relative_mouse", return_value=driver):
            self.assertFalse(pipa_bird._relative_move(1, 2))
        driver.inputs._g_context.send.assert_not_called()

    def test_driver_failure_aborts_action(self):
        driver = self.driver(succeeded=False)
        with patch.object(pipa_bird, "_relative_mouse", return_value=driver):
            with self.assertRaises(RuntimeError):
                pipa_bird._wait_controller_action(pipa_bird._relative_move(1, 2), "aim")


if __name__ == "__main__":
    unittest.main()
