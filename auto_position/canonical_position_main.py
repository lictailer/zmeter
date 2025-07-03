from PyQt5 import QtWidgets, uic
import canonical_position_logic as logic
from nidaq_hardware import NIDAQHardWare

class auto_position_app(QtWidgets.QWidget):
    def __init__(self,daq):
        super(auto_position_app, self).__init__()
        # Load the .ui created in Qt Designer
        uic.loadUi('auto_position_GUI.ui', self)
        self.daq = daq
        self.RESULTS_DIR = None
        # set their text to the defaults in logic.py
        self.lineGalvoX.setText(logic.GALVO_X)
        self.lineGalvoY.setText(logic.GALVO_Y)
        self.linePD.setText(logic.PD_IN)

        # Widgets are loaded directly as attributes by uic.loadUi
        self.button_auto_position.clicked.connect(self.start_auto_position)

    def start_auto_position(self):
        # Override logic parameters with user inputs
        logic.GALVO_X = self.lineGalvoX.text()
        logic.GALVO_Y = self.lineGalvoY.text()
        logic.PD_IN   = self.linePD.text()

        logic.X_CENTER   = self.spinXCenter.value()
        logic.Y_CENTER   = self.spinYCenter.value()
        logic.X_RANGE    = self.spinXRange.value()
        logic.Y_RANGE    = self.spinYRange.value()
        logic.X_PTS      = int(self.spinXPts.value())
        logic.Y_PTS      = int(self.spinYPts.value())

        logic.X0         = self.spinX0.value()
        logic.Y0         = self.spinY0.value()
        logic.UPSAMPLE   = int(self.spinUpsample.value())

        # Optionally let user override results folder
        rd = self.textResultsDir.toPlainText().strip()
        if rd:
            self.RESULTS_DIR = rd

        # Call the core logic
        ap = logic.AutoPositionSystem(self.daq)
        print("Starting autopositioning…")
        logic.auto_positon(ap,save_dir=self.RESULTS_DIR)

if __name__ == '__main__':
    import sys
    app = QtWidgets.QApplication(sys.argv)
    daq = NIDAQHardWare()
    w = auto_position_app(daq)
    w.show()
    sys.exit(app.exec_())
