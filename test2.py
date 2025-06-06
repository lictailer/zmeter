import sys
from PyQt6 import QtWidgets, QtCore
import pyqtgraph as pg
import numpy as np
from scipy.interpolate import interp2d

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
    def __init__(self, data, x_label, y_label, z_label, x_step=1.0, y_step=1.0):
        super().__init__()
        
        self.x_step = x_step
        self.y_step = y_step
        
        # Set up the layout
        self.layout = QtWidgets.QVBoxLayout()
        
        # Add a label for displaying coordinates and value
        self.label = QtWidgets.QLabel()
        self.layout.addWidget(self.label)
        
        # Set up the data and plot
        self.data = data
        self.plot = self.addPlot(row=0, col=0)
        self.image = pg.ImageItem(image=self.data)
        
        # Adjust the image position so pixels are centered
        self.image.setRect(QtCore.QRectF(-0.5 * self.x_step, -0.5 * self.y_step, data.shape[1] * self.x_step, data.shape[0] * self.y_step))
        
        self.plot.addItem(self.image)
        self.plot.setLabels(left=y_label, bottom=x_label, top=z_label)
        
        # Set tick marks to follow step size
        x_ticks = [(i * self.x_step, str(i * self.x_step)) for i in range(data.shape[1] + 1)]
        y_ticks = [(i * self.y_step, str(i * self.y_step)) for i in range(data.shape[0] + 1)]
        self.plot.getAxis('bottom').setTicks([x_ticks])
        self.plot.getAxis('left').setTicks([y_ticks])
        
        # Create and add the CustomROI
        self.roi = CustomROI([0, 0], [self.x_step, self.y_step], snapSize=min(self.x_step, self.y_step), pen=pg.mkPen(color=(0, 0, 0, 0)))
        self.roi.addTranslateHandle([0.5, 0.5])  # Increase the size of the TranslateHandle
        
        self.plot.addItem(self.roi)

        # Create and add the infinite lines
        self.h_line = pg.InfiniteLine(angle=0, movable=True)
        self.v_line = pg.InfiniteLine(angle=90, movable=True)
        self.plot.addItem(self.h_line)
        self.plot.addItem(self.v_line)
        
        # Create the interpolation function
        x = np.arange(data.shape[1]) * self.x_step
        y = np.arange(data.shape[0]) * self.y_step
        self.interp_func = interp2d(x, y, data, kind='cubic')

        # Connect signals
        self.roi.sigRegionChanged.connect(self.update_lines_from_roi)
        self.h_line.sigPositionChanged.connect(self.update_roi_from_lines)
        self.v_line.sigPositionChanged.connect(self.update_roi_from_lines)
        
        # Update the label with initial ROI position
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
        # Adjust coordinates to account for pixel center
        if -0.5 * self.x_step <= x < (self.data.shape[1] - 0.5) * self.x_step and -0.5 * self.y_step <= y < (self.data.shape[0] - 0.5) * self.y_step:
            value = self.interp_func(x, y)[0]
            self.label.setText(f'Coordinates: ({x:.4e}, {y:.4e}), Value: {value:.4e}')
        else:
            self.label.setText('Out of bounds')
    
    def keyPressEvent(self, event):
        pos = self.roi.pos()
        x, y = pos.x(), pos.y()
        step = 0.1  # Step size for each key press
        if event.key() == QtCore.Qt.Key.Key_Right and x < self.data.shape[1] * self.x_step - step:
            self.roi.setPos([x + step, y])
        elif event.key() == QtCore.Qt.Key.Key_Left and x > -0.5 * self.x_step + step:
            self.roi.setPos([x - step, y])
        elif event.key() == QtCore.Qt.Key.Key_Up and y > -0.5 * self.y_step + step:
            self.roi.setPos([x, y - step])
        elif event.key() == QtCore.Qt.Key.Key_Down and y < self.data.shape[0] * self.y_step - step:
            self.roi.setPos([x, y + step])
        self.update_lines_from_roi()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    data = np.array([
        [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
        [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5],
        [-0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0],
        [-1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
        [-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
        [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5],
        [-2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0],
        [-3.0, -2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5],
        [-3.5, -3.0, -2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0],
        [-4.0, -3.5, -3.0, -2.5, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5]
    ])
    window = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(window)
    plot_widget = ImagePlot(data, 'LOSO_artificial_channel_A', 'L1SO_artificial_channel_B', 'LOG1_lockin_0_aux_2', x_step=1, y_step=1)
    layout.addWidget(plot_widget)
    layout.addWidget(plot_widget.label)
    window.show()
    sys.exit(app.exec())
