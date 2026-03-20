import os
import sys
import time
import types
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if "win32com" not in sys.modules:
    win32com_module = types.ModuleType("win32com")
    win32com_client_module = types.ModuleType("win32com.client")
    win32com_module.client = win32com_client_module
    sys.modules["win32com"] = win32com_module
    sys.modules["win32com.client"] = win32com_client_module

from PyQt6 import QtCore

from core.artificial_channel_logic import ArtificialChannelLogic
from core.device_command_router import DeviceCommandClient, DeviceCommandRouter
from core.mainWindow import MainWindow


class FakeLogic:
    def __init__(self):
        self.values = {
            "x": 0.0,
            "y": 0.0,
            "voltage": 1.5,
        }
        self.write_log = []

    def set_x(self, value):
        self.values["x"] = float(value)
        self.write_log.append(("x", float(value)))

    def get_x(self):
        return self.values["x"]

    def set_y(self, value):
        self.values["y"] = float(value)
        self.write_log.append(("y", float(value)))

    def get_y(self):
        return self.values["y"]

    def set_voltage(self, value):
        self.values["voltage"] = float(value)
        self.write_log.append(("voltage", float(value)))

    def get_voltage(self):
        return self.values["voltage"]

    def set_broken(self, _value):
        raise RuntimeError("set_broken failed")

    def get_broken(self):
        raise RuntimeError("get_broken failed")

    def set_pair(self, _left, _right):
        return None

    def get_with_arg(self, extra):
        return extra


class FakeEquipment:
    def __init__(self):
        self.logic = FakeLogic()


class FakeScanList:
    def __init__(self):
        self.setter_updates = []
        self.getter_updates = []

    def setter_equipment_info_updated(self, info):
        self.setter_updates.append(info)

    def getter_equipment_info_updated(self, info):
        self.getter_updates.append(info)


class FeatureDevice(QtCore.QObject):
    def __init__(self, router):
        super().__init__()
        self.client = DeviceCommandClient(router, "feature_0", parent=self)
        self.responses = []
        self.catalog_updates = []
        self.client.sig_response.connect(self.responses.append)
        self.client.sig_catalog_changed.connect(self.catalog_updates.append)


class Harness:
    pass


def bind_main_window_method(harness, method_name):
    setattr(harness, method_name, getattr(MainWindow, method_name).__get__(harness, Harness))


def build_harness():
    harness = Harness()
    harness.equips = {"fake_0": FakeEquipment()}
    harness.setter_equipment_info_for_scanning = {}
    harness.getter_equipment_info_for_scanning = {}
    harness.setter_equipment_info = {}
    harness.getter_equipment_info = {}
    harness.device_channel_catalog = {}
    harness.scanlist = FakeScanList()

    for method_name in [
        "_safe_signature",
        "_is_valid_getter",
        "_is_valid_setter",
        "_make_artificial_channel_writer",
        "_make_artificial_channel_reader",
        "_is_nan_value",
        "_set_default_wait",
        "_set_default_count",
        "write_artificial_channel",
        "read_artificial_channel",
        "make_variables_dictionary",
        "make_equipment_info",
        "setup_default_channel_info",
        "update_artificial_channel_scan_info",
        "get_variable",
        "write_info",
        "read_info",
        "build_device_channel_catalog",
        "refresh_device_catalog",
        "get_device_channel_catalog",
        "inject_command_router_metadata",
        "on_artificial_channel_config_applied",
    ]:
        bind_main_window_method(harness, method_name)

    harness.make_equipment_info()
    harness.setup_default_channel_info()
    harness.artificial_channel_logic = ArtificialChannelLogic(
        write_channel=harness.write_info,
        read_channel=harness.read_info,
        original_channel_x_name="fake_0_x",
        original_channel_y_name="fake_0_y",
        original_channel_x_limits=(-1.0, 1.0),
        original_channel_y_limits=(-1.0, 1.0),
    )
    harness.update_artificial_channel_scan_info()
    harness.command_router = DeviceCommandRouter(main_window=harness)
    harness.inject_command_router_metadata()
    harness.refresh_device_catalog()
    return harness


def wait_for(predicate, timeout=1.0):
    app = QtCore.QCoreApplication.instance()
    if app is None:
        app = QtCore.QCoreApplication([])

    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


class DeviceCommandBusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])

    def setUp(self):
        self.harness = build_harness()

    def test_catalog_generation_filters_nonstandard_methods(self):
        catalog = self.harness.get_device_channel_catalog()

        self.assertIn("fake_0", catalog)
        self.assertEqual(
            catalog["fake_0"]["readable"],
            ["broken", "voltage", "x", "y"],
        )
        self.assertEqual(
            catalog["fake_0"]["writable"],
            ["broken", "voltage", "x", "y"],
        )
        self.assertNotIn("with_arg", catalog["fake_0"]["readable"])
        self.assertNotIn("pair", catalog["fake_0"]["writable"])
        self.assertEqual(catalog["default"]["readable"], [])
        self.assertEqual(catalog["default"]["writable"], ["wait", "count"])
        self.assertEqual(catalog["artificial_channel"]["readable"], ["n", "E"])
        self.assertEqual(catalog["artificial_channel"]["writable"], ["n", "E"])

    def test_valid_routed_write_and_read_use_mainwindow_path(self):
        responses = []
        self.harness.command_router.sig_command_responded.connect(responses.append)

        self.harness.command_router.sig_command_requested.emit(
            {
                "request_id": "write-1",
                "source_device": "feature_0",
                "action": "write",
                "target_device": "fake_0",
                "channel": "voltage",
                "value": 2.75,
            }
        )
        self.assertTrue(wait_for(lambda: len(responses) == 1))
        self.assertTrue(responses[0]["ok"])
        self.assertEqual(self.harness.equips["fake_0"].logic.values["voltage"], 2.75)
        self.assertIn(("voltage", 2.75), self.harness.equips["fake_0"].logic.write_log)

        self.harness.command_router.sig_command_requested.emit(
            {
                "request_id": "read-1",
                "source_device": "feature_0",
                "action": "read",
                "target_device": "fake_0",
                "channel": "voltage",
                "value": None,
            }
        )
        self.assertTrue(wait_for(lambda: len(responses) == 2))
        self.assertTrue(responses[1]["ok"])
        self.assertEqual(responses[1]["value"], 2.75)

    def test_list_catalog_returns_separate_readable_and_writable_lists(self):
        responses = []
        self.harness.command_router.sig_command_responded.connect(responses.append)

        self.harness.command_router.sig_command_requested.emit(
            {
                "request_id": "catalog-1",
                "source_device": "feature_0",
                "action": "list_catalog",
                "target_device": None,
                "channel": None,
                "value": None,
            }
        )
        self.assertTrue(wait_for(lambda: len(responses) == 1))
        self.assertTrue(responses[0]["ok"])
        self.assertEqual(
            responses[0]["catalog"],
            self.harness.get_device_channel_catalog(),
        )

    def test_invalid_requests_are_rejected_without_execution(self):
        responses = []
        self.harness.command_router.sig_command_responded.connect(responses.append)
        logic = self.harness.equips["fake_0"].logic

        invalid_requests = [
            {
                "request_id": "bad-action",
                "source_device": "feature_0",
                "action": "reset",
                "target_device": "fake_0",
                "channel": "voltage",
                "value": None,
                "error_code": "unsupported_action",
            },
            {
                "request_id": "bad-device",
                "source_device": "feature_0",
                "action": "read",
                "target_device": "missing_0",
                "channel": "voltage",
                "value": None,
                "error_code": "unknown_device",
            },
            {
                "request_id": "bad-channel",
                "source_device": "feature_0",
                "action": "read",
                "target_device": "fake_0",
                "channel": "missing",
                "value": None,
                "error_code": "unknown_channel",
            },
            {
                "request_id": "missing-value",
                "source_device": "feature_0",
                "action": "write",
                "target_device": "fake_0",
                "channel": "voltage",
                "value": None,
                "error_code": "missing_value",
            },
        ]

        for request in invalid_requests:
            expected_error = request.pop("error_code")
            self.harness.command_router.sig_command_requested.emit(request)
            self.assertTrue(wait_for(lambda: len(responses) >= 1))
            response = responses.pop(0)
            self.assertFalse(response["ok"])
            self.assertEqual(response["error_code"], expected_error)

        self.assertEqual(logic.write_log, [])

    def test_execution_errors_return_structured_failures(self):
        responses = []
        self.harness.command_router.sig_command_responded.connect(responses.append)

        self.harness.command_router.sig_command_requested.emit(
            {
                "request_id": "broken-read",
                "source_device": "feature_0",
                "action": "read",
                "target_device": "fake_0",
                "channel": "broken",
                "value": None,
            }
        )
        self.assertTrue(wait_for(lambda: len(responses) == 1))
        self.assertFalse(responses[0]["ok"])
        self.assertEqual(responses[0]["error_code"], "execution_error")
        self.assertIn("get_broken failed", responses[0]["error_message"])

        self.harness.command_router.sig_command_requested.emit(
            {
                "request_id": "broken-write",
                "source_device": "feature_0",
                "action": "write",
                "target_device": "fake_0",
                "channel": "broken",
                "value": 1.0,
            }
        )
        self.assertTrue(wait_for(lambda: len(responses) == 2))
        self.assertFalse(responses[1]["ok"])
        self.assertEqual(responses[1]["error_code"], "execution_error")
        self.assertIn("set_broken failed", responses[1]["error_message"])

    def test_artificial_channel_reconfiguration_emits_catalog_refresh(self):
        catalog_updates = []
        self.harness.command_router.sig_catalog_changed.connect(catalog_updates.append)

        self.harness.artificial_channel_logic.apply_configuration(
            original_channel_x_name="fake_0_x",
            original_channel_y_name="fake_0_y",
            artificial_channel_x_name="n2",
            artificial_channel_y_name="E2",
            coordinate_pairs=ArtificialChannelLogic.default_coordinate_pairs,
            original_channel_x_limits=(-1.0, 1.0),
            original_channel_y_limits=(-1.0, 1.0),
        )
        self.harness.on_artificial_channel_config_applied()

        self.assertTrue(wait_for(lambda: len(catalog_updates) >= 1))
        latest_catalog = catalog_updates[-1]
        self.assertEqual(latest_catalog["artificial_channel"]["readable"], ["n2", "E2"])
        self.assertEqual(latest_catalog["artificial_channel"]["writable"], ["n2", "E2"])
        self.assertEqual(len(self.harness.scanlist.setter_updates), 1)
        self.assertEqual(len(self.harness.scanlist.getter_updates), 1)

    def test_feature_device_client_can_request_catalog_and_route_commands(self):
        feature_device = FeatureDevice(self.harness.command_router)

        feature_device.client.request_catalog(request_id="catalog")
        feature_device.client.request_write(
            "fake_0",
            "x",
            0.25,
            request_id="write",
        )
        feature_device.client.request_read(
            "fake_0",
            "x",
            request_id="read",
        )

        self.assertTrue(wait_for(lambda: len(feature_device.responses) == 3))
        self.assertEqual(feature_device.responses[0]["request_id"], "catalog")
        self.assertTrue(feature_device.responses[0]["ok"])
        self.assertEqual(feature_device.responses[1]["request_id"], "write")
        self.assertTrue(feature_device.responses[1]["ok"])
        self.assertEqual(feature_device.responses[2]["request_id"], "read")
        self.assertEqual(feature_device.responses[2]["value"], 0.25)


if __name__ == "__main__":
    unittest.main()
