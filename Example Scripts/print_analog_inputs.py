# 
# This is an example that demonstrates how to read and display the analog input values from a Four9 Core Controller.
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

            # print the analog inputs
            line = '{0}: '.format(get_time_string())
            for input in system.analog_inputs:
                if math.isnan(input.value):
                    line += '        '
                elif abs(input.value) < 0.001:
                    line += ' {0:6.2E} '.format(input.value)
                else:
                    line += ' {0:6.3f} '.format(input.value)

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
