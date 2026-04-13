# 
# This is an example that demonstrates how to read all of the system values from a Four9 Core Controller and log them
# to a CSV file.
#

import argparse
import csv
import math
import os
import time
from core_controller import *
from datetime import datetime


def main() -> None:

    parser = argparse.ArgumentParser(description='Creates and records a log file of data from a remote Four9 Core Controller')
    parser.add_argument('--fname', type=str, help='The filename for the CSV log file to be created')
    args = parser.parse_args()


    # default or custom file name
    path = 'example.csv'
    if args.fname:
        path = args.fname

    # format the file path
    path = os.path.abspath(path)

    # remote core controller
    controller = CoreController()

    # create a CSV log file
    with open(path, 'w', newline='') as file:
        print('Log file: {0}'.format(path))

        # write the column headers
        writer = csv.writer(file)
        writer.writerow(get_column_headers())

        try:
            while True:

                # read the core controller system info
                info = controller.read_system()

                # create a new row for the CSV file
                row = [get_time_string()]

                # append values, 6-temperatures, 6-heater powers, 2-analog inputs, and 3-control outputs
                for thermometer in info.thermometers:
                    row.append(get_value_string(thermometer.temperature))
                for heater in info.heaters:
                    row.append(get_value_string(heater.power))
                for analog in info.analog_inputs:
                    row.append(get_value_string(analog.value))
                for output in info.control_outputs:
                    row.append('{0}'.format('1' if output.state else '0') if output.enabled else '')

                # write the row to file
                writer.writerow(row)

                # record a sample every second
                time.sleep(1)

        except KeyboardInterrupt:
            pass # user cancelled
        except Exception as exc:
            print('Exception: {0}'.format(exc))


def get_value_string(value: float, precision: int=3) -> str:
    """Returns the string representation for the specified value. If the value
    is not-a-number (NaN), it will return an empty string.

    Args:
        value (float): The value.
        precision (int, optional): The digits of precision. Defaults to 3.
    """
    if math.isnan(value):
        return ''
    return '{{0:.{0}f}}'.format(precision).format(value)


def get_time_string() -> str:
    """Returns the current time formatted into a string.
    """
    t = datetime.now()
    return '{0:02}:{1:02}:{2:02}.{3:03.0f}'.format(t.hour, t.minute, t.second, (t.microsecond / 1000) % 1000)


def get_column_headers() -> list:
    """Returns the column headers for the CSV file.
    """
    headers = ['Time']
    for i in range(0,6):
        headers.append('Temperature {0}'.format(i+1))
    for i in range(0,6):
        headers.append('Heater {0}'.format(i+1))
    for i in range(0,2):
        headers.append('Analog {0}'.format(i+1))
    for i in range(0,3):
        headers.append('Control {0}'.format(i+1))
    return headers


if __name__ == '__main__':
    main()
