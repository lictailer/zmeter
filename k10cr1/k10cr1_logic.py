from collections import deque
from ctypes import byref, c_char_p, c_int
from time import sleep

from PyQt6 import QtCore

from core.shared_runtime.kinesis import KinesisRuntime, KinesisRuntimeLease

from . import k10cr1_hardware as ism


class K10CR1Logic(QtCore.QThread):
    DEVICE_MANAGER_COMPONENT = "k10cr1-native-integrated-stepper"

    sig_last_pos = QtCore.pyqtSignal(object)
    sig_log = QtCore.pyqtSignal(object)
    sig_connect = QtCore.pyqtSignal(object)

    def __init__(self, kinesis_runtime: KinesisRuntime | None = None):
        super().__init__()
        self.kinesis_runtime = kinesis_runtime or KinesisRuntime()
        self._kinesis_lease: KinesisRuntimeLease | None = None
        self.is_connected = False
        self.target = 0
        self.last_deg = 0
        self.job = ""

    def assign_serial(self, serial):
        self.serial_no = c_char_p(bytes(serial, "utf-8"))

    def _emit_log(self, message: object, level: str = "INFO") -> None:
        self.sig_log.emit((str(level).upper(), str(message)))

    def _build_device_list(self) -> None:
        result = int(ism.TLI_BuildDeviceList())
        if result != 0:
            raise RuntimeError(f"K10CR1 could not build the device list (code {result})")

    def _serial_text(self) -> str:
        value = self.serial_no.value or b""
        return value.decode(errors="replace")

    @staticmethod
    def _decode_c_text(value: object) -> str:
        return bytes(value).split(b"\x00", 1)[0].decode(errors="replace")

    def connect(self):
        if self.is_connected:
            return True

        serial = self._serial_text()
        self._emit_log(f"Connecting to K10CR1 {serial}.")
        lease = self.kinesis_runtime.acquire(f"K10CR1:{id(self):x}")
        opened = False
        try:
            ism.configure_runtime(self.kinesis_runtime)
            self.kinesis_runtime.ensure_device_manager(
                self.DEVICE_MANAGER_COMPONENT,
                self._build_device_list,
            )

            open_result = int(ism.ISC_Open(self.serial_no))
            if open_result != 0:
                self._emit_log(
                    "K10CR1 open failed; refreshing DeviceManager once.",
                    "WARNING",
                )
                self.kinesis_runtime.refresh_device_manager(
                    self.DEVICE_MANAGER_COMPONENT,
                    self._build_device_list,
                )
                open_result = int(ism.ISC_Open(self.serial_no))
                if open_result != 0:
                    raise RuntimeError(
                        "K10CR1 could not open after DeviceManager refresh "
                        f"(code {open_result})"
                    )
            opened = True

            hw_info = ism.TLI_HardwareInformation()
            info_result = int(
                ism.ISC_GetHardwareInfoBlock(self.serial_no, byref(hw_info))
            )
            if info_result != 0:
                self._emit_log(
                    "K10CR1 connected, but hardware information could not be read "
                    f"(code {info_result}).",
                    "WARNING",
                )
            else:
                model = self._decode_c_text(hw_info.modelNumber)
                self._emit_log(
                    f"Connected to K10CR1 {serial}; model {model}, "
                    f"firmware {hw_info.firmwareVersion}, "
                    f"channels {hw_info.numChannels}."
                )

            velocity = ism.MOT_VelocityParameters()
            ism.ISC_GetVelParamsBlock(self.serial_no, byref(velocity))
            velocity.minVelocity = c_int(0)
            velocity.acceleration = c_int(15020)
            velocity.maxVelocity = c_int(73300335)
            ism.ISC_SetVelParamsBlock(self.serial_no, byref(velocity))
            ism.ISC_GetVelParamsBlock(self.serial_no, byref(velocity))

            self._kinesis_lease = lease
            self.is_connected = True
            self.sig_connect.emit(True)
            return True
        except Exception as exc:
            if opened:
                try:
                    ism.ISC_Close(self.serial_no)
                except Exception:
                    pass
            lease.close()
            self.is_connected = False
            self.sig_connect.emit(False)
            self._emit_log(
                f"K10CR1 connection failed for {serial}: "
                f"{type(exc).__name__}: {exc}",
                "ERROR",
            )
            return False

    def disconnect(self):
        try:
            if self.is_connected:
                ism.ISC_Close(self.serial_no)
        finally:
            if self._kinesis_lease is not None:
                self._kinesis_lease.close()
                self._kinesis_lease = None
            self.sig_connect.emit(False)
            self.is_connected = False
        self._emit_log("K10CR1 disconnected.")

    def reset(self):
        return ism.ISC_ResetStageToDefaults(self.serial_no)

    def home(self):
        milliseconds = c_int(50)
        self._emit_log("K10CR1 home requested.", "WARNING")

        ism.ISC_StartPolling(self.serial_no, milliseconds)
        ism.ISC_ClearMessageQueue(self.serial_no)
        sleep(0.2)

        homing_inf = ism.MOT_HomingParameters()
        ism.ISC_SetHomingVelocity(self.serial_no, ism.c_uint(73300335))
        ism.ISC_RequestHomingParams(self.serial_no)
        err = int(ism.ISC_GetHomingParamsBlock(self.serial_no, byref(homing_inf)))

        if err != 0:
            self._emit_log(
                f"K10CR1 could not read homing information (code {err}).",
                "ERROR",
            )
            return False

        ism.ISC_Home(self.serial_no)
        sleep(0.2)
        pos = int(ism.ISC_GetPosition(self.serial_no))
        sleep(0.2)
        while pos != 0:
            sleep(0.05)
            pos = int(ism.ISC_GetPosition(self.serial_no))
            self.last_deg = pos / 49152000 * 360
            self.sig_last_pos.emit(pos)

        ism.ISC_StopPolling(self.serial_no)
        self._emit_log("K10CR1 home completed.")
        return True

    def assign_target(self, target):
        self.target = target

    def set_angle(self, angle):
        milliseconds = c_int(50)
        ism.ISC_StartPolling(self.serial_no, milliseconds)
        ism.ISC_ClearMessageQueue(self.serial_no)
        sleep(0.2)
        move_to = int(angle / 360 * 49152000)
        ism.ISC_SetMoveAbsolutePosition(self.serial_no, c_int(move_to))
        sleep(0.2)

        ism.ISC_MoveAbsolute(self.serial_no)
        sleep(0.2)
        pos = int(ism.ISC_GetPosition(self.serial_no))
        sleep(0.2)
        n = 0
        m = 0

        last5 = deque(maxlen=5)

        while True:
            sleep(0.1)
            pos = int(ism.ISC_GetPosition(self.serial_no))
            last5.append(pos)

            self.last_deg = pos / 49152000 * 360
            self.sig_last_pos.emit(pos)

            if min((pos - move_to) % 49152000, (move_to - pos) % 49152000) < 10:
                m += 1
                if m > 3:
                    break

            if len(last5) == last5.maxlen and len(set(last5)) == 1:
                self._emit_log(
                    f"K10CR1 position was unchanged for {last5.maxlen} reads "
                    f"at {pos}; stopping the move loop.",
                    "WARNING",
                )
                break

            n += 1
            if n > 1000:
                self._emit_log(
                    "K10CR1 move iteration limit was exceeded; "
                    "stopping the move loop.",
                    "WARNING",
                )
                break

        ism.ISC_StopPolling(self.serial_no)

    def get_angle(self):
        pos = int(ism.ISC_GetPosition(self.serial_no))
        return pos / 49152000 * 360
    
    def stop(self):
        self._emit_log("K10CR1 immediate stop requested.", "WARNING")
        return ism.ISC_StopImmediate(self.serial_no)

    def run(self):
        job = self.job
        self.job = ""
        try:
            if job == "connect":
                self.connect()
            elif job == "disconnect":
                self.disconnect()
            elif job == "stop":
                self.stop()
            elif job == "set_angle":
                self.set_angle(self.target)
            elif job == "home":
                self.home()
        except Exception as exc:
            self._emit_log(
                f"K10CR1 {job or 'job'} failed: {type(exc).__name__}: {exc}",
                "ERROR",
            )

# Direct hardware demonstration entry point intentionally removed.
