# 
# This is an example that demonstrates how to set the target temperature on a Four9 Core Controller.
#

import argparse
from core_controller import *

def main() -> None:

    parser = argparse.ArgumentParser(description='Sets the target temperature on a remote Four9 Core Controller')
    parser.add_argument('index', type=int, help='The zero-based index of the heater to set the target temperature')
    parser.add_argument('temperature', type=float, default=0, help='The target temperature for the specified heater')
    args = parser.parse_args()

    controller = CoreController()

    print('Set target temperature {0} = {1:.3f}'.format(args.index, args.temperature))
    controller.set_target_temperature(args.index, args.temperature)


if __name__ == '__main__':
    main()
