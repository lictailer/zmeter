"""Run this file directly to open the standalone MFLI panel.

Nothing connects until the operator clicks Connect. LabOne owns streaming,
frequency/routing, filters, and output enable/range configuration.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
import sys
import time

from PyQt6 import QtCore, QtWidgets
import pyqtgraph as pg

if __package__:
    from .MFLI_hardware import MFLIHardware, parse_address, SERVER_PORT
    from .MFLI_logic import MFLILogic, Completion
else:
    from MFLI_hardware import MFLIHardware, parse_address, SERVER_PORT
    from MFLI_logic import MFLILogic, Completion


# Local launch configuration; the UI also allows editing connection settings.
READ_TIMEOUT_SECONDS = 5.0
HISTORY_POINTS = 600


class LivePlot(QtWidgets.QGroupBox):
    """One independently selectable demodulator/quantity history."""

    def __init__(self, quantity: str):
        super().__init__()
        self.times = deque(maxlen=HISTORY_POINTS)
        self.values = deque(maxlen=HISTORY_POINTS)
        self._unit = None
        layout = QtWidgets.QVBoxLayout(self)
        selectors = QtWidgets.QHBoxLayout()
        self.demod = QtWidgets.QComboBox()
        self.demod.addItems([f"Demod {i}" for i in range(1, 5)])
        self.quantity = QtWidgets.QComboBox()
        self.quantity.addItems(["X", "Y", "R", "theta"])
        self.quantity.setCurrentText(quantity)
        self.latest = QtWidgets.QLabel("No data")
        selectors.addWidget(self.demod)
        selectors.addWidget(self.quantity)
        selectors.addWidget(self.latest, 1)
        layout.addLayout(selectors)
        self.plot = pg.PlotWidget()
        self.plot.setMinimumSize(260, 130)
        self.plot.setLabel("bottom", "Elapsed time", units="s")
        self.plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.curve = self.plot.plot(pen=pg.mkPen("#5dc4f0", width=1.5), connect="finite")
        layout.addWidget(self.plot)
        self.demod.currentIndexChanged.connect(self.clear)
        self.quantity.currentIndexChanged.connect(self.clear)
        self.clear()

    def clear(self, *_):
        self.times.clear()
        self.values.clear()
        self._unit = None
        self.curve.setData([], [])
        self.latest.setText("No data")
        self.latest.setToolTip("")
        self.plot.setTitle(f"{self.demod.currentText()} · {self.quantity.currentText()}")
        self.plot.setLabel("left", self.quantity.currentText())

    def update_batch(self, batch, elapsed: float):
        channel = self.demod.currentIndex() + 1
        if channel in batch.problems:
            self.latest.setText("Data unavailable")
            self.latest.setToolTip(batch.problems[channel])
            # Insert one gap, not one point per failed monitor tick.
            if self.values and self.values[-1] == self.values[-1]:
                self.times.append(elapsed)
                self.values.append(float("nan"))
                self.curve.setData(list(self.times), list(self.values))
            return
        sample = batch.samples.get(channel)
        if sample is None:
            return
        quantity = self.quantity.currentText()
        unit = "deg" if quantity == "theta" else sample.unit
        if self._unit is not None and self._unit != unit:
            self.clear()
        self._unit = unit
        value = getattr(sample, quantity)
        self.times.append(elapsed)
        self.values.append(value)
        self.curve.setData(list(self.times), list(self.values))
        self.plot.setLabel("left", quantity, units=unit)
        self.latest.setText(f"{value:.7g} {unit}")
        self.latest.setToolTip(f"{sample.frequency:g} Hz; timestamp {sample.timestamp}")


class MFLI(QtWidgets.QWidget):
    # Routed scalar channels wait on the API worker and must not occupy Qt's UI thread.
    route_commands_in_background = True
    def __init__(self, logic: MFLILogic | None = None, *, standalone=False):
        super().__init__()
        self.setWindowTitle("MFLI")
        self.standalone = standalone
        self._configuration_error = None
        self.resize(1080, 900)
        self.logic = logic if logic is not None else MFLILogic(
            MFLIHardware(read_timeout=READ_TIMEOUT_SECONDS)
        )
        self._pending = set()
        self._monitor_pending = False
        self._closing = False
        self._closed = False
        self._disconnecting = False
        self._close_after_disconnect = False
        self._epoch = time.monotonic()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._monitor_tick)
        self._build_ui()
        self.logic.completed.connect(self._completed)
        self.logic.log.connect(self._log)
        self.logic.stopped.connect(self._worker_stopped)
        self.logic.state_changed.connect(self._sync_state)
        self._controls()
        self._log("INFO", "Ready. Configure frequencies, streaming, and output settings in LabOne; then connect.")

    @staticmethod
    def _number(low=-1e9, high=1e9, suffix=""):
        editor = QtWidgets.QDoubleSpinBox()
        editor.setRange(low, high)
        editor.setDecimals(9)
        editor.setSingleStep(0.001)
        editor.setSuffix(suffix)
        editor.setKeyboardTracking(False)
        editor.setMinimumWidth(135)
        return editor

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        connection = QtWidgets.QHBoxLayout()
        self.serial = QtWidgets.QLineEdit()
        self.host = QtWidgets.QLineEdit()
        self.serial.setPlaceholderText("DEV30037")
        self.host.setPlaceholderText("Blank uses instrument hostname")
        self.port = QtWidgets.QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(SERVER_PORT)
        for label, widget in [("Serial", self.serial), ("Host", self.host), ("Port", self.port)]:
            connection.addWidget(QtWidgets.QLabel(label))
            connection.addWidget(widget)
        self.connect_button = QtWidgets.QPushButton("Connect")
        self.disconnect_button = QtWidgets.QPushButton("Disconnect")
        connection.addWidget(self.connect_button)
        connection.addWidget(self.disconnect_button)
        root.addLayout(connection)
        self.status = QtWidgets.QLabel("Disconnected")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.connect_button.clicked.connect(self._connect)
        self.disconnect_button.clicked.connect(self._disconnect)

        settings = QtWidgets.QGroupBox("Signal Output · four demodulator-associated tones")
        grid = QtWidgets.QGridLayout(settings)
        headers = ["Tone", "Amplitude (V peak)", "", "Readback (V peak)",
                   "Phase (deg)", "", "Readback (deg)", "LabOne assignment / frequency"]
        for column, label in enumerate(headers):
            grid.addWidget(QtWidgets.QLabel(label), 0, column)
        self.amplitudes, self.phases = [], []
        self.amplitude_readbacks, self.phase_readbacks, self.assignments = [], [], []
        self.write_buttons = []
        for channel in range(1, 5):
            amplitude = self._number()
            phase = self._number(-180, 180)
            phase.setSingleStep(1)
            amp_button = QtWidgets.QPushButton("Set")
            phase_button = QtWidgets.QPushButton("Set")
            amp_readback, phase_readback = QtWidgets.QLabel("—"), QtWidgets.QLabel("—")
            assignment = QtWidgets.QLabel("—")
            row = [QtWidgets.QLabel(f"OSC{channel}"), amplitude, amp_button, amp_readback,
                   phase, phase_button, phase_readback, assignment]
            for column, widget in enumerate(row):
                grid.addWidget(widget, channel, column)
            amp_button.clicked.connect(
                lambda checked=False, c=channel, e=amplitude: self._dispatch("amplitude", c, e.value()))
            phase_button.clicked.connect(
                lambda checked=False, c=channel, e=phase: self._dispatch("phase", c, e.value()))
            self.amplitudes.append(amplitude)
            self.phases.append(phase)
            self.amplitude_readbacks.append(amp_readback)
            self.phase_readbacks.append(phase_readback)
            self.assignments.append(assignment)
            self.write_buttons.extend([amp_button, phase_button])
        self.offset = self._number()
        self.offset_button = QtWidgets.QPushButton("Set DC")
        self.offset_readback = QtWidgets.QLabel("—")
        self.range_label = QtWidgets.QLabel("Range: —")
        self.refresh_button = QtWidgets.QPushButton("Refresh settings")
        grid.addWidget(QtWidgets.QLabel("DC offset (V)"), 5, 0)
        grid.addWidget(self.offset, 5, 1)
        grid.addWidget(self.offset_button, 5, 2)
        grid.addWidget(self.offset_readback, 5, 3)
        grid.addWidget(self.range_label, 5, 4, 1, 3)
        grid.addWidget(self.refresh_button, 5, 7)
        self.offset_button.clicked.connect(lambda: self._dispatch("offset", self.offset.value()))
        self.refresh_button.clicked.connect(lambda: self._dispatch("refresh"))
        self.write_buttons.append(self.offset_button)
        root.addWidget(settings)

        monitor = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton("Start graphs")
        self.pause_button = QtWidgets.QPushButton("Pause")
        self.clear_button = QtWidgets.QPushButton("Clear graphs")
        self.interval = QtWidgets.QSpinBox()
        self.interval.setRange(50, 60000)
        self.interval.setValue(100)
        self.interval.setSuffix(" ms")
        for widget in [self.start_button, self.pause_button, self.clear_button,
                       QtWidgets.QLabel("Refresh interval"), self.interval]:
            monitor.addWidget(widget)
        monitor.addStretch()
        root.addLayout(monitor)
        self.start_button.clicked.connect(self._start)
        self.pause_button.clicked.connect(self._pause)
        self.clear_button.clicked.connect(self._clear)
        self.interval.valueChanged.connect(self.timer.setInterval)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        figures = QtWidgets.QWidget()
        plots_layout = QtWidgets.QGridLayout(figures)
        self.plots = [LivePlot(quantity) for quantity in ("X", "Y", "R", "theta")]
        for i, plot in enumerate(self.plots):
            plots_layout.addWidget(plot, i // 2, i % 2)
        splitter.addWidget(figures)
        log_group = QtWidgets.QGroupBox("Device log")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        self.log_window = QtWidgets.QPlainTextEdit()
        self.log_window.setReadOnly(True)
        self.log_window.setMaximumBlockCount(500)
        self.log_window.setMinimumHeight(70)
        log_layout.addWidget(self.log_window)
        splitter.addWidget(log_group)
        splitter.setSizes([500, 150])
        splitter.setStretchFactor(0, 1)
        root.addWidget(splitter, 1)

    def _controls(self):
        allowed = not self.logic.scan_active and not self.logic.stopping
        idle = not self._pending and not self._closing and not self._disconnecting and allowed
        connected = self.logic.connected
        for editor in [self.serial, self.host, self.port]:
            editor.setEnabled(idle and not connected and not self.logic.cleanup_needed)
        self.connect_button.setEnabled(idle and not connected and not self.logic.cleanup_needed)
        self.disconnect_button.setEnabled(
            not self._closing and not self._disconnecting and not self.logic.scan_active and
            (connected or self.logic.cleanup_needed or bool(self._pending))
        )
        for widget in self.write_buttons + self.amplitudes + self.phases + [self.offset, self.refresh_button]:
            widget.setEnabled(idle and connected)
        self.start_button.setEnabled(idle and connected and not self.timer.isActive())
        self.pause_button.setEnabled(self.timer.isActive() and not self._closing)

    def _dispatch(self, action, *args, timeout_ms=10_000):
        try:
            future = self.logic.request(action, *args, timeout_ms=timeout_ms)
        except Exception as exc:
            self._log("ERROR", f"Cannot schedule {action}: {exc}")
            self.status.setText(str(exc))
            return False
        if action == "monitor":
            self._monitor_pending = not future.cancelled()
        else:
            self._pending.add(future)
            self.status.setText(f"{action.capitalize()} in progress…")
            if action == "connect":
                QtCore.QTimer.singleShot(timeout_ms, lambda: self.logic.connection_deadline(future))
        self._controls()
        return True

    def _connect(self):
        self._dispatch("connect", self.serial.text(), self.host.text(), self.port.value())

    def _disconnect(self):
        self._pause()
        if self._dispatch("disconnect"):
            self._disconnecting = True
            self._controls()

    def _start(self):
        if self.logic.connected and not self._closing:
            try:
                self.logic.monitoring_request(True)
            except RuntimeError as exc:
                self._log("WARN", str(exc))
                return
            self.timer.start(self.interval.value())
            self._log("INFO", "Live monitoring started.")
            self._controls()
            self._monitor_tick()

    def _pause(self):
        self.logic.monitoring_request(False)
        if self.timer.isActive():
            self.timer.stop()
            self._log("INFO", "Live monitoring paused.")
        self._controls()

    def _clear(self):
        self._epoch = time.monotonic()
        for plot in self.plots:
            plot.clear()

    def _monitor_tick(self):
        if self.logic.monitoring and self.timer.isActive() and not self._pending and not self._monitor_pending:
            self._dispatch("monitor")

    def _show_settings(self, settings):
        for tone in settings.tones:
            i = tone.channel - 1
            self.amplitudes[i].setValue(tone.amplitude)
            self.phases[i].setValue(tone.phase)
            self.amplitude_readbacks[i].setText(f"{tone.amplitude:.9g}")
            self.phase_readbacks[i].setText(f"{tone.phase:.9g}")
            self.assignments[i].setText(f"Osc {tone.oscillator} / {tone.frequency:.9g} Hz")
        self.offset.setValue(settings.offset)
        self.offset_readback.setText(f"{settings.offset:.9g} V")
        self.range_label.setText(f"Output range: ±{settings.output_range:g} V")

    @QtCore.pyqtSlot(object)
    def _completed(self, event: Completion):
        action = event.job.action
        self._pending.discard(event.job.future)
        if action == "monitor":
            self._monitor_pending = False
        if action == "disconnect":
            self._disconnecting = False
            if self._close_after_disconnect:
                self._close_after_disconnect = False
                if event.error is None:
                    self._dispatch("shutdown")
                else:
                    self._closing = False
        if event.error is not None:
            self.status.setText(f"{action}: {event.error}")
            if action == "shutdown":
                self._closing = False  # Keep the window alive for cleanup retry.
            if not self.logic.connected:
                self._pause()
        elif action == "connect":
            self._clear()
            self._show_settings(event.result[1])
            self.status.setText(f"Connected to {event.result[0]['serial']}")
        elif action == "refresh":
            self._show_settings(event.result)
            self.status.setText("Settings refreshed")
        elif action in {"amplitude", "phase"}:
            i = event.job.args[0] - 1
            editors = self.amplitudes if action == "amplitude" else self.phases
            labels = self.amplitude_readbacks if action == "amplitude" else self.phase_readbacks
            editors[i].setValue(event.result)
            labels[i].setText(f"{event.result:.9g}")
            self.status.setText(f"OSC{i + 1} {action} acknowledged: {event.result:.9g}")
        elif action == "offset":
            self.offset.setValue(event.result)
            self.offset_readback.setText(f"{event.result:.9g} V")
            self.status.setText(f"DC offset acknowledged: {event.result:.9g} V")
        elif action == "monitor" and self.timer.isActive() and not self._closing:
            for plot in self.plots:
                plot.update_batch(event.result, time.monotonic() - self._epoch)
            self.status.setText("Monitoring" if not event.result.problems else
                                "Monitoring · " + " | ".join(event.result.problems.values()))
        elif action in {"disconnect", "shutdown"}:
            self.status.setText("Disconnected · settings remain applied")
        if self._closing:
            self.status.setText("Closing client after the active operation finishes…")
        self._controls()

    @QtCore.pyqtSlot(str, str)
    def _log(self, level, message):
        self.log_window.appendPlainText(f"[{datetime.now():%H:%M:%S}] [{level}] {message}")
        bar = self.log_window.verticalScrollBar()
        bar.setValue(bar.maximum())

    def closeEvent(self, event):
        if not self.standalone and not self._closed:
            self.hide()
            event.ignore()
            return
        if self._closed:
            event.accept()
            return
        event.ignore()
        if self._closing:
            return
        self._pause()
        if self._disconnecting:
            self._closing = True
            self._close_after_disconnect = True
            self.status.setText("Waiting for client disconnect before closing…")
            self._controls()
            return
        self._closing = True
        if not self._dispatch("shutdown"):
            self._closing = False
        self._controls()

    @QtCore.pyqtSlot()
    def _worker_stopped(self):
        self._closed = True
        self.close()

    @QtCore.pyqtSlot()
    def _sync_state(self):
        if self.logic.monitoring and not self._closing:
            if not self.timer.isActive():
                self.timer.start(self.interval.value())
        else:
            self.timer.stop()
        if self.logic.scan_active:
            self.status.setText("Scan in progress · panel controls and monitoring suspended")
        self._controls()

    def configure_address(self, address):
        """Owner-thread prefill only; bad addresses remain a panel-level error."""
        try:
            device, host, port = parse_address(address)
        except ValueError as exc:
            self._configuration_error = str(exc)
            self.serial.clear()
            self.host.clear()
            self.status.setText(str(exc))
            self._log("ERROR", f"Address {address!r}: {exc}")
            return False
        self._configuration_error = None
        self.serial.setText(device.upper())
        self.host.setText(host)
        self.port.setValue(port)
        return True

    def startup_connect(self, address, timeout_ms=10_000):
        # Registry calls startup on the owner/UI thread, never wait here.
        if not self.configure_address(address):
            return False
        return None if self._dispatch("connect", *parse_address(address), timeout_ms=timeout_ms) else False

    def connect(self, address, timeout_ms=10_000):
        """Strict manager callback; called on a lifecycle worker, not the UI."""
        return self.logic.connect_device(*parse_address(address), timeout_ms=timeout_ms)

    def disconnect(self):
        return self.logic.disconnect_device()

    def stop_scan(self):
        self.logic.stop_scan()

    def start_scan(self):
        self.logic.start_scan()

    def force_stop(self):
        self.logic.force_stop()

    def terminate_dev(self):
        return self.logic.terminate()

    def close_managed(self):
        self.logic.assert_terminated()
        self._closed = True
        self.close()


def main(address=""):
    app = QtWidgets.QApplication(sys.argv)
    window = MFLI(standalone=True)
    if address:
        window.configure_address(address)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
