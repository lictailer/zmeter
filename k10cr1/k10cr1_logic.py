from . import k10cr1_hardware as ism
from time import sleep
from ctypes import (
    c_short,
    c_char_p,
    byref,
    c_int,
)
from PyQt6 import QtCore


class K10CR1Logic(QtCore.QThread):
    sig_last_pos = QtCore.pyqtSignal(object)
    sig_info = QtCore.pyqtSignal(object)
    sig_connect = QtCore.pyqtSignal(object)

    def __init__(self):
        QtCore.QThread.__init__(self)
        self.is_connected = False
        self.target = 0
        self.last_deg = 0
        self.job = ""

    def assign_serial(self, serial):
        self.serial_no = c_char_p(bytes(serial, "utf-8"))

    def pass_info(self, info):
        self.sig_info.emit(info)
        # print(info)

    def connect(self):
        if not ism.TLI_BuildDeviceList() == 0:
            self.pass_info("Can't build device list")
            return False
        if not ism.ISC_Open(self.serial_no) == 0:
            self.pass_info("Can't open k10cr1.")
            return False
        hw_info = ism.TLI_HardwareInformation()  # container for hw info
        err = ism.ISC_GetHardwareInfoBlock(self.serial_no, byref(hw_info))
        if err != 0:
            self.pass_info(f"Error getting HW Info Block. Error Code: {err}")
        info = f"Serial No: {hw_info.serialNumber}\nModel No: {hw_info.modelNumber}\nFirmware Version: {hw_info.firmwareVersion}\nNumber of  Channels: {hw_info.numChannels}\nType: {hw_info.type}"
        self.pass_info(info)

        ############## set velocity ##############
        inf = ism.MOT_VelocityParameters()
        ism.ISC_GetVelParamsBlock(self.serial_no, byref(inf))
        self.pass_info(f"minVelocity: {inf.minVelocity}")
        self.pass_info(f"acceleration: {inf.acceleration}")
        self.pass_info(f"maxVelocity: {inf.maxVelocity}")

        min_velocity = c_int(0)
        acceleration = c_int(15020)
        max_velocity = c_int(73300335)
        inf.minVelocity = min_velocity
        inf.acceleration = acceleration
        inf.maxVelocity = max_velocity

        # self.pass_info(f"minVelocity: {inf.minVelocity}")
        # self.pass_info(f"acceleration: {inf.acceleration}")
        # self.pass_info(f"maxVelocity: {inf.maxVelocity}")

        self.pass_info(
            f"Setting vel {ism.ISC_SetVelParamsBlock(self.serial_no, byref(inf))}"
        )

        ism.ISC_GetVelParamsBlock(self.serial_no, byref(inf))
        self.pass_info(f"minVelocity: {inf.minVelocity}")
        self.pass_info(f"acceleration: {inf.acceleration}")
        self.pass_info(f"maxVelocity: {inf.maxVelocity}")

        ############## emit signal ##############
        self.sig_connect.emit(True)
        self.is_connected = True

        return True

    def disconnect(self):
        self.pass_info(f"Closing connection {ism.ISC_Close(self.serial_no)}")
        self.sig_connect.emit(False)
        self.is_connected = False
        
    def reset(self):
        self.pass_info(ism.ISC_ResetStageToDefaults(self.serial_no))

    def home(self):
        milliseconds = c_int(50)

        self.pass_info(
            f"Starting polling {ism.ISC_StartPolling(self.serial_no, milliseconds)}"
        )
        self.pass_info(
            f"Clearing message queue {ism.ISC_ClearMessageQueue(self.serial_no)}"
        )
        sleep(0.2)

        homing_inf = ism.MOT_HomingParameters()  # container
        self.pass_info(
            f"Setting homing vel {ism.ISC_SetHomingVelocity(self.serial_no, ism.c_uint(73300335))}"
        )
        ism.ISC_RequestHomingParams(self.serial_no)
        err = ism.ISC_GetHomingParamsBlock(self.serial_no, byref(homing_inf))

        if err != 0:
            self.pass_info(f"Error getting Homing Info Block. Error Code: {err}")
            return False
        self.pass_info(f"Direction: {homing_inf.direction}")
        self.pass_info(f"Limit Sw: {homing_inf.limitSwitch}")
        self.pass_info(f"Velocity: {homing_inf.velocity}")
        self.pass_info(f"Offset Dist: {homing_inf.offsetDistance}")

        ism.ISC_Home(self.serial_no)
        sleep(0.2)
        pos = int(ism.ISC_GetPosition(self.serial_no))
        sleep(0.2)
        self.pass_info(f"Current pos: {pos}")
        while pos != 0:
            sleep(0.05)
            pos = int(ism.ISC_GetPosition(self.serial_no))
            self.pass_info(f"Current pos: {pos}")
            self.last_deg = pos / 49152000 * 360
            self.sig_last_pos.emit(pos)

        self.pass_info(f"Stopping polling {ism.ISC_StopPolling(self.serial_no)}")

    def assign_target(self, target):
        self.target = target

    def set_angle(self, angle):
        milliseconds = c_int(50)
        self.pass_info(
            f"Starting polling {ism.ISC_StartPolling(self.serial_no, milliseconds)}"
        )
        self.pass_info(
            f"Clearing message queue {ism.ISC_ClearMessageQueue(self.serial_no)}"
        )
        sleep(0.2)
        move_to = int(angle / 360 * 49152000)
        self.pass_info(
            f"Setting Absolute Position {ism.ISC_SetMoveAbsolutePosition(self.serial_no, c_int(move_to))}"
        )
        sleep(0.2)

        self.pass_info(f"Moving to {move_to}  {ism.ISC_MoveAbsolute(self.serial_no)}")
        sleep(0.2)
        pos = int(ism.ISC_GetPosition(self.serial_no))
        sleep(0.2)
        self.pass_info(f"Current pos: {pos}")
        n = 0
        while not pos == move_to and n < 1000:
            sleep(0.1)
            pos = int(ism.ISC_GetPosition(self.serial_no))
            self.last_deg = pos / 49152000 * 360
            self.pass_info(f"Current pos: {pos}")
            self.sig_last_pos.emit(pos)
            n += 1

        self.pass_info(f"Stopping polling {ism.ISC_StopPolling(self.serial_no)}")

    def get_angle(self):
        pos = int(ism.ISC_GetPosition(self.serial_no))
        return pos / 49152000 * 360
    
    def stop(self):
        #doesn't work
        self.pass_info(
            f"Stopping polling{ism.ISC_StopImmediate(self.serial_no)}"
        )

    def run(self):

        if self.job == "connect":
            self.connect()
        elif self.job == "disconnect":
            self.disconnect()
        elif self.job == "stop":
            self.stop()
        elif self.job == "set_angle":
            self.set_angle(self.target)
        elif self.job == "home":
            self.home()
        self.job = ""


if __name__ == "__main__":
    a = K10CR1Logic()
    a.assign_serial("55243324")
    # a.assign_serial("55246024")
    a.connect()
    
    deg = 10
    a.set_angle(deg)
    deg = 0
    a.set_angle(deg)

    a.home()
    a.disconnect()