import sys
import copy
import time
import datetime as _dt
import traceback
from dataclasses import dataclass
import PyQt6.QtWidgets as QtWidgets
import PyQt6.QtCore as QtCore
import PyQt6.QtGui as QtGui
from PyQt6 import uic
from .scan import Scan
from .nested_menu import NestedMenu


class ScanListShutdownTimeoutError(TimeoutError):
    """Raised when scans or the queue do not quiesce before shutdown's deadline."""

    def __init__(self, timeout_ms, pending):
        self.timeout_ms = int(timeout_ms)
        self.pending = tuple(pending)
        pending_text = ", ".join(self.pending) if self.pending else "unknown work"
        super().__init__(
            f"Scan-list shutdown did not quiesce within {self.timeout_ms} ms: "
            f"{pending_text}"
        )


class ScanListShutdownThreadError(RuntimeError):
    """Raised when scan-list shutdown is called outside its Qt owner thread."""


class ScanListShutdownInProgressError(RuntimeError):
    """Raised when shutdown is called reentrantly before quiescence is known."""


class ScanListShutdownStopError(RuntimeError):
    """Raised after quiescence when one or more scan stop requests failed."""

    def __init__(self, failures):
        self.failures = tuple(failures)
        details = "; ".join(
            f"{name}: {type(exc).__name__}: {exc}" for name, exc in self.failures
        )
        super().__init__(f"Scan stop request failed during shutdown: {details}")


class ScanCatalogRollbackError(RuntimeError):
    """Raised when catalog publication and its local rollback both fail."""

    def __init__(self, refresh_error, rollback_failures):
        self.refresh_error = refresh_error
        self.rollback_failures = tuple(rollback_failures)
        details = "; ".join(
            f"{location}: {type(exc).__name__}: {exc}"
            for location, exc in self.rollback_failures
        )
        super().__init__(
            f"Catalog consumer refresh failed ({type(refresh_error).__name__}: "
            f"{refresh_error}); rollback also failed: {details}"
        )


@dataclass(frozen=True)
class ReferenceUse:
    """A deterministic channel/device reference retained by a scan-list item."""

    device_id: str | None
    kind: str
    access: str
    collection: str
    owner_kind: str
    owner_name: str
    level: str | None
    channel: str
    path: str
    resolved: bool

    def __str__(self):
        resolution = "resolved" if self.resolved else "unresolved"
        device = self.device_id or "unknown device"
        return (
            f"{self.collection} {self.owner_kind} '{self.owner_name}' "
            f"{self.path}: {self.channel} ({device}, {resolution})"
        )


class ScanItem(QtWidgets.QLabel):
    sig_info_changed = QtCore.pyqtSignal(object)
    start = QtCore.pyqtSignal(object)
    stop = QtCore.pyqtSignal(object)

    def __init__(
        self,
        name=None,
        info=None,
        setter_equipment_info=None,
        main_window=None,
        getter_equipment_info=None,
    ):
        super().__init__()
        self.name = copy.deepcopy(name)
        self.main_window = main_window
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("border: 5px solid black;")
        self.info = copy.deepcopy(info)
        self.scan = Scan(
            name=name,
            info=self.info,
            setter_equipment_info=setter_equipment_info,
            main_window=self.main_window,
            getter_equipment_info=getter_equipment_info,
        )
        # self.scan.set_equipment_info(equipement_info)
        self.scan.sig_info_changed.connect(self.when_scan_info_changed)
        self.scan.start.connect(self.start_scan)
        self.scan.stop.connect(self.stop_scan)
        self.scan.emit()

    def when_scan_info_changed(self, info):
        self.setText(info["name"])
        self.info = info
        self.name = info["name"]
        
    def mouseMoveEvent(self, e):
        if e.buttons() == QtCore.Qt.MouseButton.LeftButton:
            drag = QtGui.QDrag(self)
            mime = QtCore.QMimeData()
            drag.setMimeData(mime)
            pixmap = QtGui.QPixmap(self.size())
            self.render(pixmap)
            drag.setPixmap(pixmap)
            drag.exec()

    def mouseDoubleClickEvent(self, e):
        self._show_and_focus_scan_window()

    def _show_and_focus_scan_window(self):
        self.scan.show()
        if self.scan.isMinimized():
            self.scan.showNormal()
        self.scan.raise_()
        self.scan.activateWindow()

    def snapshot_info(self):
        """
        Capture the latest scan configuration before drag-copying this item.
        This keeps UI-only fields in sync with the cloned ScanItem.
        """
        info_snapshot = copy.deepcopy(self.scan.info)
        info_snapshot["name"] = self.scan.lineEdit.text()
        info_snapshot["levels"] = copy.deepcopy(
            self.scan.all_level_setting.all_level_info
        )
        info_snapshot["plots"] = copy.deepcopy(self.scan.all_plot_setting.info)
        info_snapshot["comments"] = self.scan.comments_textEdit.toPlainText()
        info_snapshot["plots_per_page"] = self.scan.PlotsPerPage.currentText()
        return info_snapshot

    def refresh_catalog(self, setter_equipment_info, getter_equipment_info):
        self.scan.refresh_catalog(setter_equipment_info, getter_equipment_info)

    def start_scan(self, info):
        self.start.emit(info)

    def stop_scan(self):
        self.stop.emit(self)

    def start_queue(self):
        # Use the same flow as pressing the Scan button, then block until done
        # so queue execution remains strictly sequential.
        QtCore.QMetaObject.invokeMethod(
            self,
            "_start_scan_from_queue",
            QtCore.Qt.ConnectionType.BlockingQueuedConnection,
        )

        # Wait briefly for the scan thread to transition to running.
        # If it never starts, continue to next queue item instead of hanging.
        startup_wait_steps = 0
        while (not self.scan.logic.isRunning()) and startup_wait_steps < 40:
            QtCore.QThread.msleep(50)
            startup_wait_steps += 1

        while self.scan.logic.isRunning():
            QtCore.QThread.sleep(1)

    @QtCore.pyqtSlot()
    def _start_scan_from_queue(self):
        self.scan.showMaximized()
        if hasattr(self.scan, "_focus_plot_tab_1_for_scan_start"):
            self.scan._focus_plot_tab_1_for_scan_start(maximize=True)
        self.scan.raise_()
        self.scan.activateWindow()
        self.scan.when_scan_clicked()

    @QtCore.pyqtSlot()
    def _request_stop_from_queue(self):
        self.scan.when_stop_clicked()


class DeleteItem(QtWidgets.QLabel):
    def __init__(self, owner=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        self.resize(20, 20)
        self.setPixmap(QtGui.QPixmap("core/ui/bin.png").scaledToWidth(64))
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        e.accept()

    def dropEvent(self, e):
        widget = e.source()
        if self.owner is not None and hasattr(self.owner, "handle_delete_request"):
            self.owner.handle_delete_request(widget)
            e.accept()
            return
        if isinstance(widget, ScanItem):
            if widget.scan.logic.isRunning():
                QtWidgets.QMessageBox.warning(
                    self,
                    "Scan Running",
                    "This scan is currently running and cannot be deleted.",
                )
                e.accept()
                return
            print("ScanItem deleted")
            widget.deleteLater()
        elif isinstance(widget, ManualSetItem):
            print("ManualSetItem deleted")
            widget.deleteLater()
        e.accept()


class ManualSetItem(QtWidgets.QFrame):
    def __init__(self, channel_name, value, main_window=None):
        super().__init__()
        self.main_window = main_window
        self.channel_name = str(channel_name).strip()
        self._drag_start_pos = None

        self.setObjectName("manualSetItemWidget")
        self.setFrameShape(QtWidgets.QFrame.Shape.Box)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Plain)
        self.setLineWidth(5)
        self.setStyleSheet(
            "#manualSetItemWidget { border: 5px solid black; border-radius: 0px; }"
            "#manualSetItemWidget QLabel { border: none; }"
            "#manualSetItemWidget QLineEdit { border: none; background: transparent; }"
        )
        self.setMinimumHeight(84)
        self.setFixedHeight(self.minimumHeight())
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(4)

        self.channel_label = QtWidgets.QLabel(self.channel_name)
        self.channel_label.setWordWrap(True)
        self.channel_label.setMinimumWidth(0)

        self.channel_label.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self.channel_label.setToolTip(self.channel_name)
        layout.addWidget(self.channel_label, 0, 0, 1, 2)

        value_title = QtWidgets.QLabel("Value:")
        value_title.setMinimumWidth(55)
        self.value_edit = QtWidgets.QLineEdit(str(value))
        self.value_edit.setFixedWidth(110)
        layout.addWidget(value_title, 1, 0)
        layout.addWidget(self.value_edit, 1, 1, alignment=QtCore.Qt.AlignmentFlag.AlignLeft)

        self.installEventFilter(self)
        self.channel_label.installEventFilter(self)
        self.value_edit.installEventFilter(self)

    def text(self):
        return f"{self.channel_name}->{self.value_text()}"

    def value_text(self):
        return self.value_edit.text().strip()

    def parsed_value(self):
        return float(self.value_text())

    def _start_drag(self):
        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        drag.setMimeData(mime)
        pixmap = QtGui.QPixmap(self.size())
        self.render(pixmap)
        drag.setPixmap(pixmap)
        drag.exec()

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.MouseButtonPress:
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                self._drag_start_pos = event.globalPosition().toPoint()
            return False

        if event.type() == QtCore.QEvent.Type.MouseMove:
            if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
                if self._drag_start_pos is not None:
                    current_pos = event.globalPosition().toPoint()
                    if (
                        current_pos - self._drag_start_pos
                    ).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                        self._drag_start_pos = None
                        self._start_drag()
                        return True
            return False

        return super().eventFilter(obj, event)

    def start_queue(self):
        scan_list = getattr(self.main_window, "scanlist", None)
        if bool(getattr(scan_list, "_shutdown_sealed", False)):
            scan_list._log_warning(
                "Manual operation ignored: scan list is shutting down."
            )
            return
        if bool(getattr(scan_list, "runtime_mutation_sealed", False)):
            raise RuntimeError(
                "manual operation refused while a runtime device mutation is pending"
            )
        QtCore.QMetaObject.invokeMethod(
            self,
            "_run_manual_set_from_queue",
            QtCore.Qt.ConnectionType.BlockingQueuedConnection,
        )

    @QtCore.pyqtSlot()
    def _run_manual_set_from_queue(self):
        scan_list = getattr(self.main_window, "scanlist", None)
        if bool(getattr(scan_list, "_shutdown_sealed", False)):
            scan_list._log_warning(
                "Manual operation ignored: scan list is shutting down."
            )
            return
        if bool(getattr(scan_list, "runtime_mutation_sealed", False)):
            scan_list._log_warning(
                "Manual operation ignored: a runtime device mutation is pending."
            )
            return
        reservation = None
        reserve = getattr(self.main_window, "reserve_runtime_activity", None)
        if callable(reserve):
            reservation = reserve("manual", self.text())
        manual_started = False
        try:
            if scan_list is not None:
                scan_list._begin_manual_operation(self)
                manual_started = True
            value = self.parsed_value()
            self.main_window.write_info(value, self.channel_name)
        finally:
            if manual_started:
                scan_list._end_manual_operation(self)
            if reservation is not None:
                reservation.release()


class ScanListWidget(QtWidgets.QWidget):

    def __init__(
        self,
        allow_swap=True,
        allow_add=True,
        info=None,
        setter_equipment_info=None,
        getter_equipment_info=None,
        on_item_cloned=None,
        accept_scan_items=True,
    ):
        super().__init__()
        self.setAcceptDrops(True)
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        self.allow_swap = allow_swap
        self.allow_add = allow_add
        self.setter_equipment_info = copy.deepcopy(setter_equipment_info or {})
        self.getter_equipment_info = copy.deepcopy(getter_equipment_info or {})
        self.on_item_cloned = on_item_cloned
        self.accept_scan_items = accept_scan_items

    def setter_equipment_info_updated(self, info):
        self.refresh_catalog(info, self.getter_equipment_info)

    def getter_equipment_info_updated(self, info):
        self.refresh_catalog(self.setter_equipment_info, info)

    def refresh_catalog(
        self,
        setter_equipment_info,
        getter_equipment_info,
        *,
        refresh_items=True,
    ):
        """Replace clone-source catalogs and optionally refresh contained scans."""
        self.setter_equipment_info = copy.deepcopy(setter_equipment_info or {})
        self.getter_equipment_info = copy.deepcopy(getter_equipment_info or {})
        if not refresh_items:
            return
        for item in self.get_widgets():
            if isinstance(item, ScanItem):
                item.refresh_catalog(
                    self.setter_equipment_info,
                    self.getter_equipment_info,
                )

    def dragEnterEvent(self, e):
        e.accept()

    def dropEvent(self, e):
        widget = e.source()
        pos = e.position()
        self_swap = False

        i = 0
        for i in range(self.layout.count()):
            if widget == self.layout.itemAt(i).widget():
                self_swap = True
                break
        swap_originID = i
        if self_swap and (not self.allow_swap):
            return

        seperates = []
        for i in range(self.layout.count()):
            w = self.layout.itemAt(i).widget()
            seperates.append(w.y() + w.height() / 2)

        def find_index(y, ys):
            if ys == []:
                return 0
            if y < ys[0]:
                return 0
            if y > ys[-1]:
                return len(ys)
            for i in range(len(ys) - 1):
                if ys[i] <= y and y <= ys[i + 1]:
                    return i + 1

        i = find_index(pos.y(), seperates)
        if self_swap:
            if swap_originID < i:
                self.layout.insertWidget(i - 1, widget)
            else:
                self.layout.insertWidget(i, widget)
        else:
            if not self.allow_add:
                return
            if isinstance(widget, ScanItem) and (not self.accept_scan_items):
                return
            if type(widget) == ScanItem:
                new_item = self.clone_scan_item(widget)
                self.layout.insertWidget(
                    i,
                    new_item,
                )
                if callable(self.on_item_cloned):
                    self.on_item_cloned(new_item, self)
            elif type(widget) == ManualSetItem:
                main_window = widget.main_window
                new_item = ManualSetItem(
                    widget.channel_name, widget.value_text(), main_window=main_window
                )
                self.layout.insertWidget(i, new_item)
                if callable(self.on_item_cloned):
                    self.on_item_cloned(new_item, self)
        e.accept()

    def clone_scan_item(self, widget):
        """Clone a scan using this list's latest catalog publication."""
        return ScanItem(
            name=copy.deepcopy(widget.name),
            info=widget.snapshot_info(),
            setter_equipment_info=self.setter_equipment_info,
            main_window=widget.main_window,
            getter_equipment_info=self.getter_equipment_info,
        )

    def get_widgets(self):
        ans = []
        for i in range(self.layout.count()):
            ans.append(self.layout.itemAt(i).widget())
        return ans

    def add_item(self, item):
        self.layout.addWidget(item)

    def get_item_names(self):
        names = []
        for n in range(self.layout.count()):
            w = self.layout.itemAt(n).widget()
            names.append(w.name)
        return names


class ScanListLogic(QtCore.QThread):
    sig_scan_done = QtCore.pyqtSignal(object)
    sig_item_started = QtCore.pyqtSignal(object)
    sig_item_finished = QtCore.pyqtSignal(object)
    sig_queue_stopped = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.workers = []
        self.current_worker = None
        self.stop_after_current = False
        self.stop_now_requested = False

    def reset_control_flags(self):
        self.current_worker = None
        self.stop_after_current = False
        self.stop_now_requested = False

    def request_stop_after_current(self):
        self.stop_after_current = True

    def request_stop_now(self):
        self.stop_now_requested = True

    def run(self):
        stop_reason = ""
        while len(self.workers):
            if self.stop_now_requested:
                stop_reason = "stop_requested"
                break

            w = self.workers[0]
            self.workers.remove(w)
            self.current_worker = w

            start_ts = time.perf_counter()
            failed = False
            error_message = ""
            self.sig_item_started.emit(w)
            try:
                w.start_queue()
            except Exception as exc:
                failed = True
                name = getattr(w, "name", None)
                if name is None and hasattr(w, "text"):
                    name = w.text()
                error_message = f"{type(exc).__name__}: {exc}"
                print(f"[Queue] Skipping failed item ({type(w).__name__}): {name}. Error: {exc}")
                traceback.print_exc()
            finally:
                if isinstance(w, ScanItem):
                    run_error = getattr(w.scan, "_run_error_message", None)
                    if run_error:
                        failed = True
                        if error_message == "":
                            error_message = str(run_error)
                # Keep existing behavior: completed/processed item moves to past.
                self.sig_scan_done.emit(w)
                elapsed_seconds = max(0.0, time.perf_counter() - start_ts)
                self.sig_item_finished.emit(
                    {
                        "worker": w,
                        "elapsed_seconds": elapsed_seconds,
                        "failed": failed,
                        "error_message": error_message,
                    }
                )
                self.current_worker = None

            if self.stop_now_requested:
                stop_reason = "stop_requested"
                break
            if self.stop_after_current:
                stop_reason = "stop_after_current"
                break
            QtCore.QThread.sleep(2)

        if stop_reason == "":
            stop_reason = "completed"
        self.sig_queue_stopped.emit(stop_reason)


class ScanList(QtWidgets.QWidget):
    MAX_UI_LOG_LINES = 1000
    sig_info_changed = QtCore.pyqtSignal(object)
    start = QtCore.pyqtSignal(object)
    stop = QtCore.pyqtSignal(object)

    def __init__(
        self,
        info=None,
        setter_equipment_info=None,
        main_window=None,
        getter_equipment_info=None,
    ):
        super().__init__()
        uic.loadUi(r"core/ui/scanlist.ui", self)
        self.gridLayout.setColumnStretch(0, 1)  # available
        self.gridLayout.setColumnStretch(1, 0)  # separator line
        self.gridLayout.setColumnStretch(2, 1)  # queue
        self.gridLayout.setColumnStretch(3, 1)  # past/log column
        self.info = info
        self.setter_equipment_info = copy.deepcopy(setter_equipment_info or {})
        self.getter_equipment_info = copy.deepcopy(getter_equipment_info or {})
        self._channel_device_history = {}
        self._current_catalog_channels = set()
        self._current_setter_channels = set()
        self._current_getter_channels = set()
        self._remember_catalog_channels(
            self.setter_equipment_info,
            self.getter_equipment_info,
        )
        self.logic = ScanListLogic()
        self.main_window = main_window
        self._log_ready = False
        self._shutdown_complete = False
        self._shutdown_in_progress = False
        self._shutdown_sealed = False
        self._queue_run_started = False
        self._queue_completion_delivered = True
        self._runtime_mutation_sealed = False
        self._runtime_mutation_reason = ""
        self._runtime_mutation_widget_states = ()
        self._active_manual_operations = {}
        self._queue_activity_reservation = None

        self.logStatus_textEdit.setReadOnly(True)
        self.logStatus_textEdit.document().setMaximumBlockCount(self.MAX_UI_LOG_LINES)
        self.manual_set_menu = NestedMenu(order=1)
        self.manual_set_menu.label.hide()
        self.manual_set_menu.set_choices(self.setter_equipment_info or {})
        self.manual_set_menu.button.setText("Select channel")
        self.manual_channel_menu_layout.addWidget(self.manual_set_menu)

        self.list_available = ScanListWidget(
            info=self.info,
            setter_equipment_info=self.setter_equipment_info,
            getter_equipment_info=self.getter_equipment_info,
            on_item_cloned=self.on_item_cloned_between_lists,
        )
        for n, l in enumerate(["A", "B", "C", "D"]):
            si = ScanItem(
                name=l,
                info=self.info,
                setter_equipment_info=self.setter_equipment_info,
                main_window=self.main_window,
                getter_equipment_info=self.getter_equipment_info,
            )
            self.list_available.add_item(si)
            si.start.connect(self.start_scan)
            si.stop.connect(self.stop_scan)

        self.list_queue = ScanListWidget(
            info=self.info,
            setter_equipment_info=self.setter_equipment_info,
            getter_equipment_info=self.getter_equipment_info,
            on_item_cloned=self.on_item_cloned_between_lists,
        )
        self.list_manual = ScanListWidget(
            on_item_cloned=self.on_item_cloned_between_lists,
            accept_scan_items=False,
        )

        self.list_past = ScanListWidget(allow_swap=False, allow_add=False)

        self.scrollArea_available.setWidget(self.list_available)
        self.scrollArea_queue.setWidget(self.list_queue)
        self.scrollArea_action.setWidget(self.list_manual)
        self.scrollArea_past.setWidget(self.list_past)
        self.Layout_delete.insertWidget(0, DeleteItem(owner=self))

        self.start_pushButton.clicked.connect(self.start_queue)
        self.stop_pushButton.clicked.connect(self.stop_current_scan)
        self.stopAfter_pushButton.clicked.connect(self.stop_after_current_scan)
        self.pushButton_clear_past.clicked.connect(self.clear_past)
        self.logic.sig_scan_done.connect(self.add_to_past_scans)
        self.logic.sig_item_started.connect(self.on_queue_item_started)
        self.logic.sig_item_finished.connect(self.on_queue_item_finished)
        self.logic.sig_queue_stopped.connect(self.on_queue_stopped)
        self.logic.finished.connect(self._on_queue_thread_finished)
        self.pb_new_scan.clicked.connect(self.add_empty_scan_item)
        self.manual_add_item_pushButton.clicked.connect(self.add_manual_set_item_from_ui)
        self._log_ready = True

    def start_scan(self, info):
        if bool(getattr(self, "_shutdown_sealed", False)) or bool(
            getattr(self, "_runtime_mutation_sealed", False)
        ):
            if bool(getattr(self, "_runtime_mutation_sealed", False)):
                self._log_warning(
                    "Scan start ignored: a runtime device mutation is pending."
                )
            return
        self.start.emit(info)

    def stop_scan(self, scan):
        self.stop.emit(scan)

    def setter_equipment_info_updated(self, info):
        self.refresh_catalog(info, self.getter_equipment_info)

    def getter_equipment_info_updated(self, info):
        self.refresh_catalog(self.setter_equipment_info, info)

    def refresh_catalog(self, setter_equipment_info, getter_equipment_info):
        """Publish one display catalog to every current scan-list consumer."""
        old_setters = copy.deepcopy(self.setter_equipment_info)
        old_getters = copy.deepcopy(self.getter_equipment_info)
        old_channel_history = dict(self._channel_device_history)
        scan_items = tuple(self.iter_scan_items())

        try:
            self._apply_catalog_to_consumers(
                setter_equipment_info,
                getter_equipment_info,
                scan_items,
            )
        except Exception as refresh_error:
            rollback_failures = self._rollback_catalog_consumers(
                old_setters,
                old_getters,
                old_channel_history,
                scan_items,
            )
            if rollback_failures:
                raise ScanCatalogRollbackError(
                    refresh_error,
                    rollback_failures,
                ) from refresh_error
            raise

    def _apply_catalog_to_consumers(
        self,
        setter_equipment_info,
        getter_equipment_info,
        scan_items,
    ):
        self.setter_equipment_info = copy.deepcopy(setter_equipment_info or {})
        self.getter_equipment_info = copy.deepcopy(getter_equipment_info or {})
        self._remember_catalog_channels(
            self.setter_equipment_info,
            self.getter_equipment_info,
        )
        self._store_container_catalogs(
            self.setter_equipment_info,
            self.getter_equipment_info,
        )

        for item in scan_items:
            item.refresh_catalog(
                self.setter_equipment_info,
                self.getter_equipment_info,
            )
        self.manual_set_menu.set_choices(self.setter_equipment_info)

    def _store_container_catalogs(
        self,
        setter_equipment_info,
        getter_equipment_info,
    ):
        # Each list stores the source data used when it later drag-clones an
        # item. Update those snapshots without refreshing the same item twice.
        for container in (
            self.list_available,
            self.list_queue,
            self.list_manual,
            self.list_past,
        ):
            container.refresh_catalog(
                setter_equipment_info,
                getter_equipment_info,
                refresh_items=False,
            )

    def _rollback_catalog_consumers(
        self,
        old_setters,
        old_getters,
        old_channel_history,
        scan_items,
    ):
        failures = []
        self.setter_equipment_info = copy.deepcopy(old_setters)
        self.getter_equipment_info = copy.deepcopy(old_getters)
        self._channel_device_history = dict(old_channel_history)
        self._remember_catalog_channels(old_setters, old_getters)

        try:
            self._store_container_catalogs(old_setters, old_getters)
        except Exception as exc:
            failures.append(("scan-list containers", exc))

        for item in scan_items:
            try:
                item.refresh_catalog(old_setters, old_getters)
            except Exception as exc:
                name = str(getattr(item, "name", None) or "unnamed")
                failures.append((f"scan '{name}'", exc))

        try:
            self.manual_set_menu.set_choices(old_setters)
        except Exception as exc:
            failures.append(("manual-set menu", exc))
        return tuple(failures)

    def start_queue(self):
        if bool(getattr(self, "_shutdown_sealed", False)):
            self._log_warning("Queue start ignored: scan list is shutting down.")
            return
        if bool(getattr(self, "_runtime_mutation_sealed", False)):
            self._log_warning(
                "Queue start ignored: a runtime device mutation is pending."
            )
            return
        if self.logic.isRunning():
            self._log_warning("Queue start ignored: queue is already running.")
            return
        queues = self.list_queue.get_widgets()
        if len(queues) == 0:
            self._log_warning("Queue start ignored: queue is empty.")
            return

        reservation = None
        reserve = getattr(self.main_window, "reserve_runtime_activity", None)
        if callable(reserve):
            reservation = reserve("queue", f"{len(queues)} queued item(s)")
        self._queue_activity_reservation = reservation
        try:
            self.logic.reset_control_flags()
            self.logic.workers = queues
            self._queue_run_started = True
            self._queue_completion_delivered = False
            self.logic.start()
        except Exception:
            self._queue_run_started = False
            self._queue_completion_delivered = True
            self._queue_activity_reservation = None
            if reservation is not None:
                reservation.release()
            raise
        self._log_info(f"Queue started with {len(queues)} item(s).")

    def stop_current_scan(self):
        if not self.logic.isRunning():
            self._log_warning("Stop ignored: queue is not running.")
            return

        self.logic.request_stop_now()
        current_worker = self.logic.current_worker
        if isinstance(current_worker, ScanItem):
            QtCore.QMetaObject.invokeMethod(
                current_worker,
                "_request_stop_from_queue",
                QtCore.Qt.ConnectionType.QueuedConnection,
            )
            self._log_warning(
                f"Stop requested for current scan item '{current_worker.name}'."
            )
        elif current_worker is not None:
            self._log_warning(
                f"Stop requested during current item '{self.worker_display_name(current_worker)}'."
            )
        else:
            self._log_warning("Stop requested: queue will stop before next item.")

    def stop_after_current_scan(self):
        if not self.logic.isRunning():
            self._log_warning("Stop-after ignored: queue is not running.")
            return
        self.logic.request_stop_after_current()
        self._log_info("Queue will stop after the current item.")

    def check(self):
        for i, w in enumerate(self.list_queue.get_widgets()):
            print(i, hex(id(w)), w.scan.info, hex(id(w.scan)), w.text())

    def add_to_past_scans(self, w):
        self.list_past.layout.addWidget(w)

    def on_queue_item_started(self, worker):
        self._log_info(f"Queue item started: {self.worker_display_name(worker)}")

    def on_queue_item_finished(self, payload):
        worker = payload.get("worker")
        elapsed = float(payload.get("elapsed_seconds", 0.0))
        failed = bool(payload.get("failed", False))
        error_message = str(payload.get("error_message", "")).strip()

        item_label = self.worker_display_name(worker)
        if failed:
            if error_message:
                self._log_error(
                    f"Queue item failed: {item_label} | elapsed={elapsed:.1f}s | error={error_message}"
                )
            else:
                self._log_error(
                    f"Queue item failed: {item_label} | elapsed={elapsed:.1f}s"
                )
        else:
            self._log_info(
                f"Queue item finished: {item_label} | elapsed={elapsed:.1f}s"
            )

    def on_queue_stopped(self, reason):
        if reason == "completed":
            self._log_info("Queue completed.")
        elif reason == "stop_after_current":
            self._log_warning("Queue stopped after current item.")
        elif reason == "stop_requested":
            self._log_warning("Queue stopped by stop request.")
        else:
            self._log_warning(f"Queue stopped: {reason}")

    @QtCore.pyqtSlot()
    def _on_queue_thread_finished(self):
        # This queued acknowledgement is emitted after the queue's earlier UI
        # signals, so shutdown can prove those mutations have been delivered.
        self._queue_completion_delivered = True
        reservation = getattr(self, "_queue_activity_reservation", None)
        self._queue_activity_reservation = None
        if reservation is not None:
            reservation.release()

    def handle_delete_request(self, widget):
        if isinstance(widget, ScanItem):
            if widget.scan.logic.isRunning():
                QtWidgets.QMessageBox.warning(
                    self,
                    "Scan Running",
                    "This scan is currently running and cannot be deleted.",
                )
                return
            self._remove_widget_from_parent_layout(widget)
            widget.deleteLater()
            return

        if isinstance(widget, ManualSetItem):
            self._remove_widget_from_parent_layout(widget)
            widget.deleteLater()

    def _remove_widget_from_parent_layout(self, widget):
        parent_widget = widget.parentWidget()
        if parent_widget is None:
            return

        layout_obj = getattr(parent_widget, "layout", None)
        if callable(layout_obj):
            layout_obj = layout_obj()
        if layout_obj is not None:
            layout_obj.removeWidget(widget)

    def on_item_cloned_between_lists(self, item, target_list):
        if bool(getattr(self, "_runtime_mutation_sealed", False)):
            target_list.layout.removeWidget(item)
            item.deleteLater()
            self._log_warning(
                "Scan clone ignored: a runtime device mutation is pending."
            )
            return
        if bool(getattr(self, "_shutdown_sealed", False)):
            item.scan._shutdown_requested = True
            item.scan._start_new_scan_after_stop = False

    def clear_past(self):
        for i, w in enumerate(self.list_past.get_widgets()):
            self.list_past.layout.removeWidget(w)
            w.deleteLater()

    def add_empty_scan_item(self):
        if bool(getattr(self, "_shutdown_sealed", False)) or bool(
            getattr(self, "_runtime_mutation_sealed", False)
        ):
            return
        si = ScanItem(
            name="New Scan",
            info=self.info,
            setter_equipment_info=self.setter_equipment_info,
            main_window=self.main_window,
            getter_equipment_info=self.getter_equipment_info,
        )
        self.list_available.add_item(si)
        # self.available_info.append(si.info)

    def add_empty_manual_set_item(self):
        if bool(getattr(self, "_shutdown_sealed", False)) or bool(
            getattr(self, "_runtime_mutation_sealed", False)
        ):
            return
        item = ManualSetItem("default_wait", 0.0, main_window=self.main_window)
        self.list_manual.add_item(item)

    def add_manual_set_item_from_ui(self):
        if bool(getattr(self, "_shutdown_sealed", False)) or bool(
            getattr(self, "_runtime_mutation_sealed", False)
        ):
            return
        channel_name = str(getattr(self.manual_set_menu, "name", "")).strip()
        if channel_name in {"", "none", "void"}:
            self._log_warning("Manual-set add ignored: no channel selected.")
            return
        value = float(self.manual_set_value_spinbox.value())
        item = ManualSetItem(channel_name, value, main_window=self.main_window)
        self.list_manual.add_item(item)

    def worker_display_name(self, worker):
        if isinstance(worker, ScanItem):
            return f"scan '{worker.name}'"
        if isinstance(worker, ManualSetItem):
            return f"manual-set '{worker.text()}'"
        return f"{type(worker).__name__}"

    def _timestamp_now(self) -> str:
        return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _append_log_entry(self, message: str, *, level="INFO"):
        if not self._log_ready:
            return
        level_text = str(level).upper()
        if level_text not in {"INFO", "WARNING", "ERROR"}:
            level_text = "INFO"
        line = f"[{self._timestamp_now()}] [{level_text}] {message}"
        self.logStatus_textEdit.append(line)

    def _log_info(self, message: str):
        self._append_log_entry(message, level="INFO")

    def _log_warning(self, message: str):
        self._append_log_entry(message, level="WARNING")

    def _log_error(self, message: str):
        self._append_log_entry(message, level="ERROR")
        
    @staticmethod
    def _catalog_leaf_names(value, path=()):
        if isinstance(value, (list, tuple)):
            for entry in value:
                yield from ScanList._catalog_leaf_names(entry, path)
            return
        if isinstance(value, dict):
            for key, child in value.items():
                next_path = (*path, str(key))
                if isinstance(child, int):
                    yield "_".join(next_path)
                else:
                    yield from ScanList._catalog_leaf_names(child, next_path)
            return
        if value is not None:
            yield "_".join((*path, str(value)))

    def _remember_catalog_channels(
        self,
        setter_equipment_info,
        getter_equipment_info,
    ):
        current_by_access = {"set": set(), "get": set()}
        for access, catalog in (
            ("set", setter_equipment_info or {}),
            ("get", getter_equipment_info or {}),
        ):
            if not isinstance(catalog, dict):
                continue
            for device_id, choices in catalog.items():
                for local_channel in self._catalog_leaf_names(choices):
                    full_channel = f"{device_id}_{local_channel}"
                    current_by_access[access].add(full_channel)
                    self._channel_device_history.setdefault(
                        full_channel,
                        str(device_id),
                    )
        self._current_setter_channels = current_by_access["set"]
        self._current_getter_channels = current_by_access["get"]
        self._current_catalog_channels = (
            self._current_setter_channels | self._current_getter_channels
        )

    def _items_with_locations(self):
        """Snapshot every scan/manual item once with a deterministic location."""
        located_items = []
        seen = set()

        def append_items(collection, widgets):
            for widget in widgets:
                if not isinstance(widget, (ScanItem, ManualSetItem)):
                    continue
                if id(widget) in seen:
                    continue
                seen.add(id(widget))
                located_items.append((collection, widget))

        for collection, attribute_name in (
            ("available", "list_available"),
            ("queue", "list_queue"),
            ("past", "list_past"),
            ("manual", "list_manual"),
        ):
            container = getattr(self, attribute_name, None)
            if container is None:
                continue
            try:
                append_items(collection, container.get_widgets())
            except RuntimeError:
                continue

        append_items("active", (getattr(self.logic, "current_worker", None),))
        try:
            append_items("queue_worker", tuple(getattr(self.logic, "workers", ())))
        except RuntimeError:
            pass
        return tuple(located_items)

    def iter_scan_items(self):
        """Iterate every live scan item once, including detached queue workers."""
        return iter(
            tuple(
                item
                for _collection, item in self._items_with_locations()
                if isinstance(item, ScanItem)
            )
        )

    def iter_manual_set_items(self):
        """Iterate manual items in manual/queue/past and detached worker state."""
        return iter(
            tuple(
                item
                for _collection, item in self._items_with_locations()
                if isinstance(item, ManualSetItem)
            )
        )

    def reference_uses(self):
        """Return all live channel references without rewriting definitions."""
        uses = []
        template_info = self.info if isinstance(self.info, dict) else {}
        template_name = str(template_info.get("name", "New Scan") or "New Scan")
        for reference in Scan.channel_references_from_info(template_info):
            uses.append(
                self._make_reference_use(
                    collection="available-template",
                    owner_kind="scan-template",
                    owner_name=template_name,
                    kind=reference.kind,
                    access=reference.access,
                    level=reference.level,
                    channel=reference.channel,
                    path=reference.path,
                )
            )

        for collection, item in self._items_with_locations():
            if isinstance(item, ScanItem):
                try:
                    owner_name = str(
                        item.scan.lineEdit.text()
                        or getattr(item, "name", "")
                        or "unnamed"
                    )
                    channel_references = item.scan.channel_references()
                except RuntimeError as exc:
                    if "wrapped C/C++ object" in str(exc):
                        continue
                    raise
                for reference in channel_references:
                    uses.append(
                        self._make_reference_use(
                            collection=collection,
                            owner_kind="scan",
                            owner_name=owner_name,
                            kind=reference.kind,
                            access=reference.access,
                            level=reference.level or None,
                            channel=reference.channel,
                            path=reference.path,
                        )
                    )
                continue

            channel = str(item.channel_name).strip()
            if channel == "" or channel.lower() in {"none", "void"}:
                continue
            uses.append(
                self._make_reference_use(
                    collection=collection,
                    owner_kind="manual-set",
                    owner_name=item.text(),
                    kind="manual_set_item",
                    access="set",
                    level=None,
                    channel=channel,
                    path="channel_name",
                )
            )
        return tuple(uses)

    def _make_reference_use(
        self,
        *,
        collection,
        owner_kind,
        owner_name,
        kind,
        access,
        level,
        channel,
        path,
    ):
        return ReferenceUse(
            device_id=self._channel_device_history.get(channel),
            kind=kind,
            access=access,
            collection=collection,
            owner_kind=owner_kind,
            owner_name=owner_name,
            level=level,
            channel=channel,
            path=path,
            resolved=channel in (
                self._current_setter_channels
                if access == "set"
                else self._current_getter_channels
            ),
        )

    def find_channel_references(
        self,
        *,
        removed_setters=(),
        removed_getters=(),
    ):
        """Find exact direction-aware uses of channels proposed for removal."""
        removed_setters = frozenset(removed_setters)
        removed_getters = frozenset(removed_getters)
        return tuple(
            use
            for use in self.reference_uses()
            if (
                use.access == "set"
                and use.channel in removed_setters
            )
            or (
                use.access == "get"
                and use.channel in removed_getters
            )
        )

    def find_device_references(self, device_id):
        """Return references attributed to an exact catalog device ID."""
        device_id = str(device_id)
        return tuple(
            use for use in self.reference_uses() if use.device_id == device_id
        )

    def catalog_mutation_blockers(self):
        """Describe active queue/scan work that blocks catalog publication."""
        blockers = []
        if bool(getattr(self, "_shutdown_sealed", False)) and not bool(
            getattr(self, "_shutdown_complete", False)
        ):
            blockers.append("scan-list shutdown retry pending")
        if self.logic.isRunning():
            blockers.append("queue thread")
        if (
            self._queue_run_started
            and not self._queue_completion_delivered
        ):
            blockers.append("queue UI completion")
        blockers.extend(
            f"manual operation '{description}'"
            for description in getattr(
                self, "_active_manual_operations", {}
            ).values()
        )
        for item in self.iter_scan_items():
            try:
                name = str(
                    item.scan.lineEdit.text()
                    or getattr(item, "name", "")
                    or "unnamed"
                )
                if item.scan.logic.isRunning():
                    blockers.append(f"scan thread '{name}'")
                elif not item.scan.outputs_finalized:
                    blockers.append(f"scan output finalizer '{name}'")
            except RuntimeError as exc:
                if "wrapped C/C++ object" not in str(exc):
                    raise
        return tuple(blockers)

    @property
    def runtime_mutation_sealed(self):
        return bool(getattr(self, "_runtime_mutation_sealed", False))

    def _begin_manual_operation(self, item):
        operations = getattr(self, "_active_manual_operations", None)
        if operations is None:
            operations = {}
            self._active_manual_operations = operations
        operations[id(item)] = self.worker_display_name(item)

    def _end_manual_operation(self, item):
        getattr(self, "_active_manual_operations", {}).pop(id(item), None)

    def set_runtime_mutation_sealed(self, sealed, reason=""):
        """Prevent new scan/manual work while the manager mutates its catalog.

        Mutation is admitted only from an idle state, so disabling the current
        editors cannot hide a running stop control.  Programmatic scan starts
        are also sealed through each Scan's existing start guard.
        """

        sealed = bool(sealed)
        if sealed == bool(getattr(self, "_runtime_mutation_sealed", False)):
            if sealed and reason:
                self._runtime_mutation_reason = str(reason)
            return

        self._runtime_mutation_sealed = sealed
        self._runtime_mutation_reason = str(reason) if sealed else ""
        if sealed:
            states = []
            self._runtime_mutation_widget_states = ()
            try:
                for item in self.iter_scan_items():
                    scan = item.scan
                    states.append(
                        (
                            scan,
                            scan.isEnabled(),
                            bool(getattr(scan, "_shutdown_requested", False)),
                        )
                    )
                    scan._shutdown_requested = True
                    scan.setEnabled(False)
                states.append((self, self.isEnabled(), None))
                self.setEnabled(False)
            except Exception as seal_error:
                rollback_failures = []
                for widget, was_enabled, previous_shutdown_requested in reversed(states):
                    try:
                        if previous_shutdown_requested is not None:
                            widget._shutdown_requested = previous_shutdown_requested
                        widget.setEnabled(was_enabled)
                    except Exception as restore_error:
                        if "wrapped C/C++ object" not in str(restore_error):
                            rollback_failures.append(restore_error)
                self._runtime_mutation_sealed = False
                self._runtime_mutation_reason = ""
                if rollback_failures:
                    details = "; ".join(
                        f"{type(error).__name__}: {error}"
                        for error in rollback_failures
                    )
                    raise RuntimeError(
                        "runtime mutation scan-list seal failed and rollback "
                        f"was incomplete: {details}"
                    ) from seal_error
                raise
            self._runtime_mutation_widget_states = tuple(states)
            return

        states = getattr(self, "_runtime_mutation_widget_states", ())
        self._runtime_mutation_widget_states = ()
        restore_failures = []
        shutdown_sealed = bool(getattr(self, "_shutdown_sealed", False))
        for widget, was_enabled, previous_shutdown_requested in states:
            try:
                if previous_shutdown_requested is not None:
                    widget._shutdown_requested = (
                        True
                        if shutdown_sealed
                        else previous_shutdown_requested
                    )
                widget.setEnabled(False if shutdown_sealed else was_enabled)
            except Exception as exc:
                if "wrapped C/C++ object" not in str(exc):
                    restore_failures.append(exc)
        if restore_failures:
            details = "; ".join(
                f"{type(error).__name__}: {error}" for error in restore_failures
            )
            raise RuntimeError(
                f"runtime mutation UI restoration failed: {details}"
            )

    def is_idle_for_catalog_mutation(self):
        return not self.catalog_mutation_blockers()

    def _scan_items_snapshot(self):
        """Compatibility snapshot used by the shutdown safety barrier."""
        return list(self.iter_scan_items())

    def _seal_scan_item_for_shutdown(self, item):
        try:
            item.scan._shutdown_requested = True
            item.scan._start_new_scan_after_stop = False
        except RuntimeError as exc:
            if "wrapped C/C++ object" not in str(exc):
                raise

    def _request_scan_stop_for_shutdown(self, item):
        """Clear restart state and request stop in the scan item's Qt thread."""
        try:
            if item.thread() == QtCore.QThread.currentThread():
                item._request_stop_from_queue()
            else:
                QtCore.QMetaObject.invokeMethod(
                    item,
                    "_request_stop_from_queue",
                    QtCore.Qt.ConnectionType.BlockingQueuedConnection,
                )
        except RuntimeError as exc:
            # The item may have been deleted by an already-queued UI action.
            if "wrapped C/C++ object" in str(exc):
                return
            raise

    def _shutdown_pending(self, scan_items):
        pending = []
        if self.logic.isRunning():
            pending.append("queue thread")
        if (
            getattr(self, "_queue_run_started", False)
            and not getattr(self, "_queue_completion_delivered", True)
        ):
            pending.append("queue UI completion")
        pending.extend(
            f"manual operation '{description}'"
            for description in getattr(
                self, "_active_manual_operations", {}
            ).values()
        )

        for item in scan_items:
            try:
                scan = item.scan
                name = str(getattr(item, "name", None) or item.text() or "unnamed")
                if scan.logic.isRunning():
                    pending.append(f"scan thread '{name}'")
                outputs_finalized = getattr(scan, "outputs_finalized", None)
                if outputs_finalized is None:
                    outputs_finalized = (
                        getattr(scan, "_outputs_finalized", True)
                        and not getattr(scan, "_finalize_outputs_scheduled", False)
                    )
                if not outputs_finalized:
                    pending.append(f"output finalizer '{name}'")
            except RuntimeError as exc:
                if "wrapped C/C++ object" not in str(exc):
                    raise
        return pending

    def _close_scan_widgets(self, scan_items):
        for item in scan_items:
            try:
                item.scan.close()
            except RuntimeError:
                pass

    # ---------- public API ----------
    def shutdown(self, timeout_ms=30_000):
        """
        Stop queue/scan work, finish pending outputs, then close scan widgets.

        This method must be called from the GUI thread. The timeout is a
        cooperative deadline: Qt callbacks already executing on the GUI thread
        cannot be preempted, but an over-budget callback causes a typed timeout
        before any widget closes or application-level device teardown begins.
        A timeout or stop-request failure leaves the session sealed against new
        scan/manual work until shutdown is retried. This method never terminates
        devices itself.
        """
        if self.thread() != QtCore.QThread.currentThread():
            raise ScanListShutdownThreadError(
                "ScanList.shutdown() must run in the scan list's Qt owner thread."
            )
        if self._shutdown_complete:
            return
        if self._shutdown_in_progress:
            raise ScanListShutdownInProgressError(
                "ScanList.shutdown() is already waiting for quiescence."
            )

        timeout_ms = max(0, int(timeout_ms))
        # A failed attempt remains sealed: resuming only part of the old/new
        # queue after a timeout would permit device writes in an uncertain state.
        self._shutdown_sealed = True
        self._shutdown_in_progress = True
        scan_items = []
        seen_items = set()
        stop_requested_while_running = set()
        stop_request_failures = {}
        stable_quiescent_passes = 0
        timer = QtCore.QElapsedTimer()
        timer.start()

        try:
            if self.logic.isRunning():
                self._queue_run_started = True
                self._queue_completion_delivered = False

            while True:
                # Reassert after every nested event-loop pass in case queue
                # startup had already been posted before shutdown began.
                if not getattr(self.logic, "stop_now_requested", False):
                    self.logic.request_stop_now()

                # Queue signals can move an item between lists while events are
                # pumped, so merge fresh snapshots into one deduplicated set.
                for item in self._scan_items_snapshot():
                    if id(item) not in seen_items:
                        seen_items.add(id(item))
                        scan_items.append(item)

                currently_running = set()
                for item in scan_items:
                    try:
                        self._seal_scan_item_for_shutdown(item)
                        if item.scan.logic.isRunning():
                            item_id = id(item)
                            currently_running.add(item_id)
                            if item_id not in stop_requested_while_running:
                                try:
                                    self._request_scan_stop_for_shutdown(item)
                                except Exception as exc:
                                    name = str(
                                        getattr(item, "name", None)
                                        or item.text()
                                        or "unnamed"
                                    )
                                    stop_request_failures.setdefault(
                                        item_id, (name, exc)
                                    )
                                stop_requested_while_running.add(item_id)
                    except RuntimeError as exc:
                        if "wrapped C/C++ object" not in str(exc):
                            raise
                stop_requested_while_running.intersection_update(currently_running)

                app = QtCore.QCoreApplication.instance()
                if app is not None:
                    app.processEvents(
                        QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
                    )

                new_items_after_events = False
                for item in self._scan_items_snapshot():
                    if id(item) in seen_items:
                        continue
                    seen_items.add(id(item))
                    scan_items.append(item)
                    self._seal_scan_item_for_shutdown(item)
                    new_items_after_events = True

                if self.logic.isRunning():
                    self._queue_run_started = True
                    self._queue_completion_delivered = False

                pending = self._shutdown_pending(scan_items)
                elapsed_ms = timer.elapsed()
                deadline_exceeded = elapsed_ms > timeout_ms or (
                    (pending or new_items_after_events) and elapsed_ms >= timeout_ms
                )
                if deadline_exceeded:
                    if not pending:
                        if new_items_after_events:
                            pending = ["scan-list mutation during shutdown"]
                        else:
                            pending = ["GUI callback exceeded shutdown deadline"]
                    raise ScanListShutdownTimeoutError(timeout_ms, pending)

                if pending or new_items_after_events:
                    stable_quiescent_passes = 0
                else:
                    stable_quiescent_passes += 1
                    # A second empty pump drains work posted by the first pass,
                    # including deferred finalizers and queue UI signals.
                    if stable_quiescent_passes >= 2:
                        break

                # Let worker threads advance without monopolizing the GUI CPU;
                # the next iteration immediately pumps Qt events again.
                QtCore.QThread.msleep(5)

            if stop_request_failures:
                raise ScanListShutdownStopError(stop_request_failures.values())

            self._close_scan_widgets(scan_items)
            super().close()
            self._shutdown_complete = True
        finally:
            self._shutdown_in_progress = False


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = ScanList()
    window.show()
    app.exec()
