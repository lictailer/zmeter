"""Channel selection widgets. Construction never accesses instruments."""
from PyQt6 import QtWidgets
from .measurement_io import Channel


class ChannelPicker(QtWidgets.QWidget):
    def __init__(self, access):
        super().__init__()
        self.access, self.catalog = access, {}
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.device, self.channel = QtWidgets.QComboBox(), QtWidgets.QComboBox()
        layout.addWidget(self.device)
        layout.addWidget(self.channel)
        self.device.currentTextChanged.connect(self._device_changed)

    def ref(self):
        return Channel(self.device.currentText(), self.channel.currentText())

    def set_ref(self, ref):
        self.device.blockSignals(True)
        self.device.clear()
        self.device.addItems(sorted(set(self.catalog) | {ref.device}))
        self.device.setCurrentText(ref.device)
        self.device.blockSignals(False)
        self.channel.clear()
        self.channel.addItems(sorted(set(self.catalog.get(ref.device, {}).get(self.access, ())) | {ref.channel}))
        self.channel.setCurrentText(ref.channel)

    def refresh(self, catalog):
        ref, self.catalog = self.ref(), catalog
        self.set_ref(ref)

    def _device_changed(self, device):
        self.channel.clear()
        self.channel.addItems(sorted(self.catalog.get(device, {}).get(self.access, ())))
