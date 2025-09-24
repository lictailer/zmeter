import logging
import time
from pylablib.devices.Andor.AndorSDK2 import AndorSDK2Camera
from pylablib.devices.Andor.Shamrock import ShamrockSpectrograph
import matplotlib.pyplot as plt
import numpy as np

class AndorCameraHardware:
    """
    Python driver for Andor cameras using pylablib's AndorSDK2Camera class.
    
    Key design guidelines:
    1. **pylablib first** – communicate via pylablib's camera interface.
    2. **Symmetric API** – every setting provides a *setter* (``write=True``)
       and *getter* (``read=True``) in the same method.
    3. **Human-readable enums** – expose descriptive strings to users while
       translating to camera parameters internally via mapping dictionaries.
    4. **Robust I/O helpers** – centralise camera operations with error handling.
    5. **Thin abstraction** – driver should not hide the underlying camera
       commands; instead, document them clearly.
    """

    # ---------------- initialisation ----------------
    def __init__(self, camera_index: int = 0, temperature = None, fan_mode: str = 'off'):
        """Connect to the Andor camera.

        Parameters
        ----------
        camera_index : int
            Camera index (default: 0 for first available camera)
        temperature :
            Temperature control mode: 'off', None or value in Celsius
        fan_mode : str
            Fan mode: 'off', 'on'
        """
        self._camera_index = camera_index
        self._camera = AndorSDK2Camera(idx=self._camera_index, temperature=temperature, fan_mode=fan_mode)
        logging.info(f"Connected to Andor camera at index {camera_index}")
        self._exposure_time = 0.0

    # -------------- low-level helpers ---------------
    def _safe_get(self, func, *args, **kwargs):
        """Safely execute a getter function with retry logic."""
        attempts = 0
        while attempts < 3:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                attempts += 1
                logging.warning(
                    "Get operation failed (%s). Retry %d/3", exc, attempts
                )
                time.sleep(0.05)
        raise RuntimeError(f"Camera is not responding to get operation")

    def _safe_set(self, func, *args, **kwargs):
        """Safely execute a setter function with error handling."""
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            logging.error(f"Set operation failed: {exc}")
            raise RuntimeError(f"Failed to set parameter: {exc}")

    # -------------- identity / reset ----------------
    def get_device_info(self) -> dict:
        """Return camera device information."""
        return self._safe_get(self._camera.get_device_info)

    def close(self):
        """Close camera connection."""
        try:
            if hasattr(self, '_camera') and self._camera is not None:
                self._camera.close()
        except Exception as exc:
            logging.warning(f"Error closing camera: {exc}")

    # -------------- acquisition modes ---------------
    _acq_mode_map = {
        "single": "single",
        "continuous": "cont", 
        "kinetic": "kinetic",
        "accumulate": "accum"
    }

    def acquisition_mode(self, mode=None, *, write=False, read=False):
        """Set or query the acquisition mode.

        Usage examples
        --------------
        >>> cam.acquisition_mode("single", write=True)  # set single shot mode
        >>> current = cam.acquisition_mode(read=True)    # -> 'single'
        """
        if write and mode is not None:
            if mode in self._acq_mode_map:
                self._safe_set(self._camera.set_acquisition_mode, self._acq_mode_map[mode])
            elif mode in self._acq_mode_map.values():
                self._safe_set(self._camera.set_acquisition_mode, mode)
            else:
                raise ValueError(f"mode must be one of {list(self._acq_mode_map.keys())}")
        elif read:
            acq_mode = self._safe_get(self._camera.get_acquisition_mode)
            for key, value in self._acq_mode_map.items():
                if value == acq_mode:
                    return key
            return acq_mode  # return raw value if not in mapping
        else:
            raise ValueError("Either write or read must be True")

    # -------------- exposure time -------------------
    def exposure_time(self, time_s: float | None = None, *, write=False, read=False):
        """Set or query the exposure time in seconds.

        Parameters
        ----------
        time_s : float
            Exposure time in seconds (must be positive)
        """
        if write and time_s is not None:
            if time_s <= 0:
                raise ValueError("exposure time must be positive")
            self._safe_set(self._camera.set_exposure, time_s)
            self._exposure_time = time_s
        elif read:
            self._exposure_time = self._safe_get(self._camera.get_exposure)
            return self._exposure_time
        else:
            raise ValueError("Either write or read must be True")

    # -------------- temperature ---------------------
    def temperature(self, temp_c: int | None = None, *, write=False, read=False):
        """Set or query the detector temperature in Celsius.

        Parameters
        ----------
        temp_c : int
            Target temperature in Celsius
        """
        if write and temp_c is not None:
            self._safe_set(self._camera.set_temperature, temp_c)
        elif read:
            return self._safe_get(self._camera.get_temperature)
        else:
            raise ValueError("Either write or read must be True")
        
    def cooler(self, cooler: bool | None = None, *, write=False, read=False):
        """Set or query the cooler mode.

        Parameters
        ----------
        cooler : bool
            Cooler mode: True, False
        """
        if write and cooler is not None:
            self._safe_set(self._camera.set_cooler, cooler)
        elif read:
            return None
        else:
            raise ValueError("Either write or read must be True")

    # -------------- readout speed -------------------
    _read_mode_list = {
            "fvb",
            "single_track",
            "multi_track",
            "random_track",
            "image"
        }

    def read_mode(self, mode: str | None = None, *, write=False, read=False):
        """Set or query the read mode.

        Parameters
        ----------
        mode : str or int
            Read mode. Can be string from valid modes or integer index:
            - "full_frame" (4): Full frame readout
            - "multi_track" (3): Multiple track readout  
            - "random_track" (2): Random track readout
            - "single_track" (1): Single track readout
            - "image" (0): Image readout mode
        """
        if write and mode is not None:
            if mode in self._read_mode_list:
                self._safe_set(self._camera.set_read_mode, mode)
            else:
                raise ValueError(f"mode must be one of {self._read_mode_list}")
        elif read:
            mode = self._safe_get(self._camera.get_read_mode)
            return mode  # return raw value if not in mapping
        else:
            raise ValueError("Either write or read must be True")

    # -------------- acquisition setup methods -------
    def setup_accumulation_mode(self, num_acc: int = 1, cycle_time_acc: float = 0.0, *, write=False, read=False):
        """Set up or query accumulation acquisition mode parameters.

        Parameters
        ----------
        num_acc : int
            Number of accumulated frames
        cycle_time_acc : float
            Acquisition period (0.0 = minimal possible based on exposure and transfer time)
        """
        if write:
            self._safe_set(self._camera.setup_accum_mode, num_acc, cycle_time_acc)
        elif read:
            return self._safe_get(self._camera.get_accum_mode_parameters)
        else:
            raise ValueError("Either write or read must be True")

    def setup_continuous_mode(self, cycle_time: float = 0.0, *, write=False, read=False):
        """Set up or query continuous acquisition mode parameters.

        Parameters
        ----------
        cycle_time : float
            Acquisition period (0.0 = minimal possible based on exposure and transfer time)
        """
        if write:
            self._safe_set(self._camera.setup_cont_mode, cycle_time)
        elif read:
            return self._safe_get(self._camera.get_cont_mode_parameters)
        else:
            raise ValueError("Either write or read must be True")

    def setup_kinetic_mode(self, num_cycle: int, cycle_time: float = 0.0, 
                          num_acc: int = 1, cycle_time_acc: float = 0.0, 
                          num_prescan: int = 0, *, write=False, read=False):
        """Set up or query kinetic acquisition mode parameters.

        Parameters
        ----------
        num_cycle : int
            Number of kinetic cycle frames
        cycle_time : float
            Acquisition period between accum frames
        num_acc : int
            Number of accumulated frames
        cycle_time_acc : float
            Accum acquisition period
        num_prescan : int
            Number of prescans
        """
        if write:
            self._safe_set(self._camera.setup_kinetic_mode, num_cycle, cycle_time, 
                          num_acc, cycle_time_acc, num_prescan)
        elif read:
            return self._safe_get(self._camera.get_kinetic_mode_parameters)
        else:
            raise ValueError("Either write or read must be True")

    def setup_fast_kinetic_mode(self, num_acc: int, cycle_time_acc: float = 0.0, *, write=False, read=False):
        """Set up or query fast kinetic acquisition mode parameters.

        Parameters
        ----------
        num_acc : int
            Number of accumulated frames
        cycle_time_acc : float
            Acquisition period (0.0 = minimal possible)
        """
        if write:
            self._safe_set(self._camera.setup_fast_kinetic_mode, num_acc, cycle_time_acc)
        elif read:
            return self._safe_get(self._camera.get_fast_kinetic_mode_parameters)
        else:
            raise ValueError("Either write or read must be True")

    # -------------- acquisition control --------------
    def start_acquisition(self):
        """Start camera acquisition (automatically sets it up as well)."""
        self._safe_set(self._camera.start_acquisition)

    def stop_acquisition(self):
        """Stop camera acquisition."""
        self._safe_set(self._camera.stop_acquisition)

    def wait_for_frame(self, timeout: float | None = None):
        """Wait for the next available frame.
        
        Parameters
        ----------
        timeout : float, optional
            Timeout in seconds. None for default timeout.
        """
        if timeout is not None:
            self._safe_get(self._camera.wait_for_frame, timeout=timeout)
        else:
            self._safe_get(self._camera.wait_for_frame)

    def read_oldest_image(self):
        """Get the oldest image which hasn't been read yet."""
        return self._safe_get(self._camera.read_oldest_image)

    def read_newest_image(self):
        """Get the newest image in the buffer."""
        return self._safe_get(self._camera.read_newest_image)

    # -------------- acquisition timing ---------------
    def get_acquisition_timings(self):
        """Get acquisition timing information.
        
        Returns
        -------
        tuple
            (exposure, accum_cycle_time, kinetic_cycle_time)
        """
        return self._safe_get(self._camera.get_cycle_timings)

    def get_frame_period(self):
        """Get frame period timing.
        
        Returns
        -------
        tuple
            (exposure, frame_period)
        """
        return self._safe_get(self._camera.get_frame_period)

    # -------------- buffer management ----------------
    def get_frames_status(self):
        """Get information about frames in the buffer."""
        return self._safe_get(self._camera.get_frames_status)

    def clear_acquisition(self):
        """Clear the acquisition buffer."""
        self._safe_set(self._camera.clear_acquisition)

    # -------------- image acquisition ---------------
    def snap_image(self):
        """Acquire a single image and return the data array."""
        return self._safe_get(self._camera.snap, timeout=self._exposure_time+5)

    def get_detector_size(self) -> tuple:
        """Get the detector size (width, height)."""
        return self._safe_get(self._camera.get_detector_size)

    def get_minimum_shutter_time(self) -> float:
        """Get the minimum shutter time in seconds."""
        return self._safe_get(self._camera.get_min_shutter_times)

    # -------------- connection teardown -------------
    def disconnect(self):
        """Safely close the camera connection"""
        if not hasattr(self, '_camera') or self._camera is None:
            return  # nothing to do

        try:
            self._camera.close()
        except Exception as exc:
            logging.warning(f"Error during disconnect: {exc}")

        self._camera = None



class ShamrockSpectrogramHardware:
    """
    Python driver for Andor Shamrock spectrographs using pylablib's ShamrockSpectrograph class.
    
    Key design guidelines:
    1. **pylablib first** – communicate via pylablib's spectrograph interface.
    2. **Symmetric API** – every setting provides a *setter* (``write=True``)
       and *getter* (``read=True``) in the same method.
    3. **Human-readable enums** – expose descriptive strings to users while
       translating to spectrograph parameters internally via mapping dictionaries.
    4. **Robust I/O helpers** – centralise spectrograph operations with error handling.
    5. **Thin abstraction** – driver should not hide the underlying spectrograph
       commands; instead, document them clearly.
    """

    # ---------------- initialisation ----------------
    def __init__(self, idx: int = 0):
        """Connect to the Andor Shamrock spectrograph.

        Parameters
        ----------
        idx : int
            Spectrograph index (default: 0 for first available spectrograph)
        """
        self._idx = idx
        self._spectrograph = ShamrockSpectrograph(idx=self._idx)
        logging.info(f"Connected to Shamrock spectrograph at index {idx}")

    # -------------- low-level helpers ---------------
    def _safe_get(self, func, *args, **kwargs):
        """Safely execute a getter function with retry logic."""
        attempts = 0
        while attempts < 3:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                attempts += 1
                logging.warning(
                    "Get operation failed (%s). Retry %d/3", exc, attempts
                )
                time.sleep(0.05)
        raise RuntimeError(f"Spectrograph is not responding to get operation")

    def _safe_set(self, func, *args, **kwargs):
        """Safely execute a setter function with error handling."""
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            logging.error(f"Set operation failed: {exc}")
            raise RuntimeError(f"Failed to set parameter: {exc}")

    # -------------- identity / info ------------------
    def get_device_info(self) -> dict:
        """Return spectrograph device information."""
        return self._safe_get(self._spectrograph.get_device_info)

    def get_optical_parameters(self):
        """Get device optical parameters (focal_length, angular_deviation, focal_tilt)."""
        return self._safe_get(self._spectrograph.get_optical_parameters)

    # -------------- wavelength control ---------------
    def center_wavelength(self, wavelength: float | None = None, *, write=False, read=False):
        """Set or query the center wavelength in nanometers.

        Usage examples
        --------------
        >>> spec.center_wavelength(500.0, write=True)  # set to 500 nm
        >>> current = spec.center_wavelength(read=True) # -> 500.0
        """
        if write and wavelength is not None:
            if wavelength <= 0:
                raise ValueError("wavelength must be positive")
            self._safe_set(self._spectrograph.set_wavelength, wavelength)
        elif read:
            return self._safe_get(self._spectrograph.get_wavelength)
        else:
            raise ValueError("Either write or read must be True")

    def wavelength_range(self, read=False):
        """Get the available wavelength range.
        
        Returns
        -------
        tuple
            (min_wavelength, max_wavelength) in nanometers
        """
        if read:
            return self._safe_get(self._spectrograph.get_wavelength_range)
        else:
            raise ValueError("read must be True for wavelength_range")

    # -------------- grating control ------------------
    _grating_map = {
        "grating_1": 1,
        "grating_2": 2,
        "grating_3": 3,
    }

    def grating(self, grating_num: str | int | None = None, *, write=False, read=False):
        """Set or query the active grating.

        Usage examples
        --------------
        >>> spec.grating("grating_1", write=True)  # select grating 1
        >>> spec.grating(2, write=True)           # select grating 2
        >>> current = spec.grating(read=True)     # -> 'grating_1'
        """
        if write and grating_num is not None:
            if grating_num in self._grating_map:
                self._safe_set(self._spectrograph.set_grating, self._grating_map[grating_num])
            elif isinstance(grating_num, int) and grating_num in self._grating_map.values():
                self._safe_set(self._spectrograph.set_grating, grating_num)
            else:
                valid_gratings = list(self._grating_map.keys()) + list(self._grating_map.values())
                raise ValueError(f"grating must be one of {valid_gratings}")
        elif read:
            grating_idx = self._safe_get(self._spectrograph.get_grating)
            for key, value in self._grating_map.items():
                if value == grating_idx:
                    return key
            return grating_idx  # return raw value if not in mapping
        else:
            raise ValueError("Either write or read must be True")

    def grating_info(self, grating_num: int | None = None):
        """Get information about a specific grating or all gratings.
        
        Parameters
        ----------
        grating_num : int, optional
            Grating number (1, 2, 3). If None, returns info for all gratings.
        """
        if grating_num is not None:
            return self._safe_get(self._spectrograph.get_grating_info, grating_num)
        else:
            return self._safe_get(self._spectrograph.get_all_grating_info)

    # -------------- slit control --------------------
    _slit_map = {
        "input_slit": "input",
        "output_slit": "output",
        "side_slit": "side"
    }

    def slit_width(self, slit_type: str, width: float | None = None, *, write=False, read=False):
        """Set or query slit width in micrometers.

        Parameters
        ----------
        slit_type : str
            Type of slit: "input_slit", "output_slit", or "side_slit"
        width : float
            Slit width in micrometers (must be positive)
        """
        if slit_type not in self._slit_map:
            raise ValueError(f"slit_type must be one of {list(self._slit_map.keys())}")
        
        slit_name = self._slit_map[slit_type]
        
        if write and width is not None:
            if width <= 0:
                raise ValueError("slit width must be positive")
            self._safe_set(self._spectrograph.set_slit_width, slit_name, width)
        elif read:
            return self._safe_get(self._spectrograph.get_slit_width, slit_name)
        else:
            raise ValueError("Either write or read must be True")

    def slit_width_range(self, slit_type: str):
        """Get the available slit width range for a specific slit.
        
        Parameters
        ----------
        slit_type : str
            Type of slit: "input_slit", "output_slit", or "side_slit"
            
        Returns
        -------
        tuple
            (min_width, max_width) in micrometers
        """
        if slit_type not in self._slit_map:
            raise ValueError(f"slit_type must be one of {list(self._slit_map.keys())}")
        
        slit_name = self._slit_map[slit_type]
        return self._safe_get(self._spectrograph.get_slit_width_range, slit_name)

    # -------------- flipper mirror control -----------
    _flipper_map = {
        "direct": "direct",
        "side": "side"
    }

    def flipper_mirror(self, position: str | None = None, *, write=False, read=False):
        """Set or query flipper mirror position.

        Parameters
        ----------
        position : str
            Mirror position: "direct" or "side"
        """
        if write and position is not None:
            if position not in self._flipper_map:
                raise ValueError(f"position must be one of {list(self._flipper_map.keys())}")
            self._safe_set(self._spectrograph.set_flipper_mirror, self._flipper_map[position])
        elif read:
            pos = self._safe_get(self._spectrograph.get_flipper_mirror)
            for key, value in self._flipper_map.items():
                if value == pos:
                    return key
            return pos  # return raw value if not in mapping
        else:
            raise ValueError("Either write or read must be True")

    # -------------- wavelength calibration -----------
    def pixel_to_wavelength(self, pixel_array):
        """Convert pixel positions to wavelengths using current calibration.
        
        Parameters
        ----------
        pixel_array : array-like
            Pixel positions to convert
            
        Returns
        -------
        array-like
            Corresponding wavelengths in nanometers
        """
        return self._safe_get(self._spectrograph.pixel_to_wavelength, pixel_array)

    def wavelength_to_pixel(self, wavelength_array):
        """Convert wavelengths to pixel positions using current calibration.
        
        Parameters
        ----------
        wavelength_array : array-like
            Wavelengths in nanometers to convert
            
        Returns
        -------
        array-like
            Corresponding pixel positions
        """
        return self._safe_get(self._spectrograph.wavelength_to_pixel, wavelength_array)

    def get_wavelength_calibration(self, detector_size=None):
        """Get wavelength calibration for the detector.
        
        Parameters
        ----------
        detector_size : tuple, optional
            (width, height) of detector. If None, uses default.
            
        Returns
        -------
        array-like
            Wavelength array corresponding to detector pixels
        """
        if detector_size is not None:
            return self._safe_get(self._spectrograph.get_wavelength_calibration, detector_size)
        else:
            return self._safe_get(self._spectrograph.get_wavelength_calibration)

    # -------------- filter wheel control ------------
    def filter_position(self, position: int | None = None, *, write=False, read=False):
        """Set or query filter wheel position.

        Parameters
        ----------
        position : int
            Filter position (1-based indexing)
        """
        if write and position is not None:
            if not isinstance(position, int) or position < 1:
                raise ValueError("filter position must be a positive integer")
            self._safe_set(self._spectrograph.set_filter, position)
        elif read:
            return self._safe_get(self._spectrograph.get_filter)
        else:
            raise ValueError("Either write or read must be True")

    def filter_info(self):
        """Get information about available filters."""
        return self._safe_get(self._spectrograph.get_filter_info)

    # -------------- detector integration --------------
    def detector_offset(self, offset: float | None = None, *, write=False, read=False):
        """Set or query detector offset in pixels.

        Parameters
        ----------
        offset : float
            Detector offset in pixels
        """
        if write and offset is not None:
            self._safe_set(self._spectrograph.set_detector_offset, offset)
        elif read:
            return self._safe_get(self._spectrograph.get_detector_offset)
        else:
            raise ValueError("Either write or read must be True")

    # -------------- system status --------------------
    def is_calibrated(self):
        """Check if the spectrograph is properly calibrated."""
        return self._safe_get(self._spectrograph.is_calibrated)

    def get_status(self):
        """Get overall system status information."""
        return self._safe_get(self._spectrograph.get_status)

    # -------------- utility functions ---------------
    def home_grating(self):
        """Home the grating to its reference position."""
        self._safe_set(self._spectrograph.home_grating)

    def reset_spectrograph(self):
        """Reset the spectrograph to default settings."""
        self._safe_set(self._spectrograph.reset)

    # -------------- connection teardown -------------
    def close(self):
        """Close spectrograph connection."""
        try:
            if hasattr(self, '_spectrograph') and self._spectrograph is not None:
                self._spectrograph.close()
        except Exception as exc:
            logging.warning(f"Error closing spectrograph: {exc}")

    def disconnect(self):
        """Safely close the spectrograph connection"""
        if not hasattr(self, '_spectrograph') or self._spectrograph is None:
            return  # nothing to do

        try:
            self._spectrograph.close()
        except Exception as exc:
            logging.warning(f"Error during disconnect: {exc}")

        self._spectrograph = None

# -----------------------------------------------------------------------------
# Example usage – requires an actual Andor camera to work
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # try:
    #     # Connect to first available camera
    #     cam = AndorCameraHardware(camera_index=0)

    #     print("Device info:", cam.get_device_info())
    #     print("Detector size:", cam.get_detector_size())

    #     # Demonstrate the API patterns
    #     cam.acquisition_mode("single", write=True)
    #     print("Acquisition mode:", cam.acquisition_mode(read=True))

    #     cam.exposure_time(0.1, write=True)
    #     print("Exposure time:", cam.exposure_time(read=True))

    #     print("Current temperature:", cam.temperature(read=True))

    #     print("Read mode before:", cam.read_mode(read=True))
    #     cam.read_mode("fvb", write=True)
    #     print("Read mode after:", cam.read_mode(read=True))

    #     print("Minimum shutter time:", cam.get_minimum_shutter_time())

    #     line_data = cam.snap_image()
    #     print(line_data)
    #     plt.plot(np.linspace(0, 1, len(line_data[0])), line_data[0])
    #     plt.show()
    #     # Take an image
    #     # image = cam.snap_image()
    #     # print(f"Captured image shape: {image.shape}")
    #     # fig, ax = plt.subplots()
    #     # pc=ax.imshow(image, origin="lower")
    #     # plt.colorbar(pc,ax=ax)

    #     # plt.show()


    #     cam.disconnect()

    # except Exception as e:
    #     print(f"Error: {e}")
    #     print("Make sure an Andor camera is connected and drivers are installed")

    try:
        # Connect to first available camera
        cam = AndorCameraHardware(camera_index=0)

        print("Device info:", cam.get_device_info())
        print("Detector size:", cam.get_detector_size())

        # Demonstrate different acquisition modes
        cam.acquisition_mode("single", write=True)
        print("Acquisition mode:", cam.acquisition_mode(read=True))

        # Set up accumulation mode
        cam.setup_accumulation_mode(10, 0.1, write=True)
        cam.acquisition_mode("accumulate", write=True)
        print("Accumulation parameters:", cam.setup_accumulation_mode(read=True))

        # Set up continuous mode  
        cam.setup_continuous_mode(0.05, write=True)
        cam.acquisition_mode("continuous", write=True)
        print("Continuous parameters:", cam.setup_continuous_mode(read=True))

        # Demonstrate continuous acquisition loop
        print("Starting continuous acquisition...")
        cam.start_acquisition()
        
        images = []
        for i in range(5):
            cam.wait_for_frame()
            image = cam.read_oldest_image()
            images.append(image)
            print(f"Captured frame {i+1}: shape {image.shape}")
        
        cam.stop_acquisition()
        print("Acquisition stopped")

        cam.disconnect()

    except Exception as e:
        print(f"Error: {e}")
        print("Make sure an Andor camera is connected and drivers are installed")


    # try:
    #     # Connect to first available spectrograph
    #     spec = ShamrockSpectrogramHardware(idx=0)

    #     print("Device info:", spec.get_device_info())
    #     print("Optical parameters:", spec.get_optical_parameters())

    #     # Demonstrate wavelength control
    #     spec.center_wavelength(550.0, write=True)  # Set to 550 nm
    #     print("Center wavelength:", spec.center_wavelength(read=True))
    #     print("Wavelength range:", spec.wavelength_range(read=True))

    #     # Demonstrate grating control
    #     spec.grating("grating_1", write=True)
    #     print("Current grating:", spec.grating(read=True))
    #     print("Grating info:", spec.grating_info())

    #     # Demonstrate slit control
    #     spec.slit_width("input_slit", 100.0, write=True)  # 100 μm
    #     print("Input slit width:", spec.slit_width("input_slit", read=True))
    #     print("Input slit range:", spec.slit_width_range("input_slit"))

    #     # Demonstrate flipper mirror
    #     spec.flipper_mirror("direct", write=True)
    #     print("Flipper mirror:", spec.flipper_mirror(read=True))

    #     # Demonstrate calibration functions
    #     print("Is calibrated:", spec.is_calibrated())
        
    #     # Get wavelength calibration for a 1024 pixel detector
    #     wavelengths = spec.get_wavelength_calibration((1024, 1))
    #     print(f"Wavelength calibration: {wavelengths[0]:.2f} to {wavelengths[-1]:.2f} nm")

    #     spec.disconnect()
        
    # except Exception as e:
    #     print(f"Error: {e}")
    #     print("Make sure a Shamrock spectrograph is connected and drivers are installed")