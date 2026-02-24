from __future__ import annotations

import json
from typing import Callable

from PyQt6 import QtCore, QtWidgets, uic

from .artificial_channel_logic import ArtificialChannelLogic
from .nested_menu import NestedMenu


class ArtificialChannel2D(QtWidgets.QWidget):
    def __init__(
        self,
        logic: ArtificialChannelLogic,
        setter_equipment_info: dict,
        on_config_applied: Callable[[], None] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        uic.loadUi("core/ui/artificial_channel_2D.ui", self)
        self.setWindowFlag(QtCore.Qt.WindowType.Window, True)
        self.setWindowModality(QtCore.Qt.WindowModality.NonModal)

        self.logic = logic
        self._on_config_applied = on_config_applied
        self._available_original_channels: set[str] = set()

        self._install_nested_menus(setter_equipment_info)
        self._connect_signals()
        self._load_from_logic_config()
        self._update_state_labels(self.logic.state)
        self.setWindowTitle("artificial channel 2D")

    def _install_nested_menus(self, setter_equipment_info: dict):
        channel_choices = []
        self._available_original_channels = set()
        for equipment_name, channel_names in setter_equipment_info.items():
            if equipment_name in ("artificial_channel", "default"):
                continue
            channel_choices.append({equipment_name: channel_names})
            for channel_name in channel_names:
                self._available_original_channels.add(
                    f"{equipment_name}_{channel_name}"
                )
        if not channel_choices:
            channel_choices = [{"none": ["none"]}]

        self.ocx_nested_menu = NestedMenu(order=24)
        self.ocx_nested_menu.label.setText("x: ")
        self.ocx_nested_menu.set_choices(channel_choices)

        self.ocy_nested_menu = NestedMenu(order=25)
        self.ocy_nested_menu.label.setText("y: ")
        self.ocy_nested_menu.set_choices(channel_choices)

        self.gridLayout.replaceWidget(self.OCx_nest, self.ocx_nested_menu)
        self.gridLayout.replaceWidget(self.OCy_nest, self.ocy_nested_menu)
        self.OCx_nest.deleteLater()
        self.OCy_nest.deleteLater()

    def _connect_signals(self):
        self.setconfig_pushButton.clicked.connect(self._on_set_config_clicked)
        self.setvalue_pushButton.clicked.connect(self._on_set_value_clicked)
        if hasattr(self, "saveconfig_pushButton"):
            self.saveconfig_pushButton.clicked.connect(self._on_save_config_clicked)
        if hasattr(self, "loadconfig_pushButton"):
            self.loadconfig_pushButton.clicked.connect(self._on_load_config_clicked)
        self.logic.sig_state_changed.connect(self._update_state_labels)

    def _load_from_logic_config(self):
        self.ocx_nested_menu.set_chosen_one(self.logic.original_channel_x_name)
        self.ocy_nested_menu.set_chosen_one(self.logic.original_channel_y_name)

        self.artificialchannelnamex_textEdit.setPlainText(
            self.logic.artificial_channel_x_name
        )
        self.artificialchannelnamey_textEdit.setPlainText(
            self.logic.artificial_channel_y_name
        )

        coordinate_pairs = self.logic.default_coordinate_pairs
        if hasattr(self.logic, "coordinate_pairs"):
            coordinate_pairs = self.logic.coordinate_pairs

        pair_spinboxes = [
            (
                self.pair1_OCx_doubleSpinBox,
                self.pair1_OCy_doubleSpinBox,
                self.pair1_ACx_doubleSpinBox,
                self.pair1_ACy_doubleSpinBox,
            ),
            (
                self.pair2_OCx_doubleSpinBox,
                self.pair2_OCy_doubleSpinBox,
                self.pair2_ACx_doubleSpinBox,
                self.pair2_ACy_doubleSpinBox,
            ),
            (
                self.pair3_OCx_doubleSpinBox,
                self.pair3_OCy_doubleSpinBox,
                self.pair3_ACx_doubleSpinBox,
                self.pair3_ACy_doubleSpinBox,
            ),
        ]

        for pair_widget, pair_value in zip(pair_spinboxes, coordinate_pairs):
            (ocx_box, ocy_box, acx_box, acy_box) = pair_widget
            (oc_xy, ac_xy) = pair_value
            ocx_box.setValue(float(oc_xy[0]))
            ocy_box.setValue(float(oc_xy[1]))
            acx_box.setValue(float(ac_xy[0]))
            acy_box.setValue(float(ac_xy[1]))

        x_low, x_high = self.logic.original_channel_limits[
            self.logic.original_channel_x_name
        ]
        y_low, y_high = self.logic.original_channel_limits[
            self.logic.original_channel_y_name
        ]
        self.OCx_lowlimit_doubleSpinBox.setValue(x_low)
        self.OCx_highlimit_doubleSpinBox.setValue(x_high)
        self.OCy_lowlimit_doubleSpinBox.setValue(y_low)
        self.OCy_highlimit_doubleSpinBox.setValue(y_high)

        self._update_config_labels()

    def _on_set_config_clicked(self) -> bool:
        original_channel_x_name = self.ocx_nested_menu.name.strip()
        original_channel_y_name = self.ocy_nested_menu.name.strip()
        if original_channel_x_name == "":
            original_channel_x_name = self.logic.original_channel_x_name
        if original_channel_y_name == "":
            original_channel_y_name = self.logic.original_channel_y_name

        artificial_channel_x_name = self.artificialchannelnamex_textEdit.toPlainText().strip()
        artificial_channel_y_name = self.artificialchannelnamey_textEdit.toPlainText().strip()
        if artificial_channel_x_name == "":
            artificial_channel_x_name = self.logic.artificial_channel_x_name
        if artificial_channel_y_name == "":
            artificial_channel_y_name = self.logic.artificial_channel_y_name

        coordinate_pairs = (
            (
                (
                    self.pair1_OCx_doubleSpinBox.value(),
                    self.pair1_OCy_doubleSpinBox.value(),
                ),
                (
                    self.pair1_ACx_doubleSpinBox.value(),
                    self.pair1_ACy_doubleSpinBox.value(),
                ),
            ),
            (
                (
                    self.pair2_OCx_doubleSpinBox.value(),
                    self.pair2_OCy_doubleSpinBox.value(),
                ),
                (
                    self.pair2_ACx_doubleSpinBox.value(),
                    self.pair2_ACy_doubleSpinBox.value(),
                ),
            ),
            (
                (
                    self.pair3_OCx_doubleSpinBox.value(),
                    self.pair3_OCy_doubleSpinBox.value(),
                ),
                (
                    self.pair3_ACx_doubleSpinBox.value(),
                    self.pair3_ACy_doubleSpinBox.value(),
                ),
            ),
        )

        x_limits = (
            self.OCx_lowlimit_doubleSpinBox.value(),
            self.OCx_highlimit_doubleSpinBox.value(),
        )
        y_limits = (
            self.OCy_lowlimit_doubleSpinBox.value(),
            self.OCy_highlimit_doubleSpinBox.value(),
        )

        try:
            self.logic.apply_configuration(
                original_channel_x_name=original_channel_x_name,
                original_channel_y_name=original_channel_y_name,
                artificial_channel_x_name=artificial_channel_x_name,
                artificial_channel_y_name=artificial_channel_y_name,
                coordinate_pairs=coordinate_pairs,
                original_channel_x_limits=x_limits,
                original_channel_y_limits=y_limits,
            )
        except Exception as exc:
            print(f"[ArtificialChannel2D] Set config failed: {exc}")
            QtWidgets.QMessageBox.warning(self, "Set Config Failed", str(exc))
            return False

        self._update_config_labels()
        if self._on_config_applied is not None:
            self._on_config_applied()
        return True

    def _on_set_value_clicked(self):
        try:
            self.logic.set_artificial_channel_values(
                self.ACx_setvalue_doubleSpinBox.value(),
                self.ACy_setvalue_doubleSpinBox.value(),
            )
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Set Value Failed", str(exc))

    def _get_current_config_for_save(self) -> dict:
        coordinate_pairs = []
        for original_xy, artificial_xy in self.logic.coordinate_pairs:
            coordinate_pairs.append(
                [
                    [float(original_xy[0]), float(original_xy[1])],
                    [float(artificial_xy[0]), float(artificial_xy[1])],
                ]
            )

        original_x_limits = self.logic.original_channel_limits[
            self.logic.original_channel_x_name
        ]
        original_y_limits = self.logic.original_channel_limits[
            self.logic.original_channel_y_name
        ]
        artificial_x_limits = self.logic.artificial_channel_limits[
            self.logic.artificial_channel_x_name
        ]
        artificial_y_limits = self.logic.artificial_channel_limits[
            self.logic.artificial_channel_y_name
        ]

        return {
            "original_channels": {
                "x": self.logic.original_channel_x_name,
                "y": self.logic.original_channel_y_name,
            },
            "artificial_channels": {
                "x": self.logic.artificial_channel_x_name,
                "y": self.logic.artificial_channel_y_name,
            },
            "coordinate_pairs": coordinate_pairs,
            "original_channel_limits": {
                "x": [float(original_x_limits[0]), float(original_x_limits[1])],
                "y": [float(original_y_limits[0]), float(original_y_limits[1])],
            },
            "artificial_channel_limits": {
                "x": [float(artificial_x_limits[0]), float(artificial_x_limits[1])],
                "y": [float(artificial_y_limits[0]), float(artificial_y_limits[1])],
            },
            "equations": {
                "forward_x": self.logic.equations.get(
                    self.logic.artificial_channel_x_name, "Unknown"
                ),
                "forward_y": self.logic.equations.get(
                    self.logic.artificial_channel_y_name, "Unknown"
                ),
                "inverse_x": self.logic.inverse_equations.get(
                    self.logic.original_channel_x_name, "Unknown"
                ),
                "inverse_y": self.logic.inverse_equations.get(
                    self.logic.original_channel_y_name, "Unknown"
                ),
            },
        }

    def _on_save_config_clicked(self):
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Artificial Channel 2D Config",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if file_path == "":
            return
        if not file_path.lower().endswith(".json"):
            file_path = f"{file_path}.json"

        try:
            config = self._get_current_config_for_save()
            with open(file_path, "w", encoding="utf-8") as handle:
                json.dump(config, handle, indent=2)
        except Exception as exc:
            print(f"[ArtificialChannel2D] Save config failed: {exc}")
            return

        print(f"[ArtificialChannel2D] Config saved to '{file_path}'.")

    def _on_load_config_clicked(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load Artificial Channel 2D Config",
            "",
            "JSON Files (*.json);;All Files (*)",
        )
        if file_path == "":
            return

        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                config = json.load(handle)

            original_channels = config["original_channels"]
            artificial_channels = config["artificial_channels"]
            coordinate_pairs_raw = config["coordinate_pairs"]
            original_limits = config["original_channel_limits"]

            original_channel_x_name = str(original_channels["x"])
            original_channel_y_name = str(original_channels["y"])
            artificial_channel_x_name = str(artificial_channels["x"])
            artificial_channel_y_name = str(artificial_channels["y"])

            if (
                original_channel_x_name not in self._available_original_channels
                or original_channel_y_name not in self._available_original_channels
            ):
                missing = [
                    name
                    for name in (original_channel_x_name, original_channel_y_name)
                    if name not in self._available_original_channels
                ]
                print(
                    "[ArtificialChannel2D] Load config failed: original channel(s) not available: "
                    f"{missing}"
                )
                return

            if len(coordinate_pairs_raw) != 3:
                raise ValueError("coordinate_pairs must contain exactly 3 pairs.")

            coordinate_pairs = []
            for pair in coordinate_pairs_raw:
                original_xy = pair[0]
                artificial_xy = pair[1]
                coordinate_pairs.append(
                    (
                        (float(original_xy[0]), float(original_xy[1])),
                        (float(artificial_xy[0]), float(artificial_xy[1])),
                    )
                )

            x_limits = (
                float(original_limits["x"][0]),
                float(original_limits["x"][1]),
            )
            y_limits = (
                float(original_limits["y"][0]),
                float(original_limits["y"][1]),
            )
        except Exception as exc:
            print(f"[ArtificialChannel2D] Load config failed: {exc}")
            return

        try:
            self.ocx_nested_menu.set_chosen_one(original_channel_x_name)
            self.ocy_nested_menu.set_chosen_one(original_channel_y_name)
            self.artificialchannelnamex_textEdit.setPlainText(artificial_channel_x_name)
            self.artificialchannelnamey_textEdit.setPlainText(artificial_channel_y_name)

            pair_spinboxes = [
                (
                    self.pair1_OCx_doubleSpinBox,
                    self.pair1_OCy_doubleSpinBox,
                    self.pair1_ACx_doubleSpinBox,
                    self.pair1_ACy_doubleSpinBox,
                ),
                (
                    self.pair2_OCx_doubleSpinBox,
                    self.pair2_OCy_doubleSpinBox,
                    self.pair2_ACx_doubleSpinBox,
                    self.pair2_ACy_doubleSpinBox,
                ),
                (
                    self.pair3_OCx_doubleSpinBox,
                    self.pair3_OCy_doubleSpinBox,
                    self.pair3_ACx_doubleSpinBox,
                    self.pair3_ACy_doubleSpinBox,
                ),
            ]

            for widget_group, pair_value in zip(pair_spinboxes, coordinate_pairs):
                (ocx_box, ocy_box, acx_box, acy_box) = widget_group
                (oc_xy, ac_xy) = pair_value
                ocx_box.setValue(float(oc_xy[0]))
                ocy_box.setValue(float(oc_xy[1]))
                acx_box.setValue(float(ac_xy[0]))
                acy_box.setValue(float(ac_xy[1]))

            self.OCx_lowlimit_doubleSpinBox.setValue(float(x_limits[0]))
            self.OCx_highlimit_doubleSpinBox.setValue(float(x_limits[1]))
            self.OCy_lowlimit_doubleSpinBox.setValue(float(y_limits[0]))
            self.OCy_highlimit_doubleSpinBox.setValue(float(y_limits[1]))

            if not self._on_set_config_clicked():
                print(
                    "[ArtificialChannel2D] Load config failed: imported values could not be applied."
                )
                return
        except Exception as exc:
            print(f"[ArtificialChannel2D] Load config apply failed: {exc}")
            return

        print(f"[ArtificialChannel2D] Config loaded from '{file_path}'.")

    def _update_config_labels(self):
        self.ACx_label.setText(self.logic.artificial_channel_x_name)
        self.ACy_label.setText(self.logic.artificial_channel_y_name)
        self.OCx_label.setText(self.logic.original_channel_x_name)
        self.OCy_label.setText(self.logic.original_channel_y_name)

        self.equation1_label.setText(
            self.logic.equations.get(self.logic.artificial_channel_x_name, "Unknown")
        )
        self.equation2_label.setText(
            self.logic.equations.get(self.logic.artificial_channel_y_name, "Unknown")
        )
        self.equation3_label.setText(
            self.logic.inverse_equations.get(self.logic.original_channel_x_name, "Unknown")
        )
        self.equation4_label.setText(
            self.logic.inverse_equations.get(self.logic.original_channel_y_name, "Unknown")
        )

        x_low, x_high = self.logic.artificial_channel_limits[
            self.logic.artificial_channel_x_name
        ]
        y_low, y_high = self.logic.artificial_channel_limits[
            self.logic.artificial_channel_y_name
        ]
        self.ACx_limit_label.setText(f"[{x_low:.6f}, {x_high:.6f}]")
        self.ACy_limit_label.setText(f"[{y_low:.6f}, {y_high:.6f}]")

        self.ACx_setvalue_doubleSpinBox.setRange(x_low, x_high)
        self.ACy_setvalue_doubleSpinBox.setRange(y_low, y_high)

    def _update_state_labels(self, state: dict):
        self._update_config_labels()

        acx = state.get(self.logic.artificial_channel_x_name, "Unknown")
        acy = state.get(self.logic.artificial_channel_y_name, "Unknown")
        ocx = state.get(self.logic.original_channel_x_name, "Unknown")
        ocy = state.get(self.logic.original_channel_y_name, "Unknown")

        self.ACx_value_label.setText(self._format_value(acx))
        self.ACy_value_label.setText(self._format_value(acy))
        self.OCx_value_label.setText(self._format_value(ocx))
        self.OCy_value_label.setText(self._format_value(ocy))

    @staticmethod
    def _format_value(value):
        if isinstance(value, str):
            return value
        try:
            return f"{float(value):.6f}"
        except Exception:
            return "Unknown"
