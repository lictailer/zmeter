from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock

from core.device_management.config import ProfileValidationError, load_profile
from core.device_management.models import ConnectionFieldSpec, DriverConfigSpec


class DeviceProfileConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "config" / "profiles").mkdir(parents=True)
        self.driver_specs = {
            "mock_device": DriverConfigSpec(
                driver_id="mock_device",
                connection_fields={
                    "address": ConnectionFieldSpec((str,)),
                    "metadata": ConnectionFieldSpec((list,)),
                },
            ),
            "unavailable_driver": DriverConfigSpec(
                driver_id="unavailable_driver",
                connection_fields={},
                available=False,
                unavailable_reason="optional SDK is missing",
            ),
        }

    def valid_payload(self):
        return {
            "schema_version": 1,
            "profile": "mock",
            "paths": {"save": "./data", "backup": None},
            "devices": [
                {
                    "id": "mock_device_1",
                    "driver": "mock_device",
                    "enabled": True,
                    "connect_on_start": False,
                    "connection": {"address": "MOCK::TEST"},
                    "scan_channels": {"set": None, "get": None},
                }
            ],
        }

    def write_profile(self, payload, name="test.json"):
        path = self.root / "config" / "profiles" / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def load(self, path):
        return load_profile(
            path,
            driver_specs=self.driver_specs,
            repository_root=self.root,
        )

    def test_valid_profile_is_immutable_and_paths_are_repository_relative(self):
        path = self.write_profile(self.valid_payload())

        profile = self.load(path)

        self.assertEqual(profile.profile, "mock")
        self.assertEqual(profile.paths.save, (self.root / "data").resolve())
        self.assertIsNone(profile.paths.backup)
        self.assertEqual(tuple(device.id for device in profile.devices), ("mock_device_1",))
        self.assertEqual(profile.devices[0].connection["address"], "MOCK::TEST")
        with self.assertRaises(TypeError):
            profile.devices[0].connection["address"] = "changed"
        with self.assertRaises(FrozenInstanceError):
            profile.profile = "changed"

        payload = self.valid_payload()
        payload["devices"][0]["connection"]["metadata"] = [
            {"nested": [1, 2]}
        ]
        nested_profile = self.load(self.write_profile(payload, "nested.json"))
        metadata = nested_profile.devices[0].connection["metadata"]
        self.assertIsInstance(metadata, tuple)
        with self.assertRaises(TypeError):
            metadata[0]["nested"] = (3,)

    def test_relative_profile_filename_does_not_depend_on_current_directory(self):
        self.write_profile(self.valid_payload(), "relative.json")
        unrelated = self.root / "unrelated"
        unrelated.mkdir()

        with mock.patch("os.getcwd", return_value=str(unrelated)):
            profile = self.load(Path("config") / "profiles" / "relative.json")

        self.assertEqual(profile.source_path, self.root / "config" / "profiles" / "relative.json")

    def test_loading_in_fresh_process_does_not_import_device_or_vendor_modules(self):
        path = self.write_profile(self.valid_payload())
        repository_root = Path(__file__).resolve().parents[1]
        script = """
import sys
from pathlib import Path
from core.device_management.config import load_profile
from core.device_management.models import ConnectionFieldSpec, DriverConfigSpec

specs = {
    "mock_device": DriverConfigSpec(
        driver_id="mock_device",
        connection_fields={"address": ConnectionFieldSpec((str,))},
    )
}
load_profile(Path(sys.argv[1]), driver_specs=specs, repository_root=Path(sys.argv[2]))
watched = ("mockDevice", "devices", "pyvisa", "clr")
loaded = sorted(
    name for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in watched)
)
if loaded:
    raise SystemExit("unexpected device/vendor imports: " + ", ".join(loaded))
print("profile load remained device/vendor-import free")
"""

        result = subprocess.run(
            [sys.executable, "-B", "-c", script, str(path), str(self.root)],
            cwd=repository_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("device/vendor-import free", result.stdout)

    def test_duplicate_json_keys_are_rejected(self):
        path = self.root / "config" / "profiles" / "duplicate-key.json"
        path.write_text(
            '{"schema_version": 1, "schema_version": 2, '
            '"profile": "mock", "paths": {"save": "./data", '
            '"backup": null}, "devices": []}',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ProfileValidationError, "duplicate JSON field"):
            self.load(path)

    def test_schema_version_errors_are_actionable(self):
        for value, pattern in ((None, "must be an integer"), (True, "must be an integer"), (2, "unsupported")):
            with self.subTest(value=value):
                payload = self.valid_payload()
                if value is None:
                    payload.pop("schema_version")
                else:
                    payload["schema_version"] = value
                with self.assertRaisesRegex(ProfileValidationError, pattern):
                    self.load(self.write_profile(payload))

    def test_invalid_and_duplicate_device_ids_are_collected(self):
        payload = self.valid_payload()
        payload["devices"] = [
            {**payload["devices"][0], "id": ""},
            {**payload["devices"][0], "id": "bad label"},
            {**payload["devices"][0], "id": "same_id"},
            {**payload["devices"][0], "id": "same_id"},
            {**payload["devices"][0], "id": "default"},
        ]

        with self.assertRaises(ProfileValidationError) as raised:
            self.load(self.write_profile(payload))

        message = str(raised.exception)
        self.assertIn("id must be a non-empty string", message)
        self.assertIn("may contain only", message)
        self.assertIn("duplicates", message)
        self.assertIn("is reserved", message)

    def test_duplicate_device_errors_use_original_json_indices(self):
        payload = self.valid_payload()
        device = payload["devices"][0]
        payload["devices"] = ["not-an-object", device, dict(device)]

        with self.assertRaises(ProfileValidationError) as raised:
            self.load(self.write_profile(payload))

        self.assertIn("devices[2].id duplicates devices[1].id", str(raised.exception))

    def test_unknown_driver_is_rejected_even_when_device_is_disabled(self):
        payload = self.valid_payload()
        payload["devices"][0]["driver"] = "missing_driver"
        payload["devices"][0]["enabled"] = False

        with self.assertRaisesRegex(ProfileValidationError, "is not registered"):
            self.load(self.write_profile(payload))

    def test_unavailable_driver_only_blocks_an_enabled_entry(self):
        payload = self.valid_payload()
        device = payload["devices"][0]
        device["driver"] = "unavailable_driver"
        device["connection"] = {}

        with self.assertRaisesRegex(ProfileValidationError, "optional SDK is missing"):
            self.load(self.write_profile(payload))

        device["enabled"] = False
        profile = self.load(self.write_profile(payload))
        self.assertFalse(profile.devices[0].enabled)

    def test_connection_keys_and_types_follow_driver_spec(self):
        payload = self.valid_payload()
        payload["devices"][0]["connection"] = {
            "address": 3,
            "fallback_address": "DO-NOT-USE",
        }

        with self.assertRaises(ProfileValidationError) as raised:
            self.load(self.write_profile(payload))

        message = str(raised.exception)
        self.assertIn("unsupported field 'fallback_address'", message)
        self.assertIn("connection.address must be str", message)

    def test_channel_filter_types_are_validated_but_unknown_names_are_retained(self):
        payload = self.valid_payload()
        filters = payload["devices"][0]["scan_channels"]
        filters["set"] = ["set_channel_A", "future_channel"]
        filters["get"] = ["", 4]

        with self.assertRaises(ProfileValidationError) as raised:
            self.load(self.write_profile(payload))

        self.assertIn("scan_channels.get[0] must be a non-empty string", str(raised.exception))
        self.assertIn("scan_channels.get[1] must be a non-empty string", str(raised.exception))

        filters["get"] = ["unknown_but_valid"]
        profile = self.load(self.write_profile(payload))
        self.assertEqual(
            profile.devices[0].scan_channels.setters,
            ("set_channel_A", "future_channel"),
        )
        self.assertEqual(
            profile.devices[0].scan_channels.getters,
            ("unknown_but_valid",),
        )

    def test_invalid_paths_fail_without_creating_output(self):
        payload = self.valid_payload()
        payload["paths"] = {"save": "\u0000bad", "backup": 42}

        with self.assertRaises(ProfileValidationError) as raised:
            self.load(self.write_profile(payload))

        self.assertIn("paths.save is invalid", str(raised.exception))
        self.assertIn("paths.backup must be", str(raised.exception))
        self.assertFalse((self.root / "data").exists())

    def test_checked_in_mock_profile_is_valid_and_preserves_startup_values(self):
        repository_root = Path(__file__).resolve().parents[1]
        profile = load_profile(
            repository_root / "config" / "profiles" / "mock.json",
            driver_specs={"mock_device": self.driver_specs["mock_device"]},
            repository_root=repository_root,
        )

        self.assertEqual(profile.profile, "mock")
        self.assertEqual([device.id for device in profile.devices], ["mock_device_1", "mock_device_2"])
        self.assertTrue(all(device.enabled for device in profile.devices))
        self.assertTrue(all(not device.connect_on_start for device in profile.devices))
        self.assertEqual(profile.paths.save, repository_root / "data")
        self.assertIsNone(profile.paths.backup)


if __name__ == "__main__":
    unittest.main()
