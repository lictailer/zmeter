from nidaq_core.nidaq import NIDAQ
from PyQt6 import QtWidgets, uic, QtCore
import sys

app = QtWidgets.QApplication(sys.argv)
window = NIDAQ()
window.logic.initialize("Dev1")
window.show()
app.exec()
