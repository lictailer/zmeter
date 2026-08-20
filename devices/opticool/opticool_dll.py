"""Lazy acquisition of the fixed OptiCool vendor runtime.

Importing the device package must remain safe on computers without pythonnet or
the Quantum Design installation.  The Connect worker calls
``load_vendor_runtime`` for each attempt until the complete load succeeds.
"""

from importlib import import_module
import time


VENDOR_DLL_PATH = r"C:\QdOptiCool\LabVIEW\QDInstrument.dll"


def load_vendor_runtime():
    # Keep the existing initialization ordering and one-second vendor delay,
    # but perform both inside the device worker instead of module import.
    from . import opticool_dll_solve_olefail  # noqa: F401

    clr = import_module("clr")
    dll = clr.AddReference(VENDOR_DLL_PATH)
    time.sleep(1)
    quantum_design = import_module("QuantumDesign")
    system = import_module("System")
    return dll, quantum_design, system

if __name__ == "__main__":
    from PyQt5 import QtWidgets
    import sys
    from scan import Scan
    a = sys.argv
    app = QtWidgets.QApplication(sys.argv)
    window = Scan()
    window.show()
    app.exec_()
