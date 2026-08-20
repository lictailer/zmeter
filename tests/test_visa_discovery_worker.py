from __future__ import annotations

import os
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtTest, QtWidgets

from core.shared_runtime.visa import VisaRuntime
from core.shared_runtime.visa_qt import (
    ADDRESS_HORIZONTAL_PADDING,
    ADDRESS_MINIMUM_WIDTH,
    VisaDiscoveryWorker,
    VisaResourceRefresh,
)


class FakeManager:
    def __init__(self):
        self.list_calls = 0
        self.close_calls = 0

    def list_resources(self, _query="?*::INSTR"):
        self.list_calls += 1
        return ("GPIB0::1::INSTR",)

    def close(self):
        self.close_calls += 1


class VisaDiscoveryWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_discovery_occurs_only_when_worker_runs_and_emits_signals(self):
        manager = FakeManager()
        runtime = VisaRuntime(manager_factory=lambda: manager)
        worker = VisaDiscoveryWorker(runtime)
        resources = []
        errors = []
        finished = []
        worker.resources.connect(resources.append)
        worker.error.connect(errors.append)
        worker.finished.connect(lambda: finished.append(True))
        self.assertEqual(manager.list_calls, 0)
        worker.run()
        self.assertEqual(resources, [("GPIB0::1::INSTR",)])
        self.assertEqual(errors, [])
        self.assertEqual(finished, [True])
        self.assertEqual(manager.list_calls, 1)


class FakeDiscoveryRuntime:
    def __init__(self, resources=(), error: Exception | None = None):
        self.resources = tuple(resources)
        self.error = error
        self.list_calls = 0
        self.open_calls = 0

    def list_resources(self, _query="?*::INSTR"):
        self.list_calls += 1
        if self.error is not None:
            raise self.error
        return self.resources

    def open_resource(self, *_args, **_kwargs):
        self.open_calls += 1
        raise AssertionError("VISA refresh must not open a resource")


class VisaResourceRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _make_refresh(self, runtime, *, timeout_ms=10_000):
        parent = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(parent)
        combo = QtWidgets.QComboBox(parent)
        layout.addWidget(combo)
        refresh = VisaResourceRefresh(
            runtime,
            combo,
            parent,
            timeout_ms=timeout_ms,
        )
        self.addCleanup(parent.close)
        return combo, refresh

    def _wait_until(self, predicate, timeout_ms=2000):
        deadline = time.monotonic() + timeout_ms / 1000
        while not predicate() and time.monotonic() < deadline:
            QtWidgets.QApplication.processEvents()
            QtTest.QTest.qWait(5)
        self.assertTrue(predicate(), "timed out waiting for Qt worker")

    def test_initial_refresh_is_deferred_and_long_addresses_are_visible(self):
        address = "USB0::0x1234::0x5678::SERIAL-NUMBER-WITH-LONG-SUFFIX::INSTR"
        runtime = FakeDiscoveryRuntime((address,))
        combo, refresh = self._make_refresh(runtime)

        self.assertEqual(runtime.list_calls, 0)
        self._wait_until(
            lambda: runtime.list_calls == 1 and not refresh.controller.busy
        )

        expected_width = (
            combo.fontMetrics().horizontalAdvance(address)
            + ADDRESS_HORIZONTAL_PADDING
        )
        self.assertEqual(combo.currentText(), address)
        self.assertGreaterEqual(combo.minimumWidth(), ADDRESS_MINIMUM_WIDTH)
        self.assertGreaterEqual(combo.minimumWidth(), expected_width)
        self.assertGreaterEqual(combo.view().minimumWidth(), expected_width)
        self.assertEqual(runtime.open_calls, 0)

        refresh.button.click()
        self._wait_until(
            lambda: runtime.list_calls == 2 and not refresh.controller.busy
        )
        self.assertEqual(runtime.open_calls, 0)

    def test_initial_refresh_error_leaves_manual_refresh_enabled(self):
        runtime = FakeDiscoveryRuntime(error=RuntimeError("backend unavailable"))
        _combo, refresh = self._make_refresh(runtime)

        self._wait_until(
            lambda: (
                runtime.list_calls == 1
                and not refresh.controller.busy
                and "backend unavailable" in refresh.button.toolTip()
                and refresh.button.isEnabled()
            )
        )

        self.assertTrue(refresh.button.isEnabled())
        self.assertIn("backend unavailable", refresh.button.toolTip())
        self.assertEqual(runtime.open_calls, 0)

    def test_timeout_ignores_late_result_and_retains_worker_until_finished(self):
        class BlockingRuntime(FakeDiscoveryRuntime):
            def __init__(self):
                super().__init__(("GPIB0::LATE::INSTR",))
                self.entered = threading.Event()
                self.release = threading.Event()

            def list_resources(self, _query="?*::INSTR"):
                self.list_calls += 1
                self.entered.set()
                if not self.release.wait(2):
                    raise TimeoutError("test did not release VISA discovery")
                return self.resources

        runtime = BlockingRuntime()
        combo, refresh = self._make_refresh(runtime, timeout_ms=20)
        controller = refresh.controller

        self._wait_until(runtime.entered.is_set)
        self._wait_until(lambda: "timed out" in refresh.button.toolTip())
        self.assertTrue(controller.busy)
        self.assertFalse(refresh.button.isEnabled())
        self.assertFalse(controller.refresh())

        refresh._owner.close()
        QtWidgets.QApplication.processEvents()
        self.assertTrue(controller.busy)

        runtime.release.set()
        self._wait_until(lambda: not controller.busy)
        self.assertEqual(combo.count(), 0)
        self.assertTrue(refresh.button.isEnabled())


if __name__ == "__main__":
    unittest.main()
