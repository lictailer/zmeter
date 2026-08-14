from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core.shared_runtime import RuntimeServices
from start_zmeter import create_equipment


class StartupSharedRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_checked_in_mock_profile_constructs_no_vendor_runtime(self):
        services = RuntimeServices()
        equips, setters, getters = create_equipment(services)
        self.addCleanup(lambda: [equipment.close() for equipment in equips.values()])
        self.assertEqual(set(equips), {"mock_device_1", "mock_device_2"})
        self.assertFalse(services.visa.diagnostics["manager_created"])
        self.assertFalse(services.kinesis.diagnostics["validated"])
        self.assertIn("ni6423", setters)
        self.assertIn("ni6423", getters)
        result = services.shutdown()
        self.assertFalse(result["visa"]["manager_created"])
        self.assertFalse(result["kinesis"]["validated"])


if __name__ == "__main__":
    unittest.main()
