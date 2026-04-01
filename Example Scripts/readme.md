# Four9 Core Controller - Script Interface
*Updated 02/17/2025*

This document provides information about the scripting interface that is supported by the Four9 Core Controller
software application.


## Configuration
The configuration for the scripting interface can be accessed within the Core Controller software by selecting 
Tools -> Scripting... from within the main menu. The configuration can also be accessed by clicking the 'Scripting' 
button in the bottom right corner of the application's status bar.

The scripting interface communicates via an HTTP interface over a specific URL. The scripting interface URL must be 
reserved within the host Windows OS before the application can use it.

From within the Scripting Configuration window, click the 'RESERVE' button to reserve the scripting URL for the 
specified port. The default port is 5000. The port can be any number, but the python scripts must match the port that 
is used by the Core Controller software. Use the 'RELEASE' button to remove and release the reservation.

Note, reserving and releasing of the port/URL requires administrator privileges on the PC, so Windows will prompt for
access to complete the requested action.

Use the toggle switch within the configuration window to enable or disable the scripting interface.


## Web Browser Support
Once enabled and running, the scripting interface can be accessed via a web browser. For example, the system 
information can be queried at the following URL: http://localhost:5000/core-controller/v1/system
- where '5000' is the port,
- where 'v1' is the scripting API version


## Python Installation Requirements
The example scripts are written in python. Python will need to be installed on the machine that will be running the
scripts.

### Dependencies
The python scripts require the "requests" package to be installed. See https://docs.python-requests.org
The requests package can be installed using pip as follows:

    python -m pip install requests

see https://docs.python-requests.org/en/latest/user/install/ for more info on installation of requests.


## Example Python Scripts
Once the scripting interface is enabled and running in the Core Controller software, the example scripts can be 
executed. The following example scripts are provided in this installation.

    log_csv.py                  : Continually reads and logs the values for the system to a CSV formatted file
    print_analog_inputs.py      : Continually displays the analog input values for the system
    print_control_outputs.py    : Continually displays the control output states for the system
    print_heaters.py            : Continually displays the heater output power levels for the system
    print_temperatures.py       : Continually displays the thermometer temperature values for the system
    set_all_heaters_off.py      : Sets all of the heater outputs to off (zero power output)
    set_control_output.py       : Sets a control output to the specified state
    set_heater_power.py         : Sets a heater output to the specified power level
    set_target_temperature.py   : Sets a heater to the specified target temperature
    start_warm_up.py            : Starts the warm up process
    stop_warm_up.py             : Stops the warm up process

An example script can be ran as follows:

```
    python .\print_temperatures.py
```

## Running Scripts from Remote PC
The python scripts can be ran from a separate remote PC other than the PC running the Four9 Core Controller software.

By default, the Windows firewall will block the incoming requests on the PC running the Four9 Core Controller software.
Turn on the "Allow External Access" option within the Scripting configuration window of the software to allow the
incoming requests on the configured port.

Update the Python script to specify the base URL for how to reach the remote PC. The `CoreController` class will 
default to a localhost URL which is for running the scripts on the same machine that is running the Core Controller 
software. The example below shows how to define the remote machine by IP address (192.168.1.10).

```python
# provide the remote IP address within the constructor
controller = CoreController('http:\\192.168.1.10')

# or, specify the remote address after construction
controller.base_url = 'http:\\192.168.1.10'
```