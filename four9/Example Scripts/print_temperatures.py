# 
# This is an example that demonstrates how to read and display the temperature values from a Four9 Core Controller.
#

import math
import time
from core_controller import *
from datetime import datetime

def main() -> None:

    try:

        controller = CoreController()

        while True:
            # read the current system data
            system = controller.read_system()

            # print the temperatures
            line = '{0}: '.format(get_time_string())
            for thermometer in system.thermometers:
                if math.isnan(thermometer.temperature):
                    line += '         '
                else:
                    line += ' {} '.format(thermometer.temperature)

            print(line)
            time.sleep(0.05)

    except KeyboardInterrupt:
        pass # user cancelled
    except Exception as exc:
        print('Exception: {0}'.format(exc))


def get_time_string() -> str:
    """Returns the current time formatted into a string."""
    t = datetime.now()
    return '{0:02}:{1:02}:{2:02}.{3:03.0f}'.format(t.hour, t.minute, t.second, (t.microsecond / 1000) % 1000)


if __name__ == '__main__':
    main()
