import os
import sys

from PyQt6 import QtWidgets

from core.scan_info import ScanInfo
from core.mainWindow import MainWindow
from core.shared_runtime import RuntimeServices

# ------------------------------------------------------------
# Import the equipment modules you plan to use below.  Comment out any
# devices that are not required in your particular setup.
# ------------------------------------------------------------
# from opticool.opticool_main import OptiCool
# from montana2.montana2_main import Montana2

# from sr830_v2.sr830_main import SR830 #please use sr830_v2 instead of the original sr830, please report the bugs to Xuguo
# from sr860.sr860_main import SR860
# from keithley24xx.keithley24xx_main import Keithley24xx
# from hp34401a.hp34401a_main import HP34401A

# from nidaq.nidaq_main import NIDAQ
# from ni6423.ni6423_main import NI6423

# from k10cr1.k10cr1_main import K10CR1
# from BBD30X.BBD30X_main import BBD30X
# from tlpm.tlpm_main import TLPM

# from pem100.pem100_main import PEM100
# from sp150.sp150_main import SP150

# from auto_focus.autofocus_main import autofocus_main
# from auto_focus.autofocus_logic import stepper_and_galvo_xyz
# from autofocus_xuguo.autofocusXZ_main import AutofocusXZMain

from mockDevice.mock_device_main import MockDevice


save_path = os.path.join(os.getcwd(), "data")
# backup_main_path = r"Z:\\Xuguo\\SHG Desktop Backup"
backup_main_path = None


def create_equipment(runtime_services: RuntimeServices):
    """Instantiate and connect to all equipment required for the session."""

    equips = {
        # "SR860_0": SR860(runtime_services.visa),
        # "SR860_1": SR860(runtime_services.visa),
        # "SR830_2": SR830(runtime_services.visa),
        # "SR830_3": SR830(),
        # "SR830_4": SR830(),
        # "nidaq": NIDAQ(),
        # "ni6423": NI6423(),
        # "DMM_A": HP34401A(runtime_services.visa),
        # "HWP_exc": K10CR1(runtime_services.kinesis),
        # "HWP_det": K10CR1(runtime_services.kinesis),
        # "delay_stage": BBD30X(kinesis_runtime=runtime_services.kinesis),
        # "Keithley_bg": Keithley24xx(runtime_services.visa),
        # "Keithley_tg": Keithley24xx(runtime_services.visa),
        # "pem": PEM100(visa_runtime=runtime_services.visa),
        # "monochromator": SP150(visa_runtime=runtime_services.visa),
        # "tlpm_0": TLPM(),
        #"opticool": OptiCool(),
        # "montana2": Montana2(),
        "mock_device_1": MockDevice(),
        "mock_device_2": MockDevice(),
        # "autofocusXZ": AutofocusXZMain(),
    }

    # ------------------------------------------------------------
    # Connection commands – adjust to match your instrument addresses.
    # ------------------------------------------------------------
    # equips["nidaq"].connect("Dev1")
    # equips["ni6423"].connect("Dev2")

    # equips["HWP_exc"].connect(serial="55369504")
    # equips["HWP_det"].connect(serial="55243324")

    # equips["SR860_0"].connect_visa("GPIB0::7::INSTR")
    # equips["SR860_1"].connect_visa("GPIB0::8::INSTR")
    # equips["SR830_2"].connect_visa("GPIB0::9::INSTR")
    # equips["SR830_3"].connect_visa("GPIB0::10::INSTR")
    # equips["SR830_4"].connect_visa("GPIB0::11::INSTR")

    # equips["Keithley_bg"].connect_visa("GPIB2::17::INSTR")
    # equips["Keithley_tg"].connect_visa("GPIB2::18::INSTR")

    # equips["DMM_A"].connect_visa("GPIB0::21::INSTR")

    # equips["tlpm_0"].connect()

    # Optional scan-channel filters by equipment label.
    # If a label is missing, all get_/set_ channels from that device logic are exposed.
    # Unknown channel names are silently skipped.
    # Only ni6423 support this function so far
    equips_set_channels = {
        "ni6423": ["AO0", "AO1"],
    }
    equips_get_channels = {
        "ni6423": ["AI0", "AI1", "AI4", "counter0"],
    }

    return equips, equips_set_channels, equips_get_channels


def main():
    """Application entry point.  Edit this function to customise paths and devices."""

    # Paths where data and backups are stored – adjust as needed.

    # ------------------------------------------------------------
    # Qt must be initialised *before* instantiating any QWidget-based
    # equipment such as SR860().
    # ------------------------------------------------------------
    app = QtWidgets.QApplication(sys.argv)
    runtime_services = RuntimeServices()

    # Hardware setup (widgets can be created safely now)
    equips, equips_set_channels, equips_get_channels = create_equipment(
        runtime_services
    )

    window = MainWindow(
        info=ScanInfo,
        save_path=save_path,
        backup_main_path=backup_main_path,
        equips=equips,
        equips_set_channels=equips_set_channels,
        equips_get_channels=equips_get_channels,
    )
    window.show()
    window.setWindowTitle("Main Window")
    try:
        return app.exec()
    finally:
        diagnostics = runtime_services.shutdown()
        for family in ("visa", "kinesis"):
            error = diagnostics.get(f"{family}_error")
            if error:
                print(f"Shared {family} shutdown warning: {error}")


if __name__ == "__main__":
    sys.exit(main())
