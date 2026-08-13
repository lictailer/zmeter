from PyQt6 import QtCore

try:
    from .BBD30X_hardware import BBD30x_hardware
except ImportError:
    from BBD30X_hardware import BBD30x_hardware


class BBD30X_Logic(QtCore.QThread):

    sig_last_pos = QtCore.pyqtSignal(object)
    sig_connect = QtCore.pyqtSignal(object)

    def __init__(self, hardware=None):
        QtCore.QThread.__init__(self)
        self.is_connected = False
        self.target = 0
        self.last_deg = 0
        self.job = ""
        self.hw = hardware if hardware is not None else BBD30x_hardware()
        self.hardware = self.hw
        self.serial = ""
        self.vel = 0
        self.acc = 0

    def preset_serial(self, serial):
        self.serial = serial

    def connect(self, serial: str):
        if self.is_connected:
            return True
        self.hw.connect(serial)
        self.is_connected = True
        self.sig_connect.emit(True)
        return True

    def disconnect(self):
        try:
            self.hw.disconnect()
        finally:
            self.is_connected = False
            self.sig_connect.emit(False)

    def preset_target(self, pos):
        self.target = pos

    def set_pos(self, pos_mm):
        pos_mm=float(pos_mm)
        self.hw.move(pos_mm)
        self.read_pos()

    def read_pos(self):
        read = self.hw.get_position_mm()
        self.sig_last_pos.emit(read)
        return read

    def get_pos(self):
        return self.read_pos()

    def home(self):
        self.hw.home()

    def preset_velocity_params(self, vel, acc):
        self.vel = vel
        self.acc = acc

    def set_velocity_params(self, vel, acc):
        self.hw.set_velocity_params(vel, acc)

    def run(self):
        if self.job == "connect":
            self.connect(self.serial)

        elif self.job == "disconnect":
            self.disconnect()

        elif self.job == "set":
            self.set_pos(self.target)

        elif self.job == "read":
            self.read_pos()

        elif self.job == "home":
            self.home()

        elif self.job == "set_velocity_params":
            self.set_velocity_params(self.vel, self.acc)

        self.job = ""
