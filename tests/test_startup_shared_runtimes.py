from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core.shared_runtime import RuntimeServices
from start_zmeter import (
    DEFAULT_PROFILE_PATH,
    REPOSITORY_ROOT,
    create_profile_session,
)


class StartupSharedRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_checked_in_mock_profile_constructs_no_vendor_runtime(self):
        services = RuntimeServices()
        self.addCleanup(services.shutdown)
        profile, manager = create_profile_session(services)
        self.addCleanup(manager.teardown_all)
        snapshot = manager.snapshot()

        self.assertEqual(profile.profile, "mock")
        self.assertEqual(profile.source_path, DEFAULT_PROFILE_PATH)
        self.assertEqual(profile.paths.save, REPOSITORY_ROOT / "data")
        self.assertIsNone(profile.paths.backup)
        self.assertEqual(
            tuple(snapshot.equipment),
            ("mock_device_1", "mock_device_2"),
        )
        self.assertEqual(
            dict(snapshot.setter_filters),
            {"mock_device_1": None, "mock_device_2": None},
        )
        self.assertEqual(
            dict(snapshot.getter_filters),
            {"mock_device_1": None, "mock_device_2": None},
        )
        self.assertTrue(
            all(
                not record.instance.logic.hardware.connected
                for record in snapshot.records
            )
        )
        self.assertFalse(services.visa.diagnostics["manager_created"])
        self.assertFalse(services.kinesis.diagnostics["validated"])

    def test_launcher_import_does_not_import_any_device_or_vendor_module(self):
        script = r"""
import sys
import start_zmeter

watched = (
    "mockDevice", "devices", "pyvisa", "clr", "nidaqmx", "PyDAQmx",
    "BBD30X", "opticool", "sr830", "sr860", "tlpm",
)
loaded = sorted(
    name for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in watched)
)
if loaded:
    raise SystemExit("unexpected launcher import: " + ", ".join(loaded))
print("launcher import remained device/vendor free")
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("device/vendor free", result.stdout)

    def test_qt_options_are_consumed_before_strict_profile_parsing(self):
        script = r"""
from pathlib import Path
from PyQt6 import QtWidgets
from start_zmeter import _parse_launch_options

app = QtWidgets.QApplication([
    "zmeter", "-platform", "offscreen",
    "--profile", "config/profiles/session.local.json",
])
options = _parse_launch_options(app.arguments()[1:])
assert options.profile == Path("config/profiles/session.local.json")
print("Qt options and strict launcher options separated")
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("strict launcher options separated", result.stdout)

    def test_relative_profile_path_is_resolved_from_repository_not_current_directory(self):
        services = RuntimeServices()
        self.addCleanup(services.shutdown)
        original_directory = Path.cwd()

        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                profile, manager = create_profile_session(
                    services,
                    Path("config/profiles/mock.json"),
                )
            finally:
                os.chdir(original_directory)

        self.addCleanup(manager.teardown_all)
        self.assertEqual(profile.source_path, DEFAULT_PROFILE_PATH)
        self.assertEqual(profile.paths.save, REPOSITORY_ROOT / "data")

    def test_disabled_profile_entry_never_calls_its_registered_factory(self):
        payload = {
            "schema_version": 1,
            "profile": "disabled_mock",
            "paths": {"save": "./data", "backup": None},
            "devices": [
                {
                    "id": "disabled_mock",
                    "driver": "mock_device",
                    "enabled": False,
                    "connect_on_start": False,
                    "connection": {"address": "MOCK::INSTR"},
                    "scan_channels": {"set": None, "get": None},
                }
            ],
        }
        services = RuntimeServices()
        self.addCleanup(services.shutdown)

        with tempfile.TemporaryDirectory() as directory:
            profile_path = Path(directory) / "disabled.json"
            profile_path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch(
                "core.device_management.registry._create_mock_device",
                side_effect=AssertionError("disabled factory must stay lazy"),
            ) as factory:
                profile, manager = create_profile_session(services, profile_path)

        self.addCleanup(manager.teardown_all)
        self.assertFalse(profile.devices[0].enabled)
        self.assertEqual(manager.snapshot().records, ())
        factory.assert_not_called()
        self.assertFalse(services.visa.diagnostics["manager_created"])
        self.assertFalse(services.kinesis.diagnostics["validated"])


if __name__ == "__main__":
    unittest.main()
