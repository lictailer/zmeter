from __future__ import annotations

import inspect
import os
import sys
import types
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets


def _install_nidaqmx_import_stub():
    """Import NI6423 without loading a driver or constructing a real task."""

    nidaqmx = types.ModuleType("nidaqmx")

    class ForbiddenTask:
        def __init__(self, *args, **kwargs):
            raise AssertionError("NI task construction is forbidden in unit tests")

    nidaqmx.Task = ForbiddenTask
    constants = types.ModuleType("nidaqmx.constants")
    for name in (
        "AcquisitionType",
        "CountDirection",
        "Edge",
        "Level",
        "TaskMode",
        "TriggerType",
    ):
        setattr(constants, name, SimpleNamespace())
    system = types.ModuleType("nidaqmx.system")
    system.System = type("ForbiddenSystem", (), {})
    sys.modules["nidaqmx"] = nidaqmx
    sys.modules["nidaqmx.constants"] = constants
    sys.modules["nidaqmx.system"] = system


_install_nidaqmx_import_stub()

from core.device_management.models import ChannelFilters, DeviceConfig
from core.device_management.registry import build_default_registry
from devices.ni6423.ni6423_logic import NI6423Logic


class NI6423RegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_registry_constructs_disconnected_widget_without_ni_task(self):
        registry = build_default_registry()
        config = DeviceConfig(
            id="ni6423_test",
            driver="ni6423",
            enabled=True,
            connect_on_start=False,
            connection={"device_name": "DevTest"},
            scan_channels=ChannelFilters(setters=None, getters=None),
        )

        adapter = registry.create(config, SimpleNamespace())
        self.addCleanup(adapter.close)
        self.addCleanup(adapter.terminate)

        self.assertFalse(adapter.connected())
        self.assertFalse(adapter.instance.logic.is_initialized)
        self.assertIsNone(adapter.instance.logic.daq)
        self.assertEqual(adapter.instance.dev_name_lineEdit.text(), "DevTest")

    def test_exact_dynamic_scan_channels_are_preserved(self):
        logic = NI6423Logic()
        setters = {
            name[4:]
            for name in dir(logic)
            if name.startswith("set_")
            and callable(getattr(logic, name))
            and len(inspect.signature(getattr(logic, name)).parameters) == 1
        }
        getters = {
            name[4:]
            for name in dir(logic)
            if name.startswith("get_")
            and callable(getattr(logic, name))
            and len(inspect.signature(getattr(logic, name)).parameters) == 0
        }

        self.assertEqual(setters, {f"AO{i}" for i in range(4)})
        self.assertEqual(
            getters,
            {f"AI{i}" for i in range(32)}
            | {f"AO{i}" for i in range(4)}
            | {"counter0"},
        )


if __name__ == "__main__":
    unittest.main()
