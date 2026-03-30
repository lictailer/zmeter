from .scan_info import *
from .individual_setter import IndividualSetter
from .nested_menu import NestedMenu


class IndividualLevel(QtWidgets.QWidget):
    sig_info_changed = QtCore.pyqtSignal(object)

    def __init__(self, individual_level_info=None,setter_equipment_info=None,getter_equipment_info=None):
        super(IndividualLevel, self).__init__()
        uic.loadUi("core/ui/individual_level.ui", self)
        self.setter_equipment_info = setter_equipment_info
        self.getter_equipment_info = getter_equipment_info
        self.set_record_equipment_info()
        self.set_manual_set_channel_menu()
        self.horizontalLayout.insertWidget(0, self.getter_nested_menu)
        if hasattr(self, "label_3"):
            self.label_3.hide()
        self.manual_set_channel_layout.insertWidget(0, self.manual_set_menu)
        self.set_setter_equipment_info(self.setter_equipment_info)

        self.record = []
        if individual_level_info == None:
            self.set_info(copy.deepcopy(ScanInfo['levels']['level1']))
        else:
            self.set_info(individual_level_info)

        self.master_add_one_pb.clicked.connect(self.when_add_clicked)
        self.master_delete_one_pb.clicked.connect(self.delete_master)
        self.record_clean_pb.clicked.connect(self.when_clean_clicked)
        self.manual_set_before_add_pb.clicked.connect(self.when_add_manual_set_before_clicked)
        self.manual_set_after_add_pb.clicked.connect(self.when_add_manual_set_after_clicked)
        self.manual_set_before_remove_last_pb.clicked.connect(self.when_remove_last_manual_set_before_clicked)
        self.manual_set_after_remove_last_pb.clicked.connect(self.when_remove_last_manual_set_after_clicked)
        self.manual_set_clear_all_pb.clicked.connect(self.when_clear_all_manual_set_clicked)
        self.settle_time_spinbox.valueChanged.connect(self.when_settle_time_changed)
        
    def set_record_equipment_info(self):
        self.getter_nested_menu = NestedMenu()
        self.getter_nested_menu.label.hide()
        self.getter_nested_menu.set_choices(self.getter_equipment_info)
        self.getter_nested_menu.sig_self_changed.connect(self.when_combobox_changed)

    def set_manual_set_channel_menu(self):
        self.manual_set_menu = NestedMenu()
        self.manual_set_menu.set_choices(self.setter_equipment_info)

    def set_info(self, info,):
        if 'settle_time' not in info:
            info['settle_time'] = 0.0
        if 'manual_set_before' not in info:
            info['manual_set_before'] = []
        if 'manual_set_after' not in info:
            info['manual_set_after'] = []
        self.individual_level_info = info
        self.update_ui()

    def set_setter_equipment_info(self, setter_equipment_info):
        self.setter_equipment_info = setter_equipment_info
        self.manual_set_menu.set_choices(self.setter_equipment_info)
        
        for i in range(self.verticalLayout.count()):
            item = self.verticalLayout.itemAt(i).widget()
            if type(item) == IndividualSetter:
                item.set_setter_equipment_info(setter_equipment_info)

    def set_getter_equipment_info(self, getter_equipment_info):
        self.getter_equipment_info = getter_equipment_info
        self.getter_nested_menu.set_choices(self.getter_equipment_info)
    
    def update_ui(self):
        clearLayout(self.verticalLayout)
        for setter in self.individual_level_info['setters']:
            self.add_master(info=self.individual_level_info['setters'][setter])
        self._refresh_record_label()
        # self.individual_level_info['setting_array']=self.get_setting_array(personalized_method=False)

        self.setting_method_le.blockSignals(True)
        self.setting_method_le.setText(self.individual_level_info.get('setting_method', ''))
        self.setting_method_le.blockSignals(False)

        if self.individual_level_info['setting_method'] == '':
            self.enable_setting_method_checkBox.setChecked(False)
        else:
            self.enable_setting_method_checkBox.setChecked(True)

        self.settle_time_spinbox.blockSignals(True)
        self.settle_time_spinbox.setValue(float(self.individual_level_info['settle_time']))
        self.settle_time_spinbox.blockSignals(False)
        self.update_manual_set_labels()
            
        self.sig_info_changed.emit([self, self.individual_level_info])

    def _refresh_record_label(self):
        getters = [g for g in self.individual_level_info['getters'] if g != 'none']
        if len(getters) == 0:
            self.individual_level_info['getters'] = ['none']
            self.record_label.setText('Record: (none)')
            return
        self.individual_level_info['getters'] = getters
        self.record_label.setText('Record: ' + ', '.join(getters))

    def when_add_clicked(self):
        self.add_master()

    def add_master(self, info=None):
        w = IndividualSetter(info,setter_equipment_info=self.setter_equipment_info,order=self.verticalLayout.count()+1)
        self.verticalLayout.addWidget(w)
        w.sig_self_changed.connect(self.setter_changed)
        self.setter_changed(w)

    def _format_manual_set_list(self, dict_list):
        if not dict_list:
            return "(empty)"
        text_list = []
        for i, mapping in enumerate(dict_list, start=1):
            for key, value in mapping.items():
                text_list.append(f"{i}. {key}->{value}")
        return " | ".join(text_list)

    def update_manual_set_labels(self):
        self.manual_set_before_label.setText(
            self._format_manual_set_list(self.individual_level_info['manual_set_before'])
        )
        self.manual_set_after_label.setText(
            self._format_manual_set_list(self.individual_level_info['manual_set_after'])
        )

    def _add_manual_set(self, key):
        channel = self.manual_set_menu.name
        if channel in ["", "void", "none"]:
            return
        value = float(self.manual_set_value_spinbox.value())
        self.individual_level_info[key].append({channel: value})
        self.update_manual_set_labels()
        self.sig_info_changed.emit([self, self.individual_level_info])

    def when_add_manual_set_before_clicked(self):
        self._add_manual_set('manual_set_before')

    def when_add_manual_set_after_clicked(self):
        self._add_manual_set('manual_set_after')

    def _remove_last_manual_set(self, key):
        if len(self.individual_level_info[key]) == 0:
            return
        self.individual_level_info[key].pop()
        self.update_manual_set_labels()
        self.sig_info_changed.emit([self, self.individual_level_info])

    def when_remove_last_manual_set_before_clicked(self):
        self._remove_last_manual_set('manual_set_before')

    def when_remove_last_manual_set_after_clicked(self):
        self._remove_last_manual_set('manual_set_after')

    def when_clear_all_manual_set_clicked(self):
        self.individual_level_info['manual_set_before'] = []
        self.individual_level_info['manual_set_after'] = []
        self.update_manual_set_labels()
        self.sig_info_changed.emit([self, self.individual_level_info])

    def setter_changed(self, setter):
        info = setter.info
        for i in range(self.verticalLayout.count()):
            w = self.verticalLayout.itemAt(i).widget()
            if w == setter:
                break
        self.individual_level_info['setters'][f'setter{i}'] = info
        # self.setting_method_changed()

    def get_setting_array(self, personalized_method=False):
        cmd = self.individual_level_info['setting_method']
        destinations = {}
        letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M',
                   'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z']
        for i, s in enumerate(self.individual_level_info['setters']):
            s = self.individual_level_info['setters'][s]
            if s['explicit']:
                destinations[f'{letters[i]}'] = s['destinations']
            else:
                destinations[f'{letters[i]}'] = s['linear_setting']['destinations']

        return Brakets(cmd, destinations, personalized_input=personalized_method).output

    def update_setting_array(self):
        if self.enable_setting_method_checkBox.isChecked():
            self.individual_level_info['setting_method'] = self.setting_method_le.text()
            self.individual_level_info['setting_array'] = self.get_setting_array(personalized_method=True)
            # print(self.info['setting_array'])
            self.sig_info_changed.emit([self, self.individual_level_info])
        elif not self.enable_setting_method_checkBox.isChecked():
            self.individual_level_info['setting_method'] = ''
            self.individual_level_info['setting_array'] = self.get_setting_array(personalized_method=False)
            self.sig_info_changed.emit([self, self.individual_level_info])  

    def delete_master(self):
        n = self.verticalLayout.count()
        if n <= 1:
            return
        w = self.verticalLayout.itemAt(n-1).widget()
        self.verticalLayout.removeWidget(w)
        w.deleteLater()
        self.individual_level_info['setters'].pop(f'setter{n-1}')
        # self.setting_method_changed()

    def when_combobox_changed(self, widget):
        channel = widget.name
        if channel == 'void':
            return
        getters = [g for g in self.individual_level_info['getters'] if g != 'none']
        if channel in getters:
            getters.remove(channel)
        else:
            getters.append(channel)
        self.individual_level_info['getters'] = getters
        self._refresh_record_label()
        self.sig_info_changed.emit([self, self.individual_level_info])

    def when_clean_clicked(self):
        self.individual_level_info['getters'] = ['none']
        self._refresh_record_label()
        # self.getter_nested_menu.setCurrentIndex(0)
        self.sig_info_changed.emit([self, self.individual_level_info])

    def when_settle_time_changed(self, value):
        self.individual_level_info['settle_time'] = float(value)
        self.sig_info_changed.emit([self, self.individual_level_info])


# if __name__ == "__main__":
#     app = QtWidgets.QApplication(sys.argv)
#     window = IndividualLevel()
#     info = copy.deepcopy(ScanInfo['levels']['level0'])
#     window.set_info(info)
#     window.show()
#     app.exec()


class AllLevelSetting(QtWidgets.QWidget):
    sig_info_changed = QtCore.pyqtSignal(object)

    def __init__(self, all_level_info=None, setter_equipment_info=None, getter_equipment_info=None):
        super(AllLevelSetting, self).__init__()
        uic.loadUi("core/ui/scan_setting.ui", self)
        self.add_pb.clicked.connect(self.add_level)
        self.getter_equipment_info=getter_equipment_info
        self.delete_pb.clicked.connect(self.delete_level)
        self.setter_equipment_info=setter_equipment_info
        if all_level_info:
            self.set_info(all_level_info)
        
        

    def set_info(self, info):
        self.all_level_info = info
        self.update_ui()
    
    def set_setter_equipment_info(self,setter_equipment_info):
        self.setter_equipment_info=setter_equipment_info
        # print(self.equipment_info)
        for i in range(self.verticalLayout.count()):
            item = self.verticalLayout.itemAt(i).widget()
            if type(item) == IndividualLevel:
                item.set_setter_equipment_info(self.setter_equipment_info)

    def set_getter_equipment_info(self, getter_equipment_info):
        self.getter_equipment_info = getter_equipment_info
        for i in range(self.verticalLayout.count()):
            item = self.verticalLayout.itemAt(i).widget()
            if type(item) == IndividualLevel:
                item.set_getter_equipment_info(self.getter_equipment_info)
        

    def update_ui(self):
        for i in range(self.verticalLayout.count()):
            self.verticalLayout.itemAt(i).widget().deleteLater()
        for l in self.all_level_info:
            w = IndividualLevel(individual_level_info=self.all_level_info[l],setter_equipment_info=self.setter_equipment_info,getter_equipment_info=self.getter_equipment_info)
            #fix last line
            self.verticalLayout.addWidget(w)
            w.groupBox.setTitle(f'level: {self.verticalLayout.count()-1}')
            w.sig_info_changed.connect(self.update_info)
            self.update_info([w, w.individual_level_info])

    def add_level(self):
        w = IndividualLevel(setter_equipment_info=self.setter_equipment_info,getter_equipment_info=self.getter_equipment_info)
        # w.set_setter_equipment_info(self.equipment_info)
        self.verticalLayout.addWidget(w)
        w.groupBox.setTitle(f'level: {self.verticalLayout.count()-1}')
        w.sig_info_changed.connect(self.update_info)
        self.update_info([w, w.individual_level_info])


    def delete_level(self):
        n = self.verticalLayout.count()
        if n == 0:
            return
        w = self.verticalLayout.itemAt(n-1).widget()
        self.verticalLayout.removeWidget(w)
        w.deleteLater()
        self.all_level_info.pop(f'level{n-1}')
        self.sig_info_changed.emit(self.all_level_info)

    def update_info(self, level_and_info):
    
        level = level_and_info[0]
        info = level_and_info[1]
        for i in range(self.verticalLayout.count()):
            if level == self.verticalLayout.itemAt(i).widget():
                n = i
                break
        self.all_level_info[f'level{n}'] = info
        self.sig_info_changed.emit( self.all_level_info)
        # print("all level info emitted")
        # print(info)

    def update_all_setting_array(self):
        for i in range(self.verticalLayout.count()):
            self.verticalLayout.itemAt(i).widget().update_setting_array()

    def settings(self):
        print(self.all_level_info)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = AllLevelSetting()
    # info = copy.deepcopy(ScanInfo['levels'])
    # window.set_info(info)
    window.show()
    app.exec()
