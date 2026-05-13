from PyQt6 import QtWidgets, uic


class ScanRangeWindow(QtWidgets.QWidget):
    def __init__(self, limits_path="", on_reload_clicked=None, parent=None):
        super().__init__(parent)
        uic.loadUi("core/ui/scan_range.ui", self)
        self.setWindowTitle("Scan Range")
        self.set_limits_path(limits_path)
        self.set_status("Ready")

        if callable(on_reload_clicked):
            self.reload_button.clicked.connect(on_reload_clicked)

    def set_limits_path(self, path):
        self.limits_path_label.setText(str(path))

    def set_status(self, status):
        self.status_label.setText(str(status))
