import sys
import unittest
from unittest.mock import MagicMock

from PyQt6.QtCore import QCoreApplication

# Ensure a Qt application instance exists (required for signals)
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

from sr860_logic import SR860_Logic


class TestSR860Logic(unittest.TestCase):
    """Unit-tests for SR860_Logic with mocked SR860_Hardware."""

    def setUp(self):
        # Create logic instance and replace its hardware with a MagicMock
        self.logic = SR860_Logic()
        self.mock_hw = MagicMock()

        # --- configure mock return values ---
        self.mock_hw.get_frequency.return_value = 123.0
        self.mock_hw.get_amplitude.return_value = 0.456
        self.mock_hw.get_time_constant.return_value = 3
        self.mock_hw.get_sensitivity.return_value = 10
        self.mock_hw.get_phase.return_value = 45.0
        self.mock_hw.get_X.return_value = 1.23
        self.mock_hw.get_Y.return_value = 4.56
        self.mock_hw.get_R.return_value = 5.0
        self.mock_hw.get_Theta.return_value = 30.0
        self.mock_hw.get_display.return_value = {
            "green": 1.0,
            "blue": 2.0,
            "yellow": 3.0,
            "orange": 4.0,
        }
        self.mock_hw.get_aux_out.return_value = 1.234
        self.mock_hw.get_aux_in.return_value = 2.345
        self.mock_hw.unlocked.return_value = False
        self.mock_hw.input_overload.return_value = True

        # Attach mock to logic
        self.logic.hardware = self.mock_hw
        self.logic.connected = True

    # -------- helper to capture signal emission --------
    def _capture_signal(self, signal, trigger_func, *args, **kwargs):
        container = {}

        def _slot(val):
            container["val"] = val

        signal.connect(_slot)
        try:
            result = trigger_func(*args, **kwargs)
        finally:
            signal.disconnect(_slot)
        return result, container.get("val")

    # ------------------ tests -------------------------
    def test_getters(self):
        getter_map = {
            "get_frequency": (self.logic.sig_frequency, 123.0),
            "get_amplitude": (self.logic.sig_amplitude, 0.456),
            "get_time_constant": (self.logic.sig_time_constant, 3),
            "get_sensitivity": (self.logic.sig_sensitivity, 10),
            "get_phase": (self.logic.sig_phase, 45.0),
            "get_X": (self.logic.sig_X, 1.23),
            "get_Y": (self.logic.sig_Y, 4.56),
            "get_R": (self.logic.sig_R, 5.0),
            "get_Theta": (self.logic.sig_Theta, 30.0),
            "get_display": (self.logic.sig_display, {
                "green": 1.0,
                "blue": 2.0,
                "yellow": 3.0,
                "orange": 4.0,
            }),
        }
        for method_name, (signal, exp_val) in getter_map.items():
            with self.subTest(method=method_name):
                method = getattr(self.logic, method_name)
                ret, emitted = self._capture_signal(signal, method)
                print(f"{method_name}: returned={ret}, signal_emitted={emitted}")
                self.assertEqual(ret, exp_val)
                self.assertEqual(emitted, exp_val)

    def test_setters(self):
        # Frequency
        self.logic.setpoint_frequency = 1000.0
        self.logic.set_frequency()
        print(f"set_frequency: setpoint={self.logic.setpoint_frequency}")
        self.mock_hw.set_frequency.assert_called_with(1000.0)

        # Amplitude
        self.logic.setpoint_amplitude = 0.111
        self.logic.set_amplitude()
        print(f"set_amplitude: setpoint={self.logic.setpoint_amplitude}")
        self.mock_hw.set_amplitude.assert_called_with(0.111)

        # Time constant
        self.logic.setpoint_time_constant = 5
        self.logic.set_time_constant()
        print(f"set_time_constant: setpoint={self.logic.setpoint_time_constant}")
        self.mock_hw.set_time_constant.assert_called_with(5)

        # Sensitivity
        self.logic.setpoint_sensitivity = 8
        self.logic.set_sensitivity()
        print(f"set_sensitivity: setpoint={self.logic.setpoint_sensitivity}")
        self.mock_hw.set_sensitivity.assert_called_with(8)

        # Phase
        self.logic.setpoint_phase = 90.0
        self.logic.set_phase()
        print(f"set_phase: setpoint={self.logic.setpoint_phase}")
        self.mock_hw.set_phase.assert_called_with(90.0)

        # Aux output
        self.logic.setpoint_aux_channel = 2
        self.logic.setpoint_aux_voltage = 2.222
        self.logic.set_aux_out()
        print(
            f"set_aux_out: channel={self.logic.setpoint_aux_channel}, voltage={self.logic.setpoint_aux_voltage}"
        )
        self.mock_hw.set_aux_out.assert_called_with(2, 2.222)

    def test_status_methods(self):
        _, emitted_unlock = self._capture_signal(
            self.logic.sig_unlocked, self.logic.unlocked
        )
        self.assertFalse(emitted_unlock)
        self.mock_hw.unlocked.assert_called_once()

        _, emitted_overload = self._capture_signal(
            self.logic.sig_input_overload, self.logic.input_overload
        )
        self.assertTrue(emitted_overload)
        self.mock_hw.input_overload.assert_called_once()

    def test_run_dispatch(self):
        # Verify that run() dispatches a queued job correctly
        self.logic.job = "get_frequency"
        self.logic.run()
        self.mock_hw.get_frequency.assert_called_once()

        # Test a setter job
        self.logic.setpoint_frequency = 200.0
        self.logic.job = "set_frequency"
        self.logic.run()
        self.mock_hw.set_frequency.assert_called_with(200.0)


if __name__ == "__main__":
    unittest.main() 