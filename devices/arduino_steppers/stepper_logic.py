"""Worker/UI boundary and explicit numeric scan channels for three motors."""
import threading
from PyQt6 import QtCore
from .stepper_hardware import AXES, MotorStopped, StepperHardware


class StepperLogic(QtCore.QThread):
    sig_busy = QtCore.pyqtSignal(bool)
    sig_connected = QtCore.pyqtSignal(bool)
    sig_axis = QtCore.pyqtSignal(object)
    sig_status = QtCore.pyqtSignal(str)
    sig_error = QtCore.pyqtSignal(str)

    def __init__(self, hardware=None):
        super().__init__()
        self.hardware = hardware if hardware is not None else StepperHardware()
        self.stop_event = threading.Event()
        self._operation = threading.Lock()
        self._jobs = threading.Lock()
        self._job = None

    @property
    def connected(self):
        return self.hardware.connected

    def is_busy(self):
        return self.isRunning() or self._operation.locked()

    def _publish(self, axis):
        info = self.hardware.info[axis]
        steps = self.hardware.positions[axis]
        self.sig_axis.emit(dict(axis=axis, steps=steps, angle=steps * 360 / info.steps_per_revolution,
                                rpm=info.speed_rpm, steps_per_rev=info.steps_per_revolution,
                                max_rpm=info.maximum_rpm))

    def connect(self, address):
        with self._operation:
            self.hardware.connect(address, self.stop_event)
            for axis in AXES:
                self._publish(axis)
        self.sig_connected.emit(True)
        self.sig_status.emit("Connected; positions are software counters since board reset, not encoders")
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

    def _axis_call(self, axis, operation, *args):
        if not self._operation.acquire(blocking=False):
            raise RuntimeError("Another motor operation is active")
        self.sig_busy.emit(True)
        try:
            if not self.connected:
                raise RuntimeError("Connect arduino_steppers first")
            value = operation(axis, *args)
            return value
        finally:
            if axis in self.hardware.positions and axis in self.hardware.info:
                self._publish(axis)  # Last acknowledged data, no extra I/O on failure/stop.
            self._operation.release()
            self.sig_busy.emit(False)

    def move_steps(self, axis, value):
        return self._axis_call(axis, self.hardware.move_steps, value, self.stop_event)

    def move_angle(self, axis, value):
        return self._axis_call(axis, self.hardware.move_angle, value, self.stop_event)

    def read_steps(self, axis):
        return self._axis_call(axis, self.hardware.read_steps)

    def read_angle(self, axis):
        return self._axis_call(axis, self.hardware.read_angle)

    def change_speed(self, axis, value):
        return self._axis_call(axis, self.hardware.set_speed, value)

    def read_speed(self, axis):
        return self._axis_call(axis, lambda motor: self.hardware.read_info(motor).speed_rpm)

    # Absolute native positions; no relative-jog aliases in the scan catalog.
    def set_stepperA_steps(self, value): return self.move_steps("A", value)
    def get_stepperA_steps(self): return self.read_steps("A")
    def set_stepperB_steps(self, value): return self.move_steps("B", value)
    def get_stepperB_steps(self): return self.read_steps("B")
    def set_stepperC_steps(self, value): return self.move_steps("C", value)
    def get_stepperC_steps(self): return self.read_steps("C")
    def set_stepperA_angle(self, value): return self.move_angle("A", value)
    def get_stepperA_angle(self): return self.read_angle("A")
    def set_stepperB_angle(self, value): return self.move_angle("B", value)
    def get_stepperB_angle(self): return self.read_angle("B")
    def set_stepperC_angle(self, value): return self.move_angle("C", value)
    def get_stepperC_angle(self): return self.read_angle("C")
    def set_stepperA_speed_rpm(self, value): return self.change_speed("A", value)
    def get_stepperA_speed_rpm(self): return self.read_speed("A")
    def set_stepperB_speed_rpm(self, value): return self.change_speed("B", value)
    def get_stepperB_speed_rpm(self): return self.read_speed("B")
    def set_stepperC_speed_rpm(self, value): return self.change_speed("C", value)
    def get_stepperC_speed_rpm(self): return self.read_speed("C")

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
