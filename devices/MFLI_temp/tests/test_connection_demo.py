"""Offline tests: no real vendor API is imported or instantiated."""

import builtins
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "connection_demo.py"


def load_demo():
    spec = importlib.util.spec_from_file_location("mfli_connection_demo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeServer:
    """Only the allowed connection and read operations exist on this fake."""

    def __init__(self):
        self.calls = []
        self.fail_at = None
        self.close_error = None
        self.device_type = "MFLI"
        self.clockbase = 60_000_000.0
        self.serial = "12345"
        self.connected = ""
        self.devices = {"DEV12345": {"INTERFACE": "PCIe", "INTERFACES": "PCIe"}}

    def record(self, operation, *args):
        self.calls.append((operation, *args))
        if operation == self.fail_at:
            raise RuntimeError(f"Simulated {operation} failure")

    def connectDevice(self, device, interface):
        self.record("connectDevice", device, interface)

    def getString(self, path):
        self.record("getString", path)
        return {
            "/zi/devices/connected": self.connected,
            "/zi/devices": json.dumps(self.devices),
            "/dev12345/features/devtype": self.device_type,
            "/dev12345/features/serial": self.serial,
            "/dev12345/features/options": "",
            "/zi/about/version": "26.4.1",
        }[path]

    def getInt(self, path):
        self.record("getInt", path)
        if path != "/zi/about/revision":
            raise AssertionError(path)
        return 123456

    def getDouble(self, path):
        self.record("getDouble", path)
        if path != "/dev12345/clockbase":
            raise AssertionError(path)
        return self.clockbase

    def version(self):
        self.record("version")
        return "26.7.1"

    def disconnect(self):
        self.record("disconnect")
        if self.close_error:
            raise RuntimeError(self.close_error)


class ConnectionDemoTests(unittest.TestCase):
    def setUp(self):
        # This guard catches accidental vendor imports even if the package is installed.
        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "zhinst" or name.startswith("zhinst."):
                raise AssertionError("Offline test attempted to import the real vendor API")
            return real_import(name, *args, **kwargs)

        self.guard = patch("builtins.__import__", side_effect=guarded_import)
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.demo = load_demo()
        # Tests must be independent of the user's editable bench configuration.
        self.demo.DEVICE_ID = ""
        self.demo.SERVER_HOST = ""
        self.demo.SERVER_PORT = 8004
        self.server = FakeServer()
        self.factory = Mock(return_value=self.server)
        self.out = io.StringIO()
        self.err = io.StringIO()

    def run_main(self, args):
        with redirect_stdout(self.out), redirect_stderr(self.err):
            return self.demo.main(args, server_factory=self.factory)

    def test_import_and_help_do_not_load_vendor_or_connect(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.factory.assert_not_called()

    def test_missing_serial_does_not_connect(self):
        self.assertEqual(self.run_main([]), 1)
        self.factory.assert_not_called()
        self.assertIn("Set DEVICE_ID", self.err.getvalue())

    def test_invalid_config_does_not_connect(self):
        for args in (["--device", "*"], ["--device", "dev12345", "--port", "0"],
                     ["--device", "dev12345", "--port", "65536"],
                     ["--device", "dev12345", "--host", "http://instrument/"]):
            with self.subTest(args=args):
                self.assertEqual(self.run_main(args), 1)
        self.factory.assert_not_called()

    def test_success_uses_embedded_interface_and_allows_different_versions(self):
        self.assertEqual(self.run_main(["--device", "DEV12345"]), 0)
        self.factory.assert_called_once_with("mf-dev12345", 8004, 6, allow_version_mismatch=True)
        self.assertIn(("connectDevice", "dev12345", "PCIe"), self.server.calls)
        self.assertEqual(self.server.calls[-1], ("disconnect",))
        self.assertIn("60 MHz", self.out.getvalue())
        self.assertIn("SUCCESS", self.out.getvalue())
        self.assertIn("Python API: 26.7.1 | Data Server: 26.4.1", self.out.getvalue())
        self.assertIn("Options: (none)", self.out.getvalue())
        allowed = {"connectDevice", "getString", "getInt", "getDouble", "version", "disconnect"}
        self.assertTrue(all(call[0] in allowed for call in self.server.calls))

    def test_already_connected_device_is_not_reattached(self):
        self.server.connected = "DEV99999, DEV12345 "
        self.server.fail_at = "connectDevice"
        self.assertEqual(self.run_main(["--device", "dev12345"]), 0)
        self.assertFalse(any(call[0] == "connectDevice" for call in self.server.calls))
        self.assertNotIn(("getString", "/zi/devices"), self.server.calls)

    def test_advertised_interfaces_when_no_active_interface(self):
        for available, expected in (("PCIe", "PCIe"), ("USB", "USB"), ("USB,1GbE", "1GbE")):
            with self.subTest(available=available):
                self.server.devices["DEV12345"] = {"INTERFACE": "none", "INTERFACES": available}
                self.server.calls.clear()
                self.assertEqual(self.run_main(["--device", "dev12345"]), 0)
                self.assertIn(("connectDevice", "dev12345", expected), self.server.calls)

    def test_reported_usb_interface_is_used(self):
        self.server.devices["DEV12345"] = {"INTERFACE": "USB", "INTERFACES": "USB,1GbE"}
        self.assertEqual(self.run_main(["--device", "dev12345"]), 0)
        self.assertIn(("connectDevice", "dev12345", "USB"), self.server.calls)

    def test_device_not_visible_does_not_attempt_attachment(self):
        self.server.devices = {}
        self.assertEqual(self.run_main(["--device", "dev12345"]), 1)
        self.assertIn("not visible", self.err.getvalue())
        self.assertFalse(any(call[0] == "connectDevice" for call in self.server.calls))
        self.assertEqual(self.server.calls[-1], ("disconnect",))

    def test_no_interface_does_not_guess(self):
        self.server.devices["DEV12345"] = {"INTERFACE": "unknown", "INTERFACES": ""}
        self.assertEqual(self.run_main(["--device", "dev12345"]), 1)
        self.assertIn("no available interface", self.err.getvalue())
        self.assertFalse(any(call[0] == "connectDevice" for call in self.server.calls))
        self.assertEqual(self.server.calls[-1], ("disconnect",))

    def test_host_and_port_override(self):
        self.assertEqual(self.run_main(["--device", "dev12345", "--host", "169.254.1.2", "--port", "8006"]), 0)
        self.factory.assert_called_once_with("169.254.1.2", 8006, 6, allow_version_mismatch=True)

    def test_editable_defaults(self):
        self.demo.DEVICE_ID = "dev12345"
        self.demo.SERVER_HOST = "mf-dev12345.local"
        self.assertEqual(self.run_main([]), 0)
        self.factory.assert_called_once_with("mf-dev12345.local", 8004, 6, allow_version_mismatch=True)

    def test_server_connection_and_version_errors(self):
        for message in ("Server unavailable", "API/Data Server version mismatch"):
            with self.subTest(message=message):
                self.factory.side_effect = RuntimeError(message)
                self.assertEqual(self.run_main(["--device", "dev12345"]), 1)
                self.assertIn(message, self.err.getvalue())
        self.assertEqual(self.server.calls, [])
        self.assertNotIn("SUCCESS", self.out.getvalue())

    def test_partial_connection_failure_closes_client(self):
        self.server.fail_at = "connectDevice"
        self.assertEqual(self.run_main(["--device", "dev12345"]), 1)
        self.assertEqual(self.server.calls[-1], ("disconnect",))

    def test_wrong_device_closes_client(self):
        self.server.device_type = "UHFLI"
        self.assertEqual(self.run_main(["--device", "dev12345"]), 1)
        self.assertIn("Expected an MFLI", self.err.getvalue())
        self.assertEqual(self.server.calls[-1], ("disconnect",))
        self.assertNotIn("SUCCESS", self.out.getvalue())

    def test_read_failure_closes_client(self):
        self.server.fail_at = "getDouble"
        self.assertEqual(self.run_main(["--device", "dev12345"]), 1)
        self.assertIn("getDouble failure", self.err.getvalue())
        self.assertEqual(self.server.calls[-1], ("disconnect",))

    def test_invalid_clock_is_not_success(self):
        for value in (0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.server.clockbase = value
                self.assertEqual(self.run_main(["--device", "dev12345"]), 1)
                self.assertEqual(self.server.calls[-1], ("disconnect",))
        self.assertNotIn("SUCCESS", self.out.getvalue())

    def test_empty_serial_is_not_success(self):
        self.server.serial = ""
        self.assertEqual(self.run_main(["--device", "dev12345"]), 1)
        self.assertEqual(self.server.calls[-1], ("disconnect",))

    def test_cleanup_failure_is_not_success(self):
        self.server.close_error = "client close failed"
        self.assertEqual(self.run_main(["--device", "dev12345"]), 1)
        self.assertIn("client close failed", self.err.getvalue())
        self.assertNotIn("SUCCESS", self.out.getvalue())

    def test_cleanup_failure_preserves_original_read_error(self):
        self.server.fail_at = "getDouble"
        self.server.close_error = "client close failed"
        self.assertEqual(self.run_main(["--device", "dev12345"]), 1)
        self.assertIn("FAILED: Simulated getDouble failure", self.err.getvalue())
        self.assertIn("Cleanup also failed: client close failed", self.err.getvalue())

    def test_interrupt_closes_client(self):
        self.server.getDouble = Mock(side_effect=KeyboardInterrupt)
        self.assertEqual(self.run_main(["--device", "dev12345"]), 130)
        self.assertEqual(self.server.calls[-1], ("disconnect",))


if __name__ == "__main__":
    unittest.main()
