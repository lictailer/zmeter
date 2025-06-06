from nested_menu import NestedMenu
from scan_info import *


class LinearSetting(QtWidgets.QWidget):
    sig_info_changed = QtCore.pyqtSignal(object)

    def __init__(self, info=None):
        super(LinearSetting, self).__init__()
        uic.loadUi("ui/linear_setting.ui", self)
        if info == None:
            self.info = copy.deepcopy(ScanInfo['levels']['level0']['setters']['setter0']["linear_setting"])
        else:
            self.info = info
        self.widgets = [self.start_le, self.end_le, self.step_le, self.mid_le, self.span_le, self.points_le,]
        self.set_info(self.info)
        self.start_le.editingFinished.connect(self.when_start_editingFinished)
        self.end_le.editingFinished.connect(self.when_end_editingFinished)
        self.step_le.editingFinished.connect(self.when_step_editingFinished)
        self.mid_le.editingFinished.connect(self.when_mid_editingFinished)
        self.span_le.editingFinished.connect(self.when_span_editingFinished)
        self.points_le.editingFinished.connect(self.when_points_textEdited)

    def set_info(self, info):
        self.info = info
        self.update_ui()

    def when_start_editingFinished(self):
        if not is_float(self.start_le.text()):
            return
        self.info['start'] = float(self.start_le.text())
        self.info['mid'] = (self.info['start']+self.info['end'])/2
        self.info['span'] = self.info['end']-self.info['start']
        self.info['step'] = self.info['span']/(self.info['points']-1)
        self.update_ui()

    def when_end_editingFinished(self):
        if not is_float(self.end_le.text()):
            return
        self.info['end'] = float(self.end_le.text())
        self.info['mid'] = (self.info['start']+self.info['end'])/2
        self.info['span'] = self.info['end']-self.info['start']
        self.info['step'] = self.info['span']/(self.info['points']-1)
        self.update_ui()

    def when_step_editingFinished(self):
        if not is_float(self.step_le.text()):
            return
        self.info['step'] = float(self.step_le.text())
        self.info['points'] = round(self.info['span']/self.info['step']+1)
        self.info['step'] = self.info['span']/(self.info['points']-1)
        self.update_ui()

    def when_mid_editingFinished(self):
        if not is_float(self.mid_le.text()):
            return
        self.info['mid'] = float(self.mid_le.text())
        self.info['start'] = self.info['mid']-self.info['span']/2
        self.info['end'] = self.info['mid']+self.info['span']/2
        self.update_ui()

    def when_span_editingFinished(self):
        if not is_float(self.span_le.text()):
            return
        self.info['span'] = float(self.span_le.text())
        self.info['start'] = self.info['mid']-self.info['span']/2
        self.info['end'] = self.info['mid']+self.info['span']/2
        self.info['step'] = self.info['span']/(self.info['points']-1)
        self.update_ui()

    def when_points_textEdited(self):
        if not is_float(self.points_le.text()):
            return
        num = int(self.points_le.text())
        if num < 1:
            return
        self.info['points'] = num
        if num != 1:
            self.info['step'] = self.info['span']/(self.info['points']-1)
        else:
            self.info['step'] = 0
        self.update_ui()

    def update_ui(self):
        for w in self.widgets:
            w.blockSignals(True)
        self.start_le.setText(str(self.info['start']))
        self.end_le.setText(str(self.info['end']))
        self.step_le.setText(str(self.info['step']))
        self.mid_le.setText(str(self.info['mid']))
        self.span_le.setText(str(self.info['span']))
        self.points_le.setText(str(self.info['points']))
        for w in self.widgets:
            w.blockSignals(False)
        self.info['destinations'] = np.linspace(self.info['start'], self.info['end'], self.info['points'])
        self.sig_info_changed.emit(self.info)
        # print(self.info['destinations'])


# if __name__ == "__main__":
#     app = QtWidgets.QApplication(sys.argv)
#     info = {
#         'start': 0,
#         'end': 1,
#         'step': 0.25,
#         'mid': 0.5,
#         'span': 1,
#         'points': 5,
#         'destinations': [0, 0.25, 0.5, 0.75, 1]}
#     window = LinearSetting()
#     # window.set_info(info)
#     window.show()
#     app.exec()


class ExplicitSetting(QtWidgets.QWidget):
    sig_info_changed = QtCore.pyqtSignal(object)

    def __init__(self, info=None):
        super(ExplicitSetting, self).__init__()
        uic.loadUi("ui/explicit_setting.ui", self)
        if info == None:
            self.info = copy.deepcopy(ScanInfo['levels']['level0']['setters']['setter0']['explicit_setting'])
        else:
            self.info = info
        self.update_ui()
        self.textEdit.textChanged.connect(self.when_explicit_input_changed)

    def set_info(self, info):
        self.info = info
        self.update_ui()

    def update_ui(self):
        self.textEdit.blockSignals(True)
        text = ''
        for d in self.info:
            text += f"{d}, "
        text = text[0:-2]
        self.textEdit.setText(text)
        self.textEdit.blockSignals(False)

    def csv_text_to_array(self, text):
        try:
            f = list(filter(None, text.split(',')))
            l = list(map(float, f))
            return np.array(l)
        except:
            print(f"cannot convert {text} to numpy array")
            return np.array([])

    def when_explicit_input_changed(self):
        text = self.textEdit.toPlainText()
        self.info = self.csv_text_to_array(text)
        self.sig_info_changed.emit(self.info)


# if __name__ == "__main__":
#     app = QtWidgets.QApplication(sys.argv)
#     window = ExplicitSetting()
#     info = [1, 2, 3, 1, 2, 3, 1, 2, 3]
#     window.set_info(info)
#     window.show()
#     app.exec()


class IndividualSetter(QtWidgets.QWidget):
    sig_self_changed = QtCore.pyqtSignal(object)

    def __init__(self, info=None,setter_equipment_info=None):
        super(IndividualSetter, self).__init__()
        uic.loadUi("ui/individual_setter.ui", self)
        self.equipment_info=setter_equipment_info
        self.linear_setting = LinearSetting()
        self.explicit_setting = ExplicitSetting()
        self.nested_menu = NestedMenu()
        self.verticalLayout.insertWidget(0, self.nested_menu)
        self.layout().addWidget(self.linear_setting)
        self.layout().addWidget(self.explicit_setting)
        if info == None:
            self.info = copy.deepcopy(ScanInfo['levels']['level0']['setters']['setter0'])
        else:
            self.info = info
        self.update_ui()
        self.explicit_cb.stateChanged.connect(self.when_explicit_cb_state_changed)
        self.linear_setting.sig_info_changed.connect(self.when_linear_setting_changed)
        self.explicit_setting.sig_info_changed.connect(self.when_explicit_setting_changed)
        self.nested_menu.sig_self_changed.connect(self.when_nested_men_changed)
        self.set_setter_equipment_info(self.equipment_info)

    def set_setter_equipment_info(self,equipment_info):
        self.nested_menu.set_choices(equipment_info)

    def set_info(self, info: dict):
        self.info = info
        self.update_ui()

    def update_ui(self):
        self.nested_menu.set_chosen_one(self.info['channel'])
        self.explicit_cb.setChecked(self.info['explicit'])
        self.explicit_setting.set_info(self.info["explicit_setting"])
        self.when_explicit_cb_state_changed(self.info['explicit'])
        self.linear_setting.set_info(self.info["linear_setting"])
        

    def when_explicit_cb_state_changed(self, state):
        self.info['explicit'] = state
        if state:
            self.linear_setting.hide()
            self.explicit_setting.show()
            self.info['destinations'] = self.explicit_setting.info
        else:
            self.explicit_setting.hide()
            self.linear_setting.show()
            self.info['destinations'] = self.linear_setting.info['destinations']
        self.sig_self_changed.emit(self)

    def when_linear_setting_changed(self, info):
        self.info['linear_setting'] = info
        self.sig_self_changed.emit(self)

    def when_explicit_setting_changed(self, info):
        self.info['explicit_setting'] = info
        self.info['destinations'] = self.explicit_setting.info
        self.sig_self_changed.emit(self)

    def when_nested_men_changed(self, widget):
        self.info['channel'] = widget.name
        self.sig_self_changed.emit(self)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    info = ScanInfo['levels']['level0']['setters']['setter1']
    window = IndividualSetter()
    window.set_info(info)
    window.show()
    app.exec()
