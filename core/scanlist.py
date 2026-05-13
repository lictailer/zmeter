import sys
import copy
import time
import datetime as _dt
import traceback
import PyQt6.QtWidgets as QtWidgets
import PyQt6.QtCore as QtCore
import PyQt6.QtGui as QtGui
from PyQt6 import uic
from .scan import Scan
from .nested_menu import NestedMenu


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
        QtCore.QMetaObject.invokeMethod(
            self,
            "_run_manual_set_from_queue",
            QtCore.Qt.ConnectionType.BlockingQueuedConnection,
        )

    @QtCore.pyqtSlot()
    def _run_manual_set_from_queue(self):
        value = self.parsed_value()
        self.main_window.write_info(value, self.channel_name)


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
        self.setter_equipment_info = setter_equipment_info
        self.getter_equipment_info = getter_equipment_info
        self.on_item_cloned = on_item_cloned
        self.accept_scan_items = accept_scan_items

    def setter_equipment_info_updated(self, info):
        for i in range(self.layout.count()):
            item = self.layout.itemAt(i).widget()
            if type(item) == ScanItem:
                print("hellow")
                item.scan.when_setter_equipment_info_change(info)

    def getter_equipment_info_updated(self, info):
        for i in range(self.layout.count()):
            item = self.layout.itemAt(i).widget()
            if type(item) == ScanItem:
                item.scan.when_getter_equipment_info_change(info)

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
                plot_setting_info = widget.snapshot_info()
                name = copy.deepcopy(widget.name)
                main_window = widget.main_window
                new_item = ScanItem(
                    name=name,
                    info=plot_setting_info,
                    setter_equipment_info=self.setter_equipment_info,
                    main_window=main_window,
                    getter_equipment_info=self.getter_equipment_info,
                )
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
        self.setter_equipment_info = setter_equipment_info
        self.getter_equipment_info = getter_equipment_info
        self.logic = ScanListLogic()
        self.main_window = main_window
        self._log_ready = False

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
        self.pb_new_scan.clicked.connect(self.add_empty_scan_item)
        self.manual_add_item_pushButton.clicked.connect(self.add_manual_set_item_from_ui)
        self._log_ready = True

    def start_scan(self, info):
        self.start.emit(info)

    def stop_scan(self, scan):
        self.stop.emit(scan)

    def setter_equipment_info_updated(self, info):
        self.setter_equipment_info = info
        self.list_available.setter_equipment_info_updated(self.setter_equipment_info)
        self.list_queue.setter_equipment_info_updated(self.setter_equipment_info)
        self.manual_set_menu.set_choices(self.setter_equipment_info or {})
        self.manual_set_menu.name = ""
        self.manual_set_menu.button.setText("Select channel")

    def getter_equipment_info_updated(self, info):
        self.getter_equipment_info = info
        self.list_available.getter_equipment_info_updated(self.getter_equipment_info)
        self.list_queue.getter_equipment_info_updated(self.getter_equipment_info)

    def start_queue(self):
        if self.logic.isRunning():
            self._log_warning("Queue start ignored: queue is already running.")
            return
        queues = self.list_queue.get_widgets()
        if len(queues) == 0:
            self._log_warning("Queue start ignored: queue is empty.")
            return

        self.logic.reset_control_flags()
        self.logic.workers = queues
        self.logic.start()
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

    def on_item_cloned_between_lists(self, item, _target_list):
        pass

    def clear_past(self):
        for i, w in enumerate(self.list_past.get_widgets()):
            self.list_past.layout.removeWidget(w)
            w.deleteLater()

    def add_empty_scan_item(self):
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
        item = ManualSetItem("default_wait", 0.0, main_window=self.main_window)
        self.list_manual.add_item(item)

    def add_manual_set_item_from_ui(self):
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
        
    def _cleanup(self):
        """Close every Scan window and stop the worker thread."""
        for container in (self.list_available,
                          self.list_queue,
                          self.list_past):
            for w in container.get_widgets():
                if isinstance(w, ScanItem):
                    try:
                        w.scan.close()
                    except RuntimeError:
                        pass

        if self.logic.isRunning():
            self.logic.requestInterruption()
            self.logic.quit()
            self.logic.wait()

    # ---------- public API ----------
    def shutdown(self):
        """
        Call this *from your code* when you really want to
        tear everything down and then close the main widget.
        """
        self._cleanup()
        super().close()            # now close normally


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = ScanList()
    window.show()
    app.exec()
