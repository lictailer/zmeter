import inspect
import os
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from devices.four9.four9_hardware import Four9ProtocolError
from devices.four9.four9_logic import Four9Logic


def _status(target=10.0, temperature=9.5, stable=False, reason="unstable"):
    return {
        "target": target,
        "stable": stable,
        "latest_temperature": temperature,
        "stability_metrics": {"stable_reason": reason},
        "last_error": "",
    }


class _FakeHardware:
    host = "127.0.0.1"
    port = 5050
    socket_timeout_s = 10.0

    def __init__(self, statuses=None):
        self.is_connected = False
        self.target = 0.0
        self.statuses = list(statuses or [_status()])
        self.last_status = self.statuses[-1]
        self.set_calls = []
        self.status_calls = 0

    def connect_hardware(self, host, port):
        self.host = host
        self.port = port
        self.is_connected = True
        return True

    def disconnect(self):
        self.is_connected = False

    def set_temperature(self, target):
        self.target = float(target)
        self.set_calls.append(self.target)
        return self.target

    def get_status(self):
        self.status_calls += 1
        if self.statuses:
            self.last_status = self.statuses.pop(0)
        result = dict(self.last_status)
        result["target"] = self.target
        return result


class Four9LogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = (
            QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        )

    def make_logic(self, statuses=None, **kwargs):
        hardware = _FakeHardware(statuses)
        logic = Four9Logic(hardware=hardware, **kwargs)
        self.assertTrue(logic.connect())
        return logic, hardware

    def test_scan_facing_methods_are_exactly_the_requested_channels(self):
        getters = {
            name
            for name, method in inspect.getmembers(Four9Logic, inspect.isfunction)
            if name.startswith("get_")
        }
        setters = {
            name
            for name, method in inspect.getmembers(Four9Logic, inspect.isfunction)
            if name.startswith("set_")
        }
        self.assertEqual(getters, {"get_temperature"})
        self.assertEqual(
            setters, {"set_temperature", "set_temperature_stable"}
        )

    def test_get_temperature_returns_value_and_emits_full_passive_status(self):
        logic, _hardware = self.make_logic(
            [_status(target=25, temperature=24.75, stable=True, reason="normal")]
        )
        temperatures = []
        targets = []
        stability = []
        logic.sig_temperature.connect(temperatures.append)
        logic.sig_target_temperature.connect(targets.append)
        logic.sig_temperature_stable.connect(
            lambda stable, reason: stability.append((stable, reason))
        )

        self.assertEqual(logic.get_temperature(), 24.75)
        self.assertEqual(temperatures, [24.75])
        self.assertEqual(targets, [0.0])
        self.assertEqual(stability, [(True, "normal")])

    def test_set_temperature_updates_target_temperature_and_stability(self):
        logic, hardware = self.make_logic(
            [_status(temperature=19.8, stable=False, reason="waiting_for_full_window")]
        )
        temperatures = []
        targets = []
        stability = []
        logic.sig_temperature.connect(temperatures.append)
        logic.sig_target_temperature.connect(targets.append)
        logic.sig_temperature_stable.connect(
            lambda stable, reason: stability.append((stable, reason))
        )

        self.assertEqual(logic.set_temperature(20), 20.0)
        self.assertEqual(hardware.set_calls, [20.0])
        self.assertEqual(temperatures, [19.8])
        self.assertEqual(targets, [20.0, 20.0])
        self.assertEqual(stability, [(False, "waiting_for_full_window")])

    def test_stable_wait_uses_server_flag_and_returns_true(self):
        logic, hardware = self.make_logic(
            [
                _status(temperature=29.0, stable=False, reason="unstable"),
                _status(temperature=30.0, stable=True, reason="timeout_override"),
            ],
            stable_wait_timeout_s=1,
            stable_poll_interval_s=0.001,
        )
        stability = []
        logic.sig_temperature_stable.connect(
            lambda stable, reason: stability.append((stable, reason))
        )

        self.assertTrue(logic.set_temperature_stable(30))
        self.assertEqual(hardware.status_calls, 2)
        self.assertEqual(stability[-1], (True, "timeout_override"))

    def test_timeout_logs_and_returns_false_without_raising(self):
        logic, hardware = self.make_logic(
            [_status(temperature=39, stable=False)],
            stable_wait_timeout_s=0,
            stable_poll_interval_s=1,
        )
        messages = []
        logic.sig_log.connect(lambda payload: messages.append(payload[1]))

        self.assertFalse(logic.set_temperature_stable(40))
        self.assertEqual(hardware.status_calls, 1)
        self.assertTrue(any("timed out" in message for message in messages))
        self.assertTrue(any("scan will continue" in message for message in messages))

    def test_successful_set_and_get_do_not_log_routine_results(self):
        logic, _hardware = self.make_logic(
            [
                _status(temperature=19.8, stable=False),
                _status(temperature=20.0, stable=True),
            ]
        )
        entries = []
        logic.sig_log.connect(entries.append)

        self.assertEqual(logic.set_temperature(20), 20.0)
        self.assertEqual(logic.get_temperature(), 20.0)
        self.assertEqual(entries, [])

    def test_abort_interrupts_wait_promptly(self):
        logic, _hardware = self.make_logic(
            [_status(temperature=49, stable=False)],
            stable_wait_timeout_s=10,
            stable_poll_interval_s=5,
        )
        result = []
        worker = threading.Thread(
            target=lambda: result.append(logic.set_temperature_stable(50))
        )
        worker.start()
        deadline = time.monotonic() + 1
        while not logic._stable_wait_active and time.monotonic() < deadline:
            time.sleep(0.001)
        logic.request_abort_stable_wait()
        worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [False])

    def test_default_polling_and_timeout_values(self):
        logic = Four9Logic(hardware=_FakeHardware())
        self.assertEqual(logic.stable_poll_interval_s, 1.0)
        self.assertEqual(logic.stable_wait_timeout_s, 7200.0)

    def test_invalid_status_shape_invalidates_connection(self):
        invalid_status = _status()
        invalid_status.pop("stable")
        logic, hardware = self.make_logic([invalid_status])

        with self.assertRaisesRegex(Four9ProtocolError, "boolean stable"):
            logic.get_temperature()

        self.assertFalse(logic.is_connected)
        self.assertFalse(hardware.is_connected)


if __name__ == "__main__":
    unittest.main()
