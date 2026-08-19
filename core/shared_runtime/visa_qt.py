"""Qt worker/controller for automatic, off-UI-thread VISA discovery."""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from .visa import VisaRuntime


ADDRESS_MINIMUM_WIDTH = 320
ADDRESS_HORIZONTAL_PADDING = 48
DEFAULT_DISCOVERY_TIMEOUT_MS = 10_000


_retained_controllers: set["VisaDiscoveryController"] = set()


class VisaDiscoveryWorker(QtCore.QObject):
    resources = QtCore.pyqtSignal(tuple)
    error = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()

    def __init__(self, runtime: VisaRuntime, query: str = "?*::INSTR") -> None:
        super().__init__()
        self.runtime = runtime
        self.query = query

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            self.resources.emit(self.runtime.list_resources(self.query))
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class VisaDiscoveryController(QtCore.QObject):
    resources = QtCore.pyqtSignal(tuple)
    error = QtCore.pyqtSignal(str)
    busy_changed = QtCore.pyqtSignal(bool)

    def __init__(
        self,
        runtime: VisaRuntime,
        parent=None,
        *,
        timeout_ms: int = DEFAULT_DISCOVERY_TIMEOUT_MS,
    ) -> None:
        super().__init__(parent)
        if type(timeout_ms) is not int or timeout_ms <= 0:
            raise ValueError("VISA discovery timeout must be a positive integer")
        self.runtime = runtime
        self.timeout_ms = timeout_ms
        self._thread: QtCore.QThread | None = None
        self._worker: VisaDiscoveryWorker | None = None
        self._busy = False
        self._timed_out = False
        self._detached = False
        self._timeout_timer = QtCore.QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)

    @property
    def busy(self) -> bool:
        return self._busy

    @QtCore.pyqtSlot()
    def refresh(self) -> bool:
        if self.busy:
            return False
        thread = QtCore.QThread(self)
        worker = VisaDiscoveryWorker(self.runtime)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.resources.connect(self._forward_resources)
        worker.error.connect(self._forward_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        self._busy = True
        self._timed_out = False
        self.busy_changed.emit(True)
        thread.start()
        self._timeout_timer.start(self.timeout_ms)
        return True

    @QtCore.pyqtSlot(tuple)
    def _forward_resources(self, resources: tuple[str, ...]) -> None:
        if not self._timed_out:
            self.resources.emit(resources)

    @QtCore.pyqtSlot(str)
    def _forward_error(self, message: str) -> None:
        if not self._timed_out:
            self.error.emit(message)

    @QtCore.pyqtSlot()
    def _on_timeout(self) -> None:
        if not self.busy or self._timed_out:
            return
        self._timed_out = True
        self.retain_until_finished()
        self.error.emit(
            f"VISA discovery timed out after {self.timeout_ms / 1000:g} s; "
            "waiting for the vendor call to finish safely"
        )

    def retain_until_finished(self, *, detach=False) -> bool:
        if not self.busy:
            return False
        if detach:
            application = QtCore.QCoreApplication.instance()
            if application is not None and self.parent() is not application:
                self.setParent(application)
                self._detached = True
        _retained_controllers.add(self)
        return True

    @QtCore.pyqtSlot()
    def _finished(self) -> None:
        self._timeout_timer.stop()
        self._busy = False
        self._thread = None
        self._worker = None
        self.busy_changed.emit(False)
        _retained_controllers.discard(self)
        if self._detached:
            self.deleteLater()


class VisaResourceRefresh(QtCore.QObject):
    """Populate and size a VISA address combo without blocking the UI thread."""

    def __init__(
        self,
        runtime: VisaRuntime,
        combo_box: QtWidgets.QComboBox,
        parent: QtWidgets.QWidget,
        *,
        timeout_ms: int = DEFAULT_DISCOVERY_TIMEOUT_MS,
    ) -> None:
        super().__init__(parent)
        self._owner = parent
        self.combo_box = combo_box
        self.controller = VisaDiscoveryController(
            runtime,
            self,
            timeout_ms=timeout_ms,
        )
        self.button = QtWidgets.QPushButton("Refresh VISA", parent)
        self.button.setObjectName("refresh_visa_button")
        self.button.clicked.connect(self.controller.refresh)
        self.controller.resources.connect(self._replace_resources)
        self.controller.error.connect(self._show_error)
        self.controller.busy_changed.connect(
            lambda busy: self.button.setEnabled(not busy)
        )
        self._insert_button(parent)
        self._resize_address_selector()
        parent.installEventFilter(self)
        QtCore.QTimer.singleShot(0, self.controller.refresh)

    def eventFilter(self, watched, event):
        controller = getattr(self, "controller", None)
        if watched is getattr(self, "_owner", None) and controller is not None:
            if event.type() == QtCore.QEvent.Type.Close:
                controller.retain_until_finished()
            elif event.type() == QtCore.QEvent.Type.DeferredDelete:
                controller.retain_until_finished(detach=True)
        return super().eventFilter(watched, event)

    @QtCore.pyqtSlot(tuple)
    def _replace_resources(self, resources: tuple[str, ...]) -> None:
        current = self.combo_box.currentText().strip()
        self.combo_box.clear()
        self.combo_box.addItems(resources)
        if current and current not in resources:
            self.combo_box.addItem(current)
        if current:
            self.combo_box.setCurrentText(current)
        self._resize_address_selector()
        self.button.setToolTip(f"Found {len(resources)} VISA resource(s)")

    @QtCore.pyqtSlot(str)
    def _show_error(self, message: str) -> None:
        self.button.setToolTip(f"VISA discovery failed: {message}")

    def _resize_address_selector(self) -> None:
        texts = [
            self.combo_box.itemText(index)
            for index in range(self.combo_box.count())
        ]
        text_width = max(
            (self.combo_box.fontMetrics().horizontalAdvance(text) for text in texts),
            default=0,
        )
        width = max(
            ADDRESS_MINIMUM_WIDTH,
            text_width + ADDRESS_HORIZONTAL_PADDING,
        )
        self.combo_box.setMinimumWidth(width)
        self.combo_box.view().setMinimumWidth(width)
        self.combo_box.view().setTextElideMode(QtCore.Qt.TextElideMode.ElideNone)

    def _insert_button(self, parent: QtWidgets.QWidget) -> None:
        container = self.combo_box.parentWidget() or parent
        layout = container.layout() or parent.layout()
        if isinstance(layout, QtWidgets.QGridLayout):
            layout.addWidget(
                self.button,
                layout.rowCount(),
                0,
                1,
                max(1, layout.columnCount()),
            )
        elif layout is not None:
            layout.addWidget(self.button)
        else:
            self.button.setParent(parent)
            self.button.move(
                self.combo_box.x(),
                self.combo_box.y() + self.combo_box.height() + 4,
            )
            self.button.show()
