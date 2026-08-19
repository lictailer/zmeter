import argparse
import sys
from pathlib import Path

from PyQt6 import QtWidgets

from core.scan_info import ScanInfo
from core.mainWindow import MainWindow
from core.scanlist import ScanListShutdownStopError, ScanListShutdownTimeoutError
from core.device_management import (
    DeviceManager,
    DeviceStartupError,
    ProfileValidationError,
    build_default_registry,
    load_profile,
)
from core.shared_runtime import RuntimeServices

REPOSITORY_ROOT = Path(__file__).resolve().parent
DEFAULT_PROFILE_PATH = REPOSITORY_ROOT / "config" / "profiles" / "mock.json"


def _parse_launch_options(argv):
    parser = argparse.ArgumentParser(description="Launch ZMeter")
    parser.add_argument(
        "--profile",
        type=Path,
        default=DEFAULT_PROFILE_PATH,
        help=(
            "profile JSON path; relative paths are resolved from the "
            "repository root"
        ),
    )
    return parser.parse_args(argv)


def create_profile_session(
    runtime_services: RuntimeServices,
    profile_path: str | Path = DEFAULT_PROFILE_PATH,
):
    """Validate a selected profile, then construct its enabled devices."""
    registry = build_default_registry()
    profile = load_profile(
        profile_path,
        driver_specs=registry.config_specs,
        repository_root=REPOSITORY_ROOT,
    )
    manager = DeviceManager(registry, runtime_services)
    manager.load_profile(profile)
    return profile, manager


def main(argv=None):
    """Launch the selected validated profile."""
    launch_arguments = list(sys.argv[1:] if argv is None else argv)
    # QApplication must exist before any enabled QWidget-based device is built.
    # Qt consumes its own options (for example ``-platform`` and ``-style``)
    # first. Strict parsing of what remains prevents a misspelled ``--profile``
    # from silently launching the default profile.
    app = QtWidgets.QApplication([sys.argv[0], *launch_arguments])
    options = _parse_launch_options(app.arguments()[1:])
    runtime_services = RuntimeServices()
    profile = None
    device_manager = None
    window = None
    startup_error = None
    pending_shutdown_error = None
    safe_to_release_runtimes = True
    try:
        try:
            profile, device_manager = create_profile_session(
                runtime_services,
                options.profile,
            )
        except ProfileValidationError as exc:
            message = str(exc)
            print(message, file=sys.stderr)
            QtWidgets.QMessageBox.critical(
                None,
                "Invalid ZMeter Profile",
                message,
            )
            return 2
        except DeviceStartupError as exc:
            startup_error = exc
            raise
        assert profile is not None
        window = MainWindow(
            info=ScanInfo,
            save_path=str(profile.paths.save),
            backup_main_path=(
                None
                if profile.paths.backup is None
                else str(profile.paths.backup)
            ),
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
