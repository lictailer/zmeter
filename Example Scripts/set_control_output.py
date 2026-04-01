# 
# This is an example that demonstrates how to set the control output states on a Four9 Core Controller.
#

import argparse
from core_controller import *

def main() -> None:

    parser = argparse.ArgumentParser(description='Sets a control output on a remote Four9 Core Controller')
    parser.add_argument('index', type=int, help='The zero-based index of the control output to be set')
    parser.add_argument('--on', action='store_true', dest='state', default=False, help='Sets the control output ON')
    parser.add_argument('--off', action='store_false', dest='state', help='Sets the control output OFF')
    args = parser.parse_args()

    controller = CoreController()

    print('Set control output {0} = {1}'.format(args.index, 'on' if args.state else 'off'))
    controller.set_control_output(args.index, args.state)


if __name__ == '__main__':
    main()
