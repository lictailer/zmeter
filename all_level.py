
from scan_info import *
from individual_setter import IndividualSetter
from nested_menu import NestedMenu


class IndividualLevel(QtWidgets.QWidget):
    sig_info_changed = QtCore.pyqtSignal(object)

    def __init__(self, individual_level_info=None,setter_equipment_info=None,getter_equipment_info=None, manual_set_before_info=None, manual_set_after_info=None):
        super(IndividualLevel, self).__init__()
        uic.loadUi("ui/individual_level.ui", self)
        self.setter_equipment_info=setter_equipment_info
        self.getter_equipment_info = getter_equipment_info
        if individual_level_info != None:
            self.manual_set_before_info = individual_level_info["manual_set_before"]
            self.manual_set_after_info = individual_level_info["manual_set_after"]
        else:
            self.manual_set_before_info = ""
            self.manual_set_after_info = ""
        self.set_record_equipment_info()
        self.set_setter_equipment_info(self.setter_equipment_info)
        self.set_manual_set_info()
        self.horizontalLayout.insertWidget(1,self.nested_menu)
        self.master_add_one_pb.clicked.connect(self.when_add_clicked)
        self.master_delete_one_pb.clicked.connect(self.delete_master)
        self.record_clean_pb.clicked.connect(self.when_clean_clicked)
        self.setting_method_le.editingFinished.connect(self.setting_method_changed)
        self.manual_set_before.editingFinished.connect(self.when_manual_set_before_changed)
        self.manual_set_after.editingFinished.connect(self.when_manual_set_after_changed)
        


# change name level_info to info

        self.record = []
        if individual_level_info == None:
            self.set_info(copy.deepcopy(ScanInfo['levels']['level1']))
        else:
            self.set_info(individual_level_info)
        
    def set_record_equipment_info(self):
        self.nested_menu = NestedMenu()
        self.nested_menu.set_choices(self.getter_equipment_info)
        # print(EquipmentInfo)
        self.nested_menu.sig_self_changed.connect(self.when_combobox_changed)

    def set_info(self, info,):
        self.individual_level_info = info
        self.update_ui()

    def set_setter_equipment_info(self, setter_equipment_info):
    #set the equipments available according to the given equipment info
        
        for i in range(self.verticalLayout.count()):
            item = self.verticalLayout.itemAt(i).widget()
            if type(item) == IndividualSetter:
                item.set_setter_equipment_info(setter_equipment_info)
        



        #     for key in value.keys():
        #         self.record_cb.addItem(key)
        #         print(key)
    
    def update_ui(self):
        # print(self.info)
        self.setting_method_le.setText(self.individual_level_info['setting_method'])
        clearLayout(self.verticalLayout)
        for setter in self.individual_level_info['setters']:
            self.add_master(info=self.individual_level_info['setters'][setter])
        text = ''
        for getter in self.individual_level_info['getters']:
            text += f"{getter}, "
        self.record_label.setText(text)
        self.individual_level_info['setting_array']=self.get_setting_array()
        self.sig_info_changed.emit([self, self.individual_level_info])
        # print("updated")
        
        #updated
        # for equipment in self.equipment_info:
        #     pass

    def when_add_clicked(self):
        self.add_master()

    def add_master(self, info=None):
        w = IndividualSetter(info,setter_equipment_info=self.setter_equipment_info)
        self.verticalLayout.addWidget(w)
        w.sig_self_changed.connect(self.setter_changed)
        self.setter_changed(w)

    def set_manual_set_info(self):
        self.manual_set_before.setText(self.convert_dict_list_to_text(self.manual_set_before_info))
        self.manual_set_after.setText(self.convert_dict_list_to_text(self.manual_set_after_info))

    def setter_changed(self, setter):
        info = setter.info
        for i in range(self.verticalLayout.count()):
            w = self.verticalLayout.itemAt(i).widget()
            if w == setter:
                break
        self.individual_level_info['setters'][f'setter{i}'] = info
        self.setting_method_changed()

    def get_setting_array(self):
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
            # print(destinations[f'{letters[i]}'])

        qualify = True
        for letter in destinations.keys():
            if letter not in cmd:
                qualify = False
        for letter in cmd:
            if letter in letters:
                if letter not in destinations.keys():
                    qualify = False
        if not qualify:
            cmd = ''
            for letter in destinations.keys():
                cmd += letter
            cmd = f"({cmd})"
        return Brakets(cmd, destinations).output

    def setting_method_changed(self):
        self.individual_level_info['setting_method'] = self.setting_method_le.text()
        self.individual_level_info['setting_array'] = self.get_setting_array()
        # print(self.info['setting_array'])
        self.sig_info_changed.emit([self, self.individual_level_info])

    def delete_master(self):
        n = self.verticalLayout.count()
        if n <= 1:
            return
        w = self.verticalLayout.itemAt(n-1).widget()
        self.verticalLayout.removeWidget(w)
        w.deleteLater()
        self.individual_level_info['setters'].pop(f'setter{n-1}')
        self.setting_method_changed()

    def when_combobox_changed(self, widget):
        if 'none' in self.individual_level_info['getters']:
            self.individual_level_info['getters'].remove('none')
        t=widget.name
        if t == 'void':
            return
        if t in self.individual_level_info['getters']:
            return
        self.individual_level_info['getters'].append(t)
        text = 'record: '
        for r in self.individual_level_info['getters']:
            text += f"{r}, "
        self.record_label.setText(text)
        self.sig_info_changed.emit([self, self.individual_level_info])

    def when_clean_clicked(self):
        self.individual_level_info['getters'] = ['none']
        self.record_label.setText('none')
        # self.nested_menu.setCurrentIndex(0)
        self.sig_info_changed.emit([self, self.individual_level_info])
    
    def convert_text_to_dict_list(self,text):
        mappings = text.split(',')
        dict_list = []
        for mapping in mappings:
            temp, value = mapping.split('->')
            value = float(value)
            key=temp.strip()
            dict_list.append({key: value})
        
        return dict_list
    
    def convert_dict_list_to_text(self, dict_list):
        text = ""
        for i in range(len(dict_list)):
            if i != 0:
                text += ", "
                
            for key, value in dict_list[i].items():
                text += f"{key}->{value}"
        return text

    def when_manual_set_before_changed(self):
        text = self.manual_set_before.text()
        self.individual_level_info['manual_set_before'] = self.convert_text_to_dict_list(text)
        self.sig_info_changed.emit([self, self.individual_level_info])
    
    def when_manual_set_after_changed(self):
        text = self.manual_set_after.text()
        self.individual_level_info['manual_set_after'] = self.convert_text_to_dict_list(text)
        self.sig_info_changed.emit([self, self.individual_level_info])

    def when_artificial_channel_added(self):
        text = self.artificial_channel.text()
        equation,new_channel = text.split('=')



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
        uic.loadUi("ui/scan_setting.ui", self)
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

    def settings(self):
        print(self.all_level_info)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = AllLevelSetting()
    # info = copy.deepcopy(ScanInfo['levels'])
    # window.set_info(info)
    window.show()
    app.exec()
