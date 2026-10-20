"""Worker/UI boundary and the absolute Z angle scan channel."""
import threading
from PyQt6 import QtCore
from .nema11_hardware import MotorStopped, Nema11Hardware


class Nema11Logic(QtCore.QThread):
    sig_busy = QtCore.pyqtSignal(bool)
    sig_connected = QtCore.pyqtSignal(bool)
    sig_position = QtCore.pyqtSignal(object)
    sig_status = QtCore.pyqtSignal(str)
    sig_error = QtCore.pyqtSignal(str)

    def __init__(self, hardware=None):
        super().__init__()
        self.hardware = hardware if hardware is not None else Nema11Hardware()
        self.stop_event = threading.Event()
        self._operation = threading.Lock()
        self._jobs = threading.Lock()
        self._job = None

    @property
    def connected(self):
        return self.hardware.connected

    def is_busy(self):
        return self.isRunning() or self._operation.locked()

    def connect(self, address):
        with self._operation:
            self.hardware.connect(address, self.stop_event)
            self.sig_position.emit(self.hardware.position)
        self.sig_connected.emit(True)
        self.sig_status.emit("Connected; current position set to 0 deg")
        return True

    def configure(self, limits, timeout):
        if self.is_busy():
            raise RuntimeError("Wait for the active motor operation before changing limits")
        self.hardware.configure(limits, timeout)

    def disconnect(self):
        if not self._operation.acquire(blocking=False):
            raise RuntimeError("Wait for the current motor segment before disconnecting")
        try:
            self.hardware.disconnect()
        finally:
            self._operation.release()
        self.sig_connected.emit(False)
        self.sig_status.emit("Disconnected; no motion/home/zero command sent")

    def _call(self, operation, *args):
        if not self._operation.acquire(blocking=False):
            raise RuntimeError("Another motor operation is active")
        self.sig_busy.emit(True)
        try:
            if not self.connected:
                raise RuntimeError("Connect nema11_stepper first")
            return operation(*args)
        finally:
            if self.hardware.position is not None:
                self.sig_position.emit(self.hardware.position)  # Last encoder reading, no extra I/O.
            self._operation.release()
            self.sig_busy.emit(False)

    def move_angle(self, value):
        return self._call(self.hardware.move_angle, value, self.stop_event)

    def read_angle(self):
        return self._call(self.hardware.read_angle)

    # Absolute encoder-confirmed shaft angle in degrees; the only scan channel.
    def set_z_angle(self, value): return self.move_angle(value)
    def get_z_angle(self): return self.read_angle()

    def submit(self, operation, *args):
        with self._jobs:
            if self.is_busy() or self._job is not None:
                self.sig_error.emit("Motor controller is busy")
                return False
            self.stop_event.clear()
            self._job = operation, args
            self.sig_busy.emit(True)
            self.start()
            return True

    def run(self):
        try:
            operation, args = self._job
            operation(*args)
        except MotorStopped as exc:
            self.sig_status.emit(str(exc))
        except Exception as exc:
            self.sig_error.emit(str(exc))
        finally:
            with self._jobs:
                self._job = None
            self.sig_busy.emit(False)

    def force_stop(self):
        self.stop_event.set()
        self.sig_status.emit("Stop requested; waiting for any in-flight segment acknowledgement")
        return True

    def stop_scan(self):
        if self.is_busy():
            raise RuntimeError("A motor operation is still active")
        self.stop_event.clear()

    def start_scan(self):
        self.stop_event.clear()

    def terminate_dev(self, wait_ms=3000):
        self.stop_event.set()
        if self.isRunning() and not self.wait(wait_ms):
            return False
        if not self._operation.acquire(timeout=wait_ms / 1000):
            return False
        try:
            self.hardware.disconnect()
        finally:
            self._operation.release()
        self.sig_connected.emit(False)
        return True
