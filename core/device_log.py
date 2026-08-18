"""Shared presentation helpers for in-memory device logs."""

from __future__ import annotations

from datetime import datetime

from PyQt6 import QtWidgets


DEFAULT_VISIBLE_LINES = 8
MAX_LOG_ENTRIES = 500


def configure_device_log(
    editor: QtWidgets.QPlainTextEdit,
    *,
    visible_lines: int = DEFAULT_VISIBLE_LINES,
) -> None:
    """Configure a device log without owning device-event policy."""

    editor.setReadOnly(True)
    editor.setMaximumBlockCount(MAX_LOG_ENTRIES)
    editor.setSizePolicy(
        QtWidgets.QSizePolicy.Policy.Expanding,
        QtWidgets.QSizePolicy.Policy.Expanding,
    )
    line_height = editor.fontMetrics().lineSpacing()
    frame_height = 2 * editor.frameWidth()
    document_margin = int(editor.document().documentMargin() * 2)
    editor.setMinimumHeight(
        max(1, int(visible_lines)) * line_height + frame_height + document_margin
    )
    editor.setMaximumHeight(16777215)


def append_device_log(
    editor: QtWidgets.QPlainTextEdit,
    level: object,
    message: object,
) -> None:
    """Append one timestamped entry and keep the newest entry visible."""

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    editor.appendPlainText(f"[{timestamp}] [{str(level).upper()}] {message}")
    scrollbar = editor.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
