import os
import threading
import time
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from core.device_management import build_default_registry
from core.shared_runtime.visa import VisaRuntime
from devices.hp34401a.hp34401a_main import HP34401A
from devices.ni6423.ni6423_main import NI6423
from devices.nidaq.nidaq_main import NIDAQ
from devices.sr830.sr830_main import SR830
from devices.sr860.sr860_main import SR860
from devices.tlpm.tlpm_main import TLPM


class _LifecycleLogic:
    def __init__(self):
        self.connected = True
        self._connected = True
        self.is_connected = True
        self.is_initialized = True
        self.dev_name = "Dev1"
        self.running = False
        self.do_read_indefinitely = False
        self.prepare_calls = []
        self.resume_calls = 0
        self.force_calls = 0
        self.start_calls = 0
        self.stop_requests = 0
        self.job = ""

    def isRunning(self):
        return self.running

    def lifecycle_busy(self):
        return self.running

    def prepare_scan(self, timeout_ms):
        self.prepare_calls.append((timeout_ms, QtCore.QThread.currentThread()))
        self.running = False
        self.do_read_indefinitely = False
        return True

    def resume_scan(self):
        self.resume_calls += 1
        return True

    def force_stop(self):
        self.force_calls += 1
        return True

    def request_force_stop(self):
        self.force_calls += 1
        return True

    def request_stop(self):
        self.stop_requests += 1

    def start(self):
        self.start_calls += 1
        self.running = True


class _TimerProbe:
    def __init__(self, active=True):
        self.active = active
        self.stop_threads = []
        self.start_threads = []

    def isActive(self):
        return self.active

    def stop(self):
        self.stop_threads.append(QtCore.QThread.currentThread())
        self.active = False

    def start(self, *_args):
        self.start_threads.append(QtCore.QThread.currentThread())
        self.active = True


class _NoHardwareVisaManager:
    def list_resources(self, _query="?*::INSTR"):
        return ()

    def open_resource(self, *_args, **_kwargs):
        raise AssertionError("lifecycle tests must not open VISA resources")

    def close(self):
        return None


class MonitorScanLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.widgets = []
        self.visa_runtimes = []

    def tearDown(self):
        for widget in self.widgets:
            timer = getattr(widget, "timer", None)
            if isinstance(timer, QtCore.QTimer):
                timer.stop()
            widget.close()
            widget.deleteLater()
        self.app.processEvents()
        for runtime in self.visa_runtimes:
            runtime.shutdown()

    def _make_widget(self, widget_type):
        if widget_type in (HP34401A, SR830, SR860):
            runtime = VisaRuntime(manager_factory=_NoHardwareVisaManager)
            self.visa_runtimes.append(runtime)
            widget = widget_type(runtime)
        else:
            widget = widget_type()
        timer = getattr(widget, "timer", None)
        if isinstance(timer, QtCore.QTimer):
            timer.stop()
        widget.logic = _LifecycleLogic()
        self.widgets.append(widget)
        return widget

    def test_registry_exposes_complete_monitor_lifecycle(self):
        registry = build_default_registry()
        for driver_id in (
            "ni6423",
            "nidaq",
            "hp34401a",
            "sr830",
            "sr860",
            "tlpm",
        ):
            with self.subTest(driver_id=driver_id):
                registration = registry.registration(driver_id)
                self.assertIsNotNone(registration.stop_scan)
                self.assertIsNotNone(registration.start_scan)
                self.assertIsNotNone(registration.force_stop)
                self.assertIsNotNone(registration.is_busy)

    def test_timer_monitors_restore_only_when_previously_active(self):
        for widget_type in (NIDAQ, HP34401A, SR830, SR860):
            with self.subTest(widget=widget_type.__name__, initially_active=True):
                widget = self._make_widget(widget_type)
                self.assertTrue(widget.start_timer())
                self.assertTrue(widget.timer.isActive())

                self.assertTrue(widget.stop_scan())
                self.assertTrue(widget.stop_scan())
                self.assertFalse(widget.timer.isActive())
                self.assertTrue(widget.start_scan())
                self.assertTrue(widget.start_scan())
                self.assertTrue(widget.timer.isActive())

            with self.subTest(widget=widget_type.__name__, initially_active=False):
                widget = self._make_widget(widget_type)
                self.assertFalse(widget.timer.isActive())
                self.assertTrue(widget.stop_scan())
                self.assertTrue(widget.start_scan())
                self.assertFalse(widget.timer.isActive())

    def test_ni6423_restores_exact_monitor_mode_and_preserves_it_on_force_stop(self):
        widget = self._make_widget(NI6423)
        widget.monitor_mode = "counter"
        widget.active_monitor_channel = "counter0"
        widget.timer.start()

        self.assertTrue(widget.stop_scan())
        self.assertTrue(widget.stop_scan())
        self.assertTrue(widget.force_stop())
        self.assertFalse(widget.start_counter_monitor())
        self.assertTrue(widget.start_scan())

        self.assertEqual(widget.monitor_mode, "counter")
        self.assertEqual(widget.active_monitor_channel, "counter0")
        self.assertTrue(widget.timer.isActive())

        widget.stop_monitor()
        self.assertTrue(widget.stop_scan())
        self.assertTrue(widget.start_scan())
        self.assertIsNone(widget.monitor_mode)
        self.assertIsNone(widget.active_monitor_channel)
        self.assertFalse(widget.timer.isActive())

    def test_monitor_callbacks_do_not_submit_jobs_during_scan_ownership(self):
        cases = (
            (NIDAQ, "monitor"),
            (HP34401A, "_monitor"),
            (SR830, "monitor"),
            (SR860, "monitor"),
        )
        for widget_type, monitor_name in cases:
            with self.subTest(widget=widget_type.__name__):
                widget = self._make_widget(widget_type)
                widget._scan_active = True
                widget.logic.running = False
                getattr(widget, monitor_name)()
                self.assertEqual(widget.logic.start_calls, 0)

    def test_quiesce_timeout_is_returned_as_preparation_failure(self):
        widget = self._make_widget(NIDAQ)
        widget.timer.start()
        widget.logic.prepare_scan = lambda _timeout_ms: False

        self.assertFalse(widget.stop_scan())
        self.assertFalse(widget.timer.isActive())

    def test_nidaq_restores_selected_monitor_method(self):
        widget = self._make_widget(NIDAQ)
        widget.inputMethod_comboBox.setCurrentText("Sample Counter")
        widget.timer.start()

        self.assertTrue(widget.stop_scan())
        widget.inputMethod_comboBox.setCurrentText("AI0")
        self.assertTrue(widget.start_scan())

        self.assertEqual(widget.inputMethod_comboBox.currentText(), "Sample Counter")
        self.assertTrue(widget.timer.isActive())

    def test_tlpm_indefinite_monitor_intent_is_restored_exactly(self):
        widget = self._make_widget(TLPM)
        widget._monitor_requested = True
        widget.logic.running = True
        widget.logic.do_read_indefinitely = True
        widget.logic.freq = 17.0

        self.assertTrue(widget.stop_scan())
        widget.freq_doubleSpinBox.setValue(3.0)
        self.assertTrue(widget.force_stop())
        self.assertFalse(widget._start_logic_job("do_read_power"))
        self.assertTrue(widget.start_scan())
        self.assertTrue(widget._monitor_requested)
        self.assertTrue(widget.logic.running)
        self.assertEqual(widget.logic.freq, 17.0)

        widget.logic.running = False
        widget._monitor_requested = False
        self.assertTrue(widget.stop_scan())
        self.assertTrue(widget.start_scan())
        self.assertFalse(widget._monitor_requested)

    def test_owner_thread_handles_timer_while_worker_waits_off_gui(self):
        widget = self._make_widget(NIDAQ)
        timer = _TimerProbe(active=True)
        widget.timer = timer
        result = []

        worker = threading.Thread(target=lambda: result.append(widget.stop_scan()))
        worker.start()
        deadline = time.monotonic() + 2.0
        while worker.is_alive() and time.monotonic() < deadline:
            self.app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 20)
            time.sleep(0.002)
        worker.join(timeout=0.1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [True])
        self.assertEqual(timer.stop_threads, [widget.thread()])
        self.assertNotEqual(widget.logic.prepare_calls[0][1], widget.thread())


if __name__ == "__main__":
    unittest.main()
