import sys
import os
import copy
import time
from PyQt6 import QtWidgets, QtCore, QtGui, uic
import pyqtgraph as pg
import numpy as np
from pathlib import Path
import math
import datetime
from .brakets import Brakets
import re
from copy import deepcopy
import json
import tkinter as tk
from tkinter import filedialog
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QFileDialog,
    QVBoxLayout,
    QWidget,
    QTextEdit,
    QLabel,
)
from pptx import Presentation
from pptx.util import Inches, Pt
from PIL import ImageGrab


ScanInfo = {
    "levels": {
        "level0": {
            "setters": {
                "setter0": {
                    "channel": "none",
                    "explicit": False,
                    "linear_setting": {
                        "start": 0,
                        "end": 10,
                        "step": 1,
                        "mid": 5,
                        "span": 10,
                        "points": 11,
                        "destinations": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                    },
                    "explicit_setting": [-1, 1, 0],
                    "destinations": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                },
                "setter1": {
                    "channel": "L0S1dummy2",
                    "explicit": True,
                    "linear_setting": {
                        "start": 0,
                        "end": 100,
                        "step": 1,
                        "mid": 50,
                        "span": 100,
                        "points": 101,
                        "destinations": np.linspace(0, 100, 101),
                    },
                    "explicit_setting": [-2, 2, 0],
                    "destinations": [-2, 2, 0],
                },
            },
            "setting_method": "[AB]",
            "getters": [],
            "setting_array": [],
            "manual_set_before": [],
            "manual_set_after": [],
        },
        "level1": {
            "setters": {
                "setter0": {
                    "channel": "L1S0dummy2",
                    "explicit": False,
                    "linear_setting": {
                        "start": 0,
                        "end": 2,
                        "step": 1,
                        "mid": 1,
                        "span": 2,
                        "points": 3,
                        "destinations": [0, 1, 2],
                    },
                    "explicit_setting": [-2, 2, 0],
                    "destinations": [0, 1, 2],
                }
            },
            "setting_method": "[A]",
            "getters": ["none"],
            "setting_array": [],
            "manual_set_before": [],
            "manual_set_after": [],
        },
    },
    "data": {},
    "plots": {"line_plots": {}, "image_plots": {}},
}


ScanInfo = {
    "levels": {
        "level0": {
            "setters": {
                "setter0": {
                    "channel": "nidaq_0_AO0",
                    "explicit": False,
                    "linear_setting": {
                        "start": -0.5,
                        "end": 0.5,
                        "step": 0.01,
                        "mid": 0,
                        "span": 1,
                        "points": 101,
                        "destinations": np.linspace(-0.5, 0.5, 101),
                    },
                    "explicit_setting": [-1, 1, 0],
                    "destinations": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                },
            },
            "setting_method": "[A]",
            "getters": ["nidaq_0_AI0"],
            "setting_array": [],
            "manual_set_before": [],
            "manual_set_after": [],
        },
        "level1": {
            "setters": {
                "setter0": {
                    "channel": "nidaq_0_AO1",
                    "explicit": False,
                    "linear_setting": {
                        "start": -0.5,
                        "end": 0.5,
                        "step": 0.01,
                        "mid": 0,
                        "span": 1,
                        "points": 101,
                        "destinations": np.linspace(-0.5, 0.5, 101),
                    },
                    "explicit_setting": [-2, 2, 0],
                    "destinations": [0, 1, 2],
                }
            },
            "setting_method": "[A]",
            "getters": [],
            "setting_array": [],
            "manual_set_before": [],
            "manual_set_after": [],
        },
    },
    "data": {},
    "plots": {
        "line_plots": {},
        "image_plots": {"0": {"x": "level0", "y": "level1", "z": "L0G0_nidaq_0_AI1"}},
    },
    "name": "reflection",
}
EquipmentInfo = [
    {"DAQ": ["AI0", "AI1", "AI2"]},
    {"lockin_0": [{"X": 1}, {"Y": 1}, {"R": 1}, {"Theta": 1}, {"time_constant": 10}]},
    {"lockin_1": [{"X": 1}, {"Y": 1}, {"R": 1}, {"Theta": 1}, {"time_constant": 10}]},
    {"lockin_2": [{"X": 1}, {"Y": 1}, {"R": 1}, {"Theta": 1}, {"time_constant": 10}]},
    {"TLPM power(W)": 1},
    {"OptiCool Temperature (K)": 1},
    {"OptiCool Magnetic Field (T)": 1},
]


pg.setConfigOptions(imageAxisOrder="row-major")


def clearLayout(layout):
    while layout.count():
        child = layout.takeAt(0)
        if child.widget():
            child.widget().deleteLater()


def is_float(element: any) -> bool:
    # If you expect None to be passed:
    if element is None:
        return False
    if element == "":
        return False
    try:
        float(element)
        return True
    except ValueError:
        return False
