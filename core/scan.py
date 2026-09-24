import datetime as _dt
import copy
from dataclasses import dataclass
import json
import re
import time
import traceback
from .scan_info import *
from .scan_logic import ScanLogic
from .all_level import AllLevelSetting
from .all_plot_settings import AllPlotSetting
from .all_plots import AllPlots
from .construct_scan_coordinates import Construct
from .all_plots import LinePlot
from .all_plots import ImagePlot
import os, shutil
from .append_to_ppt import add_slide_with_png_bytes, add_slide_with_qpixmap


_AVERAGE_GETTER_REFERENCE = re.compile(r"^level(\d+)_average_(.+)$")
_PLOT_CHANNEL_REFERENCE = re.compile(r"^L\d+([SG])\d+_(.+)$")


@dataclass(frozen=True)
class ScanChannelReference:
    """One channel occurrence retained by a live scan definition."""

    kind: str
    access: str
    level: str | None
    channel: str
    path: str


@dataclass(frozen=True)
class _CapturedImage:
    png: bytes
    width: int
    height: int


@dataclass(frozen=True)
class _OutputSlide:
    title: str
    text: str
    images: tuple[_CapturedImage, ...]
    positions: tuple[tuple[int, int, int, int], ...] | None = None
    comments: str = ""


@dataclass(frozen=True)
class _ScanOutputSnapshot:
    ppt_path: str | None
    slides: tuple[_OutputSlide, ...]
    json_path: str | None
    json_payload: dict
    json_name: str
    backup_dir: str
    recovery_dir: str


@dataclass(frozen=True)
class _BoundaryOutcome:
    value: object = None
    error: Exception | None = None
    traceback_text: str = ""


@dataclass(frozen=True)
class _OutputJobResult:
    messages: tuple[tuple[str, str], ...]
    timings: tuple[tuple[str, float], ...]
    restore_error: Exception | None = None


@dataclass(frozen=True)
class _PrepareJobResult:
    device_elapsed: float
    data_elapsed: float = 0.0
    error: Exception | None = None
    restore_error: Exception | None = None


class _ScanJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, float) and np.isnan(obj):
            return "NaN"
        return super().default(obj)


class _BoundaryWorker(QtCore.QObject):
    done = QtCore.pyqtSignal()

    def __init__(self, operation):
        super().__init__()
        self._operation = operation
        self.outcome = None

    @QtCore.pyqtSlot()
    def run(self):
        try:
            self.outcome = _BoundaryOutcome(value=self._operation())
        except Exception as exc:
            self.outcome = _BoundaryOutcome(
                error=exc,
                traceback_text=traceback.format_exc(),
            )
        finally:
            self.done.emit()


def _write_json_payload(path, payload):
    with open(path, "w", encoding="utf-8") as json_file:
        json.dump(payload, json_file, cls=_ScanJSONEncoder, indent=4)


def _write_recovery_payload(snapshot, messages):
    temporary_path = None
    try:
        os.makedirs(snapshot.recovery_dir, exist_ok=True)
        safe_name = re.sub(
            r"[^A-Za-z0-9._-]+", "_", str(snapshot.json_name or "scan.json")
        ).strip("._") or "scan.json"
        if not safe_name.lower().endswith(".json"):
            safe_name = f"{safe_name}.json"
        timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        stem = f"recovery_{timestamp}_{safe_name}"
        recovery_path = os.path.join(snapshot.recovery_dir, stem)
        count = 1
        while os.path.exists(recovery_path):
            name_part, extension = os.path.splitext(stem)
            recovery_path = os.path.join(
                snapshot.recovery_dir, f"{name_part}_{count}{extension}"
            )
            count += 1

        temporary_path = f"{recovery_path}.{os.getpid()}.tmp"
        _write_json_payload(temporary_path, snapshot.json_payload)
        os.replace(temporary_path, recovery_path)
        messages.append(("WARNING", f"Recovery JSON saved: {recovery_path}"))
    except Exception as exc:
        if temporary_path and os.path.exists(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                pass
        messages.append(
            (
                "ERROR",
                f"Recovery JSON save failed: {type(exc).__name__}: {exc}",
            )
        )


def _persist_scan_outputs(snapshot):
    """Persist one immutable completion snapshot without touching Qt widgets."""
    messages = []
    timings = []
    json_path = snapshot.json_path
    resolved_json_name = snapshot.json_name
    if json_path is not None:
        try:
            folder, selected_name = os.path.split(json_path)
            resolved_json_name = selected_name or snapshot.json_name
            candidate = json_path
            count = 1
            while os.path.exists(candidate):
                name_part, extension = os.path.splitext(resolved_json_name)
                candidate = os.path.join(
                    folder, f"{name_part}_{count}{extension}"
                )
                count += 1
            json_path = candidate
            resolved_json_name = os.path.basename(candidate)
        except Exception as exc:
            json_path = None
            messages.append(
                (
                    "ERROR",
                    "Primary JSON path preparation failed; writing recovery JSON: "
                    f"{type(exc).__name__}: {exc}",
                )
            )

    if snapshot.ppt_path:
        ppt_written = False
        started = time.perf_counter()
        try:
            ppt_folder = os.path.dirname(snapshot.ppt_path)
            if ppt_folder:
                os.makedirs(ppt_folder, exist_ok=True)
            for slide in snapshot.slides:
                slide_title = slide.title
                if resolved_json_name != snapshot.json_name:
                    slide_title = slide_title.replace(
                        snapshot.json_name, resolved_json_name, 1
                    )
                add_slide_with_png_bytes(
                    ppt_path=snapshot.ppt_path,
                    slide_title=slide_title,
                    slide_text=slide.text,
                    png_images=tuple(image.png for image in slide.images),
                    image_sizes=tuple(
                        (image.width, image.height) for image in slide.images
                    ),
                    image_positions=slide.positions,
                    comments_text=slide.comments,
                )
            messages.append(
                (
                    "INFO",
                    f"PPT save succeeded: {snapshot.ppt_path} "
                    f"({len(snapshot.slides)} slide(s))",
                )
            )
            ppt_written = True
        except Exception as exc:
            messages.append(
                ("ERROR", f"PPT save failed: {type(exc).__name__}: {exc}")
            )
        timings.append(("PPT write", time.perf_counter() - started))

        started = time.perf_counter()
        if not ppt_written:
            pass
        elif os.path.exists("Z:\\"):
            if snapshot.backup_dir:
                try:
                    os.makedirs(snapshot.backup_dir, exist_ok=True)
                    backup_target = os.path.join(
                        snapshot.backup_dir, os.path.basename(snapshot.ppt_path)
                    )
                    shutil.copy2(snapshot.ppt_path, backup_target)
                    messages.append(("INFO", f"PPT backup succeeded: {backup_target}"))
                except Exception as exc:
                    messages.append(
                        (
                            "WARNING",
                            f"PPT backup failed: {type(exc).__name__}: {exc}",
                        )
                    )
            else:
                messages.append(("WARNING", "PPT backup skipped: backup path is empty."))
        else:
            messages.append(("WARNING", "PPT backup skipped: drive Z: not found."))
        timings.append(("PPT backup copy", time.perf_counter() - started))

    started = time.perf_counter()
    json_written = False
    if json_path is None:
        messages.append(
            ("WARNING", "Manual save canceled by user; writing recovery JSON.")
        )
        _write_recovery_payload(snapshot, messages)
    else:
        try:
            json_folder = os.path.dirname(json_path)
            if json_folder:
                os.makedirs(json_folder, exist_ok=True)
            _write_json_payload(json_path, snapshot.json_payload)
            messages.append(("INFO", f"Manual save succeeded: {json_path}"))
            json_written = True
        except Exception as exc:
            messages.append(
                ("ERROR", f"Manual save failed: {type(exc).__name__}: {exc}")
            )
            _write_recovery_payload(snapshot, messages)
    timings.append(("JSON write", time.perf_counter() - started))

    if json_path is not None and json_written:
        started = time.perf_counter()
        if os.path.exists("Z:\\"):
            if snapshot.backup_dir:
                try:
                    os.makedirs(snapshot.backup_dir, exist_ok=True)
                    backup_target = os.path.join(
                        snapshot.backup_dir, os.path.basename(json_path)
                    )
                    shutil.copy2(json_path, backup_target)
                    messages.append(("INFO", f"JSON backup succeeded: {backup_target}"))
                except Exception as exc:
                    messages.append(
                        (
                            "WARNING",
                            f"JSON backup failed: {type(exc).__name__}: {exc}",
                        )
                    )
            else:
                messages.append(("WARNING", "JSON backup skipped: backup path is empty."))
        else:
            messages.append(("WARNING", "JSON backup skipped: drive Z: not found."))
        timings.append(("JSON backup copy", time.perf_counter() - started))

    return _OutputJobResult(tuple(messages), tuple(timings))


class Scan(QtWidgets.QWidget):
    MAX_UI_LOG_LINES = 1000

    sig_info_changed = QtCore.pyqtSignal(object)
    start = QtCore.pyqtSignal(object)
    stop = QtCore.pyqtSignal()
    def __init__(self,name=None, info=None,setter_equipment_info=None,main_window=None,getter_equipment_info=None):
        super(Scan, self).__init__()
        uic.loadUi("core/ui/scan.ui", self)

        self.logic = ScanLogic(main_window=main_window)
        # self.logic.sig_capture_ui.connect(self.capture_ui)###### April 2025
        self.logic.sig_new_data.connect(self.new_data)
        self.logic.sig_update_remaining_time.connect(self.update_remaining_time_label)
        self.logic.sig_update_remaining_points.connect(self.update_remaining_points_label)
        self.logic.sig_auto_backup.connect(self.auto_backup)
        self.logic.sig_scan_error.connect(self.handle_scan_error)

        
        self.main_window=main_window
        self.finished = False
        self.setter_equipment_info = setter_equipment_info
        self.getter_equipment_info = getter_equipment_info

        self._start_new_scan_after_stop = False
        self._start_cancel_requested = False
        self._shutdown_requested = False
        self._queue_configuration_locked = False
        self._queue_configuration_widget_states = ()
        self._scan_configuration_locked = False
        self._scan_configuration_widget_states = ()
        self._configuration_widget_locks = {}

        self.scan_button.clicked.connect(self.when_scan_clicked)
        self.stop_button.clicked.connect(self.when_stop_clicked)
        self.load_button.clicked.connect(self.when_load_clicked)
        self.save_button.clicked.connect(self.when_save_clicked)

        self.scan_button_1.clicked.connect(self.when_scan_clicked)
        self.stop_button_1.clicked.connect(self.when_stop_clicked)
        self.pause_button_1.clicked.connect(self.when_pause_clicked)
        self.resume_button_1.clicked.connect(self.when_resume_clicked)
        self.save_plots_button_1.clicked.connect(self.when_save_plots_clicked)
        self.update_plots_button_1.clicked.connect(self.update_all_plots)

        self.scan_button_2.clicked.connect(self.when_scan_clicked)
        self.stop_button_2.clicked.connect(self.when_stop_clicked)
        self.pause_button_2.clicked.connect(self.when_pause_clicked)
        self.resume_button_2.clicked.connect(self.when_resume_clicked)
        self.save_plots_button_2.clicked.connect(self.when_save_plots_clicked)
        self.update_plots_button_2.clicked.connect(self.update_all_plots)

        self.scan_button_3.clicked.connect(self.when_scan_clicked)
        self.stop_button_3.clicked.connect(self.when_stop_clicked)
        self.pause_button_3.clicked.connect(self.when_pause_clicked)
        self.resume_button_3.clicked.connect(self.when_resume_clicked)
        self.save_plots_button_3.clicked.connect(self.when_save_plots_clicked)
        self.update_plots_button_3.clicked.connect(self.update_all_plots)

        self.all_level_setting = AllLevelSetting(all_level_info=info['levels'],setter_equipment_info=setter_equipment_info,getter_equipment_info=getter_equipment_info)
        # print(equipment_info)
        self.all_plot_setting = AllPlotSetting(level_info=info['levels'])
        self.verticalLayout_2.addWidget(self.all_plot_setting)
        self.graphing_plots = [
            AllPlots(level_info=info['levels'], page_number=i)
            for i in range(3)
        ]
        self.plots1_layout.addWidget(self.graphing_plots[0])
        self.plots2_layout.addWidget(self.graphing_plots[1])
        self.plots3_layout.addWidget(self.graphing_plots[2])
        self._configure_plot_tab_stretch()

        self.scrollArea.setWidget(self.all_level_setting)
        if info is None:
            self.info = {'name': 'no name',
                         'levels': self.all_level_setting.all_level_info,
                         'data': {},
                         'plots': self.all_plot_setting.info,
                         'comments': '',
                         'scan_log': []}
        else:
            self.info = info
            self.info['name']=name
            self.info.setdefault('comments', '')
            self.info.setdefault('scan_log', [])
            # print(name)

        self._display_log_history = []
        self._current_scan_log = []
        self._run_start_time = None
        self._run_stop_reason = None
        self._run_error_message = None
        self._stop_intent_logged = False
        self._finalize_outputs_scheduled = False
        self._outputs_finalized = True
        self._scan_state = "idle"
        self._last_start_error = None
        self._boundary_thread = None
        self._boundary_worker = None
        self._boundary_completion = None
        self._runtime_activity_reservation = None
        self._participating_device_ids = ()
        self.logStatus_textEdit.setReadOnly(True)
        self.logStatus_textEdit.document().setMaximumBlockCount(self.MAX_UI_LOG_LINES)
        self._replace_current_scan_log(self.info.get("scan_log", []))

        self.populate()
        self.all_level_setting.sig_info_changed.connect(self.when_all_level_setting_infochanged)
        self.all_plot_setting.sig_info_changed.connect(self.when_all_plot_setting_infochanged)
        self.all_level_setting.sig_info_changed.connect(self.all_plot_setting.set_level_info_slot)
        self.lineEdit.textChanged.connect(self.when_name_changed)
        self.all_level_setting.sig_info_changed.emit(self.all_level_setting.all_level_info)
        # When Scan is instantiated from an existing info dict (e.g. drag-copy
        # across scan-list areas), rehydrate persisted UI choices.
        ppp_val = self.info.get("plots_per_page", None)
        if ppp_val is not None:
            idx = self.PlotsPerPage.findText(str(ppp_val))
            if idx != -1:
                self.PlotsPerPage.setCurrentIndex(idx)
        plots_info = self.info.get("plots", None)
        if isinstance(plots_info, dict):
            self.all_plot_setting.update_ui(plots_info)
        terminal_signal = getattr(self.logic, "sig_scan_terminal", None)
        if terminal_signal is not None:
            terminal_signal.connect(self.scan_finished)
        else:
            self.logic.sig_scan_finished.connect(self.scan_finished)

    @property
    def outputs_finalized(self) -> bool:
        """Return whether restore and output work for the last run is complete."""
        return bool(self._outputs_finalized and not self._finalize_outputs_scheduled)

    @property
    def scan_state(self) -> str:
        """Return the explicit scan-boundary state used by queue/shutdown gates."""
        return self._scan_state

    def _set_scan_state(self, state):
        if state not in {"idle", "preparing", "running", "finalizing"}:
            raise ValueError(f"unknown scan state: {state}")
        self._scan_state = state

    def _start_boundary_job(self, operation, completion):
        active = self._boundary_thread
        if active is not None and active.isRunning():
            raise RuntimeError("scan boundary worker is already running")

        thread = QtCore.QThread(self)
        worker = _BoundaryWorker(operation)
        worker.moveToThread(thread)
        self._boundary_thread = thread
        self._boundary_worker = worker
        self._boundary_completion = completion
        thread.started.connect(worker.run)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(self._boundary_job_finished)
        thread.start()

    @QtCore.pyqtSlot()
    def _boundary_job_finished(self):
        worker = self._boundary_worker
        outcome = None if worker is None else worker.outcome
        completion = self._boundary_completion
        thread = self._boundary_thread
        self._boundary_worker = None
        self._boundary_thread = None
        self._boundary_completion = None
        if thread is not None:
            thread.deleteLater()
        if outcome is None:
            outcome = _BoundaryOutcome(
                error=RuntimeError("scan boundary worker returned no outcome")
            )
        if completion is not None:
            completion(outcome)

    @QtCore.pyqtSlot(bool)
    def set_queue_configuration_locked(self, locked: bool) -> None:
        """Lock configuration controls while this scan is the current queue item."""

        locked = bool(locked)
        if locked == self._queue_configuration_locked:
            return
        widgets = self._configuration_widgets(include_scan_buttons=True)
        self._apply_configuration_widget_lock("queue", widgets, locked)
        self._queue_configuration_locked = locked
        self._queue_configuration_widget_states = (
            tuple((widget, False) for widget in widgets) if locked else ()
        )

    def _configuration_widgets(self, *, include_scan_buttons):
        # The scan name and comments are completion metadata, not executable
        # configuration.  Keep them editable so finalization can capture the
        # operator's latest text, matching the legacy scan workflow.
        widgets = [
            self.PlotsPerPage,
            self.all_level_setting,
            self.all_plot_setting,
            self.load_button,
            self.save_button,
        ]
        if include_scan_buttons:
            widgets.extend(
                (
                    self.scan_button,
                    self.scan_button_1,
                    self.scan_button_2,
                    self.scan_button_3,
                )
            )
        return tuple(widgets)

    def _apply_configuration_widget_lock(self, reason, widgets, locked):
        if locked:
            for widget in widgets:
                state = self._configuration_widget_locks.get(widget)
                if state is None:
                    state = [widget.isEnabledTo(self), set()]
                    self._configuration_widget_locks[widget] = state
                state[1].add(reason)
                widget.setEnabled(False)
            return

        for widget, state in tuple(self._configuration_widget_locks.items()):
            reasons = state[1]
            if reason not in reasons:
                continue
            reasons.remove(reason)
            if reasons:
                continue
            widget.setEnabled(state[0])
            del self._configuration_widget_locks[widget]

    def _set_scan_configuration_locked(self, locked):
        """Seal editable scan inputs across prepare, run, and finalization."""
        locked = bool(locked)
        if locked == self._scan_configuration_locked:
            return
        widgets = self._configuration_widgets(include_scan_buttons=False)
        self._apply_configuration_widget_lock("scan", widgets, locked)
        self._scan_configuration_locked = locked
        self._scan_configuration_widget_states = (
            tuple((widget, False) for widget in widgets) if locked else ()
        )

    def when_save_plots_clicked(self):  # Mohamed Change: April 2025
        base = self._next_unique_data_name()
        ppt_text = self.main_window.ppt_path.toPlainText().strip()

        if ppt_text == "":
            file_name, _ = QFileDialog.getSaveFileName(
                self, "Select PPT", f"{base}.pptx", "PPT Files (*.pptx)"
            )
            if not file_name:
                return
        else:
            file_name = os.path.normpath(ppt_text.strip('"'))

        if not file_name.lower().endswith(".pptx"):
            file_name = f"{file_name}.pptx"

        folder = os.path.dirname(file_name)
        if folder and not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)

        comments_text = self.comments_textEdit.toPlainText().strip()
        save_time = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        non_empty_tabs = []
        try:
            # First slide: always save settings + main window overview.
            overview_title = f"{base}.json - Settings and Main Window"
            overview_text = f"Saved: {save_time}"
            setting_shot = self.settingTab.grab()
            main_window_shot = self.main_window.grab()
            overview_positions = [
                (20, 70, 450, 380),   # settingTab
                (490, 70, 450, 380),  # main_window
            ]

            add_slide_with_qpixmap(
                ppt_path=file_name,
                slide_title=overview_title,
                slide_text=overview_text,
                pixmap_images=[setting_shot, main_window_shot],
                image_positions=overview_positions,
                comments_text=comments_text,
            )

            for tab_index, tab in enumerate([self.Plots1Tab, self.Plots2Tab, self.Plots3Tab], start=1):
                if tab.findChildren((LinePlot, ImagePlot)):
                    non_empty_tabs.append((tab_index, tab))

            for tab_index, tab in non_empty_tabs:
                slide_title = f"{base}.json - Plots Tab {tab_index}"
                slide_text = f"Saved: {save_time}"
                screenshot = tab.grab()

                add_slide_with_qpixmap(
                    ppt_path=file_name,
                    slide_title=slide_title,
                    slide_text=slide_text,
                    pixmap_images=[screenshot],
                    image_positions=[(20, 70, 920, 450)],
                )
        except Exception as exc:
            self._log_error(f"PPT save failed: {type(exc).__name__}: {exc}")
            return

        self._log_info(
            f"PPT save succeeded: {file_name} "
            f"(1 overview + {len(non_empty_tabs)} plot slide(s))"
        )

        if os.path.exists(r"Z:\\"):
            backup_sub = self._backup_subfolder()
            if backup_sub:
                backup_dir = os.path.join(backup_sub)
                os.makedirs(backup_dir, exist_ok=True)
                backup_target = os.path.join(backup_dir, os.path.basename(file_name))
                try:
                    shutil.copy2(file_name, backup_target)
                    self._log_info(f"PPT backup succeeded: {backup_target}")
                except Exception as exc:
                    self._log_warning(f"PPT backup failed: {type(exc).__name__}: {exc}")
            else:
                self._log_warning("PPT backup skipped: backup path is empty.")
        else:
            self._log_warning("PPT backup skipped: drive Z: not found.")


    def scan_finished(self, _terminal_result=None):
        status = self._get_finish_status()
        elapsed_seconds = self._get_elapsed_seconds()
        elapsed_str = str(_dt.timedelta(seconds=elapsed_seconds)) if elapsed_seconds is not None else "unknown"
        completed_points = getattr(self.logic, "completed_points", 0)
        total_points = getattr(self.logic, "total_points", 0)
        finish_message = (
            f"Scan finished | status={status} | time_cost={elapsed_str} | "
            f"points={completed_points}/{total_points}"
        )
        if status == "completed":
            self._log_info(finish_message)
        elif status == "error":
            self._log_error(finish_message)
        else:
            self._log_warning(finish_message)

        if self._run_error_message:
            self._log_error(f"Error summary: {self._run_error_message}")

        if self._finalize_outputs_scheduled:
            self._log_warning("Scan finalize already scheduled; skipping duplicate finish handling.")
            return

        self._set_scan_state("finalizing")
        self._finalize_outputs_scheduled = True
        QtCore.QTimer.singleShot(0, self._finalize_scan_outputs)

    @staticmethod
    def _capture_png(widget):
        pixmap = widget.grab()
        payload = QtCore.QByteArray()
        buffer = QtCore.QBuffer(payload)
        if not buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError("could not open PNG capture buffer")
        try:
            if not pixmap.save(buffer, "PNG"):
                raise RuntimeError("failed to encode widget capture as PNG")
        finally:
            buffer.close()
        return _CapturedImage(bytes(payload), pixmap.width(), pixmap.height())

    def _build_output_snapshot(self):
        serial = f"{self.main_window.scanlist.serial.value():04d}"
        base = f"{serial}_{self.info.get('name', 'scan')}"
        comments_text = self.comments_textEdit.toPlainText().strip()
        save_time = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        slides = []
        ppt_path = None
        try:
            ppt_text = self.main_window.ppt_path.toPlainText().strip()
            if ppt_text:
                ppt_path = os.path.normpath(ppt_text.strip('"'))
            else:
                ppt_path, _ = QFileDialog.getSaveFileName(
                    self, "Select PPT", f"{base}.pptx", "PPT Files (*.pptx)"
                )
                ppt_path = os.path.normpath(ppt_path) if ppt_path else None
            if ppt_path and not ppt_path.lower().endswith(".pptx"):
                ppt_path = f"{ppt_path}.pptx"

            if ppt_path:
                overview_images = (
                    self._capture_png(self.settingTab),
                    self._capture_png(self.main_window),
                )
                slides.append(
                    _OutputSlide(
                        title=f"{base}.json - Settings and Main Window",
                        text=f"Saved: {save_time}",
                        images=overview_images,
                        positions=((20, 70, 450, 380), (490, 70, 450, 380)),
                        comments=comments_text,
                    )
                )
                for tab_index, tab in enumerate(
                    (self.Plots1Tab, self.Plots2Tab, self.Plots3Tab), start=1
                ):
                    if not tab.findChildren((LinePlot, ImagePlot)):
                        continue
                    slides.append(
                        _OutputSlide(
                            title=f"{base}.json - Plots Tab {tab_index}",
                            text=f"Saved: {save_time}",
                            images=(self._capture_png(tab),),
                            positions=((20, 70, 920, 450),),
                        )
                    )
        except Exception as exc:
            ppt_path = None
            slides = []
            self._log_error(
                f"PPT capture failed: {type(exc).__name__}: {exc}"
            )

        self.update_alllevel_setting_array()
        self.info["comments"] = self.comments_textEdit.toPlainText()
        self.info["plots_per_page"] = self.PlotsPerPage.currentText()
        self._sync_scan_log_to_info()
        json_payload = copy.deepcopy(self.info)

        json_name = f"{base}.json"
        json_path = None
        try:
            save_text = self.main_window.save_info_path.toPlainText().strip()
            if save_text:
                json_folder = os.path.normpath(save_text.strip('"'))
                json_path = os.path.join(json_folder, json_name)
            else:
                json_path, _ = QFileDialog.getSaveFileName(
                    self, "Select File to Save", json_name
                )
                json_path = os.path.normpath(json_path) if json_path else None
            if json_path:
                _folder, selected_name = os.path.split(json_path)
                json_name = selected_name or json_name
        except Exception as exc:
            json_path = None
            self._log_error(
                "Primary JSON path preparation failed; writing recovery JSON: "
                f"{type(exc).__name__}: {exc}"
            )

        data_root = QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.StandardLocation.GenericDataLocation
        )
        recovery_dir = (
            os.path.join(data_root, "ZMeter", "recovery") if data_root else ""
        )
        snapshot = _ScanOutputSnapshot(
            ppt_path=ppt_path,
            slides=tuple(slides),
            json_path=json_path,
            json_payload=json_payload,
            json_name=json_name,
            backup_dir=self._backup_subfolder(),
            recovery_dir=recovery_dir,
        )
        return snapshot

    def _restore_and_persist(self, snapshot):
        restore_error = None
        messages = []
        timings = []
        started = time.perf_counter()
        try:
            self.main_window.start_equipments(self._participating_device_ids)
        except Exception as exc:
            restore_error = exc
        timings.append(("device restore", time.perf_counter() - started))

        if snapshot is not None:
            output_result = _persist_scan_outputs(snapshot)
            messages.extend(output_result.messages)
            timings.extend(output_result.timings)
        return _OutputJobResult(
            tuple(messages), tuple(timings), restore_error=restore_error
        )

    def _finalize_scan_outputs(self):
        """Capture Qt-owned pixels, then restore devices and persist off-thread."""
        snapshot = None
        try:
            snapshot = self._build_output_snapshot()
        except Exception as exc:
            self._log_error(
                f"Output snapshot failed: {type(exc).__name__}: {exc}"
            )
        self._start_boundary_job(
            lambda: self._restore_and_persist(snapshot),
            lambda outcome: self._complete_scan_finalization(outcome, snapshot),
        )

    def _complete_scan_finalization(self, outcome, snapshot):
        restart_after_finalize = False
        try:
            if outcome.error is not None:
                self._log_error(
                    "Scan finalization worker failed: "
                    f"{type(outcome.error).__name__}: {outcome.error}"
                )
            elif isinstance(outcome.value, _OutputJobResult):
                result = outcome.value
                for level, message in result.messages:
                    if level == "ERROR":
                        self._log_error(message)
                    elif level == "WARNING":
                        self._log_warning(message)
                    else:
                        self._log_info(message)
                if result.restore_error is not None:
                    self.handle_scan_error(
                        "Equipment restart failed: "
                        f"{type(result.restore_error).__name__}: "
                        f"{result.restore_error}"
                    )

            if snapshot is not None:
                current_serial = self.main_window.scanlist.serial.value()
                self.main_window.scanlist.serial.setValue(current_serial + 1)

            restart_after_finalize = bool(
                self._start_new_scan_after_stop and not self._shutdown_requested
            )
            self._start_new_scan_after_stop = False
        finally:
            self._finalize_outputs_scheduled = False
            self._outputs_finalized = True
            self._set_scan_state("idle")
            self._set_scan_configuration_locked(False)
            self._release_runtime_activity_reservation()

        if restart_after_finalize:
            self._start_scan_now()

    def handle_scan_error(self, error_message: str):
        self._run_error_message = error_message
        self._log_error(f"Scan error: {error_message}")

    def set_setter_equipment_info(self,info):
        self.setter_equipment_info=info
        self.all_level_setting.set_setter_equipment_info(self.setter_equipment_info)

    def set_getter_equipment_info(self, info):
        self.getter_equipment_info = info
        self.all_level_setting.set_getter_equipment_info(self.getter_equipment_info)

    def refresh_catalog(self, setter_equipment_info, getter_equipment_info):
        """Refresh both scan menus without rewriting the scan definition."""
        self.setter_equipment_info = setter_equipment_info
        self.getter_equipment_info = getter_equipment_info
        self.all_level_setting.refresh_catalog_choices(
            setter_equipment_info,
            getter_equipment_info,
        )

    def channel_references(self):
        """Return immutable references from the live level editor model.

        The live ``AllLevelSetting`` model is authoritative while an editor is
        open.  In particular, this avoids reporting the older ``ScanItem.info``
        copy while an edit is still being reflected through Qt signals.
        """
        level_model = getattr(
            getattr(self, "all_level_setting", None),
            "all_level_info",
            self.info.get("levels", {}),
        )
        plot_model = getattr(
            getattr(self, "all_plot_setting", None),
            "info",
            self.info.get("plots", {}),
        )
        return self.channel_references_from_models(level_model, plot_model)

    @classmethod
    def channel_references_from_info(cls, info):
        """Return references retained by a scan template/persisted dictionary."""
        if not isinstance(info, dict):
            return ()
        return cls.channel_references_from_models(
            info.get("levels", {}),
            info.get("plots", {}),
        )

    @classmethod
    def channel_references_from_models(cls, level_model, plot_model):
        references = []

        for level_key, level_info in (level_model or {}).items():
            if not isinstance(level_info, dict):
                continue

            setters = level_info.get("setters", {})
            if isinstance(setters, dict):
                for setter_key, setter_info in setters.items():
                    if not isinstance(setter_info, dict):
                        continue
                    channel = cls._reference_channel(setter_info.get("channel"))
                    if channel is None:
                        continue
                    references.append(
                        ScanChannelReference(
                            kind="setter",
                            access="set",
                            level=str(level_key),
                            channel=channel,
                            path=(
                                f"levels.{level_key}.setters.{setter_key}.channel"
                            ),
                        )
                    )

            getters = level_info.get("getters", ())
            if isinstance(getters, (list, tuple)):
                for getter_index, getter_token in enumerate(getters):
                    channel = cls._reference_channel(getter_token)
                    if channel is None:
                        continue
                    kind = "getter"
                    average_match = _AVERAGE_GETTER_REFERENCE.match(channel)
                    if average_match is not None:
                        kind = "average_getter"
                        channel = average_match.group(2)
                    references.append(
                        ScanChannelReference(
                            kind=kind,
                            access="get",
                            level=str(level_key),
                            channel=channel,
                            path=f"levels.{level_key}.getters[{getter_index}]",
                        )
                    )

            for manual_key in ("manual_set_before", "manual_set_after"):
                manual_sets = level_info.get(manual_key, ())
                if not isinstance(manual_sets, (list, tuple)):
                    continue
                for manual_index, mapping in enumerate(manual_sets):
                    if not isinstance(mapping, dict):
                        continue
                    for channel_name in mapping:
                        channel = cls._reference_channel(channel_name)
                        if channel is None:
                            continue
                        references.append(
                            ScanChannelReference(
                                kind=manual_key,
                                access="set",
                                level=str(level_key),
                                channel=channel,
                                path=(
                                    f"levels.{level_key}.{manual_key}"
                                    f"[{manual_index}]"
                                ),
                            )
                        )

        for plot_kind, plots in (plot_model or {}).items():
            if not isinstance(plots, dict):
                continue
            for plot_key, plot_info in plots.items():
                if not isinstance(plot_info, dict):
                    continue
                for field, token in plot_info.items():
                    token = cls._reference_channel(token)
                    if token is None:
                        continue
                    plot_match = _PLOT_CHANNEL_REFERENCE.match(token)
                    if plot_match is None:
                        continue
                    direction, channel = plot_match.groups()
                    kind = "plot_setter" if direction == "S" else "plot_getter"
                    access = "set" if direction == "S" else "get"
                    average_match = _AVERAGE_GETTER_REFERENCE.match(channel)
                    if average_match is not None:
                        kind = "plot_average_getter"
                        channel = average_match.group(2)
                    references.append(
                        ScanChannelReference(
                            kind=kind,
                            access=access,
                            level=None,
                            channel=channel,
                            path=f"plots.{plot_kind}.{plot_key}.{field}",
                        )
                    )

        return tuple(references)

    @staticmethod
    def _reference_channel(channel):
        if not isinstance(channel, str):
            return None
        channel = channel.strip()
        if channel == "" or channel.lower() in {"none", "void"}:
            return None
        return channel

    def populate(self):
        self.lineEdit.setText(self.info['name'])
        self.comments_textEdit.setPlainText(self.info.get('comments', ''))
        self.setWindowTitle(self.info['name'])

    def _configure_plot_tab_stretch(self):
        """
        Keep the plot region as the vertical stretch owner in each tab.
        This avoids the spacer row consuming extra height when only one plot exists.
        """
        for tab in [self.Plots1Tab, self.Plots2Tab, self.Plots3Tab]:
            layout = tab.layout()
            if layout is None:
                continue
            # Reset first, then assign stretch to the plot container row (index 0).
            for i in range(layout.count()):
                layout.setStretch(i, 0)
            layout.setStretch(0, 1)

    def _focus_plot_tab_1_for_scan_start(self, maximize=False):
        if maximize:
            self.showMaximized()
        if hasattr(self, "ScanTab") and hasattr(self, "Plots1Tab"):
            self.ScanTab.setCurrentWidget(self.Plots1Tab)

    def _timestamp_now(self) -> str:
        return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _sync_scan_log_to_info(self):
        self.info["scan_log"] = list(self._current_scan_log)

    def _replace_current_scan_log(self, lines):
        normalized = []
        for line in lines or []:
            if line is None:
                continue
            text = str(line).rstrip("\r\n")
            if text == "":
                continue
            normalized.append(text)
        self._current_scan_log = normalized
        self._sync_scan_log_to_info()

    def _append_log_entry(
        self,
        message: str,
        *,
        level="INFO",
        include_timestamp=True,
        persist_current_run=True,
    ):
        level_text = str(level).upper()
        if level_text not in {"INFO", "WARNING", "ERROR"}:
            level_text = "INFO"

        if include_timestamp:
            line = f"[{self._timestamp_now()}] [{level_text}] {message}"
        else:
            line = str(message).rstrip("\r\n")
        if line == "":
            return

        self._display_log_history.append(line)
        self.logStatus_textEdit.append(line)

        if persist_current_run:
            self._current_scan_log.append(line)
            self._sync_scan_log_to_info()

    def _log_info(self, message: str, *, persist_current_run=True):
        self._append_log_entry(message, level="INFO", persist_current_run=persist_current_run)

    def _log_warning(self, message: str, *, persist_current_run=True):
        self._append_log_entry(message, level="WARNING", persist_current_run=persist_current_run)

    def _log_error(self, message: str, *, persist_current_run=True):
        self._append_log_entry(message, level="ERROR", persist_current_run=persist_current_run)

    def _start_new_scan_log_session(self):
        self._current_scan_log = []
        self._sync_scan_log_to_info()
        self._run_start_time = _dt.datetime.now()
        self._run_stop_reason = None
        self._run_error_message = None
        self._stop_intent_logged = False

    def _mark_stop_reason(self, reason: str):
        if self._run_stop_reason is None:
            self._run_stop_reason = reason

    def _build_start_summary(self) -> str:
        level_count = len(getattr(self.logic, "level_target_counts", []))
        points_per_level = list(getattr(self.logic, "level_target_counts", []))
        total_points = int(getattr(self.logic, "total_points", 0))
        setter_counts = [len(setters) for setters in getattr(self.logic, "level_setters", [])]

        getter_counts = []
        for getters in getattr(self.logic, "level_getters", []):
            if len(getters) == 1 and getters[0] == "none":
                getter_counts.append(0)
            else:
                getter_counts.append(len(getters))

        return (
            f"Start summary | name={self.info.get('name', 'no name')} | levels={level_count} | "
            f"points_per_level={points_per_level} | total_points={total_points} | "
            f"setters_per_level={setter_counts} | getters_per_level={getter_counts}"
        )

    def _get_elapsed_seconds(self):
        if self._run_start_time is not None:
            return max(0, int((_dt.datetime.now() - self._run_start_time).total_seconds()))
        elapsed = getattr(self.logic, "elapsed_time", None)
        if elapsed is None:
            return None
        return max(0, int(elapsed))

    def _get_finish_status(self) -> str:
        if self._run_error_message:
            return "error"
        if self._run_stop_reason == "restart_requested":
            return "stopped for restart"
        if self._run_stop_reason == "user_stop":
            return "stopped by user"
        return "completed"

    def emit(self):
        self.sig_info_changed.emit(self.info)

    def when_name_changed(self):
        self.info['name'] = self.lineEdit.text()
        self.setWindowTitle(self.info['name'])
        self.sig_info_changed.emit(self.info)

    def when_all_level_setting_infochanged(self, info):

        
        self.info['levels'] = info
        # print("all level setting info recieved")
        # for i in range(self.all_plot_setting.verticalLayout_line.count()):
        #     w = self.all_plot_setting.verticalLayout_line.itemAt(i).widget()
        #     w.blockSignals(True)
        # for i in range(self.all_plot_setting.verticalLayout_image.count()):
        #     w = self.all_plot_setting.verticalLayout_image.itemAt(i).widget()
        #     w.blockSignals(True)
        self.all_plot_setting.set_level_info(info)
        for gp in self.graphing_plots:
            gp.set_level_info(info)
        # for i in range(self.all_plot_setting.verticalLayout_image.count()):
        #     w = self.all_plot_setting.verticalLayout_image.itemAt(i).widget()
        #     w.blockSignals(True)
        # for i in range(self.all_plot_setting.verticalLayout_image.count()):
        #     w = self.all_plot_setting.verticalLayout_image.itemAt(i).widget()
        #     w.blockSignals(True)

    def when_all_plot_setting_infochanged(self, plot_setting_info):
        info = plot_setting_info
        self.info['plots'] = info

        # for i in range(self.all_plot_setting.verticalLayout_line.count()):
        #     w = self.all_plot_setting.verticalLayout_line.itemAt(i).widget()
        #     w.blockSignals(True)
        # for i in range(self.all_plot_setting.verticalLayout_image.count()):
        #     w = self.all_plot_setting.verticalLayout_image.itemAt(i).widget()
        #     w.blockSignals(True)

        for gp in self.graphing_plots:
            gp.receive_plot_info(plot_setting_info)

        # for i in range(self.all_plot_setting.verticalLayout_image.count()):
        #     w = self.all_plot_setting.verticalLayout_image.itemAt(i).widget()
        #     w.blockSignals(True)
        # for i in range(self.all_plot_setting.verticalLayout_image.count()):
        #     w = self.all_plot_setting.verticalLayout_image.itemAt(i).widget()
        #     w.blockSignals(True)
        # print(self.info['name'])
        self.sig_info_changed.emit(self.info)

    def set_main_window(self, mainwindow):
        self.main_window = mainwindow
        self.logic.main_window = mainwindow

    def _resolve_participating_device_ids(self):
        """Resolve the physical devices used by the current executable scan model."""
        if self.main_window is None or not hasattr(self.main_window, "equips"):
            return ()

        physical_channels = []
        for reference in self.channel_references():
            if reference.kind.startswith("plot_"):
                continue
            channel = reference.channel
            if channel.startswith("default_"):
                continue
            if channel.startswith("artificial_channel_"):
                if reference.access != "set":
                    continue
                artificial_logic = getattr(
                    self.main_window, "artificial_channel_logic", None
                )
                if artificial_logic is not None:
                    physical_channels.extend(
                        (
                            artificial_logic.original_channel_x_name,
                            artificial_logic.original_channel_y_name,
                        )
                    )
                continue
            physical_channels.append(channel)

        resolve = getattr(
            self.main_window, "resolve_device_label_for_channel", None
        )
        if not callable(resolve):
            return ()
        selected = {resolve(channel) for channel in physical_channels}
        return tuple(label for label in self.main_window.equips if label in selected)

    def _capture_participating_device_ids(self):
        device_ids = self._resolve_participating_device_ids()
        self._participating_device_ids = device_ids
        self.logic.participating_device_ids = device_ids
        return device_ids

    def _start_scan_now(self):
        """Accept a fresh scan and prepare its devices without blocking Qt."""
        if self._shutdown_requested:
            self._start_new_scan_after_stop = False
            return False
        if self._scan_state != "idle":
            return False

        self._acquire_runtime_activity_reservation()
        try:
            self._last_start_error = None
            self._start_cancel_requested = False
            self._set_scan_state("preparing")
            self._outputs_finalized = False
            self._set_scan_configuration_locked(True)
            if hasattr(self, "unique_data_name"):
                del self.unique_data_name

            self._focus_plot_tab_1_for_scan_start(maximize=False)
            self._start_new_scan_log_session()

            device_ids = self._capture_participating_device_ids()
            self.update_alllevel_setting_array()
            scan_config = {"levels": copy.deepcopy(self.info["levels"])}
            self._start_boundary_job(
                lambda: self._prepare_devices(device_ids, scan_config),
                self._complete_scan_preparation,
            )
            return True
        except Exception:
            self._set_scan_state("idle")
            self._outputs_finalized = True
            self._set_scan_configuration_locked(False)
            self._release_runtime_activity_reservation()
            raise

    def _prepare_devices(self, device_ids, scan_config):
        phase = "device"
        device_elapsed = 0.0
        data_elapsed = 0.0
        started = time.perf_counter()
        try:
            self.main_window.stop_equipments_for_scanning(device_ids)
            device_elapsed = time.perf_counter() - started
            phase = "data"
            started = time.perf_counter()
            self.logic.initialize_scan_data(scan_config)
            data_elapsed = time.perf_counter() - started
            return _PrepareJobResult(
                device_elapsed,
                data_elapsed=data_elapsed,
            )
        except Exception as exc:
            if phase == "device":
                device_elapsed = time.perf_counter() - started
            else:
                data_elapsed = time.perf_counter() - started
            restore_error = None
            try:
                self.main_window.start_equipments(device_ids)
            except Exception as rollback_exc:
                restore_error = rollback_exc
            return _PrepareJobResult(
                device_elapsed,
                data_elapsed=data_elapsed,
                error=exc,
                restore_error=restore_error,
            )

    def _complete_scan_preparation(self, outcome):
        if outcome.error is not None:
            self._fail_preparation(outcome.error)
            return
        result = outcome.value
        if not isinstance(result, _PrepareJobResult):
            self._fail_preparation(
                RuntimeError("device preparation returned an invalid result")
            )
            return
        if result.error is not None:
            if result.restore_error is not None:
                self._log_error(
                    "Preparation rollback failed: "
                    f"{type(result.restore_error).__name__}: {result.restore_error}"
                )
            self._fail_preparation(result.error)
            return
        if self._shutdown_requested or self._start_cancel_requested:
            self._begin_start_rollback(
                RuntimeError(
                    "scan start canceled before execution"
                    if self._start_cancel_requested
                    else "scan start canceled because shutdown is in progress"
                )
            )
            return

        try:
            self.logic.reset_flags()
            self.logic.go_scan = True
            self.update_all_plots()
            self._set_scan_state("running")
            self.logic.start()
            self._log_info("Scan started.")
            self._log_info(self._build_start_summary())
        except Exception as exc:
            self._begin_start_rollback(exc)

    def _fail_preparation(self, error):
        self._last_start_error = error
        self.handle_scan_error(
            f"Scan preparation failed: {type(error).__name__}: {error}"
        )
        self._set_scan_state("idle")
        self._outputs_finalized = True
        self._set_scan_configuration_locked(False)
        self._release_runtime_activity_reservation()

    def _begin_start_rollback(self, error):
        self._last_start_error = error
        self.handle_scan_error(
            f"Scan start failed: {type(error).__name__}: {error}"
        )
        self._set_scan_state("finalizing")
        self._start_boundary_job(
            lambda: self._restore_after_start_failure(),
            self._complete_start_rollback,
        )

    def _restore_after_start_failure(self):
        started = time.perf_counter()
        self.main_window.start_equipments(self._participating_device_ids)
        return time.perf_counter() - started

    def _complete_start_rollback(self, outcome):
        try:
            if outcome.error is not None:
                self._log_error(
                    "Scan start rollback failed: "
                    f"{type(outcome.error).__name__}: {outcome.error}"
                )
        finally:
            self._set_scan_state("idle")
            self._outputs_finalized = True
            self._set_scan_configuration_locked(False)
            self._release_runtime_activity_reservation()

    def _acquire_runtime_activity_reservation(self):
        if self._runtime_activity_reservation is not None:
            raise RuntimeError("scan runtime activity is already reserved")
        reserve = getattr(self.main_window, "reserve_runtime_activity", None)
        if callable(reserve):
            name = str(self.lineEdit.text() or self.info.get("name", "scan"))
            self._runtime_activity_reservation = reserve("scan", name)

    def _release_runtime_activity_reservation(self):
        reservation = self._runtime_activity_reservation
        self._runtime_activity_reservation = None
        if reservation is not None:
            reservation.release()

    def _request_logic_stop(self):
        """Request a clean stop from ScanLogic, including paused state."""
        force_stop_error = None
        try:
            self.main_window.force_stop_equipments(
                self._participating_device_ids
            )
        except Exception as exc:
            # Always tell ScanLogic to stop even when a device's best-effort
            # force-stop callback reports a failure.
            force_stop_error = exc

        if hasattr(self.logic, "request_stop"):
            self.logic.request_stop()
        else:
            self.logic.received_stop = True
            if hasattr(self.logic, "received_pause"):
                self.logic.received_pause = False

        self.logic.stop_scan = True
        if force_stop_error is not None:
            raise force_stop_error

    def when_stop_clicked(self):
        self._start_new_scan_after_stop = False

        if self._scan_state == "preparing":
            self._start_cancel_requested = True
            self._mark_stop_reason("user_stop")
            self._log_warning("Stop requested while scan preparation is running.")
            return

        # Do nothing when no scan thread is active; this avoids accidental save flows.
        if not self.logic.isRunning():
            return

        self._mark_stop_reason("user_stop")
        if not self._stop_intent_logged:
            self._log_warning("Stop requested by user.")
            self._stop_intent_logged = True
        self._request_logic_stop()

    def when_scan_clicked(self):
        if self._shutdown_requested:
            self._start_new_scan_after_stop = False
            return False

        if self._scan_state == "preparing":
            self._log_warning("Scan start ignored: device preparation is still running.")
            return False
        if self._scan_state == "finalizing":
            self._start_new_scan_after_stop = True
            self._log_info("Scan restart queued until finalization completes.")
            return False
        if self._scan_state == "running" and not self.logic.isRunning():
            self._start_new_scan_after_stop = True
            self._log_info("Scan restart queued while completion is being delivered.")
            return False

        # If a scan is already running (paused or not), stop it first.
        # scan_finished() will save current data, then we start a fresh scan.
        if self.logic.isRunning():
            self._mark_stop_reason("restart_requested")
            if not self._stop_intent_logged:
                self._log_warning(
                    "Scan button clicked during active run; requesting stop before restart."
                )
                self._stop_intent_logged = True
            self._request_logic_stop()
            self._start_new_scan_after_stop = True
            return False

        self._start_new_scan_after_stop = False
        return self._start_scan_now()

    def when_pause_clicked(self):
        """Pause the running scan thread (no-op if not running)."""
        if not self.logic.isRunning():
            return

        self._log_info("Pause requested.")

        # Preferred: use ScanLogic pause API if you added it
        if hasattr(self.logic, "request_pause"):
            self.logic.request_pause()
        else:
            # Fallback: direct flag
            self.logic.received_pause = True

    def when_resume_clicked(self):
        """Resume a paused scan (no-op if not running)."""
        if not self.logic.isRunning():
            return

        self._log_info("Resume requested.")

        if hasattr(self.logic, "request_resume"):
            self.logic.request_resume()
        else:
            self.logic.received_pause = False
            # If you used a QWaitCondition in ScanLogic, you'd also need wakeAll()
            # but without that infrastructure, this fallback only works if your loop polls the flag.

    def start_scan(self):
        """Compatibility entry point for the staged non-blocking start flow."""
        return self._start_scan_now()
    
    def update_alllevel_setting_array(self):
        self.all_level_setting.update_all_setting_array()


    def update_all_plots(self):
        """Call AllPlots.update_plots() for every page."""
        self.update_alllevel_setting_array()
        for gp in self.graphing_plots:

            
            gp.update_plots()

    def new_data(self,info):
        emit_metadata = None
        if isinstance(info, (list, tuple)) and len(info) >= 3:
            new_data, current_target_index, emit_metadata = info[0], info[1], info[2]
        else:
            new_data, current_target_index = info

        self.info['data']=new_data

        source_level = None
        changed_getter_indices = None
        if isinstance(emit_metadata, dict):
            source_level = emit_metadata.get("source_level")
            changed_getter_indices = emit_metadata.get("changed_getter_indices")
            if changed_getter_indices is not None:
                changed_getter_indices = set(changed_getter_indices)

        def should_update_plot(plot_widget):
            if source_level is None or changed_getter_indices is None:
                return True
            getter_level = getattr(plot_widget, "getter_level_number", None)
            getter_index = getattr(plot_widget, "getter_number", None)
            if getter_level is None or getter_index is None:
                return True
            return getter_level == source_level and getter_index in changed_getter_indices

        for gp in self.graphing_plots:
            for plot in range(gp.plots_layout.count()):
                w = gp.plots_layout.itemAt(plot).widget()
                if isinstance(w,LinePlot):
                    if not should_update_plot(w):
                        continue
                    if(current_target_index[w.setter_level_number]==0):
                        w.y_coordinates=np.full(w.setting_info_length, np.nan)
                    w.data=new_data                
                    # plot_line method now handles clearing and preserves v_line position
                    w.plot_line(current_target_index)
                if isinstance(w,ImagePlot):
                    if not should_update_plot(w):
                        continue
                    w.update_image(new_data,current_target_index)

    def _backup_subfolder(self) -> str:
        """
        Return the text inside the “backup_path” box (trimmed), whatever
        type it is: QPlainTextEdit, QLineEdit, or a plain string attribute.
        """
        widget = getattr(self.main_window, "backup_path", None)
        if widget is None:
            widget = getattr(self.main_window, "backup_Path", None)
        if widget is None:
            return ""                                # not found

        # Qt widgets
        if callable(getattr(widget, "toPlainText", None)):
            return widget.toPlainText().strip()
        if callable(getattr(widget, "text", None)):
            return widget.text().strip()

        # already a string
        return str(widget).strip()

    def _next_unique_data_name(self) -> str:
        """
        Return a base-name (no extension) that is unique in the folder
        chosen in the 'save_info_path' text box. We remember the first
        value we hand out during this session so both Save and Save-Plots
        use the *same* name.
        """
        if hasattr(self, "unique_data_name"):
            return self.unique_data_name           # already decided

        serial = f'{self.main_window.scanlist.serial.value():04d}'
        base   = f"{serial}_{self.info['name']}"

        folder_txt = self.main_window.save_info_path.toPlainText().strip()
        folder     = os.path.normpath(folder_txt) if folder_txt else os.getcwd()
        os.makedirs(folder, exist_ok=True)

        candidate = base
        count = 1
        while os.path.exists(os.path.join(folder, f"{candidate}.json")):
            candidate = f"{base}_{count}"
            count    += 1

        self.unique_data_name = candidate          # remember for later
        return candidate

    # def when_save_plots_clicked(self):
    #     serial = f'{self.main_window.scanlist.serial.value():04d}'
    #     name = self.info['name']
    #     name = f'{serial}_{name}'
    #     text = self.main_window.ppt_path.toPlainText()
    #     if text == '':
    #         fileName, _ = QFileDialog.getSaveFileName(self, 'Select PPT', '', 'PPT Files (*.pptx)')
    #     else:
    #         fileName = os.path.normpath(text.strip('"'))

    #     # Check if the file exists
    #     if not os.path.exists(fileName):
    #         prs = Presentation()
    #     else:
    #         # Load the existing presentation
    #         prs = Presentation(fileName)

    #     # Take the screenshot
    #     screenshot_path = "screenshot.png"
    #     widget_width, widget_height = self.screenshot_widget(self.tab_2, screenshot_path)

    #     try:
    #         # Creating the new slide
    #         slide_layout = prs.slide_layouts[6]
    #         slide = prs.slides.add_slide(slide_layout)

    #         # Scaling the screenshot
    #         slide_width = prs.slide_width
    #         slide_height = prs.slide_height
    #         width_ratio = slide_width / widget_width
    #         height_ratio = slide_height / widget_height
    #         scaling_factor = min(width_ratio, height_ratio)
    #         new_width = widget_width * scaling_factor
    #         new_height = widget_height * scaling_factor
    #         left = (slide_width - new_width) / 2
    #         top = (slide_height - new_height) / 2

    #         # Attaching the image
    #         slide.shapes.add_picture(screenshot_path, left, top, width=new_width, height=new_height)

    #         # Attach name
    #         left_inch = Inches(0.5)
    #         top_inch = Inches(0.5)
    #         width_inch = Inches(2)
    #         height_inch = Inches(1)
    #         text_box_left = slide.shapes.add_textbox(left_inch, top_inch, width_inch, height_inch)
    #         tf_left = text_box_left.text_frame
    #         tf_left.text = name

    #         # Attach comments
    #         left_inch = slide_width - Inches(4)
    #         text_box_right = slide.shapes.add_textbox(left_inch, top_inch, width_inch, height_inch)
    #         tf_right = text_box_right.text_frame
    #         tf_right.text = self.comments_textEdit.toPlainText()

    #         prs.save(fileName)
    #         print('Screenshot saved at', fileName)
    #     except Exception as e:
    #         print(f'An error occurred while saving the presentation: {e}')

    def when_save_plots_clicked2(self):
        """Save a PowerPoint slide for every tab that actually shows plots."""
        serial = f'{self.main_window.scanlist.serial.value():04d}'
        name   = self._next_unique_data_name()  
        text   = self.main_window.ppt_path.toPlainText()

        count = 1
        while os.path.exists(name):
            name_part, ext = os.path.splitext(name)
            name = os.path.join(folder, f"{name_part}_{count}{ext}")
            count += 1
        self._log_info(f"PPT legacy save requested: {name}", persist_current_run=False)
        # --- choose / create PPT file --------------------------------------------------
        if text == '':
            fileName, _ = QFileDialog.getSaveFileName(self, 'Select PPT', '', 'PPT Files (*.pptx)')
            if not fileName:
                return   # user cancelled
        else:
            fileName = os.path.normpath(text.strip('"'))

        folder = os.path.dirname(fileName)
        if folder and not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)

        if not os.path.exists(fileName):
            prs = Presentation()
            prs.slide_width  = Inches(13.333)   # 16:9
            prs.slide_height = Inches(7.5)
        else:
            prs = Presentation(fileName)

        # --- walk through every tab in the tab widget ---------------------------------
        for idx, tab in enumerate([self.Plots1Tab, self.Plots2Tab, self.Plots3Tab]):

            # 1.  does this tab have at least one plot?  (no helper needed)
            if not tab.findChildren((LinePlot, ImagePlot)):
                continue          # skip empty tab

            # 2.  take screenshot of that tab
            shot_path = f"screenshot.png"
            w_px, h_px = self.screenshot_widget(tab, shot_path)

            # 3.  add blank slide & picture (same sizing logic as before)
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            sw, sh = prs.slide_width, prs.slide_height

            scale = sh / h_px
            nw, nh = w_px * scale, h_px * scale
            if nw > sw * 0.8:
                scale = (sw * 0.8) / w_px
                nw, nh = w_px * scale, h_px * scale
            left = sw - nw
            top  = (sh - nh) / 2

            slide.shapes.add_picture(shot_path, left, top, width=nw, height=nh)

            try:
                os.remove(shot_path)          # delete the PNG immediately
            except OSError:
                pass                          # silent if, for any reason, it’s gone
            
            # 4.  add name (bold) and comments box on left
            left_in = Inches(0.0)
            top_in  = Inches(0.2)
            w_in    = Inches(3.0)
            h_in    = Inches(0.5)

            tb_name = slide.shapes.add_textbox(left_in, top_in, w_in, h_in)
            tb_name.text_frame.text = name
            for p in tb_name.text_frame.paragraphs:
                for run in p.runs:
                    run.font.bold = True

            tb_comm = slide.shapes.add_textbox(left_in, top_in + h_in + Inches(0.2),
                                               w_in, h_in * 2)
            tf = tb_comm.text_frame
            tf.word_wrap = True
            tf.text = self.comments_textEdit.toPlainText()
            for p in tf.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(12)

        # --- save ----------------------------------------------------------------------
        try:
            prs.save(fileName)
            self._log_info(f"PPT legacy save succeeded: {fileName}", persist_current_run=False)

            if os.path.exists(r"Z:\\"):                      # drive exists?
                backup_sub = self._backup_subfolder()
                if backup_sub == "":
                    self._log_warning(
                        "PPT legacy backup skipped: backup path is empty.",
                        persist_current_run=False,
                    )
                else:
                    backup_dir = os.path.join(backup_sub)
                    os.makedirs(backup_dir, exist_ok=True)

                    # 1) copy the PPT we just created
                    shutil.copy2(fileName,
                                 os.path.join(backup_dir,
                                              os.path.basename(fileName)))
                    self._log_info(
                        f"PPT legacy backup succeeded: {backup_dir}",
                        persist_current_run=False,
                    )
            else:
                self._log_warning(
                    "PPT legacy backup skipped: drive Z: not found.",
                    persist_current_run=False,
                )
        except Exception as e:
            self._log_error(
                f"PPT legacy save failed: {type(e).__name__}: {e}",
                persist_current_run=False,
            )

    def screenshot_widget(self,widget, filename):
        """Capture a screenshot of the widget and save it as a PNG file."""
        pixmap = widget.grab()
        pixmap.save(filename, 'PNG')
        return pixmap.width(), pixmap.height()

    def when_save_clicked(self):
        class CustomEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                elif isinstance(obj, float) and np.isnan(obj):
                    return "NaN"
                return super().default(obj)

        def write_json_snapshot(path):
            self._sync_scan_log_to_info()
            with open(path, "w", encoding="utf-8") as json_file:
                json.dump(self.info, json_file, cls=CustomEncoder, indent=4)

        def write_recovery_snapshot(original_name):
            temporary_path = None
            try:
                data_root = QtCore.QStandardPaths.writableLocation(
                    QtCore.QStandardPaths.StandardLocation.GenericDataLocation
                )
                if not data_root:
                    raise OSError("platform-local application-data directory is unavailable")
                recovery_dir = os.path.join(data_root, "ZMeter", "recovery")
                os.makedirs(recovery_dir, exist_ok=True)

                safe_name = re.sub(
                    r"[^A-Za-z0-9._-]+",
                    "_",
                    str(original_name or self.info.get("name", "scan")),
                ).strip("._") or "scan.json"
                if not safe_name.lower().endswith(".json"):
                    safe_name = f"{safe_name}.json"
                timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                stem = f"recovery_{timestamp}_{safe_name}"
                recovery_path = os.path.join(recovery_dir, stem)
                count = 1
                while os.path.exists(recovery_path):
                    name_part, extension = os.path.splitext(stem)
                    recovery_path = os.path.join(
                        recovery_dir, f"{name_part}_{count}{extension}"
                    )
                    count += 1

                temporary_path = f"{recovery_path}.{os.getpid()}.tmp"
                write_json_snapshot(temporary_path)
                os.replace(temporary_path, recovery_path)
                self._log_warning(f"Recovery JSON saved: {recovery_path}")
                return recovery_path
            except Exception as recovery_error:
                if temporary_path and os.path.exists(temporary_path):
                    try:
                        os.remove(temporary_path)
                    except OSError:
                        pass
                self._log_error(
                    "Recovery JSON save failed: "
                    f"{type(recovery_error).__name__}: {recovery_error}"
                )
                return None

        self.update_alllevel_setting_array()
        self.info["comments"] = self.comments_textEdit.toPlainText()
        self.info["plots_per_page"] = self.PlotsPerPage.currentText()
        self._sync_scan_log_to_info()

        text = self.main_window.save_info_path.toPlainText().strip()
        base_name = f"{self.info.get('name', 'scan')}.json"
        try:
            base_name = self._next_unique_data_name() + ".json"
            self.name = base_name

            if not text:
                fileName, _ = QFileDialog.getSaveFileName(
                    self, "Select File to Save", self.name
                )
                if not fileName:
                    self._log_warning(
                        "Manual save canceled by user; writing recovery JSON."
                    )
                    write_recovery_snapshot(base_name)
                    return
                folder, file = os.path.split(fileName)
                base_name = file
            else:
                folder = os.path.normpath(text.strip('"'))
                os.makedirs(folder, exist_ok=True)
                fileName = os.path.join(folder, base_name)

            count = 1
            while os.path.exists(fileName):
                name_part, ext = os.path.splitext(base_name)
                fileName = os.path.join(folder, f"{name_part}_{count}{ext}")
                count += 1
        except Exception as error:
            self._log_error(
                f"Manual save preparation failed: {type(error).__name__}: {error}"
            )
            write_recovery_snapshot(base_name)
            return

        try:
            write_json_snapshot(fileName)
            self._log_info(f"Manual save succeeded: {fileName}")

            if os.path.exists(r"Z:\\"):
                backup_sub = self._backup_subfolder()
                if backup_sub:
                    backup_dir = os.path.join(backup_sub)
                    os.makedirs(backup_dir, exist_ok=True)
                    backup_target = os.path.join(backup_dir, os.path.basename(fileName))
                    try:
                        shutil.copy2(fileName, backup_target)
                        self._log_info(f"JSON backup succeeded: {backup_target}")
                    except Exception as exc:
                        self._log_warning(
                            f"JSON backup failed: {type(exc).__name__}: {exc}"
                        )
                else:
                    self._log_warning("JSON backup skipped: backup path is empty.")
            else:
                self._log_warning("JSON backup skipped: drive Z: not found.")
        except Exception as e:
            self._log_error(f"Manual save failed: {type(e).__name__}: {e}")
            write_recovery_snapshot(base_name)

    def when_load_clicked(self):
        def handle_special_values(value):
            if value == "NaN":
                return np.nan
            return value

        def convert_special_values(obj):
            if isinstance(obj, list):
                return [convert_special_values(item) for item in obj]
            elif isinstance(obj, dict):
                return {key: convert_special_values(val) for key, val in obj.items()}
            else:
                return handle_special_values(obj)

        default_dir = self.main_window.save_info_path.toPlainText()
        fileName, _ = QFileDialog.getOpenFileName(
            self,
            "Open File",
            default_dir,
            "All Files (*);;Text Files (*.txt)",
        )
        if not fileName:
            self._log_warning("Load canceled by user.", persist_current_run=False)
            return

        try:
            with open(fileName, "r") as file:
                content = file.read()

            loaded_info = convert_special_values(json.loads(content))
            if not isinstance(loaded_info, dict):
                raise ValueError("Loaded file did not contain a scan dictionary.")

            self.info = loaded_info
            self.info.setdefault("comments", "")
            self.info.setdefault("scan_log", [])
            if not isinstance(self.info.get("scan_log"), list):
                self.info["scan_log"] = []

            ppp_val = self.info.get("plots_per_page", None)
            if ppp_val is not None:
                idx = self.PlotsPerPage.findText(str(ppp_val))
                if idx != -1:
                    self.PlotsPerPage.setCurrentIndex(idx)
        except Exception as e:
            self._log_error(
                f"Load failed: {type(e).__name__}: {e}",
                persist_current_run=False,
            )
            return

        loaded_log_lines = list(self.info.get("scan_log", []))

        widget = self.scrollArea.takeWidget()
        if widget:
            widget.deleteLater()

        for gp in self.graphing_plots:
            gp.setParent(None)
            gp.deleteLater()
        self.graphing_plots.clear()

        self.verticalLayout_2.removeWidget(self.all_plot_setting)
        self.all_plot_setting.setParent(None)
        self.all_plot_setting.deleteLater()

        self.all_level_setting = AllLevelSetting(
            all_level_info=self.info["levels"],
            setter_equipment_info=self.setter_equipment_info,
            getter_equipment_info=self.getter_equipment_info,
        )
        self.all_plot_setting = AllPlotSetting(level_info=self.info["levels"])
        self.verticalLayout_2.addWidget(self.all_plot_setting)
        self.scrollArea.setWidget(self.all_level_setting)
        self.graphing_plots = [AllPlots(level_info=self.info["levels"], page_number=i) for i in range(3)]
        self.plots1_layout.addWidget(self.graphing_plots[0])
        self.plots2_layout.addWidget(self.graphing_plots[1])
        self.plots3_layout.addWidget(self.graphing_plots[2])
        self._configure_plot_tab_stretch()

        self.populate()
        self.all_level_setting.sig_info_changed.connect(self.when_all_level_setting_infochanged)
        self.all_plot_setting.sig_info_changed.connect(self.when_all_plot_setting_infochanged)
        self.all_level_setting.sig_info_changed.connect(self.all_plot_setting.set_level_info_slot)
        self.all_level_setting.sig_info_changed.emit(self.all_level_setting.all_level_info)

        self.all_plot_setting.update_ui(self.info["plots"])
        for gp in self.graphing_plots:
            gp.receive_plot_info(self.info["plots"])
        self.update_all_plots()

        data = self.info.get("data", {})
        level_number = len(self.info["levels"])
        targets_array_FEL = []
        setters_targets_len_FEL = []

        for l in range(level_number):
            targets_array_FEL.append(self.info["levels"][f"level{l}"]["setting_array"])
            setters_targets_len_FEL.append(len(targets_array_FEL[l]) - 1)

        if data:
            for gp in self.graphing_plots:
                for plot in range(gp.plots_layout.count()):
                    w = gp.plots_layout.itemAt(plot).widget()
                    if isinstance(w, LinePlot):
                        w.load_plot(data, setters_targets_len_FEL)
                    if isinstance(w, ImagePlot):
                        w.load_image(data, setters_targets_len_FEL)

        self._replace_current_scan_log(loaded_log_lines)
        for line in loaded_log_lines:
            self._append_log_entry(line, include_timestamp=False, persist_current_run=False)

        self._log_info(
            f"Loaded scan JSON: {fileName} (loaded {len(loaded_log_lines)} log lines).",
            persist_current_run=False,
        )

    def when_setter_equipment_info_change(self,setter_equipment_info):
        self.setter_equipment_info=setter_equipment_info
        self.all_level_setting.set_setter_equipment_info(self.setter_equipment_info)

    def when_getter_equipment_info_change(self, getter_equipment_info):
        self.getter_equipment_info = getter_equipment_info
        self.all_level_setting.set_getter_equipment_info(self.getter_equipment_info)

    def scan_setters(self):
        destination=self.destinations[self.current_destinations_index]
        value=self.values_to_set[self.current_values_to_set_index]
        output=[]
        if "level" in destination:
            self.current_scanning_level=destination
            self.current_destinations_index+=1
            return(self.scan_setters())
        if isinstance(value, list):
            for i in range(len(value)):
                temp=[]
                destination = self.destinations[self.current_destinations_index]
                temp.append(value[i])
                temp.append(destination)
                output.append(temp)
                self.current_destinations_index += 1
        else:
            destination = self.destinations[self.current_destinations_index]
            output.append(value)
            output.append(destination)                
            self.current_destinations_index += 1
        self.current_values_to_set_index+=1
        return(output)
        
    def update_remaining_time_label(self, time_str):
        self.scan_time_info_1.setText(f"Remaining / Total Time: {time_str}")
        self.scan_time_info_2.setText(f"Remaining / Total Time: {time_str}")
        self.scan_time_info_3.setText(f"Remaining / Total Time: {time_str}")

    def update_remaining_points_label(self, point_str):
        self.scan_point_info_1.setText(f"Finished / Total Points: {point_str}")
        self.scan_point_info_2.setText(f"Finished / Total Points: {point_str}")
        self.scan_point_info_3.setText(f"Finished / Total Points: {point_str}")
    
    def auto_backup(self, trigger: bool):
        """Handle auto-backup signal from ScanLogic."""
        if not trigger:
            return

        self._log_info("Autosave triggered.")
            
        class CustomEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                elif isinstance(obj, float) and np.isnan(obj):
                    return "NaN"
                return super().default(obj)

        self.info["comments"] = self.comments_textEdit.toPlainText()

        ppp_box = self.PlotsPerPage
        self.info["plots_per_page"] = ppp_box.currentText()
        self._sync_scan_log_to_info()

        # Same data folder as normal save flow; always overwrite autosave.json.
        text = self.main_window.save_info_path.toPlainText().strip()
        if text:
            folder = os.path.normpath(text.strip('"'))
        elif hasattr(self.main_window, "save_path"):
            folder = os.path.normpath(str(self.main_window.save_path))
        else:
            folder = os.getcwd()

        os.makedirs(folder, exist_ok=True)
        fileName = os.path.join(folder, "autosave.json")

        try:
            with open(fileName, 'w') as json_file:
                json.dump(self.info, json_file, cls=CustomEncoder, indent=4)
            self._log_info(f"Autosave succeeded: {fileName}")
        except Exception as e:
            self._log_error(f"Autosave failed: {type(e).__name__}: {e}")

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    s = Scan()
    # s.all_level_setting.add_level()
    # s.all_level_setting.add_level()
    # s.all_level_setting.verticalLayout.itemAt(0).widget().add_master()
    # s.all_level_setting.verticalLayout.itemAt(1).widget().add_master()
    # s.all_plot_setting.when_add_image_clicked()
    # s.all_plot_setting.when_add_image_clicked()
    # s.all_plot_setting.when_add_image_clicked()
    # s.all_plot_setting.when_add_line_clicked()
    # s.all_plot_setting.when_add_line_clicked()
    # s.all_plot_setting.when_add_line_clicked()
    s.when_scan_clicked()
    s.show()
    app.exec()


