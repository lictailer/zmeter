# 
# This is an example that demonstrates how to start a warm up on a Four9 Core Controller.
#

from core_controller import *

def main() -> None:

    controller = CoreController()

    # query if a warm up is already running
    running = controller.get_warm_up_running()
    if running:
        print('Warm up is already running')
        return

    # start the warm up
    controller.start_warm_up()
    print('Warm up started')

if __name__ == '__main__':
    main()