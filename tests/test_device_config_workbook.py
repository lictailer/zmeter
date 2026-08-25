from __future__ import annotations

import unittest
from pathlib import Path

from openpyxl import load_workbook

from core.device_management.config import DEVICE_HEADERS


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKBOOK_PATH = REPOSITORY_ROOT / "device_config.xlsx"


class DeviceConfigWorkbookTests(unittest.TestCase):
    def test_checked_in_workbook_keeps_reviewed_device_values(self):
        workbook = load_workbook(WORKBOOK_PATH, data_only=False)
        self.addCleanup(workbook.close)
        devices = workbook["Devices"]

        self.assertEqual(tuple(cell.value for cell in devices[1]), DEVICE_HEADERS)
        self.assertEqual(devices.max_row, 201)
        self.assertEqual(list(devices.tables), ["FlatDeviceConfigTable"])

        expected_addresses = [
            "GPIB0::6::INSTR",
            "GPIB0::7::INSTR",
            "GPIB0::8::INSTR",
            "GPIB0::9::INSTR",
            "GPIB0::10::INSTR",
            "GPIB0::11::INSTR",
            "GPIB1::18::INSTR",
            "GPIB1::19::INSTR",
            "dev1",
            "dev2",
            "35995686",
            "43755678",
            "GPIB2::10::INSTR",
            "GPIB2::11::INSTR",
            "GPIB2::12::INSTR",
            "103529564",
            "127.0.0.1:5050",
            "REPLACE_WITH_MONTANA2_ADDRESS",
            None,
            None,
        ]
        address_cells = [devices.cell(row=row, column=5) for row in range(2, 22)]
        self.assertEqual([cell.value for cell in address_cells], expected_addresses)
        self.assertTrue(all(cell.number_format == "@" for cell in address_cells))
        self.assertTrue(
            all(cell.data_type in {"s", "str"} for cell in address_cells)
        )
        self.assertIs(devices["C2"].value, True)
        self.assertIs(devices["D2"].value, True)
        self.assertEqual(devices["F11"].value, "AO0, AO1")
        self.assertEqual(devices["G11"].value, "AI9,AI12, counter0")
        self.assertEqual(devices["E201"].number_format, "@")
        self.assertIn("COUNTA(A201:G201)=0", devices["H201"].value)
        self.assertIn("NOW()>=0", devices["H201"].value)
        self.assertEqual(
            [str(item.sqref) for item in devices.data_validations.dataValidation],
            ["C2:D201"],
        )
        self.assertEqual(
            [str(item.sqref) for item in devices.conditional_formatting],
            ["H2:H201"],
        )

    def test_config_check_handles_native_booleans_and_uses_guide_driver_list(self):
        formula_workbook = load_workbook(WORKBOOK_PATH, data_only=False)
        self.addCleanup(formula_workbook.close)
        values_workbook = load_workbook(WORKBOOK_PATH, data_only=True)
        self.addCleanup(values_workbook.close)

        devices = formula_workbook["Devices"]
        formula = devices["H2"].value
        self.assertIn("UPPER(TRIM(C2&\"\"))", formula)
        self.assertIn("UPPER(TRIM(D2&\"\"))", formula)
        self.assertIn("NOW()>=0", formula)
        self.assertIn("'Guide'!$D$4:$D$19", formula)
        self.assertIn("UNKNOWN DRIVER", formula)
        self.assertIn("INVALID CONNECT FLAG", formula)
        self.assertEqual(values_workbook["Devices"]["H2"].value, "AUTO-CONNECT")
        self.assertEqual(values_workbook["Devices"]["H3"].value, "DISABLED")

        accepted = {
            formula_workbook["Guide"].cell(row=row, column=4).value
            for row in range(4, 20)
        }
        self.assertEqual(
            accepted,
            {
                "mock_device",
                "ni6423",
                "nidaq",
                "pem100",
                "sp150",
                "hp34401a",
                "keithley24xx",
                "sr860",
                "sr830",
                "demo_device",
                "bbd30x",
                "k10cr1",
                "four9",
                "montana2",
                "opticool",
                "tlpm",
            },
        )


if __name__ == "__main__":
    unittest.main()
