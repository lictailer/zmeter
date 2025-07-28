from re import T
from .scan_info import *
# import random
# import warnings
# from pptx import Presentation
# from pptx.util import Inches
# from scipy.interpolate import interp2d




class LinePlot(QtWidgets.QWidget):
    sig_info_changed = QtCore.pyqtSignal(object)
    
    def __init__(self, label=None,coordinate=None,setting_info=None,data=None):
        super(LinePlot, self).__init__()
        uic.loadUi("core/ui/line_plot.ui", self)
        self.plot = pg.PlotWidget()

        self.label = QtWidgets.QLabel()
        
        self.graph.addWidget(self.plot)
        self.graph.addWidget(self.label)
        self.data=data
        self.coordinate=coordinate
        self.x_name=coordinate['x']
        self.y_name=coordinate['y']
        self.plot.setLabel('left',self.y_name)
        self.plot.setLabel('bottom',self.x_name)

        #vertical line
        self.v_line = pg.InfiniteLine(angle=90, movable=True)
        self.plot.addItem(self.v_line)
        self.v_line.sigPositionChanged.connect(self.update_label)


        if "level" in self.x_name:
            self.x_start = 0
            self.setting_info=[]
            self.setting_info_length=len(setting_info[0])
            for index in range(self.setting_info_length):
                temp_point=[]
                for setter_setting_info in setting_info:
                    temp_point.append(setter_setting_info[index])
                self.setting_info.append(temp_point)
            self.setter_level_number=int(self.x_name[-1])
            self.x_coordinates=np.arange(self.setting_info_length)

        else:
            self.setter_level_number=int(self.x_name[1])
            self.setting_info=setting_info
            self.x_start = self.setting_info[0]
            # self.setting_info=setting_info[~np.isnan(setting_info)]
            self.setting_info_length=len(self.setting_info)
            self.x_coordinates = self.setting_info
        self.getter_number=int(self.y_name[3])
                
        self.y_coordinates=np.full(self.setting_info_length, np.nan)
        self.update_count = 0
        # self.timer = QtCore.QTimer()
        # self.timer.timeout.connect(self.update_plot)
        # self.timer.start(100)
        # self.plot_line()
        
    def update_label(self):
        pos = self.v_line.pos()
        x_pos = pos.x()
        if x_pos > self.x_coordinates[-1] or x_pos < self.x_start:
            self.label.setText('Out of bounds')
            return
        
        left_bound_x = math.floor(x_pos)
        right_bound_x = math.ceil(x_pos)
        
        # Handle bounds checking
        if left_bound_x < 0 or right_bound_x >= len(self.setting_info):
            self.label.setText('Out of bounds')
            return
            
        left_val_x = self.setting_info[left_bound_x]
        right_val_x = self.setting_info[right_bound_x]
        left_bound_y = self.y_coordinates[int(left_bound_x)]
        right_bound_y = self.y_coordinates[int(right_bound_x)]
        
        # Handle X values that might be lists or single values, and might contain NaN
        x_val_text = self._format_x_values(left_val_x, right_val_x, x_pos, left_bound_x, right_bound_x)
        
        # Handle Y value interpolation
        if np.isnan(left_bound_y) or np.isnan(right_bound_y):
            y_val_text = "NaN"
        else:
            slope = self.slope(left_bound_x, left_bound_y, right_bound_x, right_bound_y)
            y_val = (x_pos - left_bound_x) * slope + left_bound_y
            y_val_text = f"{y_val:.4e}" if abs(y_val) >= 1e-3 or y_val == 0 else f"{y_val:.4e}"
        
        self.label.setText(f'X: {x_val_text}, Y: {y_val_text}')
    
    def _format_x_values(self, left_val_x, right_val_x, x_pos, left_bound_x, right_bound_x):
        """Format X values handling lists, single values, and NaN values"""
        # Convert to numpy arrays if they aren't already
        if not isinstance(left_val_x, (list, tuple, np.ndarray)):
            left_val_x = [left_val_x]
        if not isinstance(right_val_x, (list, tuple, np.ndarray)):
            right_val_x = [right_val_x]
            
        left_val_x = np.array(left_val_x)
        right_val_x = np.array(right_val_x)
        
        # Handle case where arrays have different lengths
        min_len = min(len(left_val_x), len(right_val_x))
        left_val_x = left_val_x[:min_len]
        right_val_x = right_val_x[:min_len]
        
        x_values = []
        for i in range(len(left_val_x)):
            left_val = left_val_x[i]
            right_val = right_val_x[i]
            
            # Handle NaN values
            if np.isnan(left_val) or np.isnan(right_val):
                x_values.append("NaN")
            else:
                # Interpolate between left and right values
                x_pos_slope = self.slope(left_bound_x, left_val, right_bound_x, right_val)
                x_val = (x_pos - left_bound_x) * x_pos_slope + left_val
                
                # Format the value
                if abs(x_val) >= 1e-3 or x_val == 0:
                    x_values.append(f"{x_val:.4e}")
                else:
                    x_values.append(f"{x_val:.4e}")
        
        # Join multiple values with commas
        if len(x_values) == 1:
            return x_values[0]
        else:
            return "[" + ", ".join(x_values) + "]"

    def slope(self,x1, y1, x2, y2): 
        if(x2 - x1 != 0): 
            # return (float)(y2-y1)/(x2-x1) 
            return (y2-y1)/(x2-x1)
        return 0 

    def plot_line(self,current_target_index):
        # Update the data point
        reversed_current_target_index=[]
        for i in reversed(current_target_index):
            reversed_current_target_index.append(i)
        index_tuple = tuple(reversed_current_target_index[0:len(current_target_index) - self.setter_level_number])
        self.y_coordinates[current_target_index[self.setter_level_number]] = self.data[self.setter_level_number][self.getter_number][index_tuple]
        
        # Remove existing data line if it exists
        if hasattr(self, 'line') and self.line is not None:
            try:
                self.plot.removeItem(self.line)
            except (ValueError, RuntimeError):
                # Item might already be removed or invalid
                pass
        
        # Check if v_line exists and is valid
        v_line_exists = hasattr(self, 'v_line') and self.v_line is not None
        
        if v_line_exists:
            try:
                # Test if v_line is still valid by accessing its position
                _ = self.v_line.pos()
            except (AttributeError, RuntimeError):
                v_line_exists = False
            
        if not v_line_exists:
            # Only create v_line if it doesn't exist or is invalid
            if hasattr(self, 'v_line') and self.v_line is not None:
                try:
                    self.plot.removeItem(self.v_line)
                except (ValueError, RuntimeError):
                    pass
                    
            self.v_line = pg.InfiniteLine(angle=90, movable=True)
            self.plot.addItem(self.v_line)
            self.v_line.sigPositionChanged.connect(self.update_label)
        
        # Add the updated data line
        self.line = self.plot.plot(list(self.x_coordinates), list(self.y_coordinates), pen=pg.mkPen(color=(240, 255, 255), width=2))

    def load_plot(self,data,target_index):
        target_index=target_index[self.setter_level_number::]
        reversed_current_target_index = target_index[::-1]
        # for i in target_index[::-1]:
        #     reversed_current_target_index.append(i)
        # index_list = list(reversed_current_target_index[0:len(target_index) - self.setter_level_number])
        # temp = data[self.setter_level_number][self.getter_number]
        self.y_coordinates = np.array(data[self.setter_level_number][self.getter_number])
        while True:
            if self.y_coordinates.ndim > 1:
                self.y_coordinates = self.y_coordinates[-1]
            else:
                break

        # Remove existing data line if it exists
        if hasattr(self, 'line') and self.line is not None:
            try:
                self.plot.removeItem(self.line)
            except (ValueError, RuntimeError):
                # Item might already be removed or invalid
                pass
        
        # Add the new data line (preserve v_line)
        try:
            self.line = self.plot.plot(list(self.x_coordinates), self.y_coordinates, pen=pg.mkPen(color=(240, 255, 255), width=2))
        except Exception as e:
            print(e)


class CustomROI(pg.ROI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)  # Only accept left mouse button

    def hoverEvent(self, ev):
        # Override hoverEvent to disable the yellow hover effect
        if ev.isExit():
            self.currentPen = self.pen
        else:
            self.currentPen = self.pen
        self.update()

class ImagePlot(pg.GraphicsLayoutWidget):

    def __init__(self,coordinate=None,x_setting_info=None,y_setting_info=None,level_info = None):
        super().__init__()
        self.data = np.zeros((1, 1))
        self.viewport().setAttribute(QtCore.Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
        self.x_name=coordinate['x']
        self.y_name=coordinate['y']
        self.z_name=coordinate['z']

        self.xy_label = self.addLabel('', row=1, col=0)
        # self.y_label = self.addLabel('', row=1, col=1)
        self.z_label = self.addLabel('', row=2, col=0)
        
        self.x_level_number=int(self.x_name[-1])
        self.y_level_number=int(self.y_name[-1])

        self.getter_number=int(self.z_name[3])
        self.is_full=False

        self.x_setting_info = x_setting_info
        self.y_setting_info = y_setting_info

        #set which point is plotting
        self.current_x = 0
        self.current_y = 0

        self.x_interpolate = False
        self.y_interpolate = False
        #data
        self.plot = self.addPlot(row=0, col=0)


        self.x_step = 1
        self.y_step = 1
        self.x_start = 0
        self.x_start = 0
        
        y_datashape = len(list(self.y_setting_info.values())[0])
        x_datashape = len(list(self.x_setting_info.values())[0])

        self.data_shape = [y_datashape, x_datashape]

        self.data = np.full((self.data_shape[0],self.data_shape[1]),np.nan)

        # Image plot panel
        self.image = pg.ImageItem(image = self.data)
        self.image.setRect(QtCore.QRectF(-0.5 * self.x_step, -0.5 * self.y_step, self.data.shape[1] * self.x_step, self.data.shape[0] * self.y_step))
        self.plot.addItem(self.image)
        [self.plot.getAxis(ax).setZValue(10) for ax in self.plot.axes]

        #roi
        self.roi = CustomROI([0, 0], [self.x_step, self.y_step], snapSize=min(self.x_step, self.y_step), pen=pg.mkPen(color=(0, 0, 0, 0)))
        self.roi.addTranslateHandle([0.5, 0.5])
        self.plot.addItem(self.roi)

        # Colourmap bar
        self.cbar = pg.HistogramLUTItem(image=self.image)
        self.cbar.gradient.loadPreset('viridis')
        self.addItem(self.cbar, row=0, col=1)
        self.plot.setLabel('left',self.y_name)
        self.plot.setLabel('bottom',self.x_name)
        self.plot.setLabel('top',self.z_name)

        #infinite lines
        self.v_line = pg.InfiniteLine(angle=90, movable=True)
        self.h_line = pg.InfiniteLine(angle=0, movable=True)
        # self.v_line.setValue(0)
        # self.h_line.setValue(0)
        self.plot.addItem(self.v_line, ignoreBounds=True)
        self.plot.addItem(self.h_line, ignoreBounds=True)
        self.roi.sigRegionChanged.connect(self.update_lines_from_roi)
        self.h_line.sigPositionChanged.connect(self.update_roi_from_lines)
        self.v_line.sigPositionChanged.connect(self.update_roi_from_lines)

        self.update_lines_from_roi()
        self.update_roi_text()



    def update_lines_from_roi(self):
        center = self.roi.pos() + self.roi.size() / 2
        self.h_line.setPos(center.y())
        self.v_line.setPos(center.x())
        self.update_roi_text()

    def update_roi_from_lines(self):
        center = QtCore.QPointF(self.v_line.pos().x(), self.h_line.pos().y())
        size = self.roi.size()
        top_left = center - size / 2
        self.roi.blockSignals(True)
        self.roi.setPos(top_left)
        self.roi.blockSignals(False)
        self.update_roi_text()

    def update_roi_text(self):
        pos = self.roi.pos() + self.roi.size() / 2
        x, y = pos.x(), pos.y()
        x1 = math.floor(x)
        x2 = math.ceil(x)
        y1 = math.floor(y)
        y2 = math.ceil(y)

        # Handle bounds checking
        x_out_of_bounds = x1 < 0 or x2 > self.data.shape[1] - 1
        y_out_of_bounds = y1 < 0 or y2 > self.data.shape[0] - 1
        
        # Format X values
        if x_out_of_bounds:
            x_text = 'Out of bounds'
        else:
            x_text = self._format_xy_values(self.x_setting_info, x1, x2, x, 'x')
        
        # Format Y values  
        if y_out_of_bounds:
            y_text = 'Out of bounds'
        else:
            y_text = self._format_xy_values(self.y_setting_info, y1, y2, y, 'y')
        
        # Combine X and Y text
        xy_label_text = f'X: {x_text},     Y: {y_text}'
        self.xy_label.setText(xy_label_text)

        # Handle Z value
        try:
            if x_out_of_bounds or y_out_of_bounds:
                self.z_label.setText('Out of bounds')
            else:
                value = self.data[int(y), int(x)]
                if np.isnan(value):
                    self.z_label.setText('Value: NaN')
                else:
                    self.z_label.setText(f'Value: {value:.4e}')
        except IndexError:
            self.z_label.setText('Out of bounds')
        return
    
    def _format_xy_values(self, setting_info, coord1, coord2, coord_pos, axis_name):
        """Format X or Y values handling lists, single values, and NaN values"""
        values = []
        
        for setter, setting_points in setting_info.items():
            try:
                # Handle bounds checking for this setter
                if coord1 < 0 or coord1 >= len(setting_points) or coord2 >= len(setting_points):
                    values.append("OOB")
                    continue
                    
                val_1 = setting_points[coord1]
                val_2 = setting_points[coord2]
                
                # Convert to numpy arrays if they aren't already
                if not isinstance(val_1, (list, tuple, np.ndarray)):
                    val_1 = [val_1]
                if not isinstance(val_2, (list, tuple, np.ndarray)):
                    val_2 = [val_2]
                    
                val_1 = np.array(val_1)
                val_2 = np.array(val_2)
                
                # Handle case where arrays have different lengths
                min_len = min(len(val_1), len(val_2))
                val_1 = val_1[:min_len]
                val_2 = val_2[:min_len]
                
                # Process each component
                component_values = []
                for i in range(len(val_1)):
                    v1, v2 = val_1[i], val_2[i]
                    
                    # Handle NaN values
                    if np.isnan(v1) or np.isnan(v2):
                        component_values.append("NaN")
                    else:
                        # Interpolate between the two values
                        interpolated = (coord_pos - coord1) * (v2 - v1) + v1
                        
                        # Format the value
                        if abs(interpolated) >= 1e-3 or interpolated == 0:
                            component_values.append(f"{interpolated:.4e}")
                        else:
                            component_values.append(f"{interpolated:.4e}")
                
                # Join multiple components with commas if more than one
                if len(component_values) == 1:
                    values.append(component_values[0])
                else:
                    values.append("[" + ", ".join(component_values) + "]")
                    
            except (IndexError, TypeError, ValueError):
                values.append("Error")
        
        # Join values from different setters
        if len(values) == 1:
            return values[0]
        else:
            return " | ".join(values)
    

    def keyPressEvent(self, event):
        pos = self.roi.pos()
        x, y = pos.x(), pos.y()
        step = 0.1  # Step size for each key press
        if event.key() == QtCore.Qt.Key.Key_Right and x < self.data.shape[1] * self.x_step - step - 0.5 * self.x_step:
            self.roi.setPos([x + step, y])
        elif event.key() == QtCore.Qt.Key.Key_Left and x > -0.5 * self.x_step + step:
            self.roi.setPos([x - step, y])
        elif event.key() == QtCore.Qt.Key.Key_Up and y > -0.5 * self.y_step + step:
            self.roi.setPos([x, y - step])
        elif event.key() == QtCore.Qt.Key.Key_Down and y < self.data.shape[0] * self.y_step - step - 0.5 * self.y_step:
            self.roi.setPos([x, y + step])
        self.update_lines_from_roi()


    def update_image(self,new_data,current_target_index):
        if (np.isnan(self.data[-1,-1]))==0:
            
            self.is_full=True
            self.data = np.full((self.data_shape[0],self.data_shape[1]),np.nan)
        current_y=current_target_index[self.x_level_number]
        current_x=current_target_index[self.y_level_number]
        reversed_current_target_index=[]
        for i in reversed(current_target_index):
            reversed_current_target_index.append(i)
        index_list = reversed_current_target_index[0:len(current_target_index) - self.x_level_number]
        index_tuple = tuple(index_list)

        self.data[current_x, current_y] = new_data[self.x_level_number][self.getter_number][index_tuple]

        self.image.setImage(self.data)


    def load_image(self, data, target_index):
        temp = data[self.x_level_number][self.getter_number]

        # Properly walk down the levels
        target_index = target_index[self.y_level_number+1:]

        for idx in target_index:
            temp = temp[idx]
        
        self.data = np.array(temp)

        # Final sanity check (optional, good for debugging)
        if self.data.ndim != 2:
            print(f"Warning: expected 2D array but got shape {self.data.shape}")

        # Set the image
        self.image.setImage(self.data)




class AllPlots(QtWidgets.QWidget):
    sig_info_changed = QtCore.pyqtSignal(object)

    def __init__(self, level_info=None, *, page_number: int = 0):
        super().__init__()
        uic.loadUi("core/ui/all_plots.ui", self)

        self.level_info = level_info or copy.deepcopy(ScanInfo['levels'])
        self.plot_setting_info = None
        self.page_number = page_number        # <── new
        self.grid_size = []
        self.data = None

    def sr830_xyrt_output(self,xyrt):
        self.xyrt=deepcopy(xyrt)
        for i in range(self.plots_layout.count()):
            w= self.plots_layout.itemAt(i).widget()
            w.sr830_xyrt_output(self.xyrt)

    def set_level_info(self, info):
        self.level_info = info

    def receive_plot_info(self, plot_setting_info):
        self.plot_setting_info = plot_setting_info
    
    
    def update_plots(self):    
        """Re-draw every time level-info or plot-settings change."""

        # 0.  How many plots per page right now?
        root = self.window()                      # Scan widget
        ppp = root.findChild(QtWidgets.QComboBox, "PlotsPerPage")

        ppp_setting = ppp.currentText()
        if ppp_setting == "2x1":
            per_page = 2
        elif ppp_setting == "2x2":
            per_page = 4
        elif ppp_setting == "2x4":
            per_page = 8
        elif ppp_setting == "3x3":
            per_page = 9
        elif ppp_setting == "3x4":
            per_page = 12
        else:
            per_page = 4

        # 1.  Flatten every defined plot into one list
        all_coords: list[tuple[str, dict]] = []
        if self.plot_setting_info:
            all_coords += [("line",  c)
                           for c in self.plot_setting_info["line_plots"].values()]
            all_coords += [("image", c)
                           for c in self.plot_setting_info["image_plots"].values()]

        start = self.page_number * per_page
        end   = start + per_page
        subset = all_coords[start:end]            # slice for *this* page

        # 2.  Clear any existing widgets
        while self.plots_layout.count():
            self.plots_layout.takeAt(0).widget().deleteLater()

        # 3.  Decide grid size from per_page
        if   per_page == 2:  self.grid_size = [2, 1]
        elif per_page == 4:  self.grid_size = [2, 2]
        elif per_page == 8:  self.grid_size = [2, 4]    
        elif per_page == 9:  self.grid_size = [3, 3]
        elif per_page == 12: self.grid_size = [3, 4]
        else:                self.grid_size = [2, 2]   # per_page == 4

        # 4.  Create widgets
        row = col = 0
        for kind, coord in subset:
            x_name = coord['x']; y_name = coord['y']

            if kind == "line":
                if x_name in ('None', '') or y_name in ('None', ''):
                    continue
                setting = self.get_setting_info_line(coord)
                w = LinePlot(coordinate=coord, setting_info=setting, data=self.data)
            else:
                z_name = coord.get('z', '')
                if x_name in ('None', '') or y_name in ('None', '') or z_name in ('None', ''):
                    continue
                x_set, y_set = self.get_setting_info_image(coord)
                w = ImagePlot(coordinate=coord, x_setting_info=x_set,
                              y_setting_info=y_set, level_info=self.level_info)

            self.plots_layout.addWidget(w, row, col)
            col += 1
            if col >= self.grid_size[1]:
                col = 0
                row += 1

    def get_setting_info_line(self,coordinate):
        x_name=coordinate['x']
        match_level = re.search(r'L(\d+)', x_name)

        if match_level:
            level_number = match_level.group(1)
            level = f'level{level_number}'
            setting_array=self.level_info[level]['setting_array']
            #might need to change this S to G
            match_setter = re.search(r'S(\d+)', x_name)
            setter_number = match_setter.group(1)
            
            return setting_array[int(setter_number)]
        else:
            level=f'level{x_name[-1]}'
            setting_array=self.level_info[level]['setting_array']
            return setting_array
        
    def get_setting_info_image(self,coordinate):
        x_name=coordinate['x']
        x_level=f'level{x_name[-1]}'
        x_setting_array=self.level_info[x_level]['setting_array']
        x_setters=[]
        for setter,setter_info in self.level_info[x_level]['setters'].items():
            x_setters.append(setter_info['channel'])
        x_setting_dict={}
        for i,setter in enumerate(x_setters):
            x_setting_dict[setter] = x_setting_array[i]

        y_name=coordinate['y']
        y_level=f'level{y_name[-1]}'
        y_setting_array=self.level_info[y_level]['setting_array']
        y_setters=[]
        for setter,setter_info in self.level_info[y_level]['setters'].items():
            y_setters.append(setter_info['channel'])
        y_setting_dict={}
        for i,setter in enumerate(y_setters):
            y_setting_dict[setter] = y_setting_array[i]


        return [x_setting_dict,y_setting_dict]
        


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = AllPlots()
    window.show()
    app.exec()
