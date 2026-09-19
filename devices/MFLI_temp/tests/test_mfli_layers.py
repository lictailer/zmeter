"""Strict fake-API and offscreen GUI tests. Vendor imports are forbidden."""
import builtins
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import inspect
import io
import math
import os
from pathlib import Path
import runpy
import threading
import time
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6 import QtCore, QtWidgets
from devices.mfli.MFLI_hardware import (
    MFLIHardware, DemodSample, MonitorBatch, SampleError, TransportError,
)
from devices.mfli.MFLI_logic import MFLILogic
from devices.mfli.MFLI_main import MFLI, LivePlot


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.threads = set()
        self.closed = 0
        self.fail = None
        self.kind = "MFLI"
        self.attached = "DEV12345"
        self.metadata = '{"DEV12345": {"INTERFACE": "PCIe"}}'
        self.stale = False
        self.missing_y = False
        self.xy = (3., 4.)
        self.samples = {i: 2**60 for i in range(4)}
        self.delay_started = threading.Event()
        self.release = threading.Event()
        self.delay_write = False
        self.settings = {"sigouts/0/offset": 0., "sigouts/0/range": 1.}
        self.allowed_writes = {"sigouts/0/offset"}
        for i in range(4):
            self.settings.update({
                f"sigouts/0/amplitudes/{i}": .01,
                f"demods/{i}/phaseshift": 0.,
                f"demods/{i}/oscselect": i,
                f"demods/{i}/freq": 1000. * (i + 1),
                f"demods/{i}/enable": 1,
                f"demods/{i}/rate": 100.,
                f"demods/{i}/trigger": 0,
                f"demods/{i}/adcselect": 0,
            })
            self.allowed_writes.update({f"sigouts/0/amplitudes/{i}", f"demods/{i}/phaseshift"})

    def record(self, method, *args):
        self.calls.append((method, *args))
        self.threads.add(threading.get_ident())
        if self.fail == method or (args and self.fail == args[0]):
            raise RuntimeError("Injected transport failure")

    def factory(self, host, port, level, **kwargs):
        self.record("factory", host, port, level, kwargs)
        return self

    def version(self):
        self.record("version")
        return "26.7.1"

    def getString(self, path):
        self.record("getString", path)
        return {"/zi/devices/connected": self.attached, "/zi/devices": self.metadata,
                "/zi/about/version": "26.4.1",
                "/dev12345/features/devtype": self.kind,
                "/dev12345/features/serial": "DEV12345",
                "/dev12345/features/options": "MF-MD"}[path]

    def connectDevice(self, device, interface):
        self.record("connectDevice", device, interface)

    def getDouble(self, path):
        self.record("getDouble", path)
        return self.settings[path.removeprefix("/dev12345/")]

    def getInt(self, path):
        self.record("getInt", path)
        return self.settings[path.removeprefix("/dev12345/")]

    def syncSetDouble(self, path, value):
        node = path.removeprefix("/dev12345/")
        if node not in self.allowed_writes:
            raise AssertionError(f"Out-of-scope write: {node}")
        self.record("syncSetDouble", path, value)
        if self.delay_write:
            self.delay_started.set()
            if not self.release.wait(3):
                raise RuntimeError("Test did not release blocked fake write")
        actual = round(value, 6)
        self.settings[node] = actual
        return actual

    def getSample(self, path):
        self.record("getSample", path)
        i = int(path.split("/")[3])
        if not self.stale:
            self.samples[i] += 1
        result = {"timestamp": [self.samples[i]], "x": [self.xy[0]], "y": [self.xy[1]],
                  "frequency": [1000 * (i + 1)], "phase": [999]}
        if self.missing_y:
            result.pop("y")
        return result

    def disconnect(self):
        self.record("disconnect")
        self.closed += 1


class OfflineCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        original = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name == "zhinst" or name.startswith("zhinst."):
                raise AssertionError("Real vendor import forbidden in offline tests")
            return original(name, *args, **kwargs)

        self.guard = patch("builtins.__import__", side_effect=guarded)
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        self.api = FakeAPI()
        self.hardware = MFLIHardware(self.api.factory, read_timeout=.5)

    def pump_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.002)
        self.app.processEvents()
        self.assertTrue(predicate(), "Timed out waiting for fake/offscreen operation")

    def connect_hardware(self):
        return self.hardware.connect("DEV12345", "example.invalid", 8004)

    def make_logic(self):
        logic = MFLILogic(self.hardware)

        def stop():
            self.api.fail = None
            self.api.release.set()
            if logic._worker.isRunning():
                try:
                    logic.request("shutdown")
                except RuntimeError:
                    pass
                self.pump_until(lambda: not logic._worker.isRunning())
        self.addCleanup(stop)
        return logic

    def connect_logic(self, logic):
        future = logic.request("connect", "DEV12345", "example.invalid", 8004)
        self.pump_until(lambda: future.done() and logic.connected)
        return future.result()


class HardwareTests(OfflineCase):
    def test_connection_reads_only_and_allows_version_difference(self):
        identity, settings = self.connect_hardware()
        self.assertEqual(identity["server"], "26.4.1")
        self.assertEqual(len(settings.tones), 4)
        self.assertEqual(self.api.calls[0][-1], {"allow_version_mismatch": True})
        self.assertFalse(any(c[0] == "syncSetDouble" for c in self.api.calls))
        self.hardware.disconnect()
        self.hardware.disconnect()
        self.assertEqual(self.api.closed, 1)

    def test_uses_reported_pcie_and_cleans_partial_connection(self):
        self.api.attached = ""
        self.api.kind = "OTHER"
        with self.assertRaisesRegex(ValueError, "Expected MFLI"):
            self.connect_hardware()
        self.assertIn(("connectDevice", "dev12345", "PCIe"), self.api.calls)
        self.assertEqual(self.api.closed, 1)

    def test_missing_fourth_channel_fails_and_closes(self):
        del self.api.settings["demods/3/phaseshift"]
        with self.assertRaises(TransportError):
            self.connect_hardware()
        self.assertEqual(self.api.closed, 1)

    def test_invalid_connection_makes_no_api_calls(self):
        with self.assertRaises(ValueError):
            self.hardware.connect("", "example.invalid", 8004)
        self.assertEqual(self.api.calls, [])

    def test_exact_write_mapping_and_acknowledged_value(self):
        self.connect_hardware()
        for channel in range(1, 5):
            self.assertEqual(self.hardware.write_amplitude(channel, .012345678), .012346)
            self.hardware.write_phase(channel, channel * 10)
        self.hardware.write_offset(.02)
        writes = [c[1].removeprefix("/dev12345/") for c in self.api.calls if c[0] == "syncSetDouble"]
        self.assertEqual(set(writes), self.api.allowed_writes)
        self.assertEqual(len(writes), 9)

    def test_invalid_values_and_combined_range_do_not_write(self):
        self.connect_hardware()
        operations = [lambda: self.hardware.write_phase(1, 181),
                      lambda: self.hardware.write_amplitude(0, .01),
                      lambda: self.hardware.write_amplitude(True, .01),
                      lambda: self.hardware.write_offset(math.nan),
                      lambda: self.hardware.write_amplitude(1, 1.),
                      lambda: self.hardware.write_offset(.99)]
        for operation in operations:
            with self.assertRaises(ValueError):
                operation()
        self.assertFalse(any(c[0] == "syncSetDouble" for c in self.api.calls))

    def test_range_check_reads_external_labone_changes(self):
        self.connect_hardware()
        self.api.settings["sigouts/0/offset"] = .96
        with self.assertRaisesRegex(ValueError, "Combined"):
            self.hardware.write_amplitude(1, .02)

    def test_monitor_derives_values_once_per_channel_and_units(self):
        self.connect_hardware()
        self.api.settings["demods/1/adcselect"] = 1
        batch = self.hardware.monitor()
        self.assertEqual(len(batch.samples), 4)
        self.assertEqual(batch.samples[1].R, 5)
        self.assertAlmostEqual(batch.samples[1].theta, 53.13010235415598)
        self.assertEqual(batch.samples[2].unit, "A")
        self.assertEqual(batch.samples[1].timestamp, 2**60 + 1)
        self.assertEqual(sum(c[0] == "getSample" for c in self.api.calls), 4)

    def test_disabled_invalid_rate_and_trigger_are_isolated(self):
        self.connect_hardware()
        self.api.settings["demods/0/enable"] = 0
        self.api.settings["demods/1/rate"] = 0
        self.api.settings["demods/2/trigger"] = 1
        batch = self.hardware.monitor()
        self.assertEqual(set(batch.samples), {4})
        self.assertIn("disabled", batch.problems[1])
        self.assertIn("rate", batch.problems[2])
        self.assertIn("Continuous", batch.problems[3])

    def test_duplicate_then_stale_and_recovery(self):
        self.connect_hardware()
        self.hardware.monitor()
        self.api.stale = True
        self.assertEqual(self.hardware.monitor().samples, {})
        for channel, (stamp, _) in self.hardware._last_seen.items():
            self.hardware._last_seen[channel] = stamp, time.monotonic() - 1
        self.assertEqual(len(self.hardware.monitor().problems), 4)
        self.api.stale = False
        self.assertEqual(len(self.hardware.monitor().samples), 4)

    def test_sample_failure_and_zero_phase(self):
        self.connect_hardware()
        self.api.missing_y = True
        self.assertEqual(len(self.hardware.monitor().problems), 4)
        self.api.missing_y = False
        self.api.xy = (0., 0.)
        self.assertTrue(math.isnan(self.hardware.monitor().samples[1].theta))

    def test_fresh_read_timeout_and_cancel(self):
        self.connect_hardware()
        self.assertEqual(self.hardware.read_fresh(1).timestamp, 2**60 + 2)
        self.api.stale = True
        self.hardware.read_timeout = .03
        with self.assertRaises(TimeoutError):
            self.hardware.read_fresh(1)
        self.hardware.cancel.set()
        with self.assertRaises(InterruptedError):
            self.hardware.read_fresh(1)

    def test_cleanup_failure_retains_handle_for_retry(self):
        self.connect_hardware()
        self.api.fail = "disconnect"
        with self.assertRaises(TransportError):
            self.hardware.disconnect()
        self.assertTrue(self.hardware.connected)
        self.api.fail = None
        self.hardware.disconnect()
        self.assertFalse(self.hardware.connected)

    def test_factory_failure_and_failed_write_context(self):
        self.api.fail = "factory"
        with self.assertRaisesRegex(RuntimeError, "Injected"):
            self.connect_hardware()
        self.assertFalse(self.hardware.connected)
        self.api.fail = None
        self.connect_hardware()
        self.api.fail = "syncSetDouble"
        with self.assertRaisesRegex(TransportError, "may have applied"):
            self.hardware.write_offset(.01)

    def test_invalid_acknowledgement_is_session_fault(self):
        self.connect_hardware()
        with patch.object(self.api, "syncSetDouble", return_value=None):
            with self.assertRaisesRegex(TransportError, "invalid acknowledgement"):
                self.hardware.write_phase(1, 20)


class LogicTests(OfflineCase):
    def test_exact_scalar_signatures(self):
        getters = {name: fn for name, fn in inspect.getmembers(MFLILogic, inspect.isfunction) if name.startswith("get_")}
        setters = {name: fn for name, fn in inspect.getmembers(MFLILogic, inspect.isfunction) if name.startswith("set_")}
        self.assertEqual(set(getters), {f"get_DEMOD{i}_{q}" for i in range(1, 5) for q in ("X", "Y", "R", "theta")})
        self.assertEqual(set(setters), {f"set_OSC{i}_{q}" for i in range(1, 5) for q in ("amplitude", "phase")} | {"set_output_DCoffset"})
        self.assertTrue(all(len(inspect.signature(fn).parameters) == 1 for fn in getters.values()))
        self.assertTrue(all(len(inspect.signature(fn).parameters) == 2 for fn in setters.values()))

    def test_scan_calls_are_serialized_on_worker_and_ui_call_refused(self):
        logic = self.make_logic()
        self.connect_logic(logic)
        with self.assertRaisesRegex(RuntimeError, "GUI thread"):
            logic.get_DEMOD1_X()
        with ThreadPoolExecutor(3) as pool:
            reads = [pool.submit(logic.get_DEMOD1_X), pool.submit(logic.get_DEMOD2_R),
                     pool.submit(logic.set_OSC3_phase, 30)]
            self.assertEqual([r.result(3) for r in reads], [3., 5., 30.])
        self.assertEqual(len(self.api.threads), 1)
        self.assertNotIn(threading.get_ident(), self.api.threads)

    def test_monitor_skips_busy_worker_and_disconnect_cancels_pending(self):
        logic = self.make_logic()
        self.connect_logic(logic)
        self.api.delay_write = True
        first = logic.request("phase", 1, 12)
        self.pump_until(self.api.delay_started.is_set)
        queued = logic.request("phase", 2, 20)
        self.assertTrue(logic.request("monitor").cancelled())
        disconnected = logic.request("disconnect")
        self.assertTrue(queued.cancelled())
        self.api.release.set()
        self.pump_until(disconnected.done)
        self.assertEqual(first.result(), 12)
        self.assertIsNone(disconnected.result())
        self.assertEqual(sum(c[0] == "syncSetDouble" for c in self.api.calls), 1)

    def test_transport_failure_stops_session_and_explicit_reconnect_works(self):
        logic = self.make_logic()
        self.connect_logic(logic)
        self.api.fail = "getSample"
        future = logic.request("monitor")
        self.pump_until(lambda: future.done() and not logic.connected)
        with self.assertRaises(TransportError):
            future.result()
        self.assertEqual(self.api.closed, 1)
        self.api.fail = None
        self.connect_logic(logic)

    def test_log_deduplicates_channel_errors_and_reports_recovery(self):
        logic = self.make_logic()
        messages = []
        logic.log.connect(lambda level, message: messages.append((level, message)))
        self.connect_logic(logic)
        self.api.settings["demods/1/enable"] = 0
        for _ in range(2):
            future = logic.request("monitor")
            self.pump_until(future.done)
        self.assertEqual(sum("disabled" in message for _, message in messages), 1)
        self.api.settings["demods/1/enable"] = 1
        future = logic.request("monitor")
        self.pump_until(future.done)
        self.assertTrue(any("resumed" in message for _, message in messages))

    def test_shutdown_interrupts_waiting_scan_read(self):
        logic = self.make_logic()
        self.connect_logic(logic)
        self.hardware.read_timeout = 10
        self.api.stale = True
        read = logic.request("read", 1)
        self.pump_until(lambda: any(c[0] == "getSample" for c in self.api.calls))
        closed = logic.request("shutdown")
        self.pump_until(lambda: not logic._worker.isRunning())
        with self.assertRaises(InterruptedError):
            read.result()
        self.assertIsNone(closed.result())

    def test_scan_read_errors_propagate_to_caller(self):
        logic = self.make_logic()
        self.connect_logic(logic)
        self.api.settings["demods/2/enable"] = 0
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(logic.get_DEMOD3_X)
            with self.assertRaisesRegex(SampleError, "disabled"):
                future.result(3)


class GuiTests(OfflineCase):
    def make_window(self):
        logic = self.make_logic()
        window = MFLI(logic, standalone=True)
        window.serial.setText("DEV12345")
        window.host.setText("example.invalid")
        window.show()
        self.addCleanup(window.close)
        return window

    def connect_window(self, window):
        window.connect_button.click()
        self.pump_until(lambda: window.logic.connected and not window._pending)

    def test_window_and_direct_file_import_do_not_contact_hardware(self):
        window = self.make_window()
        self.assertEqual(self.api.calls, [])
        self.assertFalse(window.start_button.isEnabled())
        # Direct-file imports use the same local imports as an IDE Run action.
        import sys
        devices = Path(__file__).resolve().parents[2]
        for name in ("MFLI_temp", "mfli"):
            folder = str(devices / name)
            with patch.object(sys, "path", [folder, *sys.path]):
                runpy.run_path(str(Path(folder) / "MFLI_main.py"), run_name="offline_import")
        self.assertEqual(self.api.calls, [])

    def test_edit_refresh_and_plot_selection_do_not_write(self):
        window = self.make_window()
        self.connect_window(window)
        window.amplitudes[0].setValue(.02)
        window.phases[1].setValue(20)
        window.offset.setValue(.03)
        window.refresh_button.click()
        self.pump_until(lambda: not window._pending)
        window.plots[0].demod.setCurrentIndex(3)
        window.plots[0].quantity.setCurrentText("R")
        self.assertFalse(any(c[0] == "syncSetDouble" for c in self.api.calls))

    def test_set_button_readback_and_monitor_selection(self):
        window = self.make_window()
        self.connect_window(window)
        window.amplitudes[0].setValue(.012345678)
        window.write_buttons[0].click()
        self.pump_until(lambda: not window._pending)
        self.assertEqual(window.amplitude_readbacks[0].text(), "0.012346")
        window.plots[3].demod.setCurrentIndex(3)
        window.start_button.click()
        self.pump_until(lambda: all(plot.values for plot in window.plots))
        window.pause_button.click()
        self.assertEqual(window.plots[0].values[-1], 3)
        self.assertAlmostEqual(window.plots[3].values[-1], 53.13010235415598)
        window.plots[0].quantity.setCurrentText("R")
        self.assertEqual(len(window.plots[0].values), 0)

    def test_plot_and_log_buffers_are_bounded(self):
        window = self.make_window()
        sample = DemodSample(1, 10, 3, 4, 5, 53.13, "V", 1000)
        for i in range(610):
            window.plots[0].update_batch(MonitorBatch({1: sample}, {}), i * .1)
        self.assertEqual(len(window.plots[0].values), 600)
        for i in range(510):
            window._log("INFO", str(i))
        self.assertEqual(window.log_window.document().blockCount(), 500)

    def test_close_during_write_keeps_ui_responsive_and_closes_once(self):
        window = self.make_window()
        self.connect_window(window)
        self.api.delay_write = True
        window.amplitudes[0].setValue(.5)
        window.write_buttons[0].click()
        self.pump_until(self.api.delay_started.is_set)
        ticks = []
        timer = QtCore.QTimer()
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start(1)
        window.close()
        self.pump_until(lambda: len(ticks) >= 3)
        self.assertFalse(window._closed)
        self.assertFalse(window.connect_button.isEnabled())
        self.api.release.set()
        self.pump_until(lambda: window._closed)
        timer.stop()
        self.assertEqual(self.api.closed, 1)

    def test_cleanup_failure_keeps_window_for_retry(self):
        window = self.make_window()
        self.connect_window(window)
        self.api.fail = "disconnect"
        window.close()
        self.pump_until(lambda: not window._closing and not window._pending)
        self.assertFalse(window._closed)
        self.assertTrue(window.logic.cleanup_needed)
        self.assertFalse(window.connect_button.isEnabled())
        self.api.fail = None
        window.close()
        self.pump_until(lambda: window._closed)

    def test_transport_failure_stops_timer(self):
        window = self.make_window()
        self.connect_window(window)
        self.api.fail = "getSample"
        window.start_button.click()
        self.pump_until(lambda: not window.logic.connected)
        self.assertFalse(window.timer.isActive())
        self.assertTrue(window.connect_button.isEnabled())
        self.assertIn("Injected transport failure", window.log_window.toPlainText())

    def test_close_waits_for_pending_disconnect(self):
        window = self.make_window()
        self.connect_window(window)
        self.api.delay_write = True
        window.amplitudes[0].setValue(.5)
        window.write_buttons[0].click()
        self.pump_until(self.api.delay_started.is_set)
        window.disconnect_button.click()
        window.close()
        self.assertTrue(window._close_after_disconnect)
        self.api.release.set()
        self.pump_until(lambda: window._closed)
        self.assertEqual(self.api.closed, 1)


if __name__ == "__main__":
    unittest.main()
