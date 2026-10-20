"""Single-motor Z panel; hardware I/O runs in the device worker, never Qt UI slots."""
from dataclasses import asdict, fields
import json
from PyQt6 import QtCore, QtWidgets
from .nema11_hardware import MotorLimits
from .nema11_logic import Nema11Logic

LIMIT_LABELS = (
    ("minimum_deg", "Minimum angle (deg)"),
    ("maximum_deg", "Maximum angle (deg)"),
    ("segment_deg", "Maximum degrees per stop-aware segment"),
    ("tolerance_deg", "Encoder position tolerance (deg)"),
    ("settle_timeout_s", "Encoder settle timeout (s)"),
)


class Nema11Stepper(QtWidgets.QWidget):
    route_commands_in_background = True

    def __init__(self, hardware=None):
        super().__init__()
        self.logic = Nema11Logic(hardware)
        self._busy = False
        self.setWindowTitle("NEMA 11 closed-loop Z stepper")
        self.resize(560, 420)
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

        self.motion = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(self.motion)
        grid.addWidget(QtWidgets.QLabel("Absolute set target"), 0, 1)
        grid.addWidget(QtWidgets.QLabel("Last encoder reading"), 0, 3)
        self.target = QtWidgets.QDoubleSpinBox()
        self.target.setDecimals(6)
        self.target.setRange(-1e8, 1e8)
        self.set_button, self.get_button = QtWidgets.QPushButton("Set"), QtWidgets.QPushButton("Get")
        self.readback = QtWidgets.QLabel("—")
        self.readback.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.readback.setMinimumWidth(130)
        for col, widget in enumerate((QtWidgets.QLabel("Z angle (deg)"), self.target,
                                      self.set_button, self.readback, self.get_button)):
            grid.addWidget(widget, 1, col)
        grid.addWidget(QtWidgets.QLabel("Local motion limits (review for your mechanics)"), 2, 0, 1, 5)
        self.limit_controls = {}
        defaults = MotorLimits()
        for row, (name, label) in enumerate(LIMIT_LABELS, 3):
            widget = QtWidgets.QDoubleSpinBox()
            widget.setDecimals(4)
            widget.setRange(-1e8, 1e8)
            widget.setValue(getattr(defaults, name))
            self.limit_controls[name] = widget
            grid.addWidget(QtWidgets.QLabel(label), row, 0, 1, 2)
            grid.addWidget(widget, row, 2, 1, 3)
        grid.addWidget(QtWidgets.QLabel("Command timeout (s)"), 8, 0, 1, 2)
        self.timeout = QtWidgets.QDoubleSpinBox()
        self.timeout.setRange(0.1, 3600)
        self.timeout.setValue(self.logic.hardware.command_timeout_s)
        grid.addWidget(self.timeout, 8, 2, 1, 3)
        outer.addWidget(self.motion)

        buttons = QtWidgets.QHBoxLayout()
        self.apply_button = QtWidgets.QPushButton("Apply local limits")
        self.stop_button = QtWidgets.QPushButton("Stop subsequent segments")
        self.save_button, self.load_button = QtWidgets.QPushButton("Save setup"), QtWidgets.QPushButton("Load setup")
        for button in (self.apply_button, self.stop_button, self.save_button, self.load_button):
            buttons.addWidget(button)
        outer.addLayout(buttons)
        note = QtWidgets.QLabel("Positions are motor-shaft degrees read from the motor encoder. "
                                "Connecting sets the current position to 0 deg. "
                                "No home/zero/motion is sent on disconnect or exit. "
                                "Apply local limits before using scan channels; panel commands also apply them.")
        note.setWordWrap(True)
        outer.addWidget(note)
        self.status_label = QtWidgets.QLabel("Disconnected")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        self.connect_button.clicked.connect(lambda: self.request_connect())
        self.disconnect_button.clicked.connect(lambda: self._submit(self.logic.disconnect))
        self.set_button.clicked.connect(lambda: self._submit(self.logic.move_angle, self.target.value()))
        self.get_button.clicked.connect(lambda: self._submit(self.logic.read_angle))
        self.stop_button.clicked.connect(self.logic.force_stop)
        self.apply_button.clicked.connect(self._apply_limits)
        self.save_button.clicked.connect(self._save)
        self.load_button.clicked.connect(self._load)
        self.logic.sig_position.connect(lambda value: self.readback.setText(f"{value:.6g}"))
        self.logic.sig_connected.connect(lambda value: self._update_controls())
        self.logic.sig_busy.connect(self._set_busy)
        self.logic.finished.connect(lambda: self._set_busy(False))
        self.logic.sig_status.connect(self.status_label.setText)
        self.logic.sig_error.connect(lambda message: self.status_label.setText("Stepper error: " + message))
        self._update_controls()

    def _limits(self):
        return MotorLimits(**{name: widget.value() for name, widget in self.limit_controls.items()})

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

    def _set_busy(self, busy):
        self._busy = busy
        self._update_controls()

    def _update_controls(self):
        connected = self.logic.connected
        for widget in (self.motion, self.apply_button, self.save_button, self.load_button):
            widget.setEnabled(not self._busy)
        self.address_lineEdit.setEnabled(not self._busy and not connected)
        self.connect_button.setEnabled(not self._busy and not connected)
        self.disconnect_button.setEnabled(not self._busy and connected)
        self.stop_button.setEnabled(self._busy)

    def setup_dict(self):
        limits = self._limits()
        limits.validate()
        return dict(schema_version=1, address=self.address_lineEdit.text(),
                    timeout_s=self.timeout.value(), limits=asdict(limits))

    def load_setup(self, data):
        if self.logic.is_busy() or self.logic.connected:
            raise RuntimeError("Disconnect and wait for idle before loading a controller setup")
        if (set(data) != {"schema_version", "address", "timeout_s", "limits"}
                or type(data["schema_version"]) is not int or data["schema_version"] != 1
                or not isinstance(data["address"], str)
                or set(data["limits"]) != {item.name for item in fields(MotorLimits)}):
            raise ValueError("Unsupported nema11_stepper setup schema")
        limits = MotorLimits(**data["limits"])
        self.logic.configure(limits, data["timeout_s"])
        self.address_lineEdit.setText(data["address"])
        self.timeout.setValue(float(data["timeout_s"]))
        for name, value in asdict(limits).items():
            self.limit_controls[name].setValue(value)

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
