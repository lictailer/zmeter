"""Screenshot for the Slack scan message (UI thread only)."""

from __future__ import annotations

from typing import Iterable

from PyQt6 import QtCore, QtGui

MAX_WIDTH = 1600
GAP = 8


def stacked_png(widgets: Iterable) -> bytes | None:
    """Grab each widget and stack the grabs top to bottom in one PNG.

    Wider grabs are scaled down to ``MAX_WIDTH``.  Returns None when there is
    nothing to show.  Must run on the UI thread (``QWidget.grab``).
    """

    images = []
    for widget in widgets:
        pixmap = widget.grab()
        if pixmap.isNull() or pixmap.width() <= 0 or pixmap.height() <= 0:
            continue
        image = pixmap.toImage()
        if image.width() > MAX_WIDTH:
            image = image.scaledToWidth(
                MAX_WIDTH, QtCore.Qt.TransformationMode.SmoothTransformation
            )
        images.append(image)
    if not images:
        return None
    width = max(image.width() for image in images)
    height = sum(image.height() for image in images) + GAP * (len(images) - 1)
    canvas = QtGui.QImage(width, height, QtGui.QImage.Format.Format_RGB32)
    canvas.fill(QtGui.QColor("white"))
    painter = QtGui.QPainter(canvas)
    try:
        y = 0
        for image in images:
            painter.drawImage(0, y, image)
            y += image.height() + GAP
    finally:
        painter.end()
    payload = QtCore.QByteArray()
    buffer = QtCore.QBuffer(payload)
    if not buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
        return None
    try:
        if not canvas.save(buffer, "PNG"):
            return None
    finally:
        buffer.close()
    return bytes(payload)
