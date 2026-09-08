import os
import unittest
from unittest import mock


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtTest, QtWidgets

from core.queue_model import LiveQueueModel, QueueItemState
from core.scanlist import ManualSetItem, ManualValueDialog, ScanListWidget


class ManualSetItemDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.item = ManualSetItem("nidaq_ao0", 0.157)
        self.item.resize(240, self.item.height())
        self.item.show()
        self.app.processEvents()

    def tearDown(self):
        self.item.close()
        self.item.deleteLater()
        self.app.processEvents()

    def test_card_has_read_only_labels_and_no_inline_line_edit(self):
        self.assertEqual(self.item.findChildren(QtWidgets.QLineEdit), [])
        self.assertEqual(self.item.channel_label.text(), "nidaq_ao0")
        self.assertEqual(self.item.value_label.text(), repr(0.157))

    def test_double_clicking_frame_channel_or_value_opens_value_dialog(self):
        opened_dialogs = []

        def reject_dialog(dialog):
            opened_dialogs.append(dialog)
            return QtWidgets.QDialog.DialogCode.Rejected

        with mock.patch.object(ManualValueDialog, "exec", new=reject_dialog):
            for target in (
                self.item,
                self.item.channel_label,
                self.item.value_label,
            ):
                QtTest.QTest.mouseDClick(
                    target,
                    QtCore.Qt.MouseButton.LeftButton,
                )
                self.app.processEvents()

        self.assertEqual(len(opened_dialogs), 3)
        self.assertTrue(all(dialog.parent() is self.item for dialog in opened_dialogs))
        self.assertTrue(
            all(dialog.value_edit.text() == repr(0.157) for dialog in opened_dialogs)
        )

    def test_dialog_commits_finite_decimal_and_scientific_values(self):
        cases = (
            ("-12.5", -12.5),
            ("6.02e-3", 0.00602),
        )

        for text, expected in cases:
            with self.subTest(text=text):
                self.assertTrue(self.item.commit_value(0.157))

                def accept_dialog(dialog):
                    dialog.value_edit.setText(text)
                    ok_button = dialog.button_box.button(
                        QtWidgets.QDialogButtonBox.StandardButton.Ok
                    )
                    self.assertTrue(ok_button.isEnabled())
                    dialog._accept_if_valid()
                    return dialog.result()

                with mock.patch.object(
                    ManualValueDialog,
                    "exec",
                    new=accept_dialog,
                ):
                    self.item._open_value_dialog()

                self.assertEqual(self.item.parsed_value(), expected)
                self.assertEqual(self.item.value_label.text(), repr(expected))

    def test_cancel_invalid_nan_and_infinite_values_preserve_commit(self):
        original_value = self.item.parsed_value()
        original_text = self.item.value_label.text()

        def cancel_dialog(dialog):
            dialog.value_edit.setText("99")
            dialog.reject()
            return dialog.result()

        with mock.patch.object(ManualValueDialog, "exec", new=cancel_dialog):
            self.item._open_value_dialog()

        self.assertEqual(self.item.parsed_value(), original_value)
        self.assertEqual(self.item.value_label.text(), original_text)

        for text in ("not-a-number", "nan", "inf", "-inf"):
            with self.subTest(text=text):

                def reject_invalid_dialog(dialog):
                    dialog.value_edit.setText(text)
                    ok_button = dialog.button_box.button(
                        QtWidgets.QDialogButtonBox.StandardButton.Ok
                    )
                    self.assertFalse(ok_button.isEnabled())
                    dialog._accept_if_valid()
                    self.assertEqual(
                        dialog.result(),
                        QtWidgets.QDialog.DialogCode.Rejected,
                    )
                    return dialog.result()

                with mock.patch.object(
                    ManualValueDialog,
                    "exec",
                    new=reject_invalid_dialog,
                ):
                    self.item._open_value_dialog()

                self.assertFalse(self.item.commit_value(text))
                self.assertEqual(self.item.parsed_value(), original_value)
                self.assertEqual(self.item.value_label.text(), original_text)

    def test_dialog_opened_while_pending_cannot_commit_after_item_becomes_current(self):
        original_value = self.item.parsed_value()
        original_text = self.item.value_label.text()

        def accept_after_queue_claim(dialog):
            dialog.value_edit.setText("42.0")
            dialog._accept_if_valid()
            self.item.set_queue_state(QueueItemState.CURRENT)
            return dialog.result()

        with mock.patch.object(
            ManualValueDialog,
            "exec",
            new=accept_after_queue_claim,
        ):
            self.item._open_value_dialog()

        self.assertEqual(self.item.parsed_value(), original_value)
        self.assertEqual(self.item.value_label.text(), original_text)
        self.assertFalse(self.item.commit_value(43.0))

    def test_claim_winning_commit_race_cannot_change_the_current_command(self):
        original_value = self.item.parsed_value()
        model = LiveQueueModel()
        entry = model.add_pending(self.item)
        self.item.bind_queue_entry(model, entry.entry_id)
        self.assertTrue(model.begin_run())
        apply_if_pending = model.apply_if_pending

        def claim_before_commit(entry_id, operation):
            self.assertIs(model.claim_next(), entry)
            return apply_if_pending(entry_id, operation)

        with mock.patch.object(
            model,
            "apply_if_pending",
            side_effect=claim_before_commit,
        ):
            self.assertFalse(self.item.commit_value(42.0))

        self.assertEqual(self.item.parsed_value(), original_value)
        self.assertEqual(self.item.value_label.text(), repr(original_value))
        self.assertIs(entry.state, QueueItemState.CURRENT)
        model.finish_current(entry.entry_id)

    def test_clone_copies_committed_float_not_transient_dialog_text(self):
        self.assertTrue(self.item.commit_value("2.5e2"))
        transient_dialog = ManualValueDialog(
            self.item.parsed_value(),
            parent=self.item,
        )
        transient_dialog.value_edit.setText("999.0")

        clone = ScanListWidget.clone_manual_item(self.item)
        try:
            self.assertIsInstance(clone.parsed_value(), float)
            self.assertEqual(clone.parsed_value(), 250.0)
            self.assertEqual(clone.value_label.text(), repr(250.0))
            self.assertEqual(clone.channel_name, self.item.channel_name)

            self.assertTrue(self.item.commit_value(300.0))
            self.assertEqual(clone.parsed_value(), 250.0)
        finally:
            transient_dialog.reject()
            transient_dialog.deleteLater()
            clone.close()
            clone.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
