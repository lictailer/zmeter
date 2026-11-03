"""The Slack row in the main window and its bot-token dialog."""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from .notifier import SlackNotifier
from .settings import SlackTokenStore


class SlackTokenDialog(QtWidgets.QDialog):
    def __init__(self, store: SlackTokenStore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Slack bot token")
        self.store = store
        self.saved_token: str | None = None

        layout = QtWidgets.QVBoxLayout(self)
        info = QtWidgets.QLabel(
            "Paste the Slack app's Bot User OAuth Token (xoxb-...).\n"
            "Scopes needed: chat:write, files:write, im:write, users:read, "
            "users:read.email."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        self.token_edit = QtWidgets.QLineEdit(self)
        self.token_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText(
            "token saved (type to replace)" if store.get() else "xoxb-..."
        )
        layout.addWidget(self.token_edit)
        where = QtWidgets.QLabel(
            "Saved in the Windows credential store on this PC."
            if store.keyring_available
            else "keyring is not installed: the token is kept only until ZMeter closes."
        )
        where.setWordWrap(True)
        layout.addWidget(where)

        buttons = QtWidgets.QHBoxLayout()
        self.save_button = QtWidgets.QPushButton("Save")
        self.clear_button = QtWidgets.QPushButton("Clear saved token")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        self.save_button.clicked.connect(self._save)
        self.clear_button.clicked.connect(self._clear)
        self.cancel_button.clicked.connect(self.reject)

    def _save(self) -> None:
        token = self.token_edit.text().strip()
        if not token:
            self.reject()
            return
        self.store.set(token)
        self.saved_token = token
        self.accept()

    def _clear(self) -> None:
        self.store.set("")
        self.saved_token = ""
        self.accept()


class SlackPanel(QtWidgets.QWidget):
    """Active · email · Test · Bot token · status, in one row."""

    def __init__(self, notifier: SlackNotifier, store: SlackTokenStore, parent=None):
        super().__init__(parent)
        self.notifier = notifier
        self.store = store

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.active_checkbox = QtWidgets.QCheckBox("Active")
        self.email_edit = QtWidgets.QLineEdit()
        self.email_edit.setPlaceholderText("your Slack email (not saved)")
        self.test_button = QtWidgets.QPushButton("Test")
        self.token_button = QtWidgets.QPushButton()
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.active_checkbox)
        layout.addWidget(self.email_edit, 1)
        layout.addWidget(self.test_button)
        layout.addWidget(self.token_button)
        layout.addWidget(self.status_label, 1)

        self.active_checkbox.setToolTip(
            "Send Slack messages when scans and queues end and when "
            "default_slack_notification is set. Needs a bot token and your email."
        )
        self.test_button.setToolTip("Send a test message to your Slack email")
        self.token_button.setToolTip("Enter or change the Slack bot token")

        self.notifier.set_token(self.store.get())
        self.active_checkbox.toggled.connect(self.notifier.set_active)
        self.email_edit.textChanged.connect(self._email_changed)
        self.test_button.clicked.connect(self._test_clicked)
        self.token_button.clicked.connect(self.open_token_dialog)
        self.notifier.sig_test_result.connect(self._show_test_result)
        self._refresh()

    def _refresh(self) -> None:
        self.token_button.setText(
            "Bot token ✓" if self.notifier.has_token else "Bot token..."
        )
        ready = self.notifier.ready
        if not ready and self.active_checkbox.isChecked():
            self.active_checkbox.setChecked(False)
        self.active_checkbox.setEnabled(ready)

    def _email_changed(self, text: str) -> None:
        self.notifier.set_email(text)
        self._refresh()

    def _test_clicked(self) -> None:
        self.status_label.setText("Testing...")
        self.notifier.test()

    def _show_test_result(self, ok: bool, message: str) -> None:
        self.status_label.setText(("OK: " if ok else "Failed: ") + message)

    def open_token_dialog(self) -> None:
        dialog = SlackTokenDialog(self.store, parent=self)
        if dialog.exec() and dialog.saved_token is not None:
            self.notifier.set_token(dialog.saved_token)
            self.status_label.setText(
                "Token saved." if dialog.saved_token else "Token cleared."
            )
            self._refresh()
