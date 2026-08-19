import os
import sys
from pathlib import Path

from PyQt6 import QtWidgets

from core.scan_info import ScanInfo
from core.mainWindow import MainWindow
from core.scanlist import ScanListShutdownStopError, ScanListShutdownTimeoutError
from core.device_management import (
    ChannelFilters,
    DeviceConfig,
    DeviceManager,
    DeviceStartupError,
    ProfileConfig,
    ProfilePaths,
    build_default_registry,
)
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


def _static_mock_profile() -> ProfileConfig:
    """Return the Phase 3 in-memory startup configuration.

    Phase 4 replaces this temporary static source with the checked-in profile
    loader. Keeping the boundary explicit makes the launcher switch separately
    reviewable while DeviceManager already owns the active instances.
    """
    repository_root = Path(__file__).resolve().parent
    devices = tuple(
        DeviceConfig(
            id=device_id,
            driver="mock_device",
            enabled=True,
            connect_on_start=False,
            connection={"address": "MOCK::INSTR"},
            scan_channels=ChannelFilters(setters=None, getters=None),
        )
        for device_id in ("mock_device_1", "mock_device_2")
    )
    return ProfileConfig(
        schema_version=1,
        profile="static_mock",
        paths=ProfilePaths(save=Path(save_path), backup=None),
        devices=devices,
        source_path=Path(__file__).resolve(),
        repository_root=repository_root,
    )


def create_device_manager(runtime_services: RuntimeServices) -> DeviceManager:
    """Construct the current static mock set behind manager ownership."""
    manager = DeviceManager(build_default_registry(), runtime_services)
    manager.load_profile(_static_mock_profile())
    return manager


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
        # "delay_stage": ["pos_mm", "pos_um", "delay_ps"],
    }
    equips_get_channels = {
        "ni6423": ["AI0", "AI1", "AI4", "counter0"],
        # "delay_stage": ["pos_mm", "pos_um", "delay_ps"],
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
    device_manager = None
    window = None
    startup_error = None
    pending_shutdown_error = None
    safe_to_release_runtimes = True
    try:
        # Phase 3 keeps the device list static while transferring ownership to
        # DeviceManager. The checked-in JSON profile becomes active in Phase 4.
        try:
            device_manager = create_device_manager(runtime_services)
        except DeviceStartupError as exc:
            startup_error = exc
            raise
        window = MainWindow(
            info=ScanInfo,
            save_path=save_path,
            backup_main_path=backup_main_path,
            device_manager=device_manager,
        )
        window.show()
        window.setWindowTitle("Main Window")
        return app.exec()
    finally:
        primary_exception_active = sys.exc_info()[0] is not None
        if window is not None:
            try:
                window.shutdown_session()
            except (ScanListShutdownTimeoutError, ScanListShutdownStopError) as first_exc:
                print(
                    "Application shutdown warning: initial scan quiescence "
                    f"failed ({type(first_exc).__name__}: {first_exc}); "
                    "requesting one final force-stop and retry."
                )
                try:
                    if device_manager is not None:
                        force_report = device_manager.force_stop_all()
                        for failure in force_report.failures:
                            print(
                                "Device force-stop warning: "
                                f"{failure.describe()}"
                            )
                    window.shutdown_session(timeout_ms=30_000)
                except (
                    ScanListShutdownTimeoutError,
                    ScanListShutdownStopError,
                ) as retry_exc:
                    safe_to_release_runtimes = False
                    pending_shutdown_error = retry_exc
                    print(
                        "Application shutdown warning: scan activity was not "
                        "safely quiesced after retry "
                        f"({type(retry_exc).__name__}: {retry_exc}). "
                        "Device and shared-runtime teardown were skipped."
                    )

        if (
            startup_error is not None
            and startup_error.cleanup_report.failures
        ):
            safe_to_release_runtimes = False
            for failure in startup_error.cleanup_report.failures:
                print(f"Startup rollback warning: {failure.describe()}")

        if device_manager is not None and safe_to_release_runtimes:
            report = device_manager.teardown_all()
            for failure in report.failures:
                print(f"Device shutdown warning: {failure.describe()}")
            if report.failures:
                safe_to_release_runtimes = False

        if safe_to_release_runtimes:
            diagnostics = runtime_services.shutdown()
            for family in ("visa", "kinesis"):
                error = diagnostics.get(f"{family}_error")
                if error:
                    print(f"Shared {family} shutdown warning: {error}")

        # A normal event-loop return must not report success when its final
        # quiescence barrier failed. If another exception is already unwinding,
        # preserve that primary failure instead of masking it here.
        if pending_shutdown_error is not None and not primary_exception_active:
            raise pending_shutdown_error


if __name__ == "__main__":
    sys.exit(main())
