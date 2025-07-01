from .scan_info import *
from .scan_logic import ScanLogic
from .all_level import AllLevelSetting
from .all_plot_settings import AllPlotSetting
from .all_plots import AllPlots
from .construct_scan_coordinates import Construct
from .all_plots import LinePlot
from .all_plots import ImagePlot
import os, shutil


class Scan(QtWidgets.QWidget):
    sig_info_changed = QtCore.pyqtSignal(object)
    start = QtCore.pyqtSignal(object)
    stop = QtCore.pyqtSignal()
    def __init__(self,name=None, info=None,setter_equipment_info=None,main_window=None,getter_equipment_info=None):
        super(Scan, self).__init__()
        # uic.loadUi("ui/scan.ui", self)
        self.ui = uic.loadUi("core/ui/scan new.ui", self)

        self.logic = ScanLogic(main_window=main_window)
        self.logic.sig_new_data.connect(self.new_data)
        self.logic.sig_update_remaining_time.connect(self.update_remaining_time_label)
        self.logic.sig_update_remaining_points.connect(self.update_remaining_points_label)

        
        self.main_window=main_window
        self.finished = False
        self.setter_equipment_info = setter_equipment_info
        self.getter_equipment_info = getter_equipment_info

        self.scan_button.clicked.connect(self.when_scan_clicked)
        self.stop_button.clicked.connect(self.when_stop_clicked)
        self.scan_button_1.clicked.connect(self.when_scan_clicked)
        self.stop_button_1.clicked.connect(self.when_stop_clicked)
        self.save_plots_button_1.clicked.connect(self.when_save_plots_clicked)
        self.update_plots_button_1.clicked.connect(self.update_all_plots)
        self.scan_button_2.clicked.connect(self.when_scan_clicked)
        self.stop_button_2.clicked.connect(self.when_stop_clicked)
        self.save_plots_button_2.clicked.connect(self.when_save_plots_clicked)
        self.update_plots_button_2.clicked.connect(self.update_all_plots)
        self.scan_button_3.clicked.connect(self.when_scan_clicked)
        self.stop_button_3.clicked.connect(self.when_stop_clicked)
        self.save_plots_button_3.clicked.connect(self.when_save_plots_clicked)
        self.update_plots_button_3.clicked.connect(self.update_all_plots)

        self.load_button.clicked.connect(self.when_load_clicked)
        self.save_button.clicked.connect(self.when_save_clicked)
        self.all_level_setting = AllLevelSetting(all_level_info=info['levels'],setter_equipment_info=setter_equipment_info,getter_equipment_info=getter_equipment_info)
        # print(equipment_info)
        self.all_plot_setting = AllPlotSetting(level_info=info['levels'])
        self.verticalLayout_2.addWidget(self.all_plot_setting)
        self.graphing_plots = [
            AllPlots(level_info=info['levels'], page_number=i)
            for i in range(3)
        ]
        self.plots1_layout.addWidget(self.graphing_plots[0])
        self.plots2_layout.addWidget(self.graphing_plots[1])
        self.plots3_layout.addWidget(self.graphing_plots[2])

        self.scrollArea.setWidget(self.all_level_setting)
        if info is None:
            self.info = {'name': 'no name',
                         'levels': self.all_level_setting.all_level_info,
                         'data': {},
                         'plots': self.all_plot_setting.info}
        else:
            self.info = info
            self.info['name']=name
            # print(name)
        self.populate()
        self.all_level_setting.sig_info_changed.connect(self.when_all_level_setting_infochanged)
        self.all_plot_setting.sig_info_changed.connect(self.when_all_plot_setting_infochanged)
        self.all_level_setting.sig_info_changed.connect(self.all_plot_setting.set_level_info_slot)
        self.lineEdit.textChanged.connect(self.when_name_changed)
        self.all_level_setting.sig_info_changed.emit(self.all_level_setting.all_level_info)
        self.logic.sig_scan_finished.connect(self.scan_finished)

    
    def scan_finished(self):
        print('finished')
        self.when_save_plots_clicked()
        self.when_save_clicked()
        current_serial = self.main_window.scanlist.serial.value()
        self.main_window.scanlist.serial.setValue(current_serial+1)

    def set_setter_equipment_info(self,info):
        self.setter_equipment_info=info
        self.all_level_setting.set_setter_equipment_info(self.setter_equipment_info)

    def populate(self):
        self.lineEdit.setText(self.info['name'])
        self.setWindowTitle(self.info['name'])

    def emit(self):
        self.sig_info_changed.emit(self.info)

    def when_name_changed(self):
        self.info['name'] = self.lineEdit.text()
        self.setWindowTitle(self.info['name'])
        self.sig_info_changed.emit(self.info)

    def when_all_level_setting_infochanged(self, info):

        
        self.info['levels'] = info
        # print("all level setting info recieved")
        # for i in range(self.all_plot_setting.verticalLayout_line.count()):
        #     w = self.all_plot_setting.verticalLayout_line.itemAt(i).widget()
        #     w.blockSignals(True)
        # for i in range(self.all_plot_setting.verticalLayout_image.count()):
        #     w = self.all_plot_setting.verticalLayout_image.itemAt(i).widget()
        #     w.blockSignals(True)
        self.all_plot_setting.set_level_info(info)
        for gp in self.graphing_plots:
            gp.set_level_info(info)
        # for i in range(self.all_plot_setting.verticalLayout_image.count()):
        #     w = self.all_plot_setting.verticalLayout_image.itemAt(i).widget()
        #     w.blockSignals(True)
        # for i in range(self.all_plot_setting.verticalLayout_image.count()):
        #     w = self.all_plot_setting.verticalLayout_image.itemAt(i).widget()
        #     w.blockSignals(True)

    def when_all_plot_setting_infochanged(self, plot_setting_info):
        info = plot_setting_info
        self.info['plots'] = info

        # for i in range(self.all_plot_setting.verticalLayout_line.count()):
        #     w = self.all_plot_setting.verticalLayout_line.itemAt(i).widget()
        #     w.blockSignals(True)
        # for i in range(self.all_plot_setting.verticalLayout_image.count()):
        #     w = self.all_plot_setting.verticalLayout_image.itemAt(i).widget()
        #     w.blockSignals(True)

        for gp in self.graphing_plots:
            gp.receive_plot_info(plot_setting_info)

        # for i in range(self.all_plot_setting.verticalLayout_image.count()):
        #     w = self.all_plot_setting.verticalLayout_image.itemAt(i).widget()
        #     w.blockSignals(True)
        # for i in range(self.all_plot_setting.verticalLayout_image.count()):
        #     w = self.all_plot_setting.verticalLayout_image.itemAt(i).widget()
        #     w.blockSignals(True)
        # print(self.info['name'])
        self.sig_info_changed.emit(self.info)

    def set_main_window(self, mainwindow):
        self.main_window = mainwindow
        self.logic.main_window = mainwindow

    def when_stop_clicked(self):
        self.main_window.force_stop_equipments()
        self.logic.received_stop = True
        self.logic.stop_scan = True

    def when_scan_clicked(self):
        if hasattr(self, "unique_data_name"):
            del self.unique_data_name
        self.main_window.stop_equipments_for_scanning()
        self.logic.reset_flags()
        self.logic.go_scan = True
        self.update_alllevel_setting_array()
        self.logic.initilize_data(self.info)
        self.update_all_plots()
        self.logic.start()

    def start_scan(self):
        if hasattr(self, "unique_data_name"):
            del self.unique_data_name
        self.logic.reset_flags()
        self.logic.go_scan = True
        self.logic.initilize_data(self.info)
        self.main_window.stop_equipments_for_scanning()
        self.logic.start()
        while self.logic.isRunning():
            time.sleep(0.1)
    
    def update_alllevel_setting_array(self):
        self.all_level_setting.update_all_setting_array()


    def update_all_plots(self):
        """Call AllPlots.update_plots() for every page."""
        self.update_alllevel_setting_array()
        for gp in self.graphing_plots:
            gp.update_plots()

    def new_data(self,info):
        new_data, current_target_index=info
        self.info['data']=new_data

        for gp in self.graphing_plots:
            for plot in range(gp.plots_layout.count()):
                w = gp.plots_layout.itemAt(plot).widget()
                if isinstance(w,LinePlot):
                    if(current_target_index[w.setter_level_number]==0):
                        w.y_coordinates=np.full(w.setting_info_length, np.nan)
                    w.data=new_data                
                    w.plot.clear()
                    w.plot_line(current_target_index)
                if isinstance(w,ImagePlot):
                    w.update_image(new_data,current_target_index)

    def _backup_subfolder(self) -> str:
        """
        Return the text inside the “backup_path” box (trimmed), whatever
        type it is: QPlainTextEdit, QLineEdit, or a plain string attribute.
        """
        widget = getattr(self.main_window, "backup_path", None)
        if widget is None:
            return ""                                # not found

        # Qt widgets
        if callable(getattr(widget, "toPlainText", None)):
            return widget.toPlainText().strip()
        if callable(getattr(widget, "text", None)):
            return widget.text().strip()

        # already a string
        return str(widget).strip()

    def _next_unique_data_name(self) -> str:
        """
        Return a base-name (no extension) that is unique in the folder
        chosen in the 'save_info_path' text box. We remember the first
        value we hand out during this session so both Save and Save-Plots
        use the *same* name.
        """
        if hasattr(self, "unique_data_name"):
            return self.unique_data_name           # already decided

        serial = f'{self.main_window.scanlist.serial.value():04d}'
        base   = f"{serial}_{self.info['name']}"

        folder_txt = self.main_window.save_info_path.toPlainText().strip()
        folder     = os.path.normpath(folder_txt) if folder_txt else os.getcwd()
        os.makedirs(folder, exist_ok=True)

        candidate = base
        count = 1
        while os.path.exists(os.path.join(folder, f"{candidate}.json")):
            candidate = f"{base}_{count}"
            count    += 1

        self.unique_data_name = candidate          # remember for later
        return candidate

    # def when_save_plots_clicked(self):
    #     serial = f'{self.main_window.scanlist.serial.value():04d}'
    #     name = self.info['name']
    #     name = f'{serial}_{name}'
    #     text = self.main_window.ppt_path.toPlainText()
    #     if text == '':
    #         fileName, _ = QFileDialog.getSaveFileName(self, 'Select PPT', '', 'PPT Files (*.pptx)')
    #     else:
    #         fileName = os.path.normpath(text.strip('"'))

    #     # Check if the file exists
    #     if not os.path.exists(fileName):
    #         prs = Presentation()
    #     else:
    #         # Load the existing presentation
    #         prs = Presentation(fileName)

    #     # Take the screenshot
    #     screenshot_path = "screenshot.png"
    #     widget_width, widget_height = self.screenshot_widget(self.tab_2, screenshot_path)

    #     try:
    #         # Creating the new slide
    #         slide_layout = prs.slide_layouts[6]
    #         slide = prs.slides.add_slide(slide_layout)

    #         # Scaling the screenshot
    #         slide_width = prs.slide_width
    #         slide_height = prs.slide_height
    #         width_ratio = slide_width / widget_width
    #         height_ratio = slide_height / widget_height
    #         scaling_factor = min(width_ratio, height_ratio)
    #         new_width = widget_width * scaling_factor
    #         new_height = widget_height * scaling_factor
    #         left = (slide_width - new_width) / 2
    #         top = (slide_height - new_height) / 2

    #         # Attaching the image
    #         slide.shapes.add_picture(screenshot_path, left, top, width=new_width, height=new_height)

    #         # Attach name
    #         left_inch = Inches(0.5)
    #         top_inch = Inches(0.5)
    #         width_inch = Inches(2)
    #         height_inch = Inches(1)
    #         text_box_left = slide.shapes.add_textbox(left_inch, top_inch, width_inch, height_inch)
    #         tf_left = text_box_left.text_frame
    #         tf_left.text = name

    #         # Attach comments
    #         left_inch = slide_width - Inches(4)
    #         text_box_right = slide.shapes.add_textbox(left_inch, top_inch, width_inch, height_inch)
    #         tf_right = text_box_right.text_frame
    #         tf_right.text = self.comments_textEdit.toPlainText()

    #         prs.save(fileName)
    #         print('Screenshot saved at', fileName)
    #     except Exception as e:
    #         print(f'An error occurred while saving the presentation: {e}')

    def when_save_plots_clicked(self):
        """Save a PowerPoint slide for every tab that actually shows plots."""
        serial = f'{self.main_window.scanlist.serial.value():04d}'
        name   = self._next_unique_data_name()  
        text   = self.main_window.ppt_path.toPlainText()

        count = 1
        while os.path.exists(name):
            name_part, ext = os.path.splitext(name)
            name = os.path.join(folder, f"{name_part}_{count}{ext}")
            count += 1
        print(name)
        # --- choose / create PPT file --------------------------------------------------
        if text == '':
            fileName, _ = QFileDialog.getSaveFileName(self, 'Select PPT', '', 'PPT Files (*.pptx)')
            if not fileName:
                return   # user cancelled
        else:
            fileName = os.path.normpath(text.strip('"'))

        folder = os.path.dirname(fileName)
        if folder and not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)

        if not os.path.exists(fileName):
            prs = Presentation()
            prs.slide_width  = Inches(13.333)   # 16:9
            prs.slide_height = Inches(7.5)
        else:
            prs = Presentation(fileName)

        # --- walk through every tab in the tab widget ---------------------------------
        for idx, tab in enumerate([self.Plots1Tab, self.Plots2Tab, self.Plots3Tab]):

            # 1.  does this tab have at least one plot?  (no helper needed)
            if not tab.findChildren((LinePlot, ImagePlot)):
                continue          # skip empty tab

            # 2.  take screenshot of that tab
            shot_path = f"screenshot.png"
            w_px, h_px = self.screenshot_widget(tab, shot_path)

            # 3.  add blank slide & picture (same sizing logic as before)
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            sw, sh = prs.slide_width, prs.slide_height

            scale = sh / h_px
            nw, nh = w_px * scale, h_px * scale
            if nw > sw * 0.8:
                scale = (sw * 0.8) / w_px
                nw, nh = w_px * scale, h_px * scale
            left = sw - nw
            top  = (sh - nh) / 2

            slide.shapes.add_picture(shot_path, left, top, width=nw, height=nh)

            try:
                os.remove(shot_path)          # delete the PNG immediately
            except OSError:
                pass                          # silent if, for any reason, it’s gone
            
            # 4.  add name (bold) and comments box on left
            left_in = Inches(0.0)
            top_in  = Inches(0.2)
            w_in    = Inches(3.0)
            h_in    = Inches(0.5)

            tb_name = slide.shapes.add_textbox(left_in, top_in, w_in, h_in)
            tb_name.text_frame.text = name
            for p in tb_name.text_frame.paragraphs:
                for run in p.runs:
                    run.font.bold = True

            tb_comm = slide.shapes.add_textbox(left_in, top_in + h_in + Inches(0.2),
                                               w_in, h_in * 2)
            tf = tb_comm.text_frame
            tf.word_wrap = True
            tf.text = self.comments_textEdit.toPlainText()
            for p in tf.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(12)

        # --- save ----------------------------------------------------------------------
        try:
            prs.save(fileName)
            print('Screenshot(s) saved to', fileName)

            if os.path.exists(r"Z:\\"):                      # drive exists?
                backup_sub = self._backup_subfolder()
                if backup_sub == "":
                    print("Backup path text box is empty – skipping backup.")
                else:
                    backup_dir = os.path.join(backup_sub)
                    os.makedirs(backup_dir, exist_ok=True)

                    # 1) copy the PPT we just created
                    shutil.copy2(fileName,
                                 os.path.join(backup_dir,
                                              os.path.basename(fileName)))
                    print("PPT Backup written to", backup_dir)
            else:
                print("Backup drive Z: not found – no backup created.")
        except Exception as e:
            print(f'An error occurred while saving the presentation: {e}')

    def screenshot_widget(self,widget, filename):
        """Capture a screenshot of the widget and save it as a PNG file."""
        pixmap = widget.grab()
        pixmap.save(filename, 'PNG')
        return pixmap.width(), pixmap.height()

    def when_save_clicked(self):
        class CustomEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                elif isinstance(obj, float) and np.isnan(obj):
                    return "NaN"
                return super().default(obj)

        ppp_box = self.PlotsPerPage                      # QComboBox
        self.info['plots_per_page'] = int(ppp_box.currentText())

        # Get user input and prepare base file name
        text = self.main_window.save_info_path.toPlainText().strip()
        serial = f'{self.main_window.scanlist.serial.value():04d}'
        base_name = self._next_unique_data_name() + ".json"
        self.name = base_name

        # Determine folder and file path
        if not text:
            fileName, _ = QFileDialog.getSaveFileName(self, 'Select File to Save', self.name)
            if not fileName:
                return  # User cancelled
            folder, file = os.path.split(fileName)
            base_name = file
        else:
            folder = os.path.normpath(text.strip('"'))
            os.makedirs(folder, exist_ok=True)
            fileName = os.path.join(folder, base_name)

        # Check for filename conflict and modify if necessary
        original_fileName = fileName
        count = 1
        while os.path.exists(fileName):
            name_part, ext = os.path.splitext(base_name)
            fileName = os.path.join(folder, f"{name_part}_{count}{ext}")
            count += 1

        # Save the JSON file
        try:
            with open(fileName, 'w') as json_file:
                json.dump(self.info, json_file, cls=CustomEncoder, indent=4)
            print(f"File saved to {fileName}")
                        # ── JSON BACKUP --------------------------------------------------
            if os.path.exists(r"Z:\\"):
                backup_sub = self._backup_subfolder()
                if backup_sub:
                    backup_dir = os.path.join(backup_sub)
                    os.makedirs(backup_dir, exist_ok=True)
                    shutil.copy2(fileName,
                                 os.path.join(backup_dir,
                                              os.path.basename(fileName)))
                    print("JSON backup written to", backup_dir)
                else:
                    print("Backup path text box is empty – JSON not backed up.")
            else:
                print("Drive Z: not found – JSON not backed up.")
        except Exception as e:
            print(f"Error saving file: {e}")


    def when_load_clicked(self):
        def handle_special_values(value):
            if value == "NaN":
                return np.nan
            return value

        def convert_special_values(obj):
            if isinstance(obj, list):
                return [convert_special_values(item) for item in obj]
            elif isinstance(obj, dict):
                return {key: convert_special_values(val) for key, val in obj.items()}
            else:
                return handle_special_values(obj)
            
        default_dir = self.main_window.save_info_path.toPlainText()
        fileName, _ = QFileDialog.getOpenFileName(self, 'Open File', default_dir, 'All Files (*);;Text Files (*.txt)')
        if fileName:
            try:
                with open(fileName, 'r') as file:
                    content = file.read()
                    
                    info = json.loads(content)  # Use json.loads() instead of json.load(file)
                    self.info = convert_special_values(info)
                    print("info",self.info)

                    ppp_val = self.info.get('plots_per_page', None)
                    if ppp_val is not None:
                        idx = self.PlotsPerPage.findText(str(ppp_val))
                        if idx != -1:
                            self.PlotsPerPage.setCurrentIndex(idx)
   
            except Exception as e:
                print(f"An error occurred: {e}")

        widget = self.scrollArea.takeWidget()
        if widget:
            widget.deleteLater()

        for gp in self.graphing_plots:
            gp.setParent(None)
            gp.deleteLater()
        self.graphing_plots.clear()

        self.verticalLayout_2.removeWidget(self.all_plot_setting)
        self.all_plot_setting.setParent(None)  # Detach the widget from its parent
        self.all_plot_setting.deleteLater()

        self.all_level_setting = AllLevelSetting(all_level_info=self.info['levels'],setter_equipment_info=self.setter_equipment_info,getter_equipment_info=self.getter_equipment_info)
        self.all_plot_setting = AllPlotSetting(level_info=self.info['levels'])
        self.verticalLayout_2.addWidget(self.all_plot_setting)
        self.scrollArea.setWidget(self.all_level_setting)
        self.graphing_plots = [
            AllPlots(level_info=self.info['levels'], page_number=i)
            for i in range(3)
        ]
        self.plots1_layout.addWidget(self.graphing_plots[0])
        self.plots2_layout.addWidget(self.graphing_plots[1])
        self.plots3_layout.addWidget(self.graphing_plots[2])

        self.populate()
        self.all_level_setting.sig_info_changed.connect(self.when_all_level_setting_infochanged)
        self.all_plot_setting.sig_info_changed.connect(self.when_all_plot_setting_infochanged)
        self.all_level_setting.sig_info_changed.connect(self.all_plot_setting.set_level_info_slot)
        self.all_level_setting.sig_info_changed.emit(self.all_level_setting.all_level_info)
       
        self.all_plot_setting.update_ui(self.info['plots'])
        for gp in self.graphing_plots:
           gp.receive_plot_info(self.info['plots'])   # store plot info
        self.update_all_plots()                           # actually create widgets

        data = self.info['data']
        level_number = len(info['levels'])
        targets_array_FEL = []
        setters_targets_len_FEL = []

        for l in range(level_number):
            targets_array_FEL.append(self.info['levels'][f'level{l}']['setting_array'])
            setters_targets_len_FEL.append(len(targets_array_FEL[l])-1)
        if self.info['data']:
            for gp in self.graphing_plots:
                for plot in range(gp.plots_layout.count()):
                    w = gp.plots_layout.itemAt(plot).widget()
                    if isinstance(w,LinePlot):
                        w.load_plot(data,setters_targets_len_FEL)
                    if isinstance(w,ImagePlot):
                        w.load_image(data,setters_targets_len_FEL)

    def when_setter_equipment_info_change(self,setter_equipment_info):
        print(setter_equipment_info)
        self.setter_equipment_info=setter_equipment_info
        self.all_level_setting.set_setter_equipment_info(self.setter_equipment_info)

    def scan_setters(self):
        destination=self.destinations[self.current_destinations_index]
        value=self.values_to_set[self.current_values_to_set_index]
        output=[]
        if "level" in destination:
            self.current_scanning_level=destination
            self.current_destinations_index+=1
            return(self.scan_setters())
        if isinstance(value, list):
            for i in range(len(value)):
                temp=[]
                destination = self.destinations[self.current_destinations_index]
                temp.append(value[i])
                temp.append(destination)
                output.append(temp)
                self.current_destinations_index += 1
        else:
            destination = self.destinations[self.current_destinations_index]
            output.append(value)
            output.append(destination)                
            self.current_destinations_index += 1
        self.current_values_to_set_index+=1
        return(output)
        
    def update_remaining_time_label(self, time_str):
        self.ui.scan_time_info_1.setText(f"Remaining / Total Time: {time_str}")
        self.ui.scan_time_info_2.setText(f"Remaining / Total Time: {time_str}")
        self.ui.scan_time_info_3.setText(f"Remaining / Total Time: {time_str}")

    def update_remaining_points_label(self, point_str):
        self.ui.scan_point_info_1.setText(f"Finished / Total Points: {point_str}")
        self.ui.scan_point_info_2.setText(f"Finished / Total Points: {point_str}")
        self.ui.scan_point_info_3.setText(f"Finished / Total Points: {point_str}")
    



if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    s = Scan()
    # s.all_level_setting.add_level()
    # s.all_level_setting.add_level()
    # s.all_level_setting.verticalLayout.itemAt(0).widget().add_master()
    # s.all_level_setting.verticalLayout.itemAt(1).widget().add_master()
    # s.all_plot_setting.when_add_image_clicked()
    # s.all_plot_setting.when_add_image_clicked()
    # s.all_plot_setting.when_add_image_clicked()
    # s.all_plot_setting.when_add_line_clicked()
    # s.all_plot_setting.when_add_line_clicked()
    # s.all_plot_setting.when_add_line_clicked()
    s.when_scan_clicked()
    s.show()
    app.exec()