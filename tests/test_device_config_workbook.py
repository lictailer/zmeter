"""Read-only checks of the shipped configuration; never construct instruments.

Rows are looked up by device id and the Guide's accepted driver IDs are read
down to the first blank cell, so adding a row or a driver does not need a row
number change here. Do not edit the workbook with openpyxl: it drops the
checkbox cells.
"""
from pathlib import Path
import unittest

from openpyxl import load_workbook

from core.device_management import build_default_registry
from core.device_management.config import DEVICE_HEADERS, load_profile

WORKBOOK_PATH = Path(__file__).resolve().parents[1] / "device_config.xlsx"
ADDED_DRIVERS = ("attodry", "mc2000b", "spectraphysicsx3_laser", "auto_focus", "arduino_steppers", "auto_position")

FIRST_DEVICE_ROW = 2
# The config-check formula and the blank rows are reserved through this row.
LAST_RESERVED_ROW = 201
FIRST_GUIDE_DRIVER_ROW = 4
ID_COLUMN, DRIVER_COLUMN, ENABLED_COLUMN, CONNECT_COLUMN, ADDRESS_COLUMN = 1, 2, 3, 4, 5
SCAN_SET_COLUMN, SCAN_GET_COLUMN, CHECK_COLUMN = 6, 7, 8
GUIDE_DRIVER_COLUMN = 4

# Cached "config check" value per device id for the shipped workbook. Every
# other id is DISABLED. The cached value of nema11_stepper is ENABLED although
# its enabled flag is FALSE; Excel recalculates the column when the file opens.
CACHED_CHECK_EXCEPTIONS = {"nema11_stepper": "ENABLED"}


def device_rows(worksheet):
    """Map device id to row number for the contiguous data rows below the header."""
    rows = {}
    row = FIRST_DEVICE_ROW
    while worksheet.cell(row, ID_COLUMN).value not in (None, ""):
        rows[worksheet.cell(row, ID_COLUMN).value] = row
        row += 1
    return rows


def last_device_row(worksheet):
    return FIRST_DEVICE_ROW + len(device_rows(worksheet)) - 1


def guide_driver_ids(worksheet):
    """Accepted driver IDs from the Guide, down to the first blank cell."""
    accepted = []
    row = FIRST_GUIDE_DRIVER_ROW
    while worksheet.cell(row, GUIDE_DRIVER_COLUMN).value not in (None, ""):
        accepted.append(worksheet.cell(row, GUIDE_DRIVER_COLUMN).value)
        row += 1
    return accepted


class DeviceConfigWorkbookTests(unittest.TestCase):
    def setUp(self):
        self.workbook = load_workbook(WORKBOOK_PATH, data_only=False)
        self.addCleanup(self.workbook.close)
        self.devices = self.workbook["Devices"]
        self.rows = device_rows(self.devices)

    def value(self, device_id, column):
        return self.devices.cell(self.rows[device_id], column).value

    def test_headers_table_extent_and_reserved_rows(self):
        self.assertEqual(self.workbook.sheetnames, ["Devices", "Guide"])
        self.assertEqual(tuple(c.value for c in self.devices[1]), DEVICE_HEADERS)
        self.assertEqual(self.devices.max_row, LAST_RESERVED_ROW)
        self.assertEqual(list(self.devices.tables), ["FlatDeviceConfigTable"])
        table = self.devices.tables["FlatDeviceConfigTable"]
        self.assertEqual(table.ref, f"A1:H{last_device_row(self.devices)}")
        self.assertEqual(table.tableStyleInfo.name, "TableStyleLight1")
        # Nothing is left below the contiguous device rows.
        for row in range(last_device_row(self.devices) + 1, LAST_RESERVED_ROW + 1):
            self.assertIsNone(self.devices.cell(row, ID_COLUMN).value, row)

    def test_existing_rows_keep_current_profile_without_autoconnect(self):
        expected_drivers = {
            "sr860_0": "sr860", "sr860_1": "sr860", "sr860_2": "sr860",
            "sr830_0": "sr830", "sr830_1": "sr830", "sr830_2": "sr830",
            "mfli_0": "mfli",
            "keithley24xx_0": "keithley24xx", "keithley24xx_1": "keithley24xx",
            "nidaq": "nidaq", "ni6423": "ni6423",
            "k10cr1_0": "k10cr1", "k10cr1_1": "k10cr1",
            "pem100": "pem100", "sp150": "sp150", "hp34401a": "hp34401a",
            "bbd30x": "bbd30x", "four9": "four9", "montana2": "montana2",
            "opticool": "opticool", "tlpm": "tlpm",
            "mock_device_0": "mockDevice", "mock_device_1": "mockDevice",
        }
        for device_id, driver in expected_drivers.items():
            with self.subTest(device_id=device_id):
                self.assertIn(device_id, self.rows)
                self.assertEqual(self.value(device_id, DRIVER_COLUMN), driver)
                self.assertIs(self.value(device_id, ENABLED_COLUMN), False)
                self.assertIs(self.value(device_id, CONNECT_COLUMN), False)
        self.assertEqual(self.value("mfli_0", ADDRESS_COLUMN), "DEV30037, 192.168.141.54")
        self.assertEqual(self.value("keithley24xx_0", ADDRESS_COLUMN), "GPIB1::18::INSTR")
        self.assertEqual(self.value("ni6423", SCAN_SET_COLUMN), "AO0, AO1")
        self.assertEqual(self.value("ni6423", SCAN_GET_COLUMN), "AI9,AI12, counter0")

    def test_new_devices_have_manual_disabled_rows_and_explicit_channels(self):
        profile = load_profile(WORKBOOK_PATH, driver_specs=build_default_registry().config_specs)
        configurations = {device.id: device for device in profile.devices}
        for driver in ADDED_DRIVERS:
            row = self.rows[driver]
            self.assertEqual([self.devices.cell(row, col).value for col in range(1, 5)],
                             [driver, driver, False, False])
            self.assertEqual(self.devices.cell(row, ADDRESS_COLUMN).number_format, "@")
            config = configurations[driver]
            self.assertFalse(config.enabled)
            self.assertFalse(config.connect_on_start)
            self.assertIsNotNone(config.scan_channels.setters)
            self.assertIsNotNone(config.scan_channels.getters)
        atto = configurations["attodry"]
        self.assertEqual(atto.connection["address"], "REPLACE_WITH_ATTODRY_ADDRESS")
        self.assertEqual(atto.scan_channels.setters, ("T", "T_stable", "B", "B_stable"))
        self.assertEqual(atto.scan_channels.getters, ("T", "B"))
        self.assertEqual(configurations["spectraphysicsx3_laser"].scan_channels.setters, ("wavelength_stable", "shutter"))
        for driver in ("auto_focus", "auto_position"):
            self.assertIn(configurations[driver].connection["address"], (None, ""))
            self.assertIn("run_key", configurations[driver].scan_channels.getters)

    def test_guide_covers_every_registry_driver_and_alias(self):
        registry = build_default_registry()
        expected = set(registry.driver_ids) | {alias for spec in registry.config_specs.values() for alias in spec.aliases}
        accepted = guide_driver_ids(self.workbook["Guide"])
        self.assertEqual(set(accepted), expected)
        self.assertEqual(len(accepted), len(set(accepted)))
        last_guide_row = FIRST_GUIDE_DRIVER_ROW + len(accepted) - 1
        for row in range(FIRST_DEVICE_ROW, LAST_RESERVED_ROW + 1):
            formula = self.devices.cell(row, CHECK_COLUMN).value
            self.assertIn(f"COUNTA(A{row}:G{row})=0", formula)
            self.assertIn(f"$D${FIRST_GUIDE_DRIVER_ROW}:$D${last_guide_row}", formula)
            self.assertIn("UNKNOWN DRIVER", formula)
            self.assertIn("INVALID CONNECT FLAG", formula)

    def test_andor_row_is_disabled_with_explicit_channels(self):
        row = self.rows["andor"]
        self.assertEqual([self.devices.cell(row, col).value for col in range(1, 5)],
                         ["andor", "andor", False, False])
        profile = load_profile(WORKBOOK_PATH, driver_specs=build_default_registry().config_specs)
        andor = {device.id: device for device in profile.devices}["andor"]
        self.assertFalse(andor.enabled)
        self.assertFalse(andor.connect_on_start)
        self.assertEqual(andor.connection["address"], "0,0")
        self.assertEqual(andor.scan_channels.setters, ("temperature", "exposure_time", "center_wavelength"))
        self.assertEqual(
            andor.scan_channels.getters,
            ("temperature", "exposure_time", "center_wavelength", "spectrum", "image"),
        )

    def test_cached_checks_match_native_boolean_flags(self):
        cached = load_workbook(WORKBOOK_PATH, data_only=True)
        self.addCleanup(cached.close)
        for device_id, row in self.rows.items():
            with self.subTest(device_id=device_id):
                self.assertIsInstance(self.devices.cell(row, ENABLED_COLUMN).value, bool)
                self.assertIsInstance(self.devices.cell(row, CONNECT_COLUMN).value, bool)
                self.assertEqual(
                    cached["Devices"].cell(row, CHECK_COLUMN).value,
                    CACHED_CHECK_EXCEPTIONS.get(device_id, "DISABLED"),
                )
        self.assertIn(cached["Devices"].cell(LAST_RESERVED_ROW, CHECK_COLUMN).value, (None, ""))


if __name__ == "__main__":
    unittest.main()
