from pathlib import Path

from PyQt6 import QtWidgets, uic

from core.shared_runtime.kinesis import KinesisRuntime

try:
    from .BBD30X_logic import BBD30X_Logic
except ImportError:
    from BBD30X_logic import BBD30X_Logic


class BBD30X(QtWidgets.QWidget):

    def __init__(self, hardware=None, kinesis_runtime: KinesisRuntime | None = None):

        super(BBD30X, self).__init__()
        ui_path = Path(__file__).with_name("bbd30x.ui")
        uic.loadUi(str(ui_path), self)
        if hardware is None:
            from .BBD30X_hardware import BBD30x_hardware
            hardware = BBD30x_hardware(kinesis_runtime)
        self.logic = BBD30X_Logic(hardware=hardware)

        self.connect_button.clicked.connect(self.connect)
        self.disconnect_button.clicked.connect(self.disconnect)
        self.home_button.clicked.connect(self.home)
        self.go_button.clicked.connect(self.set_pos)
        self.set_button.clicked.connect(self.set_velocity_params)
        self.read_button.clicked.connect(self.read_pos)

        self.logic.sig_last_pos.connect(self.update_pos)
        self.logic.sig_connect.connect(self.set_on_off)

    def set_on_off(self, status):

        if status:
            self.label_on_off.setText("ON")
        else:
            self.label_on_off.setText("OFF")

    def update_pos(self, pos_mm):
        self.last_pos_label.setText(f"last positon: {pos_mm*1e3:.2f} um")

    def connect(self, serial=""):
        if serial is False or serial is None or serial == "":
            serial = self.lineEdit.text().strip()
        else:
            serial = str(serial).strip()
            self.lineEdit.setText(serial)

        if not serial:
            return

        self.logic.job = "connect"
        self.logic.preset_serial(serial)
        self.logic.start()

    def disconnect(self):

        if self.logic.is_connected is True:
            self.logic.job = "disconnect"
            self.logic.start()

    def set_pos(self):
        pos_um = self.pos_to_go_doubleSpinBox.value()
        self.logic.preset_target(pos_um / 1e3)
        self.logic.job = "set"
        self.logic.start()
        

    def read_pos(self):

        self.logic.job = "read"
        self.logic.start()

    def home(self):

        self.logic.job = "home"
        self.logic.start()

    def set_velocity_params(self):
        if self.lineEdit_2.text() == "":
            return
        if self.lineEdit_3.text() == "":
            return
        vel = float(self.lineEdit_2.text())
        acc = float(self.lineEdit_3.text())
        self.logic.preset_velocity_params(vel, acc)
        self.logic.job = "set_velocity_params"
        self.logic.start()

    def stop_scan(self):
        pass

    def start_scan(self):
        pass

    def force_stop(self):
        if self.logic.isRunning():
            self.logic.requestInterruption()
            self.logic.wait(1000)

    def terminate_dev(self):
        self.force_stop()
        self.logic.disconnect()
        print("BBD30X terminated.")
