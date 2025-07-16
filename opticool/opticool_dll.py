import time
import opticool.opticool_dll_solve_olefail as opticool_dll_solve_olefail # to solve the ole initialize error.
import clr  # pythonnet required


dll = clr.AddReference(r"C:\QdOptiCool\LabVIEW\QDInstrument.dll")
time.sleep(1)

if __name__ == "__main__":
    from PyQt5 import QtWidgets
    import sys
    from scan import Scan
    a = sys.argv
    app = QtWidgets.QApplication(sys.argv)
    window = Scan()
    window.show()
    app.exec_()
