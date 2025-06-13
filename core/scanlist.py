import sys
import copy
import typing
from PyQt6.QtCore import QObject
import PyQt6.QtWidgets as QtWidgets
import PyQt6.QtCore as QtCore
import PyQt6.QtGui as QtGui
from PyQt6 import uic
from .scan import Scan


class ScanItem(QtWidgets.QLabel):
    sig_info_changed = QtCore.pyqtSignal(object)
    start = QtCore.pyqtSignal(object)
    stop = QtCore.pyqtSignal(object)

    def __init__(
        self,
        name=None,
        info=None,
        setter_equipment_info=None,
        main_window=None,
        getter_equipment_info=None,
    ):
        super().__init__()
        self.name = copy.deepcopy(name)
        self.main_window = main_window
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("border: 5px solid black;")
        self.info = copy.deepcopy(info)
        self.scan = Scan(
            name=name,
            info=self.info,
            setter_equipment_info=setter_equipment_info,
            main_window=self.main_window,
            getter_equipment_info=getter_equipment_info,
        )
        # self.scan.set_equipment_info(equipement_info)
        self.scan.sig_info_changed.connect(self.when_scan_info_changed)
        self.scan.start.connect(self.start_scan)
        self.scan.stop.connect(self.stop_scan)
        self.scan.emit()

    def when_scan_info_changed(self, info):
        self.setText(info["name"])
        self.info = info
        self.name = info["name"]
        
    def mouseMoveEvent(self, e):
        if e.buttons() == QtCore.Qt.MouseButton.LeftButton:
            drag = QtGui.QDrag(self)
            mime = QtCore.QMimeData()
            drag.setMimeData(mime)
            pixmap = QtGui.QPixmap(self.size())
            self.render(pixmap)
            drag.setPixmap(pixmap)
            drag.exec()

    def mouseDoubleClickEvent(self, e):
        self.scan.show()

    def start_scan(self, info):
        self.start.emit(info)

    def stop_scan(self):
        self.stop.emit(self)

    def start_queue(self):
        self.scan.start_scan()
        # while


class DeleteItem(QtWidgets.QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.resize(20, 20)
        self.setPixmap(QtGui.QPixmap("core/ui/bin.png").scaledToWidth(64))
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        e.accept()

    def dropEvent(self, e):
        widget = e.source()
        if isinstance(widget, ScanItem):
            print("ScanItem deleted")
            widget.deleteLater()
        elif isinstance(widget, ManualSetItem):
            print("ManualSetItem deleted")
            widget.deleteLater()
        e.accept()


class ManualSetItem(QtWidgets.QLineEdit):
    def __init__(self, text, main_window=None):
        super().__init__()
        self.setText(text)
        self.main_window = main_window

    def mouseMoveEvent(self, e):
        if e.buttons() == QtCore.Qt.MouseButton.LeftButton:
            drag = QtGui.QDrag(self)
            mime = QtCore.QMimeData()
            drag.setMimeData(mime)
            pixmap = QtGui.QPixmap(self.size())
            self.render(pixmap)
            drag.setPixmap(pixmap)
            drag.exec()

    def convert_text_to_dict_list(self, text):
        mappings = text.split(",")
        dict_list = []
        for mapping in mappings:
            temp, value = mapping.split("->")
            value = float(value)
            key = temp.strip()
            dict_list.append({key: value})

        return dict_list

    def start_queue(self):
        text = self.text()
        manual_set_items = self.convert_text_to_dict_list(text)
        for setting_dict in manual_set_items:
            for key, value in setting_dict.items():
                self.main_window.write_info(value, key)

        # print(f"action: {text}")


class ScanListWidget(QtWidgets.QWidget):

    def __init__(
        self,
        allow_swap=True,
        allow_add=True,
        info=None,
        setter_equipment_info=None,
        getter_equipment_info=None,
    ):
        super().__init__()
        self.setAcceptDrops(True)
        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        self.allow_swap = allow_swap
        self.allow_add = allow_add
        self.setter_equipment_info = setter_equipment_info
        self.getter_equipment_info = getter_equipment_info

    def setter_equipment_info_updated(self, info):
        for i in range(self.layout.count()):
            item = self.layout.itemAt(i).widget()
            if type(item) == ScanItem:
                print("hellow")
                item.scan.when_setter_equipment_info_change(info)

    def dragEnterEvent(self, e):
        e.accept()

    def dropEvent(self, e):
        widget = e.source()
        pos = e.position()
        self_swap = False

        i = 0
        for i in range(self.layout.count()):
            if widget == self.layout.itemAt(i).widget():
                self_swap = True
                break
        swap_originID = i
        if self_swap and (not self.allow_swap):
            return

        seperates = []
        for i in range(self.layout.count()):
            w = self.layout.itemAt(i).widget()
            seperates.append(w.y() + w.height() / 2)

        def find_index(y, ys):
            if ys == []:
                return 0
            if y < ys[0]:
                return 0
            if y > ys[-1]:
                return len(ys)
            for i in range(len(ys) - 1):
                if ys[i] <= y and y <= ys[i + 1]:
                    return i + 1

        i = find_index(pos.y(), seperates)
        if self_swap:
            if swap_originID < i:
                self.layout.insertWidget(i - 1, widget)
            else:
                self.layout.insertWidget(i, widget)
        else:
            if not self.allow_add:
                return
            if type(widget) == ScanItem:
                plot_setting_info = copy.deepcopy(widget.scan.info)
                name = copy.deepcopy(widget.name)
                main_window = widget.main_window
                self.layout.insertWidget(
                    i,
                    ScanItem(
                        name=name,
                        info=plot_setting_info,
                        setter_equipment_info=self.setter_equipment_info,
                        main_window=main_window,
                        getter_equipment_info=self.getter_equipment_info,
                    ),
                )
            elif type(widget) == ManualSetItem:
                main_window = widget.main_window
                self.layout.insertWidget(
                    i, ManualSetItem(widget.text(), main_window=main_window)
                )
        e.accept()

    def get_widgets(self):
        ans = []
        for i in range(self.layout.count()):
            ans.append(self.layout.itemAt(i).widget())
        return ans

    def add_item(self, item):
        self.layout.addWidget(item)

    def get_item_names(self):
        names = []
        for n in range(self.layout.count()):
            w = self.layout.itemAt(n).widget()
            names.append(w.name)
        return names


class ScanListLogic(QtCore.QThread):
    sig_scan_done = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.workers = []

    def run(self):
        while len(self.workers):
            w = self.workers[0]
            self.workers.remove(w)
            w.start_queue()
            self.sig_scan_done.emit(w)


class ScanList(QtWidgets.QWidget):
    sig_info_changed = QtCore.pyqtSignal(object)
    start = QtCore.pyqtSignal(object)
    stop = QtCore.pyqtSignal(object)

    def __init__(
        self,
        info=None,
        setter_equipment_info=None,
        main_window=None,
        getter_equipment_info=None,
    ):
        super().__init__()
        uic.loadUi(r"core/ui/scanlist.ui", self)
        self.info = info
        self.setter_equipment_info = setter_equipment_info
        self.getter_equipment_info = getter_equipment_info
        self.logic = ScanListLogic()
        self.main_window = main_window

        self.list_available = ScanListWidget(
            info=self.info,
            setter_equipment_info=self.setter_equipment_info,
            getter_equipment_info=self.getter_equipment_info,
        )
        for n, l in enumerate(["A", "B", "C", "D"]):
            si = ScanItem(
                name=l,
                info=self.info,
                setter_equipment_info=self.setter_equipment_info,
                main_window=self.main_window,
                getter_equipment_info=self.getter_equipment_info,
            )
            self.list_available.add_item(si)
            si.start.connect(self.start_scan)
            si.stop.connect(self.stop_scan)

        self.list_queue = ScanListWidget(
            info=self.info,
            setter_equipment_info=self.setter_equipment_info,
            getter_equipment_info=self.getter_equipment_info,
        )
        for n, l in enumerate(["1", "2", "3"]):
            si = ScanItem(
                name=l,
                info=self.info,
                setter_equipment_info=self.setter_equipment_info,
                main_window=self.main_window,
                getter_equipment_info=self.getter_equipment_info,
            )
            self.list_queue.add_item(si)
            si.start.connect(self.start_scan)
            si.stop.connect(self.stop_scan)

        self.list_manual = ScanListWidget()
        self.list_manual.add_item(
            ManualSetItem("dummy->0", main_window=self.main_window)
        )
        self.list_manual.add_item(
            ManualSetItem("Keithley_0_sour_volt_to_rampmode->0", main_window=self.main_window)
        )
        self.list_manual.add_item(
            ManualSetItem("Keithley_1_sour_volt_to_rampmode->0", main_window=self.main_window)
        )

        self.list_past = ScanListWidget(allow_swap=False, allow_add=False)

        self.scrollArea_available.setWidget(self.list_available)
        self.scrollArea_queue.setWidget(self.list_queue)
        self.scrollArea_action.setWidget(self.list_manual)
        self.scrollArea_past.setWidget(self.list_past)
        self.Layout_delete.insertWidget(0, DeleteItem())

        self.pushButton.clicked.connect(self.start_queue)
        self.pushButton_2.clicked.connect(self.check)
        self.pushButton_clear_past.clicked.connect(self.clear_past)
        self.logic.sig_scan_done.connect(self.add_to_past_scans)
        self.pb_new_scan.clicked.connect(self.add_empty_scan_item)
        self.pb_new_manual.clicked.connect(self.add_empty_manual_set_item)

    def start_scan(self, info):
        self.start.emit(info)

    def stop_scan(self, scan):
        self.stop.emit(scan)

    def setter_equipment_info_updated(self, info):
        self.setter_equipment_info = info
        self.list_available.setter_equipment_info_updated(self.setter_equipment_info)
        self.list_queue.setter_equipment_info_updated(self.setter_equipment_info)

    def start_queue(self):
        queues = []
        for w in self.list_queue.get_widgets():
            queues.append(w)
        self.logic.workers = queues
        self.logic.start()

    def check(self):
        for i, w in enumerate(self.list_queue.get_widgets()):
            print(i, hex(id(w)), w.scan.info, hex(id(w.scan)), w.text())

    def add_to_past_scans(self, w):
        self.list_past.layout.addWidget(w)

    def clear_past(self):
        for i, w in enumerate(self.list_past.get_widgets()):
            self.list_past.layout.removeWidget(w)
            w.deleteLater()

    def add_empty_scan_item(self):
        si = ScanItem(
            name="empty",
            info=self.info,
            setter_equipment_info=self.setter_equipment_info,
            main_window=self.main_window,
            getter_equipment_info=self.getter_equipment_info,
        )
        self.list_available.add_item(si)
        # self.available_info.append(si.info)

    def add_empty_manual_set_item(self):
        self.list_manual.add_item(
            ManualSetItem("dummy->0", main_window=self.main_window)
        )
        


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = ScanList()
    window.show()
    app.exec()
