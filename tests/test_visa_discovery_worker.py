from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore

from core.shared_runtime.visa import VisaRuntime
from core.shared_runtime.visa_qt import VisaDiscoveryWorker


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


if __name__ == "__main__":
    unittest.main()
