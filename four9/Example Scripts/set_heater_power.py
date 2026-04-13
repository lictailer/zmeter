# 
# This is an example that demonstrates how to set the heater output power on a Four9 Core Controller.
#

import argparse
from core_controller import *

def main() -> None:

    parser = argparse.ArgumentParser(description='Sets a heater output power on a remote Four9 Core Controller')
    parser.add_argument('index', type=int, help='The zero-based index of the heater output to be set')
    parser.add_argument('power', type=float, default=0, help='The heater power')
    args = parser.parse_args()

    controller = CoreController()

    print('Set heater {0} = {1:.3f}'.format(args.index, args.power))
    controller.set_heater_power(args.index, args.power)


if __name__ == '__main__':
    main()
