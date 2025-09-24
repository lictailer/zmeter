#!/usr/bin/env python3
"""
Standalone Andor SDK2 Camera Controller
A clean implementation for controlling Andor cameras via SDK2 without requiring pylablib.

This module provides a direct interface to Andor cameras using the SDK2 DLL.
Supports cameras like iXon, Newton, and other SDK2-compatible models.

Requirements:
- Andor SDK2 DLL (atmcd64d.dll or atmcd32d.dll)
- numpy
- ctypes (built-in)

Author: Based on pylablib implementation
"""

import ctypes
import ctypes.util
import numpy as np
import os
import sys
import platform
import time
from collections import namedtuple
from typing import Optional, Tuple, Union, List, Dict, Any


# Error definitions
class AndorError(Exception):
    """Base exception for Andor camera errors"""
    pass

class AndorTimeoutError(AndorError):
    """Timeout error during camera operations"""
    pass

class AndorNotSupportedError(AndorError):
    """Feature not supported by camera"""
    pass


# Data structures
TDetectorSize = namedtuple('TDetectorSize', ['width', 'height'])
TReadoutTime = namedtuple('TReadoutTime', ['exposure', 'accum_cycle_time', 'kinetic_cycle_time'])
TROIInfo = namedtuple('TROIInfo', ['left', 'top', 'right', 'bottom', 'hbin', 'vbin'])
TDetectorInfo = namedtuple('TDetectorInfo', ['width', 'height', 'pixel_width', 'pixel_height'])


# DLL error codes and their meanings
ANDOR_ERROR_CODES = {
    20001: "DRV_ERROR_CODES",
    20002: "DRV_SUCCESS",
    20003: "DRV_VXDNOTINSTALLED",
    20004: "DRV_ERROR_SCAN",
    20005: "DRV_ERROR_CHECK_SUM",
    20006: "DRV_ERROR_FILELOAD",
    20007: "DRV_UNKNOWN_FUNCTION",
    20008: "DRV_ERROR_VXD_INIT",
    20009: "DRV_ERROR_ADDRESS",
    20010: "DRV_ERROR_PAGELOCK",
    20011: "DRV_ERROR_PAGE_UNLOCK",
    20012: "DRV_ERROR_BOARDTEST",
    20013: "DRV_ERROR_ACK",
    20014: "DRV_ERROR_UP_FIFO",
    20015: "DRV_ERROR_PATTERN",
    20017: "DRV_ACQUISITION_ERRORS",
    20018: "DRV_ACQ_BUFFER",
    20019: "DRV_ACQ_DOWNFIFO_FULL",
    20020: "DRV_PROC_UNKNOWN_INSTRUCTION",
    20021: "DRV_ILLEGAL_OP_CODE",
    20022: "DRV_KINETIC_TIME_NOT_MET",
    20023: "DRV_ACCUM_TIME_NOT_MET",
    20024: "DRV_NO_NEW_DATA",
    20025: "PCI_DMA_FAIL",
    20026: "DRV_SPOOLERROR",
    20027: "DRV_SPOOLSETUPERROR",
    20029: "SATURATED",
    20033: "DRV_TEMPERATURE_CODES",
    20034: "DRV_TEMPERATURE_OFF",
    20035: "DRV_TEMP_NOT_STABILIZED",
    20036: "DRV_TEMPERATURE_STABILIZED",
    20037: "DRV_TEMPERATURE_NOT_REACHED",
    20038: "DRV_TEMPERATURE_OUT_RANGE",
    20039: "DRV_TEMPERATURE_NOT_SUPPORTED",
    20040: "DRV_TEMPERATURE_DRIFT",
    20049: "DRV_GENERAL_ERRORS",
    20050: "DRV_INVALID_AUX",
    20051: "DRV_COF_NOTLOADED",
    20052: "DRV_FPGAPROG",
    20053: "DRV_FLEXERROR",
    20054: "DRV_GPIBERROR",
    20055: "ERROR_DMA_UPLOAD",
    20064: "DRV_DATATYPE",
    20065: "DRV_DRIVER_ERRORS",
    20066: "DRV_P1INVALID",
    20067: "DRV_P2INVALID",
    20068: "DRV_P3INVALID",
    20069: "DRV_P4INVALID",
    20070: "DRV_INIERROR",
    20071: "DRV_COFERROR",
    20072: "DRV_ACQUIRING",
    20073: "DRV_IDLE",
    20074: "DRV_TEMPCYCLE",
    20075: "DRV_NOT_INITIALIZED",
    20076: "DRV_P5INVALID",
    20077: "DRV_P6INVALID",
    20078: "DRV_INVALID_MODE",
    20079: "DRV_INVALID_FILTER",
    20080: "DRV_I2CERRORS",
    20081: "DRV_DRV_I2CDEVNOTFOUND",
    20082: "DRV_I2CTIMEOUT",
    20083: "DRV_P7INVALID",
    20089: "DRV_USBERROR",
    20090: "DRV_IOCERROR",
    20091: "DRV_VRMVERSIONERROR",
    20093: "DRV_USB_INTERRUPT_ENDPOINT_ERROR",
    20094: "DRV_RANDOM_TRACK_ERROR",
    20095: "DRV_INVALID_TRIGGER_MODE",
    20096: "DRV_LOAD_FIRMWARE_ERROR",
    20097: "DRV_DIVIDE_BY_ZERO_ERROR",
    20098: "DRV_INVALID_RINGEXPOSURES",
    20099: "DRV_BINNING_ERROR",
    20100: "DRV_INVALID_AMPLIFIER",
    20101: "DRV_INVALID_COUNTCONVERT_MODE",
    20115: "DRV_ERROR_MAP",
    20116: "DRV_ERROR_UNMAP",
    20117: "DRV_ERROR_MDL",
    20118: "DRV_ERROR_UNMDL",
    20119: "DRV_ERROR_BUFFSIZE",
    20121: "DRV_ERROR_NOHANDLE",
    20130: "DRV_GATING_NOT_AVAILABLE",
    20131: "DRV_FPGA_VOLTAGE_ERROR",
    20990: "DRV_ERROR_NOCAMERA",
    20991: "DRV_NOT_SUPPORTED",
    20992: "DRV_NOT_AVAILABLE"
}



def _check_andor_error(error_code: int) -> None:
    """Check Andor SDK error code and raise appropriate exception if needed"""
    if error_code != 20002:  # DRV_SUCCESS
        error_msg = ANDOR_ERROR_CODES.get(error_code, f"Unknown error code: {error_code}")
        raise AndorError(f"Andor SDK error: {error_msg} ({error_code})")


def _find_andor_dll() -> str:
    """Find Andor SDK2 DLL in standard locations"""
    dll_names = []
    
    # Determine DLL names based on architecture
    if platform.architecture()[0] == '64bit':
        dll_names = ['atmcd64d.dll', 'atmcd64d_legacy.dll']
    else:
        dll_names = ['atmcd32d.dll', 'atmcd32d_legacy.dll']
    
    # Search paths
    search_paths = [
        os.getcwd(),  # Current directory
        os.path.dirname(sys.argv[0]) if sys.argv else "",  # Script directory
    ]
    
    # Add Windows Program Files directories
    if os.name == 'nt':
        program_files = os.environ.get('ProgramFiles', r'C:\Program Files')
        program_files_x86 = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
        
        andor_paths = [
            os.path.join(program_files, 'Andor SOLIS'),
            os.path.join(program_files, 'Andor SDK'),
            os.path.join(program_files_x86, 'Andor SOLIS'),
            os.path.join(program_files_x86, 'Andor SDK'),
        ]
        search_paths.extend(andor_paths)
    
    # Search for DLL
    for path in search_paths:
        if not path or not os.path.exists(path):
            continue
        for dll_name in dll_names:
            dll_path = os.path.join(path, dll_name)
            if os.path.exists(dll_path):
                return dll_path
    
    # If not found, try system PATH
    for dll_name in dll_names:
        dll_path = ctypes.util.find_library(dll_name.replace('.dll', ''))
        if dll_path:
            return dll_path
    
    raise AndorError(f"Could not find Andor SDK2 DLL. Searched for: {dll_names}")


class AndorSDK2Controller:
    """Controller for managing Andor SDK2 library initialization"""
    
    def __init__(self, dll_path: Optional[str] = None):
        self._dll = None
        self._initialized = False
        self._dll_path = dll_path or _find_andor_dll()
        self._load_dll()
    
    def _load_dll(self) -> None:
        """Load the Andor SDK2 DLL"""
        # Add DLL directory to PATH for dependency resolution
        dll_dir = os.path.dirname(self._dll_path)
        old_path = os.environ.get("PATH", "")
        
        # Temporarily add DLL directory to PATH
        if dll_dir and dll_dir not in old_path:
            os.environ["PATH"] = dll_dir + os.pathsep + old_path
        
        # try:
        # Use windll (stdcall) instead of CDLL (cdecl) for Andor SDK
        self._dll = ctypes.windll.LoadLibrary(self._dll_path)
        # except OSError as e:
        #     raise AndorError(f"Failed to load Andor DLL from {self._dll_path}: {e}")
        
        # Define function signatures
        self._setup_function_signatures()
    
    def _setup_function_signatures(self) -> None:
        """Set up ctypes function signatures for SDK functions"""
        
        # def _setup_function(name: str, restype, argtypes):
        #     """Helper to safely setup function signatures"""
        #     if hasattr(self._dll, name):
        #         func = getattr(self._dll, name)
        #         func.restype = restype
        #         func.argtypes = argtypes
        #         return True
        #     else:
        #         print(f"Warning: Function '{name}' not found in DLL")
        #         return False
        
        # Basic initialization functions
        self._dll.Initialize.restype = ctypes.c_uint
        self._dll.Initialize.argtypes = [ctypes.c_char_p]
        
        self._dll.GetNumberDevices.restype = ctypes.c_uint
        self._dll.GetNumberDevices.argtypes = [ctypes.POINTER(ctypes.c_int)]
        
        self._dll.GetCurrentCamera.restype = ctypes.c_uint
        self._dll.GetCurrentCamera.argtypes = [ctypes.POINTER(ctypes.c_int)]
        
        self._dll.SetCurrentCamera.restype = ctypes.c_uint
        self._dll.SetCurrentCamera.argtypes = [ctypes.c_int]
        
        self._dll.ShutDown.restype = ctypes.c_uint
        self._dll.ShutDown.argtypes = []
        
        # Camera information
        self._dll.GetDetector.restype = ctypes.c_uint
        self._dll.GetDetector.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        
        # Acquisition settings
        self._dll.SetExposureTime.restype = ctypes.c_uint
        self._dll.SetExposureTime.argtypes = [ctypes.c_float]
        
        self._dll.SetAcquisitionMode.restype = ctypes.c_uint
        self._dll.SetAcquisitionMode.argtypes = [ctypes.c_int]
        
        self._dll.SetReadMode.restype = ctypes.c_uint
        self._dll.SetReadMode.argtypes = [ctypes.c_int]
        
        self._dll.SetTriggerMode.restype = ctypes.c_uint
        self._dll.SetTriggerMode.argtypes = [ctypes.c_int]
        
        # ROI and binning
        self._dll.SetImage.restype = ctypes.c_uint
        self._dll.SetImage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        
        # Acquisition control
        self._dll.StartAcquisition.restype = ctypes.c_uint
        self._dll.StartAcquisition.argtypes = []
        
        self._dll.AbortAcquisition.restype = ctypes.c_uint
        self._dll.AbortAcquisition.argtypes = []
        
        self._dll.GetStatus.restype = ctypes.c_uint
        self._dll.GetStatus.argtypes = [ctypes.POINTER(ctypes.c_int)]
        
        # Data acquisition
        self._dll.GetAcquiredData.restype = ctypes.c_uint
        self._dll.GetAcquiredData.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_ulong]
        
        self._dll.GetMostRecentImage.restype = ctypes.c_uint
        self._dll.GetMostRecentImage.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_ulong]
        
        # Temperature control
        self._dll.SetTemperature.restype = ctypes.c_uint
        self._dll.SetTemperature.argtypes = [ctypes.c_int]
        
        self._dll.GetTemperature.restype = ctypes.c_uint
        self._dll.GetTemperature.argtypes = [ctypes.POINTER(ctypes.c_int)]
        
        self._dll.CoolerON.restype = ctypes.c_uint
        self._dll.CoolerON.argtypes = []
        
        self._dll.CoolerOFF.restype = ctypes.c_uint
        self._dll.CoolerOFF.argtypes = []
        
        # Shutter control
        self._dll.SetShutter.restype = ctypes.c_uint
        self._dll.SetShutter.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        
        # Amplifier settings
        self._dll.SetPreAmpGain.restype = ctypes.c_uint
        self._dll.SetPreAmpGain.argtypes = [ctypes.c_int]
        
        self._dll.SetVSSpeed.restype = ctypes.c_uint
        self._dll.SetVSSpeed.argtypes = [ctypes.c_int]
        
        self._dll.SetHSSpeed.restype = ctypes.c_uint
        self._dll.SetHSSpeed.argtypes = [ctypes.c_int, ctypes.c_int]
        
        # EMCCD settings (if applicable)
        self._dll.SetEMCCDGain.restype = ctypes.c_uint
        self._dll.SetEMCCDGain.argtypes = [ctypes.c_int]
        
        self._dll.GetEMCCDGain.restype = ctypes.c_uint
        self._dll.GetEMCCDGain.argtypes = [ctypes.POINTER(ctypes.c_int)]
    
    def initialize(self, ini_path: str = "") -> None:
        """Initialize the Andor SDK"""
        if self._initialized:
            return
        
        ini_path_bytes = ini_path.encode('utf-8') if ini_path else b""
        error_code = self._dll.Initialize(ini_path_bytes)
        _check_andor_error(error_code)
        self._initialized = True
    
    def shutdown(self) -> None:
        """Shutdown the Andor SDK"""
        if self._initialized:
            error_code = self._dll.ShutDown()
            _check_andor_error(error_code)
            self._initialized = False
    
    def get_number_devices(self) -> int:
        """Get number of connected Andor cameras"""
        num_devices = ctypes.c_int()
        error_code = self._dll.GetNumberDevices(ctypes.byref(num_devices))
        _check_andor_error(error_code)
        return num_devices.value
    
    @property
    def dll(self):
        """Access to the underlying DLL"""
        return self._dll


# Global SDK controller instance
_sdk_controller = None


def get_cameras_number() -> int:
    """Get number of connected Andor SDK2 cameras"""
    global _sdk_controller
    if _sdk_controller is None:
        _sdk_controller = AndorSDK2Controller()
        _sdk_controller.initialize()
    return _sdk_controller.get_number_devices()


class AndorSDK2Camera:
    """
    Andor SDK2 Camera Interface
    
    Provides a clean interface to control Andor cameras through SDK2.
    Supports standard camera operations like exposure control, ROI settings,
    temperature management, and frame acquisition.
    
    Args:
        idx: Camera index (starting from 0)
        ini_path: Path to initialization file (optional)
        temperature: Target temperature for cooling (optional)
        fan_mode: Fan mode ('off', 'low', 'high')
        amp_mode: Amplifier mode index (optional)
    """
    
    def __init__(self, idx: int = 0, ini_path: str = '', temperature: Optional[int] = None, 
                 fan_mode: str = 'off', amp_mode: Optional[int] = None):
        global _sdk_controller
        
        self.idx = idx
        self._opened = False
        self._acquiring = False
        
        # Initialize SDK controller if needed
        if _sdk_controller is None:
            _sdk_controller = AndorSDK2Controller()
            _sdk_controller.initialize(ini_path)
        
        self._dll = _sdk_controller.dll
        
        # Camera state tracking
        self._detector_size = None
        self._current_roi = None
        self._exposure_time = 0.001  # Default 1ms
        self._temperature_setpoint = temperature
        
        # Open the camera
        self.open()
        
        # Apply initial settings
        if temperature is not None:
            self.set_temperature(temperature)
        
        self._set_fan_mode(fan_mode)
        
        if amp_mode is not None:
            self.set_amp_mode(amp_mode)
        
        # Set reasonable defaults
        self._set_default_parameters()
    
    def open(self) -> None:
        """Open connection to the camera"""
        if self._opened:
            return
        
        # Set current camera
        # error_code = self._dll.SetCurrentCamera(self.idx)
        error_code = self._dll.GetCameraHandle(self.idx)
        print("after get camera handle", error_code)
        _check_andor_error(error_code)
        
        # Get detector information
        self._get_detector_info()
        
        self._opened = True
    
    def close(self) -> None:
        """Close connection to the camera"""
        if not self._opened:
            return
        
        if self._acquiring:
            # self.abort_acquisition()
            pass
        
        # Note: Individual camera close is handled by SDK shutdown
        self._opened = False
    
    def _get_detector_info(self) -> None:
        """Get detector size information"""
        width = ctypes.c_int()
        height = ctypes.c_int()
        error_code = self._dll.GetDetector(ctypes.byref(width), ctypes.byref(height))
        _check_andor_error(error_code)
        
        self._detector_size = TDetectorSize(width.value, height.value)
        self._current_roi = TROIInfo(0, 0, width.value - 1, height.value - 1, 1, 1)
    
    def _set_default_parameters(self) -> None:
        """Set reasonable default parameters"""
        # Set acquisition mode to single scan
        error_code = self._dll.SetAcquisitionMode(1)  # Single scan
        _check_andor_error(error_code)
        
        # Set read mode to full vertical binning
        error_code = self._dll.SetReadMode(0)  # Full vertical binning
        _check_andor_error(error_code)
        
        # Set trigger mode to internal
        error_code = self._dll.SetTriggerMode(0)  # Internal trigger
        _check_andor_error(error_code)
        
        # Set initial exposure time
        self.set_exposure(self._exposure_time)
        
        # Set shutter to closed by default
        self.set_shutter('closed')
        
        # Set full ROI
        self.set_roi()
    
    def _set_fan_mode(self, mode: str) -> None:
        """Set fan mode (placeholder - specific implementation depends on camera model)"""
        # This would typically involve setting specific registers or calling
        # model-specific functions. Implementation varies by camera model.
        pass
    
    def get_detector_size(self) -> TDetectorSize:
        """Get detector dimensions"""
        if self._detector_size is None:
            self._get_detector_info()
        return self._detector_size
    
    def set_exposure(self, exposure: float) -> None:
        """Set exposure time in seconds"""
        error_code = self._dll.SetExposureTime(ctypes.c_float(exposure))
        _check_andor_error(error_code)
        self._exposure_time = exposure
    

    
    def set_roi(self, left: int = 0, top: int = 0, right: Optional[int] = None, 
                bottom: Optional[int] = None, hbin: int = 1, vbin: int = 1) -> None:
        """
        Set Region of Interest (ROI)
        
        Args:
            left: Left pixel coordinate (0-indexed)
            top: Top pixel coordinate (0-indexed) 
            right: Right pixel coordinate (0-indexed), None for full width
            bottom: Bottom pixel coordinate (0-indexed), None for full height
            hbin: Horizontal binning factor
            vbin: Vertical binning factor
        """
        detector_size = self.get_detector_size()
        
        if right is None:
            right = detector_size.width - 1
        if bottom is None:
            bottom = detector_size.height - 1
        
        # Andor SDK uses 1-indexed coordinates
        # error_code = self._dll.SetImage(hbin, vbin, left + 1, right + 1, top + 1, bottom + 1)
        error_code = self._dll.SetImage(1, 1, 10, 50, 10, 50)
        # _check_andor_error(error_code)
        
        # self._current_roi = TROIInfo(left, top, right, bottom, hbin, vbin)
        self._current_roi = TROIInfo(10, 50, 10, 50, 1, 1)
    
    def get_roi(self) -> TROIInfo:
        """Get current ROI settings"""
        return self._current_roi
    
    def set_temperature(self, temperature: int) -> None:
        """Set target temperature for cooling"""
        error_code = self._dll.SetTemperature(temperature)
        _check_andor_error(error_code)
        self._temperature_setpoint = temperature
    
    def get_temperature(self) -> int:
        """Get current temperature"""
        temperature = ctypes.c_int()
        error_code = self._dll.GetTemperatureF(ctypes.byref(temperature))
        _check_andor_error(error_code)
        return temperature.value
    
    def start_cooling(self) -> None:
        """Start the cooler"""
        error_code = self._dll.CoolerON()
        _check_andor_error(error_code)
    
    def stop_cooling(self) -> None:
        """Stop the cooler"""
        error_code = self._dll.CoolerOFF()
        _check_andor_error(error_code)
    
    def set_shutter(self, mode: str, close_time: int = 0, open_time: int = 0) -> None:
        """
        Set shutter mode
        
        Args:
            mode: 'closed', 'open', or 'auto'
            close_time: Shutter close time (ms)
            open_time: Shutter open time (ms)
        """
        mode_map = {'closed': 2, 'open': 1, 'auto': 0}
        if mode not in mode_map:
            raise AndorError(f"Invalid shutter mode: {mode}")
        
        error_code = self._dll.SetShutter(1, mode_map[mode], close_time, open_time)
        _check_andor_error(error_code)
    
    def set_amp_mode(self, amp_mode: int) -> None:
        """Set amplifier mode"""
        # This typically involves setting pre-amp gain and readout speeds
        # Implementation depends on specific camera capabilities
        error_code = self._dll.SetPreAmpGain(amp_mode)
        _check_andor_error(error_code)
    
    def set_vsspeed(self, speed_index: int) -> None:
        """Set vertical shift speed"""
        error_code = self._dll.SetVSSpeed(speed_index)
        _check_andor_error(error_code)
    
    def set_hsspeed(self, amp_type: int, speed_index: int) -> None:
        """Set horizontal shift speed"""
        error_code = self._dll.SetHSSpeed(amp_type, speed_index)
        _check_andor_error(error_code)
    
    def set_emccd_gain(self, gain: int) -> None:
        """Set EMCCD gain (for EMCCD cameras)"""
        error_code = self._dll.SetEMCCDGain(gain)
        _check_andor_error(error_code)
    
    def get_emccd_gain(self) -> int:
        """Get current EMCCD gain"""
        gain = ctypes.c_int()
        error_code = self._dll.GetEMCCDGain(ctypes.byref(gain))
        _check_andor_error(error_code)
        return gain.value
    
    def start_acquisition(self) -> None:
        """Start image acquisition"""
        error_code = self._dll.StartAcquisition()
        _check_andor_error(error_code)
        self._acquiring = True
    
    def abort_acquisition(self) -> None:
        """Abort current acquisition"""
        error_code = self._dll.AbortAcquisition()
        _check_andor_error(error_code)
        self._acquiring = False
    
    def get_status(self) -> str:
        """Get current camera status"""
        status = ctypes.c_int()
        error_code = self._dll.GetStatus(ctypes.byref(status))
        _check_andor_error(error_code)
        
        status_map = {
            20002: "DRV_SUCCESS",
            20026: "DRV_IDLE", 
            20025: "DRV_ACQUIRING",
            20027: "DRV_TEMPCYCLE",
            20071: "DRV_NO_NEW_DATA"
        }
        return status_map.get(status.value, f"Unknown status: {status.value}")
    
    def wait_for_acquisition(self, timeout: float = 10.0) -> None:
        """Wait for acquisition to complete"""
        start_time = time.time()
        while True:
            status = self.get_status()
            if status == "DRV_IDLE":
                self._acquiring = False
                break
            elif status in ["DRV_SUCCESS", "DRV_NO_NEW_DATA"]:
                break
            
            if time.time() - start_time > timeout:
                raise AndorTimeoutError(f"Acquisition timeout after {timeout} seconds")
            
            time.sleep(0.01)  # Sleep 10ms
    
    def get_acquired_data(self) -> np.ndarray:
        """Get the most recently acquired image data"""
        roi = self.get_roi()
        width = (roi.right - roi.left + 1) // roi.hbin
        height = (roi.bottom - roi.top + 1) // roi.vbin
        size = width * height
        
        # Create buffer for image data
        image_data = (ctypes.c_int * size)()
        
        error_code = self._dll.GetMostRecentImage(image_data, size)
        _check_andor_error(error_code)
        
        # Convert to numpy array and reshape
        array = np.array(image_data, dtype=np.int32)
        return array.reshape((height, width))
    
    def snap(self, timeout: float = 10.0) -> np.ndarray:
        """
        Capture a single frame
        
        Args:
            timeout: Maximum time to wait for acquisition (seconds)
            
        Returns:
            numpy array containing the image data
        """
        # Set single scan mode
        error_code = self._dll.SetAcquisitionMode(1)  # Single scan
        _check_andor_error(error_code)
        
        # Start acquisition
        self.start_acquisition()
        
        # Wait for completion
        # self.wait_for_acquisition(timeout)
        time.sleep(10)
        
        # Get the image data
        return self.get_acquired_data()
    
    def start_continuous_acquisition(self) -> None:
        """Start continuous acquisition mode"""
        # Set run till abort mode
        error_code = self._dll.SetAcquisitionMode(5)  # Run till abort
        _check_andor_error(error_code)
        
        self.start_acquisition()
    
    def get_newest_image(self) -> np.ndarray:
        """Get the newest available image during continuous acquisition"""
        if not self._acquiring:
            raise AndorError("Camera is not acquiring")
        
        return self.get_acquired_data()
    
    def set_trigger_mode(self, mode: str) -> None:
        """
        Set trigger mode
        
        Args:
            mode: 'internal', 'external', 'external_start', 'external_exposure'
        """
        mode_map = {
            'internal': 0,
            'external': 1, 
            'external_start': 6,
            'external_exposure': 7
        }
        
        if mode not in mode_map:
            raise AndorError(f"Invalid trigger mode: {mode}")
        
        error_code = self._dll.SetTriggerMode(mode_map[mode])
        _check_andor_error(error_code)
    
    def set_acquisition_mode(self, mode: str, num_accumulations: int = 1, 
                           num_kinetics: int = 1) -> None:
        """
        Set acquisition mode
        
        Args:
            mode: 'single', 'accumulate', 'kinetic', 'continuous', 'fast_kinetic'
            num_accumulations: Number of accumulations (for accumulate mode)
            num_kinetics: Number of kinetic scans (for kinetic mode)
        """
        mode_map = {
            'single': 1,
            'accumulate': 2, 
            'kinetic': 3,
            'continuous': 5,
            'fast_kinetic': 4
        }
        
        if mode not in mode_map:
            raise AndorError(f"Invalid acquisition mode: {mode}")
        
        error_code = self._dll.SetAcquisitionMode(mode_map[mode])
        _check_andor_error(error_code)
        
        # Set additional parameters for specific modes
        if mode == 'accumulate' and hasattr(self._dll, 'SetNumberAccumulations'):
            error_code = self._dll.SetNumberAccumulations(num_accumulations)
            _check_andor_error(error_code)
        
        if mode == 'kinetic' and hasattr(self._dll, 'SetNumberKinetics'):
            error_code = self._dll.SetNumberKinetics(num_kinetics) 
            _check_andor_error(error_code)
    
    def get_readout_time(self) -> TReadoutTime:
        """Get readout timing information"""
        # These would typically be retrieved from the SDK
        # For now, return current exposure and estimated cycle times
        exposure = self._exposure_time
        
        # Rough estimates - actual values depend on camera model and settings
        readout_time = 0.001  # 1ms typical readout
        accum_cycle = exposure + readout_time
        kinetic_cycle = accum_cycle + 0.001  # Additional overhead
        
        return TReadoutTime(exposure, accum_cycle, kinetic_cycle)
    
    def get_device_info(self) -> Dict[str, Any]:
        """Get comprehensive device information"""
        info = {
            'camera_index': self.idx,
            'detector_size': self.get_detector_size(),
            'current_roi': self.get_roi(),
            'exposure_time': self._exposure_time,
            'status': self.get_status(),
            'temperature_setpoint': self._temperature_setpoint,
        }
        
        # try:
        # info['current_temperature'] = self.get_temperature()
        info['current_temperature'] = "skipped"
        # except:
        #     info['current_temperature'] = None
        
        # try:
        info['emccd_gain'] = self.get_emccd_gain()
        # except:
        #     info['emccd_gain'] = None
        
        return info
    
    def wait_for_temperature(self, tolerance: int = 1, timeout: float = 300.0) -> bool:
        """
        Wait for temperature to stabilize
        
        Args:
            tolerance: Temperature tolerance in degrees C
            timeout: Maximum wait time in seconds
            
        Returns:
            True if temperature stabilized, False if timeout
        """
        if self._temperature_setpoint is None:
            return True
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            # try:
            current_temp = self.get_temperature()
            if abs(current_temp - self._temperature_setpoint) <= tolerance:
                return True
            # except:
            #     pass
            time.sleep(1.0)
        
        return False
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()


# Utility functions
def get_all_cameras_info() -> List[Dict[str, Any]]:
    """Get information about all connected cameras"""
    num_cameras = get_cameras_number()
    cameras_info = []
    
    for i in range(num_cameras):
        # try:
        with AndorSDK2Camera(idx=i) as cam:
            info = cam.get_device_info()
            cameras_info.append(info)
        # except Exception as e:
        #     cameras_info.append({'camera_index': i, 'error': str(e)})
    
    return cameras_info


# Example usage functions
def example_single_shot():
    """Example: Capture a single image"""
    # try:
    with AndorSDK2Camera(idx=0) as cam:
        # Set exposure time to 100ms
        cam.set_exposure(0.1)
        
        # Set ROI to center 512x512 region (adjust based on your detector)
        detector_size = cam.get_detector_size()
        center_x = detector_size.width // 2
        center_y = detector_size.height // 2
        roi_size = 256
        
        cam.set_roi(
            left=center_x - roi_size,
            top=center_y - roi_size, 
            right=center_x + roi_size,
            bottom=center_y + roi_size
        )
        
        # Open shutter and capture
        cam.set_shutter('auto')
        image = cam.snap()
        
        print(f"Captured image shape: {image.shape}")
        print(f"Image data type: {image.dtype}")
        print(f"Image statistics - Min: {image.min()}, Max: {image.max()}, Mean: {image.mean():.1f}")
        
        return image
        
    # except AndorError as e:
    #     print(f"Andor camera error: {e}")
    # except Exception as e:
    #     print(f"General error: {e}")


def example_continuous_acquisition():
    """Example: Continuous acquisition with multiple frames"""
    # try:
    with AndorSDK2Camera(idx=0, temperature=-80) as cam:
        # Setup camera
        cam.set_exposure(0.05)  # 50ms exposure
        cam.set_shutter('auto')
        
        # Start cooling
        cam.start_cooling()
        print("Cooling started, waiting for temperature...")
        
        if cam.wait_for_temperature(tolerance=2, timeout=60):
            print("Temperature stabilized")
        else:
            print("Temperature stabilization timeout - proceeding anyway")
        
        # Start continuous acquisition
        cam.start_continuous_acquisition()
        
        images = []
        for i in range(10):
            # Wait a bit and grab newest image
            time.sleep(0.1)
            image = cam.get_newest_image()
            images.append(image)
            print(f"Captured frame {i+1}/10")
        
        cam.abort_acquisition()
        
        # Convert to numpy array
        image_stack = np.array(images)
        print(f"Captured {len(images)} frames with shape {image_stack.shape}")
        
        return image_stack
        
    # except AndorError as e:
    #     print(f"Andor camera error: {e}")
    # except Exception as e:
    #     print(f"General error: {e}")


def example_camera_info():
    """Example: Get information about all connected cameras"""
    # try:
    num_cameras = get_cameras_number()
    print(f"Found {num_cameras} Andor camera(s)")
    
    cameras_info = get_all_cameras_info()
    
    for i, info in enumerate(cameras_info):
        print(f"\nCamera {i}:")
        if 'error' in info:
            print(f"  Error: {info['error']}")
        else:
            print(f"  Detector size: {info['detector_size'].width} x {info['detector_size'].height}")
            print(f"  Status: {info['status']}")
            print(f"  Current temperature: {info['current_temperature']}")
            if info['emccd_gain'] is not None:
                print(f"  EMCCD gain: {info['emccd_gain']}")
                
    # except Exception as e:
    #     print(f"Error getting camera info: {e}")



if __name__ == "__main__":
    """
    Main function for testing the camera interface
    Run different examples based on command line arguments
    """
    import argparse
    
    parser = argparse.ArgumentParser(description="Andor SDK2 Camera Test")
    parser.add_argument('--mode', choices=['info', 'single', 'continuous'], 
                       default='single', help='Test mode to run')  # Changed default to 'single'
    parser.add_argument('--camera', type=int, default=0, 
                       help='Camera index to use')
    parser.add_argument('--dll-path', type=str, default=None,
                       help='Path to Andor SDK2 DLL')
    
    args = parser.parse_args()
    
    print("Andor SDK2 Standalone Camera Controller")
    print("=" * 40)
    
    local_sdk_controller = None
    
    # try:
    if args.dll_path:
        local_sdk_controller = AndorSDK2Controller(args.dll_path)
        local_sdk_controller.initialize()
        print("SDK controller initialized")
    
    if args.mode == 'info':
        example_camera_info()
    elif args.mode == 'single':
        print("Running single shot example...")
        image = example_single_shot()
        if image is not None:
            print("Single shot capture successful!")
    elif args.mode == 'continuous':
        print("Running continuous acquisition example...")
        images = example_continuous_acquisition()
        if images is not None:
            print("Continuous acquisition successful!")
            
    # except Exception as e:
    #     print(f"Error during execution: {e}")
    #     sys.exit(1)
    
    # finally:
    # Cleanup
    if local_sdk_controller and local_sdk_controller._initialized:
        # try:
        local_sdk_controller.shutdown()
        print("SDK shutdown complete")
        # except:
        #     pass