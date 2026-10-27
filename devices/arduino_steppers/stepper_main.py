"""Three-motor panel; hardware I/O runs in the device worker, never Qt UI slots."""
from dataclasses import asdict
import json
from PyQt6 import QtCore, QtWidgets
from .stepper_hardware import AXES, MotorLimits
from .stepper_logic import StepperLogic


class ArduinoSteppers(QtWidgets.QWidget):
    route_commands_in_background = True

    def __init__(self, hardware=None):
        super().__init__()
        self.logic = StepperLogic(hardware)
        self._busy = False
        self.setWindowTitle("Arduino steppers — A / B / C")
        self.resize(760, 570)
        outer = QtWidgets.QVBoxLayout(self)
        port = QtWidgets.QHBoxLayout()
        port.addWidget(QtWidgets.QLabel("COM port"))
        self.address_lineEdit = QtWidgets.QLineEdit()
        self.address_lineEdit.setPlaceholderText("Port from lab profile")
        port.addWidget(self.address_lineEdit)
        self.connect_button = QtWidgets.QPushButton("Connect")
        self.disconnect_button = QtWidgets.QPushButton("Disconnect")
        port.addWidget(self.connect_button)
        port.addWidget(self.disconnect_button)
        outer.addLayout(port)
        self.tabs = QtWidgets.QTabWidget()
        outer.addWidget(self.tabs)
        self.controls, self.readbacks, self.metadata = {}, {}, {}
        for axis in AXES:
            page = QtWidgets.QWidget()
            grid = QtWidgets.QGridLayout(page)
            grid.addWidget(QtWidgets.QLabel("Absolute set target"), 0, 1)
            grid.addWidget(QtWidgets.QLabel("Last read / acknowledged"), 0, 3)
            controls = {}
            for row, (name, label, value, operation, getter) in enumerate((
                ("angle", "Angle (degrees)", 0, self.logic.move_angle, self.logic.read_angle),
                ("steps", "Position (full steps)", 0, self.logic.move_steps, self.logic.read_steps),
                ("rpm", "Speed (RPM)", 12 if axis == "A" else 7, self.logic.change_speed, self.logic.read_speed),
            ), 1):
                target = QtWidgets.QDoubleSpinBox() if name == "angle" else QtWidgets.QSpinBox()
                if name == "angle":
                    target.setDecimals(6)
                    target.setRange(-1e8, 1e8)
                else:
                    target.setRange(1 if name == "rpm" else -2147483647,
                                    12 if name == "rpm" else 2147483647)
                target.setValue(value)
                controls[name] = target
                button, get = QtWidgets.QPushButton("Set"), QtWidgets.QPushButton("Get")
                readback = QtWidgets.QLabel("—")
                readback.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
                readback.setMinimumWidth(130)
                self.readbacks[axis, name] = readback
                for col, widget in enumerate((QtWidgets.QLabel(label), target, button, readback, get)):
                    grid.addWidget(widget, row, col)
                button.clicked.connect(lambda checked=False, a=axis, op=operation, w=target: self._submit(op, a, w.value()))
                get.clicked.connect(lambda checked=False, a=axis, op=getter: self._submit(op, a))
            self.metadata[axis] = QtWidgets.QLabel("Firmware motor configuration: not read")
            grid.addWidget(self.metadata[axis], 4, 0, 1, 5)
            grid.addWidget(QtWidgets.QLabel("Local motion limits (full steps; review for your mechanics)"), 5, 0, 1, 5)
            limits = self.logic.hardware.limits[axis]
            for row, (name, label) in enumerate((("minimum_steps", "Minimum position"),
                                                 ("maximum_steps", "Maximum position"),
                                                 ("segment_steps", "Maximum steps per stop-aware segment")), 6):
                widget = QtWidgets.QSpinBox()
                widget.setRange(1 if name == "segment_steps" else -2147483647, 2147483647)
                widget.setValue(getattr(limits, name))
                controls[name] = widget
                grid.addWidget(QtWidgets.QLabel(label), row, 0, 1, 2)
                grid.addWidget(widget, row, 2, 1, 3)
            grid.setRowStretch(9, 1)
            self.controls[axis] = controls
            self.tabs.addTab(page, "Stepper " + axis)
        bottom = QtWidgets.QHBoxLayout()
        bottom.addWidget(QtWidgets.QLabel("Command timeout (s)"))
        self.timeout = QtWidgets.QDoubleSpinBox()
        self.timeout.setRange(0.1, 3600)
        self.timeout.setValue(self.logic.hardware.command_timeout_s)
        bottom.addWidget(self.timeout)
        self.apply_button = QtWidgets.QPushButton("Apply local limits")
        self.stop_button = QtWidgets.QPushButton("Stop subsequent segments")
        bottom.addWidget(self.apply_button)
        bottom.addWidget(self.stop_button)
        outer.addLayout(bottom)
        files = QtWidgets.QHBoxLayout()
        self.save_button, self.load_button = QtWidgets.QPushButton("Save setup"), QtWidgets.QPushButton("Load setup")
        files.addWidget(self.save_button)
        files.addWidget(self.load_button)
        outer.addLayout(files)
        note = QtWidgets.QLabel("Angle and steps address the same absolute position, not separate motors. "
                               "Set targets are never overwritten by Get. Board reset/upload may reset all counters. "
                               "No home/zero/motion is sent on connect, disconnect or exit. "
                               "Apply local limits before using scan channels; panel commands also apply them.")
        note.setWordWrap(True)
        outer.addWidget(note)
        self.status_label = QtWidgets.QLabel("Disconnected")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)
        self.connect_button.clicked.connect(lambda: self.request_connect())
        self.disconnect_button.clicked.connect(lambda: self._submit(self.logic.disconnect))
        self.stop_button.clicked.connect(self.logic.force_stop)
        self.apply_button.clicked.connect(self._apply_limits)
        self.save_button.clicked.connect(self._save)
        self.load_button.clicked.connect(self._load)
        self.logic.sig_axis.connect(self._show_axis)
        self.logic.sig_connected.connect(lambda value: self._update_controls())
        self.logic.sig_busy.connect(self._set_busy)
        self.logic.finished.connect(lambda: self._set_busy(False))
        self.logic.sig_status.connect(self.status_label.setText)
        self.logic.sig_error.connect(lambda message: self.status_label.setText("Stepper error: " + message))
        self._update_controls()

    def _limits(self):
        return {axis: MotorLimits(**{name: self.controls[axis][name].value()
                                     for name in ("minimum_steps", "maximum_steps", "segment_steps")}) for axis in AXES}

    def _apply_limits(self):
        try:
            self.logic.configure(self._limits(), self.timeout.value())
            self.status_label.setText("Local limits applied; no hardware command sent")
            return True
        except Exception as exc:
            self.status_label.setText(str(exc))
            return False

    def _submit(self, operation, *args):
        return self._apply_limits() and self.logic.submit(operation, *args)

    def request_connect(self, address=None):
        if address is not None:
            self.address_lineEdit.setText(str(address))
        return self._submit(self.logic.connect, self.address_lineEdit.text().strip())

    def _show_axis(self, data):
        axis = data["axis"]
        for name in ("steps", "angle", "rpm"):
            self.readbacks[axis, name].setText(f"{data[name]:.6g}")
        self.controls[axis]["rpm"].setMaximum(data["max_rpm"])
        self.metadata[axis].setText(f"Firmware: {data['steps_per_rev']} full steps/rev; maximum configured speed {data['max_rpm']} RPM")

    def _set_busy(self, busy):
        self._busy = busy
        self._update_controls()

    def _update_controls(self):
        connected = self.logic.connected
        for widget in (self.tabs, self.timeout, self.apply_button, self.save_button, self.load_button):
            widget.setEnabled(not self._busy)
        self.address_lineEdit.setEnabled(not self._busy and not connected)
        self.connect_button.setEnabled(not self._busy and not connected)
        self.disconnect_button.setEnabled(not self._busy and connected)
        self.stop_button.setEnabled(self._busy)

    def setup_dict(self):
        for limits in self._limits().values():
            limits.validate()
        return dict(schema_version=1, address=self.address_lineEdit.text(),
                    timeout_s=self.timeout.value(), limits={a: asdict(v) for a, v in self._limits().items()})

    def load_setup(self, data):
        if self.logic.is_busy() or self.logic.connected:
            raise RuntimeError("Disconnect and wait for idle before loading a controller setup")
        if (set(data) != {"schema_version", "address", "timeout_s", "limits"}
                or type(data["schema_version"]) is not int or data["schema_version"] != 1
                or not isinstance(data["address"], str)):
            raise ValueError("Unsupported stepper setup schema")
        limits = {axis: MotorLimits(**value) for axis, value in data["limits"].items()}
        self.logic.configure(limits, data["timeout_s"])
        self.address_lineEdit.setText(str(data["address"]))
        self.timeout.setValue(float(data["timeout_s"]))
        for axis, item in limits.items():
            for name, value in asdict(item).items():
                self.controls[axis][name].setValue(value)

    def _save(self):
        try:
            payload = json.dumps(self.setup_dict(), indent=2, allow_nan=False).encode()
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save stepper setup", "", "JSON (*.json)")
            if path:
                output = QtCore.QSaveFile(path)
                if not output.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
                    raise OSError(output.errorString())
                if output.write(payload) != len(payload) or not output.commit():
                    raise OSError(output.errorString())
        except Exception as exc:
            self.status_label.setText(str(exc))

    def _load(self):
        try:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load stepper setup", "", "JSON (*.json)")
            if path:
                with open(path, encoding="utf-8") as stream:
                    self.load_setup(json.load(stream))
        except Exception as exc:
            self.status_label.setText(str(exc))

    def stop_scan(self): self.logic.stop_scan()
    def start_scan(self): self.logic.start_scan()
    def force_stop(self): return self.logic.force_stop()
    def terminate_dev(self): return self.logic.terminate_dev()
