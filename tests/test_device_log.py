from __future__ import annotations

import os
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core.device_log import append_device_log, configure_device_log


class DeviceLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.editor = QtWidgets.QPlainTextEdit()
        configure_device_log(self.editor)

    def tearDown(self):
        self.editor.close()
        self.editor.deleteLater()
        self.app.processEvents()

    def test_configuration_uses_shared_device_log_contract(self):
        line_height = self.editor.fontMetrics().lineSpacing()
        self.assertTrue(self.editor.isReadOnly())
        self.assertEqual(self.editor.maximumBlockCount(), 500)
        self.assertGreaterEqual(self.editor.minimumHeight(), 8 * line_height)
        self.assertEqual(
            self.editor.sizePolicy().verticalPolicy(),
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self.assertEqual(self.editor.maximumHeight(), 16777215)

    def test_append_formats_caps_and_scrolls(self):
        self.editor.resize(400, self.editor.minimumHeight())
        self.editor.show()
        for index in range(510):
            append_device_log(self.editor, "warning", f"message {index}")
        self.app.processEvents()

        text = self.editor.toPlainText()
        self.assertEqual(self.editor.blockCount(), 500)
        self.assertNotIn("message 0\n", text)
        self.assertIn("message 509", text)
        self.assertRegex(
            text.splitlines()[-1],
            re.compile(
                r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] "
                r"\[WARNING\] message 509$"
            ),
        )
        scrollbar = self.editor.verticalScrollBar()
        self.assertEqual(scrollbar.value(), scrollbar.maximum())


if __name__ == "__main__":
    unittest.main()
