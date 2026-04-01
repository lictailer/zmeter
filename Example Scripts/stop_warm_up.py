# 
# This is an example that demonstrates how to stop a warm up on a Four9 Core Controller.
#

from core_controller import *

def main() -> None:

    controller = CoreController()

    # query if a warm up is already running
    running = controller.get_warm_up_running()
    if not running:
        print('Warm up is not running')
        return

    controller.stop_warm_up()
    print('Warm up stopped')

if __name__ == '__main__':
    main()
