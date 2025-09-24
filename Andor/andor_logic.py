from __future__ import annotations

from PyQt6 import QtCore
import time
import numpy as np
from andor_hardware_new import AndorCameraHardware


class AndorCameraLogic(QtCore.QThread):
    """Qt thread-wrapper exposing *AndorCameraHardware* in a signal-friendly API.

    This template mimics the conventions used in *sr860_logic.py* so that UI
    developers can reuse components with minimal changes.

    Naming rules (project-wide):
    1. **get_xxx**   – scan readable parameters, displayed in scan code readable dropdown
    2. **set_xxx**   – scan settable parameters, displayed in scan code settable dropdown
    3. **query_xxx** – non-scan info/status reading (device info, detector specs, etc.)
    4. **setup_xxx** – non-scan configuration (complex mode setups, calibration, etc.)

    """

    # ----------- value update signals ---------------
    # signals are used to update the UI with the current value of the parameter
    sig_acquisition_mode = QtCore.pyqtSignal(object)
    sig_exposure_time = QtCore.pyqtSignal(object)
    sig_temperature = QtCore.pyqtSignal(object)
    sig_read_mode = QtCore.pyqtSignal(object)
    sig_detector_size = QtCore.pyqtSignal(object)
    sig_device_info = QtCore.pyqtSignal(object)

    # acquisition status signals
    sig_image_acquired = QtCore.pyqtSignal(object)  # emits numpy array
    sig_acquisition_started = QtCore.pyqtSignal(object)
    sig_acquisition_stopped = QtCore.pyqtSignal(object)
    sig_frame_ready = QtCore.pyqtSignal(object)
    sig_acquisition_timings = QtCore.pyqtSignal(object)
    sig_cooler = QtCore.pyqtSignal(object)
    sig_accum_frame_num = QtCore.pyqtSignal(object)
    sig_accum_cycle_time = QtCore.pyqtSignal(object)

    # ----------- generic state signals --------------
    sig_is_changing = QtCore.pyqtSignal(object)
    sig_connected = QtCore.pyqtSignal(object)

    # -----------------------------------------------
    def __init__(self) -> None:
        super().__init__()

        # queued instruction name processed in run()
        self.job: str = ""  # name of the next action

        # -------- set-points (set_* / setup_*) --------
        self.setpoint_camera_index: int = 0
        self.setpoint_acquisition_mode: str = "single"
        self.setpoint_exposure_time: float = 0.1  # seconds
        self.setpoint_temperature: int = -80  # Celsius
        self.setpoint_read_mode: str = "full_frame"
        self.setpoint_cooler: bool = False

        # acquisition setup parameters
        self.setpoint_accum_num_frames: int = 10
        self.setpoint_accum_cycle_time: float = 0.0
        self.setpoint_cont_cycle_time: float = 0.0
        self.setpoint_kinetic_num_cycle: int = 10
        self.setpoint_kinetic_cycle_time: float = 0.0
        self.setpoint_kinetic_num_acc: int = 1
        self.setpoint_kinetic_cycle_time_acc: float = 0.0
        self.setpoint_kinetic_num_prescan: int = 0

        # runtime state
        self.connected: bool = False
        self.reject_signal: bool = False  # reject signal is to prevent multiple jobs from running at the same time
        self.acquiring: bool = False

        self.hardware: AndorCameraHardware | None = None

    # -------------- connection helpers --------------
    def connect_camera(self):
        """Instantiate *AndorCameraHardware* and open camera connection."""
        self.hardware = AndorCameraHardware(self.setpoint_camera_index, temperature='off', fan_mode='full')
        self.device_info = self.query_device_info()
        self.connected = True
        self.sig_connected.emit(f"connected to camera {self.setpoint_camera_index}, {self.device_info}")

    # -------------- disconnect helper --------------
    def disconnect(self):
        """Safely stop the thread and close the camera connection."""
        self.reject_signal = True
        self.job = ""

        if self.isRunning():
            self.wait()

        if self.hardware is not None:
            try:
                if self.acquiring:
                    self.hardware.stop_acquisition()
                    self.acquiring = False
                self.hardware.disconnect()
            except Exception as exc:  # pragma: no cover – defensive
                print("[WARN] Error during hardware.disconnect():", exc)
            self.hardware = None

        if self.connected:
            self.connected = False
            self.sig_connected.emit("disconnected")

        # allow new jobs after future reconnect
        if not self.isRunning():
            self.reject_signal = False
        

    # -------------- getter wrappers ----------------
    def get_temperature(self):
        assert self.hardware is not None
        val = self.hardware.temperature(read=True)
        self.sig_temperature.emit(val)
        return val

    # -------------- setter wrappers ----------------
    def set_temperature(self):
        assert self.hardware is not None
        self.hardware.temperature(self.setpoint_temperature, write=True)
        self.sig_is_changing.emit(
            f"temperature set to {self.setpoint_temperature} °C"
        )
        self.sig_temperature.emit(self.setpoint_temperature)

    def setup_cooler(self):
        assert self.hardware is not None
        self.hardware.cooler(self.setpoint_cooler, write=True)
        self.sig_is_changing.emit(
            f"cooler set to {self.setpoint_cooler}"
        )
        self.sig_cooler.emit(self.setpoint_cooler)

    # -------------- query wrappers -----------------
    def query_device_info(self):
        assert self.hardware is not None
        val = self.hardware.get_device_info()
        self.sig_device_info.emit(val)
        return val

    def query_acquisition_mode(self):
        assert self.hardware is not None
        val = self.hardware.acquisition_mode(read=True)
        self.sig_acquisition_mode.emit(val)
        return val

    def query_exposure_time(self):
        assert self.hardware is not None
        val = self.hardware.exposure_time(read=True)
        self.sig_exposure_time.emit(val)
        return val

    def query_read_mode(self):
        assert self.hardware is not None
        val = self.hardware.read_mode(read=True)
        self.sig_read_mode.emit(val)
        return val

    def query_detector_size(self):
        assert self.hardware is not None
        val = self.hardware.get_detector_size()
        self.sig_detector_size.emit(val)
        return val

    def query_acquisition_timings(self):
        assert self.hardware is not None
        val = self.hardware.get_acquisition_timings()
        self.sig_acquisition_timings.emit(val)
        return val

    def query_accum_settings(self):
        assert self.hardware is not None
        frame_num, cycle_time = self.hardware.get_accum_settings()
        self.sig_accum_frame_num.emit(frame_num)
        self.sig_accum_cycle_time.emit(cycle_time)
        return frame_num, cycle_time

    # -------------- setup wrappers -----------------
    def setup_acquisition_mode(self):
        assert self.hardware is not None
        self.hardware.acquisition_mode(self.setpoint_acquisition_mode, write=True)
        self.sig_is_changing.emit(
            f"acquisition_mode set to {self.setpoint_acquisition_mode}"
        )
        self.sig_acquisition_mode.emit(self.setpoint_acquisition_mode)

    def setup_exposure_time(self):
        assert self.hardware is not None
        self.hardware.exposure_time(self.setpoint_exposure_time, write=True)
        self.sig_is_changing.emit(
            f"exposure_time set to {self.setpoint_exposure_time} s"
        )
        self.sig_exposure_time.emit(self.setpoint_exposure_time)

    def setup_read_mode(self):
        assert self.hardware is not None
        self.hardware.read_mode(self.setpoint_read_mode, write=True)
        self.sig_is_changing.emit(
            f"read_mode set to {self.setpoint_read_mode}"
        )
        self.sig_read_mode.emit(self.setpoint_read_mode)

    # -------------- acquisition setup wrappers ------
    def setup_accumulation_mode(self):
        assert self.hardware is not None
        self.hardware.setup_accumulation_mode(
            self.setpoint_accum_num_frames,
            self.setpoint_accum_cycle_time,
            write=True
        )
        print("done")
        self.sig_is_changing.emit(
            f"accumulation mode setup: {self.setpoint_accum_num_frames} frames, "
            f"cycle_time {self.setpoint_accum_cycle_time} s"
        )

    def setup_continuous_mode(self):
        assert self.hardware is not None
        self.hardware.setup_continuous_mode(
            self.setpoint_cont_cycle_time,
            write=True
        )
        self.sig_is_changing.emit(
            f"continuous mode setup: cycle_time {self.setpoint_cont_cycle_time} s"
        )

    def setup_kinetic_mode(self):
        assert self.hardware is not None
        self.hardware.setup_kinetic_mode(
            self.setpoint_kinetic_num_cycle,
            self.setpoint_kinetic_cycle_time,
            self.setpoint_kinetic_num_acc,
            self.setpoint_kinetic_cycle_time_acc,
            self.setpoint_kinetic_num_prescan,
            write=True
        )
        self.sig_is_changing.emit(
            f"kinetic mode setup: {self.setpoint_kinetic_num_cycle} cycles, "
            f"{self.setpoint_kinetic_num_acc} accumulations"
        )

    # -------------- acquisition control --------------
    def start_acquisition(self):
        assert self.hardware is not None
        self.hardware.start_acquisition()
        self.acquiring = True
        self.sig_acquisition_started.emit("acquisition started")
        self.sig_is_changing.emit("acquisition started")

    def stop_acquisition(self):
        assert self.hardware is not None
        self.hardware.stop_acquisition()
        self.acquiring = False
        self.sig_acquisition_stopped.emit("acquisition stopped")
        self.sig_is_changing.emit("acquisition stopped")

    def snap_image(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            image = self.hardware.snap_image()
            self.sig_image_acquired.emit(image)
            self.sig_is_changing.emit(f"image acquired: shape {image.shape}")
            return image
        except Exception as e:
            self.sig_is_changing.emit(f"Failed to snap image: {e}")
            raise

    def wait_for_frame(self):
        assert self.hardware is not None
        self.hardware.wait_for_frame()
        self.sig_frame_ready.emit("frame ready")

    def read_oldest_image(self):
        assert self.hardware is not None
        image = self.hardware.read_oldest_image()
        self.sig_image_acquired.emit(image)
        return image

    def read_newest_image(self):
        assert self.hardware is not None
        image = self.hardware.read_newest_image()
        self.sig_image_acquired.emit(image)
        return image

    def clear_acquisition(self):
        assert self.hardware is not None
        self.hardware.clear_acquisition()
        self.sig_is_changing.emit("acquisition buffer cleared")

    # -------------- bulk helper ---------------------
    def query_all(self):
        """Convenience method: query a representative subset of parameters."""
        self.query_acquisition_mode()
        self.query_exposure_time()
        self.query_temperature()
        self.query_read_mode()
        self.query_detector_size()
        self.query_acquisition_timings()
        self.query_accum_settings()
        time.sleep(0.05)

    def setup_current_mode(self):
        """Setup the current acquisition mode with current setpoints."""
        mode = self.setpoint_acquisition_mode
        if mode == "accumulate" or mode == "accum":
            self.setup_accumulation_mode()
            print("Accumulation mode not implemented yet")
        elif mode == "continuous" or mode == "cont":
            self.setup_continuous_mode()
        elif mode == "kinetic":
            # self.setup_kinetic_mode()
            print("Kinetic mode not implemented yet")
        # single mode doesn't need setup

    # -------------- continuous acquisition helper ----
    def start_continuous_acquisition_loop(self, num_frames: int = 10):
        """Start a continuous acquisition loop for a specified number of frames."""
        assert self.hardware is not None
        
        # Setup and start continuous mode
        self.setup_continuous_mode()
        self.setup_acquisition_mode()  # Make sure we're in continuous mode
        self.start_acquisition()
        
        images = []
        for i in range(num_frames):
            if self.reject_signal:  # Allow early termination
                break
            self.wait_for_frame()
            image = self.read_oldest_image()
            images.append(image)
            self.sig_is_changing.emit(f"continuous acquisition: frame {i+1}/{num_frames}")
            
        self.stop_acquisition()
        self.sig_is_changing.emit(f"continuous acquisition complete: {len(images)} frames")
        return images


    def get_all(self):
        self.get_temperature()
        self.query_acquisition_mode()
        self.query_exposure_time()
        self.query_read_mode()
        self.query_detector_size()
        self.query_acquisition_timings()
        time.sleep(0.05)

    # -------------- thread main ---------------------
    def run(self):
        if self.reject_signal:
            print(f"🔍 {self.job} rejected1")
            return
        if self.connected and self.hardware is not None and self.job == "connect_camera":
            print(f"🔍 {self.job} rejected2")
            return

        # generic dispatcher: call method named in self.job (no args)
        print(f"🔍 {self.job} started")
        if self.job:
            fn = getattr(self, self.job, None)
            if callable(fn):
                try:
                    print(f"🔍 {self.job} started")
                    fn()
                    print(f"✅ {self.job} completed")
                except Exception as exc:
                    print(f"[WARN] AndorCameraLogic job '{self.job}' error:", exc)
            else:
                print(f"[WARN] AndorCameraLogic has no job '{self.job}'")

            # reset marker so next queued job can run
            self.job = ""

    # -------------- stop helper ---------------------
    def stop(self):
        self.reject_signal = True
        if self.acquiring and self.hardware is not None:
            try:
                self.hardware.stop_acquisition()
                self.acquiring = False
            except Exception as exc:
                print(f"[WARN] Error stopping acquisition: {exc}")
        self.quit()
        self.wait()
        self.reject_signal = False


# -----------------------------------------------------------------------------
# Example usage – runs only when file is executed directly
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    
    logic = AndorCameraLogic()
    
    try:
        # Connect to first available camera
        logic.connect_camera()

        # Query device information
        device_info = logic.query_device_info()
        print("Device info:", device_info)

        # Example: change settings
        logic.setpoint_camera_index = 0
        logic.setpoint_acquisition_mode = "single"
        logic.setpoint_exposure_time = 0.1
        logic.setpoint_temperature = -70
        logic.setpoint_read_mode = "fvb"

        # Apply settings
        logic.setup_acquisition_mode()
        logic.setup_exposure_time()
        logic.set_temperature()
        logic.setup_read_mode()

        # Take a single image
        logic.job = "snap_image"
        logic.start()
        logic.wait()


        # Get all parameters
        logic.query_all()

        # Example: continuous acquisition setup
        logic.setpoint_acquisition_mode = "continuous"
        logic.setpoint_cont_cycle_time = 0.05
        logic.setup_current_mode()

        print("Camera logic example completed successfully")

    except Exception as e:
        print(f"Error: {e}")
        print("Make sure an Andor camera is connected and drivers are installed")
    
    finally:
        # Clean up
        logic.disconnect()
        app.quit()