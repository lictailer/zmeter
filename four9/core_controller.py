import requests
import json
from enum import Enum
from types import SimpleNamespace


class ThermometerStatus(int, Enum):
    """A code indicating the current status for a thermometer input on a Four9 Core Controller."""

    UNKNOWN = 0
    """Indicates the status is unknown"""

    OK = 1
    """Indicates the thermometer is connected and reading a valid temperature"""

    OFFLINE = 2
    """Indicates the controller for the thermometer is disconnected and offline"""

    DISABLED = 3
    """Indicates the thermometer input is disabled"""

    OUT_OF_RANGE = 4
    """Indicates the thermometer is measuring an out-of-range value"""

    OPEN_CIRCUIT = 5
    """Indicates the thermometer is disconnected and measuring an open circuit"""

    SHORT_CIRCUIT = 6
    """Indicates the thermometer is measuring a short circuit"""


class ThermometerInfo(object):
    """Information for a thermometer input of a Four9 Core Controller"""

    status : ThermometerStatus = ThermometerStatus.UNKNOWN
    """Indicates the current status of the thermometer"""

    temperature : float = float('nan')
    """Indicates the temperature measured by the thermometer. This will be not-a-number (NaN) if it is an invalid value."""


class HeaterStatus(int, Enum):
    """A code indicating the current status for a heater output on a Four9 Core Controller."""

    UNKNOWN = 0
    """Indicates the status is unknown"""

    OK = 1
    """Indicates the heater is configured and capable of applying power"""

    OFFLINE = 2
    """Indicates the controller for the heater is disconnected and offline"""

    DISABLED = 3
    """Indicates the heater output is disabled"""

    OPEN_CIRCUIT = 4
    """Indicates the heater is detecting an open circuit"""

    SHORT_CIRCUIT = 5
    """Indicates the heater is detecting a short circuit"""


class HeaterInfo(object):
    """Information for a heater output on a Four9 Core Controller"""

    status = HeaterStatus
    """Indicates the current status of the heater output"""

    power : float
    """Indicates the commanded power for the heater output"""

    readback_power : float
    """Indicates the measured power for the heater output"""

    target_temperature : float
    """Indicates the configured target temperature for the heater"""


class AnalogInputInfo(object):
    """Information for an analog input on a Four9 Core Controller"""

    enabled : bool
    """Indicates whether the input is enabled or disabled"""

    value : float
    """The value for the analog input"""

    voltage : float
    """The measured voltage on the analog input"""

    def __init__(self):
        self.enabled = False
        self.value = float(0)
        self.voltage = float(0)


class ControlOutputInfo(object):
    """Information for a control output on a Four9 Core Controller"""

    enabled : bool
    """Indicates whether the output is enabled or disabled"""

    state : bool
    """Indicates the current state of the output"""

    def __init__(self):
        self.enabled = False
        self.state = False


class SystemInfo(object):
    """Information that describes a remote Four9 Core Controller"""

    thermometers : list[ThermometerInfo]
    """Provides information for each of the individual thermometers within the system"""

    heaters : list[HeaterInfo]
    """Provides information for each of the individual heaters within the system"""

    analog_inputs : list[AnalogInputInfo]
    """Provides information for each of the analog inputs within the system"""

    control_outputs : list[ControlOutputInfo]
    """Provides information for each of the control outputs within the system"""

    def __init__(self):
        self.thermometers = []
        self.heaters = []
        self.analog_inputs = []
        self.control_outputs = []


class ServerError(RuntimeError):
    """An error that has occurred on the server."""


class ApiEndpoint(object):
    """An object that is accessed via a scripting API endpoint."""

    base_url = ''
    """The base URL to the scripting endpoint"""

    port = 0
    """The port number for the scripting endpoint"""

    def __init__(self, base_url: str, port: int):
        """Constructs a new scripting API endpoint for the given port and base URL.

        Args:
            base_url (str): The base URL for the endpoint
            port (int): The port number for the endpoint
        """
        self.base_url = base_url
        self.port = port


class CoreController(ApiEndpoint):
    """A remote Four9 Core Controller system that communicates via the scripting API"""

    DEFAULT_BASE_URL : str = 'http://localhost'
    """The default base URL, which defaults to the localhost"""

    DEFAULT_PORT : int = 4949
    """The default port number for the connection to the remote scripting API."""

    VERSION : int = 1
    """The supported version of the remote scripting API"""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, port: int = DEFAULT_PORT):
        """Constructs a remote core controller interface."""
        super(CoreController, self).__init__(base_url, port)

    def read_heater(self, index: int) -> HeaterInfo:
        """Reads and returns status information for the specified heater.

        Args:
            index (int): The zero-based index for the heater to be read.

        Returns:
            HeaterInfo: Information describing the current status of the given heater.
        """
        response = requests.get(url='{0}/heater?index={1}'.format(self.__get_base_url(), index))
        response.raise_for_status()
        obj = json.loads(response.text, object_hook=lambda d: SimpleNamespace(**d))
        return self.__parse_heater(obj)
     
    def read_thermometer(self, index: int) -> ThermometerInfo:
        """Reads and returns the status information for the specified thermometer.

        Args:
            index (int): The zero-based index for the thermometer to be read.

        Returns:
            ThermometerInfo: Information describing the current status of the given thermometer.
        """
        response = requests.get(url='{0}/thermometer?index={1}'.format(self.__get_base_url(), index))
        response.raise_for_status()
        obj = json.loads(response.text, object_hook=lambda d: SimpleNamespace(**d))
        return self.__parse_thermometer(obj)
    
    def read_system(self) -> SystemInfo:
        """Reads and returns the status information for the Core Controller system.

        Returns:
            SystemInfo: Information describing the current state of the system.
        """
        response = requests.get(url='{0}/system'.format(self.__get_base_url()))
        response.raise_for_status()
        obj = json.loads(response.text, object_hook=lambda d: SimpleNamespace(**d))
        return self.__parse_system(obj)

    def set_target_temperature(self, index: int, temperature: float) -> None:
        """Sets the target temperature for the specified heater.

        Args:
            index (int): The zero-based index for the heater to set its target temperature.
            temperature (float): The target temperature for the given heater.
        """
        response = requests.put(url='{0}/heater?index={1}&temperature={2}'.format(self.__get_base_url(), index, str(temperature)))
        response.raise_for_status()
        obj = json.loads(response.text, object_hook=lambda d: SimpleNamespace(**d))
        if obj.error:
            raise ServerError(obj.error)

    def set_heater_power(self, index: int, power: float) -> None:
        """Sets the power level for the specified heater output.

        Args:
            index (int): The zero-based index for the heater output to be set.
            power (float): The desired power, in watts, for the given heater.
        """
        response = requests.put(url='{0}/heater?index={1}&power={2}'.format(self.__get_base_url(), index, str(power)))
        response.raise_for_status()
        obj = json.loads(response.text, object_hook=lambda d: SimpleNamespace(**d))
        if obj.error:
            raise ServerError(obj.error)

    def set_heater_off(self, index: int) -> None:
        """Turns off the specified heater output.

        Args:
            index (int): The zero-based index for the heater output to be turned off.
        """
        response = requests.put(url='{0}/heater?index={1}&power=0'.format(self.__get_base_url(), index))
        response.raise_for_status()
        obj = json.loads(response.text, object_hook=lambda d: SimpleNamespace(**d))
        if obj.error:
            raise ServerError(obj.error)

    def set_all_heaters_off(self) -> None:
        """Turns off all of the heater outputs.
        """
        response = requests.put(url='{0}/heater?power=0'.format(self.__get_base_url()))
        response.raise_for_status()
        obj = json.loads(response.text, object_hook=lambda d: SimpleNamespace(**d))
        if obj.error:
            raise ServerError(obj.error)

    def set_control_output(self, index: int, state: bool) -> bool:
        """Sets the state of a control output.
 
        Args:
            index (int): The zero-based index for the control output to be set.
            state (bool): The new state for the given control output.

        Returns:
            bool: The current state of the control output.
        """
        response = requests.put(url='{0}/control?index={1}&state={2}'.format(self.__get_base_url(), index, str(state)))
        response.raise_for_status()
        obj = json.loads(response.text, object_hook=lambda d: SimpleNamespace(**d))
        if obj.error:
            raise ServerError(obj.error)
        if obj.state:
            return bool(obj.state)
        return False

    def get_warm_up_running(self) -> bool:
        """Reads and returns whether the warm up is currently running.

        Returns:
            bool: True if the warm up is running; otherwise False.
        """
        response = requests.get(url='{0}/warmup'.format(self.__get_base_url()))
        response.raise_for_status()
        obj = json.loads(response.text, object_hook=lambda d: SimpleNamespace(**d))
        return bool(obj.running)

    def start_warm_up(self) -> None:
        """Starts the system warm up process."""
        response = requests.put(url='{0}/warmup?action=start'.format(self.__get_base_url()))
        response.raise_for_status()
        obj = json.loads(response.text, object_hook=lambda d: SimpleNamespace(**d))
        if obj.error:
            raise ServerError(obj.error)

    def stop_warm_up(self) -> None:
        """Stops the system warm up process."""
        response = requests.put(url='{0}/warmup?action=stop'.format(self.__get_base_url()))
        response.raise_for_status()
        obj = json.loads(response.text, object_hook=lambda d: SimpleNamespace(**d))
        if obj.error:
            raise ServerError(obj.error)


    def start_recording(self, file: str='') -> str:
        """Starts a recording.

        Args:
            file (str, optional): The full path to the log file to be created. If a file is not 
            specified then the default will be generated.

        Returns:
            str: The full path of the recording file that has been started.
        """
        response = requests.put(url='{0}/recording?action=start&file={1}'.format(self.__get_base_url(), file))
        response.raise_for_status()
        obj = json.loads(response.text, object_hook=lambda d: SimpleNamespace(**d))
        if obj.error:
            raise ServerError(obj.error)
        return obj.file

    def stop_recording(self) -> None:
        """Stops any current recording."""
        response = requests.put(url='{0}/recording?action=stop'.format(self.__get_base_url()))
        response.raise_for_status()
        obj = json.loads(response.text, object_hook=lambda d: SimpleNamespace(**d))
        if obj.error:
            raise ServerError(obj.error)

    def __get_base_url(self) -> str:
        """Returns the URL for the scripting endpoint for this controller"""
        return '{0}:{1}/core-controller/v{2}'.format(self.base_url, self.port, self.VERSION)
    
    @staticmethod
    def __parse_heater(obj: any) -> HeaterInfo:
        heater = HeaterInfo()
        heater.status = HeaterStatus(obj.status)
        heater.power = obj.power
        heater.readback_power = obj.readbackPower
        heater.target_temperature = obj.targetTemperature
        return heater
    
    @staticmethod
    def __parse_thermometer(obj: any) -> ThermometerInfo:
        thermometer = ThermometerInfo()
        thermometer.status = ThermometerStatus(obj.status)
        thermometer.temperature = obj.temperature
        return thermometer

    @staticmethod
    def __parse_analog_input(obj: any) -> AnalogInputInfo:
        input = AnalogInputInfo()
        input.enabled = bool(obj.enabled)
        input.value = float(obj.value)
        input.voltage = float(obj.voltage)
        return input
    
    @staticmethod
    def __parse_control_output(obj: any) -> ControlOutputInfo:
        output = ControlOutputInfo()
        output.enabled = bool(obj.enabled)
        output.state = bool(obj.state)
        return output

    @staticmethod
    def __parse_system(obj: any) -> SystemInfo:
        system = SystemInfo()
        for h in obj.heaters:
            system.heaters.append(CoreController.__parse_heater(h))
        for t in obj.thermometers:
            system.thermometers.append(CoreController.__parse_thermometer(t))
        for a in obj.analogInputs:
            system.analog_inputs.append(CoreController.__parse_analog_input(a))
        for o in obj.controlOutputs:
            system.control_outputs.append(CoreController.__parse_control_output(o))
        return system