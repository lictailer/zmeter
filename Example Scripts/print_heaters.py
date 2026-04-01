# 
# This is an example that demonstrates how to read and display the heater power values from a Four9 Core Controller.
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

            # print the heater power levels
            line = '{0}: '.format(get_time_string())
            for heater in system.heaters:
                if math.isnan(heater.power):
                    line += '        '
                else:
                    line += ' {0:6.3f} '.format(heater.power)

            print(line)
            time.sleep(1)

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
