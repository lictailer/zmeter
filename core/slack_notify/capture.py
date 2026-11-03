"""Screenshot for the Slack scan message (UI thread only)."""

from __future__ import annotations

from typing import Iterable, Sequence

from PyQt6 import QtCore, QtGui

# The whole picture is shrunk to at most this many pixels wide.
MAX_WIDTH = 3200
PADDING = 10
BACKGROUND = "#1e1e1e"


def _plots_rect(area, plot_types) -> QtCore.QRect:
    """Smallest rectangle of ``area`` that holds all of its shown plots."""

    rect = QtCore.QRect()
    for plot in area.findChildren(plot_types):
        if not plot.isVisibleTo(area) or plot.width() <= 0 or plot.height() <= 0:
            continue
        top_left = plot.mapTo(area, QtCore.QPoint(0, 0))
        rect = rect.united(QtCore.QRect(top_left, plot.size()))
    return rect.intersected(area.rect())


def _physical(image: QtGui.QImage) -> QtGui.QImage:
    """Treat a grab as plain pixels.

    On a scaled Windows display (125 %, 150 %, ...) a grab carries a device
    pixel ratio; a painter would then draw it smaller than its pixel size and
    leave empty room on the right and bottom of the canvas.
    """

    image.setDevicePixelRatio(1.0)
    return image


def plots_png(
    pages: Sequence[tuple],
    plot_types,
    reference_size: QtCore.QSize | None = None,
) -> bytes | None:
    """One PNG of the plots on several tab pages, placed left to right.

    ``pages`` holds ``(page, area)`` pairs: the tab page and the widget that
    holds its plots.  Only the plots are captured (no buttons, no empty
    space), the pages are scaled to one height, and they sit on a dark
    background with a small margin.  A page that was never shown still has a
    default size, so it is first resized to ``reference_size`` (the size of
    the shown page).  Returns None when no page has a plot.  UI thread only.
    """

    grabs = []
    for page, area in pages:
        if reference_size is not None and reference_size.isValid() and page.size() != reference_size:
            page.resize(reference_size)
            page.grab()  # sends the pending resize so the page lays itself out
        rect = _plots_rect(area, plot_types)
        if rect.isEmpty():
            continue
        image = _physical(area.grab(rect).toImage())
        if not image.isNull():
            grabs.append(image)
    return side_by_side_png(grabs)


def side_by_side_png(images: Iterable[QtGui.QImage]) -> bytes | None:
    """Scale images to one height and place them left to right on a dark
    background, with ``PADDING`` around and between them and no other
    room.  The whole row is shrunk to at most ``MAX_WIDTH`` pixels wide.
    None when there is nothing to show."""

    images = [
        _physical(image) for image in images if not image.isNull() and image.width() > 0
    ]
    if not images:
        return None
    height = max(image.height() for image in images)
    widths = [round(image.width() * height / image.height()) for image in images]
    room = MAX_WIDTH - PADDING * (len(images) + 1)
    if sum(widths) > room:
        shrink = room / sum(widths)
        height = max(1, round(height * shrink))
        widths = [max(1, round(width * shrink)) for width in widths]
    scaled = [
        image
        if (image.width(), image.height()) == (width, height)
        else image.scaled(
            width,
            height,
            QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        for image, width in zip(images, widths)
    ]
    canvas_width = sum(widths) + PADDING * (len(scaled) + 1)
    canvas = QtGui.QImage(canvas_width, height + 2 * PADDING, QtGui.QImage.Format.Format_RGB32)
    canvas.fill(QtGui.QColor(BACKGROUND))
    painter = QtGui.QPainter(canvas)
    try:
        x = PADDING
        for image in scaled:
            painter.drawImage(x, PADDING, _physical(image))
            x += image.width() + PADDING
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
