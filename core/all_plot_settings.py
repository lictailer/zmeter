from .scan_info import *


class IndividualImagePlotSetting(QtWidgets.QWidget):
    sig_info_changed = QtCore.pyqtSignal(object)
    
    def __init__(self,info=None):
        super(IndividualImagePlotSetting, self).__init__()
        uic.loadUi("core/ui/individual_image_setting.ui", self)
        if info==None:
            self.info = {'x': 'None', 'y': 'None', 'z': 'None'}
        else:
            self.info = info
        self.comboBox_x.currentTextChanged.connect(self.when_cb_x_changed)
        self.comboBox_y.currentTextChanged.connect(self.when_cb_y_changed)
        self.comboBox_z.currentTextChanged.connect(self.when_cb_z_changed)
        self.available_x_level={}
        self.available_y_level={}
        self.available_z_level={}
        
    
        
    def set_level_info(self, info):
        self.is_setting_info=True
        self.level_info = info
        self.max_level=len(self.level_info.keys())-1
        for level in self.level_info.keys():
            self.available_x_level[level]=True
            self.available_y_level[level]=True
            self.available_z_level[level]=True
        self.available_y_level['level0']=False
        self.available_z_level[f'level{self.max_level}']=False
        self.available_x_level[f'level{self.max_level}']=False
 

        self.update_choices()
        self.info['x']=self.comboBox_x.currentText()
        self.info['z']=self.comboBox_z.currentText()
        self.info['y']=self.comboBox_y.currentText()
        self.is_setting_info=False
        self.emit_signal()

    def calculate_choices(self):
        x_values = []
        y_values = []
        z_values = []
        
        for li, level in enumerate(self.level_info):
            setters = self.level_info[level]['setters']
            if self.available_x_level[level]:
                x_values.append(f'level{li}')
            if self.available_y_level[level]:
                y_values.append(f'level{li}')
            
            getters = self.level_info[level]['getters']
            if self.available_z_level[level]:
                for gi, getter in enumerate(getters):
                    z_values.append(f'L{li}G{gi}_{getter}')
        return x_values,y_values, z_values

    def update_choices(self):
        self.is_setting_info=True
        x_values, y_values,  z_values = self.calculate_choices()
        previous_x = self.comboBox_x.currentText()
        previous_y = self.comboBox_y.currentText()
        previous_z = self.comboBox_z.currentText()
        self.comboBox_x.clear()
        self.comboBox_y.clear()
        self.comboBox_z.clear()
        
        self.comboBox_y.addItems(y_values)
        self.comboBox_z.addItems(z_values)
        self.comboBox_x.addItems(x_values)
        if previous_x in x_values:
            self.comboBox_x.setCurrentText(previous_x)
        if previous_y in y_values:
            self.comboBox_y.setCurrentText(previous_y)
        if previous_y in z_values:
            self.comboBox_z.setCurrentText(previous_z)
        self.is_setting_info=False
    def emit_signal(self):
        self.sig_info_changed.emit([self, self.info])

    def find_level(self,name):
        if not name:
            return None
        if "level" in name:
            level_number=name[-1]
        else:
            level_number=name[1]
        selected_level=int(level_number)
        
        return(selected_level)
    def when_cb_x_changed(self, text):
        if self.is_setting_info:
            return
        self.info['y']=self.comboBox_y.currentText()
        self.info['z']=self.comboBox_z.currentText()
        self.info['x'] = text
        selected_level_number=self.find_level(text)
        
            
        for level in self.level_info.keys():
            self.available_z_level[level]=False
            self.available_y_level[level]=False
        if selected_level_number!=None:
            self.available_y_level[f'level{selected_level_number+1}']=True
            self.available_z_level[f'level{selected_level_number}']=True
            self.available_x_level[f'level{selected_level_number}']=True
        
        self.update_choices()
        self.emit_signal()


    def when_cb_y_changed(self, text):
        if self.is_setting_info:
            return
        self.info['z']=self.comboBox_z.currentText()
        self.info['x']=self.comboBox_x.currentText()
        self.info['y'] = text
        self.emit_signal()


    def when_cb_z_changed(self, text):
        if self.is_setting_info:
            return
        self.info['x']=self.comboBox_x.currentText()
        self.info['y']=self.comboBox_y.currentText()
        self.info['z'] = text
        self.emit_signal()

    def set_choices(self,info):
        self.info = info
        self.is_setting_info = True
        self.comboBox_x.setCurrentText(self.info['x'])
        self.comboBox_y.setCurrentText(self.info['y'])
        self.comboBox_z.setCurrentText(self.info['z'])
        self.is_setting_info = False
        self.emit_signal()

# if __name__ == "__main__":
#     app = QtWidgets.QApplication(sys.argv)
#     window = IndividualImagePlotSetting()
#     window.set_level_info(ScanInfo['levels'])
#     window.show()
#     app.exec()\
        

class IndividualLinePlotSetting(QtWidgets.QWidget):
    sig_info_changed = QtCore.pyqtSignal(object)

    def __init__(self, info=None):
        super(IndividualLinePlotSetting, self).__init__()
        uic.loadUi("core/ui/individual_line_setting.ui.ui", self)
        self.info = {'x': 'None', 'y': 'None'}
        self.comboBox_x.currentTextChanged.connect(self.when_cb_x_changed)
        self.comboBox_y.currentTextChanged.connect(self.when_cb_y_changed)
        self.is_setting_choice = False
        self.avalable_level={}

    def set_level_info(self, info):
        print("all level setting info recieved")
        self.level_info = info
        for level in self.level_info.keys():
            self.avalable_level[level]=True
        # print(self.avalable_level)
        self.update_choices()
        self.info['x']=self.comboBox_x.currentText()
        self.info['y']=self.comboBox_y.currentText()
        self.emit_signal()
        

    def calculate_choices(self):
        x_values = []
        y_values = []
        for li, level in enumerate(self.level_info):
            
            x_values.append(f'level{li}')
            setters = self.level_info[level]['setters']
            for si, setter in enumerate(setters):
                x_values.append(f'L{li}S{si}_{setters[setter]["channel"]}')
            if self.avalable_level[level]==True :
                getters = self.level_info[level]['getters']
                for gi, getter in enumerate(getters):
                    y_values.append(f'L{li}G{gi}_{getter}')
        return x_values, y_values

    def update_choices(self):
        self.is_setting_choice = True
        x_values, y_values = self.calculate_choices()
        previous_x = self.comboBox_x.currentText()
        previous_y = self.comboBox_y.currentText()
        self.comboBox_x.clear()
        self.comboBox_y.clear()
        self.comboBox_y.addItems(y_values)
        self.comboBox_x.addItems(x_values)
        if previous_x in x_values:
            self.comboBox_x.setCurrentText(previous_x)
        if previous_y in y_values:
            self.comboBox_y.setCurrentText(previous_y)
        self.is_setting_choice =False
        

    def find_level(self,name):
        if not name:
            return None
        if "level" in name:
            level_number=name[-1]
        else:
            # print("the name is",name)
            level_number=name[1]
        selected_level=f'level{level_number}'
        
        return(selected_level)

    def emit_signal(self):
        self.sig_info_changed.emit([self, self.info])

    def when_cb_x_changed(self, text):
        
        if self.is_setting_choice:
            return
        self.info['y']=self.comboBox_y.currentText()
        self.is_setting_choice = True
        self.info['x'] = text
        selected_level=self.find_level(text)
        for level in self.avalable_level.keys():
            self.avalable_level[level]=False
        if selected_level != None:
            self.avalable_level[selected_level]=True
        # x_values, y_values = self.calculate_choices()
        # self.comboBox_y.clear()
        # self.comboBox_y.addItems(y_values)
        self.update_choices()
        self.is_setting_choice = False
        # print(y_values)
        self.emit_signal()

    def when_cb_y_changed(self, text):
        if self.is_setting_choice:
            return
        self.info['x']=self.comboBox_x.currentText()
        self.info['y'] = text
        self.emit_signal()

    def set_choices(self,info):
        self.info = info
        self.is_setting_choice = True
        self.comboBox_x.setCurrentText(info['x'])
        self.comboBox_y.setCurrentText(info['y'])
        self.is_setting_choice = False
        self.emit_signal()


# if __name__ == "__main__":
#     app = QtWidgets.QApplication(sys.argv)
#     window = IndividualLinePlotSetting()
#     window.set_level_info(ScanInfo['levels'])
#     window.show()
#     app.exec()


class AllPlotSetting(QtWidgets.QWidget):
    sig_info_changed = QtCore.pyqtSignal(object)

    def __init__(self,level_info=None):
        super(AllPlotSetting, self).__init__()
        uic.loadUi("core/ui/plot_setting.ui", self)
        self.info = {'line_plots': {},
                     'image_plots': {}, }
        if level_info == None:
            self.set_level_info(copy.deepcopy(ScanInfo['levels']))
        else:
            self.set_level_info(level_info)
        self.pushButton_add_line.clicked.connect(self.when_add_line_clicked)
        self.pushButton_add_image.clicked.connect(self.when_add_image_clicked)
        self.pushButton_delete_line.clicked.connect(self.when_delete_line_clicked)
        self.pushButton_delete_image.clicked.connect(self.when_delete_image_clicked)

    def set_level_info(self, level_info):
        
        self.level_info = level_info
        for i in range(self.verticalLayout_image.count()):
            w = self.verticalLayout_image.itemAt(i).widget()
            w.set_level_info(self.level_info)

        for i in range(self.verticalLayout_line.count()):
            w = self.verticalLayout_line.itemAt(i).widget()
            w.set_level_info(self.level_info)

    def set_level_info_slot(self, info):
        self.set_level_info(info)

    def emit_signal(self):
        self.sig_info_changed.emit(self.info)
# image

    def when_add_image_clicked(self):
        w = IndividualImagePlotSetting()
        w.sig_info_changed.connect(self.when_individual_image_plot_setting_changed)

        self.verticalLayout_image.addWidget(w)
        n = self.verticalLayout_image.count()
        self.info['image_plots'][f'{n-1}'] = w.info
        w.set_level_info(self.level_info)
        self.emit_signal()

    def when_individual_image_plot_setting_changed(self, widget_and_info):
        w, info = widget_and_info
        n = self.verticalLayout_image.count()
        for i in range(n):
            if self.verticalLayout_image.itemAt(i).widget() == w:
                break
        self.info['image_plots'][f'{i}'] = info
        # print(info)
        self.emit_signal()


    def when_delete_image_clicked(self):
        n = self.verticalLayout_image.count()
        if not n:
            return
        self.info['image_plots'].pop(f'{n-1}')
        w = self.verticalLayout_image.itemAt(n-1).widget()
        self.verticalLayout_image.removeWidget(w)
        w.deleteLater()
        self.emit_signal()

# line
    def when_add_line_clicked(self):
        w = IndividualLinePlotSetting()
        w.sig_info_changed.connect(self.when_individual_line_plot_setting_changed)
        self.verticalLayout_line.addWidget(w)
        n = self.verticalLayout_line.count()
        self.info['line_plots'][f'{n-1}'] = w.info
        w.set_level_info(self.level_info)   
        self.emit_signal()

    def when_individual_line_plot_setting_changed(self, widget_and_info):
        w, info = widget_and_info
        n = self.verticalLayout_line.count()
        for i in range(n):
            if self.verticalLayout_line.itemAt(i).widget() == w:
                break
        self.info['line_plots'][f'{i}'] = info
        self.emit_signal()


    def when_delete_line_clicked(self):
        n = self.verticalLayout_line.count()
        if not n:
            return
        self.info['line_plots'].pop(f'{n-1}')
        w = self.verticalLayout_line.itemAt(n-1).widget()
        self.verticalLayout_line.removeWidget(w)
        w.deleteLater()
        self.emit_signal()

    def update_ui(self,plot_setting_info):
        self.info = plot_setting_info
        image_plots_info=self.info['image_plots']
        line_plots_info = self.info['line_plots']
        for plot_index,individual_plot_info in line_plots_info.items():
            w=IndividualLinePlotSetting()
            w.sig_info_changed.connect(self.when_individual_line_plot_setting_changed)
            self.verticalLayout_line.addWidget(w)
            w.set_level_info(self.level_info)
            w.set_choices(individual_plot_info)

        for plot_index,individual_plot_info in image_plots_info.items():
            w=IndividualImagePlotSetting()
            w.sig_info_changed.connect(self.when_individual_image_plot_setting_changed)
            self.verticalLayout_image.addWidget(w)
            w.set_level_info(self.level_info)
            w.set_choices(individual_plot_info)
        self.emit_signal()






if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = AllPlotSetting()
    window.set_level_info(ScanInfo['levels'])
    window.show()
    app.exec()
