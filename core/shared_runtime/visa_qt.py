"""Qt worker/controller for explicit, off-UI-thread VISA discovery."""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from .visa import VisaRuntime


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

    def __init__(self, runtime: VisaRuntime, parent=None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self._thread: QtCore.QThread | None = None
        self._worker: VisaDiscoveryWorker | None = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    @QtCore.pyqtSlot()
    def refresh(self) -> bool:
        if self.busy:
            return False
        thread = QtCore.QThread(self)
        worker = VisaDiscoveryWorker(self.runtime)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.resources.connect(self.resources)
        worker.error.connect(self.error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        self.busy_changed.emit(True)
        thread.start()
        return True

    @QtCore.pyqtSlot()
    def _finished(self) -> None:
        self._thread = None
        self._worker = None
        self.busy_changed.emit(False)


class VisaResourceRefresh(QtCore.QObject):
    """Add and manage an explicit Refresh button for a VISA address combo."""

    def __init__(
        self,
        runtime: VisaRuntime,
        combo_box: QtWidgets.QComboBox,
        parent: QtWidgets.QWidget,
    ) -> None:
        super().__init__(parent)
        self.combo_box = combo_box
        self.controller = VisaDiscoveryController(runtime, self)
        self.button = QtWidgets.QPushButton("Refresh VISA", parent)
        self.button.setObjectName("refresh_visa_button")
        self.button.clicked.connect(self.controller.refresh)
        self.controller.resources.connect(self._replace_resources)
        self.controller.error.connect(self._show_error)
        self.controller.busy_changed.connect(
            lambda busy: self.button.setEnabled(not busy)
        )
        self._insert_button(parent)

    @QtCore.pyqtSlot(tuple)
    def _replace_resources(self, resources: tuple[str, ...]) -> None:
        current = self.combo_box.currentText().strip()
        self.combo_box.clear()
        self.combo_box.addItems(resources)
        if current and current not in resources:
            self.combo_box.addItem(current)
        if current:
            self.combo_box.setCurrentText(current)
        self.button.setToolTip(f"Found {len(resources)} VISA resource(s)")

    @QtCore.pyqtSlot(str)
    def _show_error(self, message: str) -> None:
        self.button.setToolTip(f"VISA discovery failed: {message}")

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
