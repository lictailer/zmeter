# 
# This is an example that demonstrates how to turn off all heater outputs on a Four9 Core Controller.
#

from core_controller import *

def main() -> None:

    controller = CoreController()
    controller.set_all_heaters_off()

if __name__ == '__main__':
    main()
