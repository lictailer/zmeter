"""Default scan template used when a new scan window is created.

This module only holds the ``ScanInfo`` template. It used to also carry a
large block of shared imports that other modules pulled in with
``from .scan_info import *``; those modules now import what they use
explicitly. Widget helpers live in ``core/widget_helpers.py`` and the global
pyqtgraph configuration lives in ``core/plot_config.py``.
"""

import numpy as np


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
            "setting_method": "A+B,C",
            "getters": ["nidaq_0_AI0"],
            "setting_array": [],
            "settle_time": 0.0,
            "start_wait_time": 0.0,
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
            "setting_method": "A+B,C",
            "getters": [],
            "setting_array": [],
            "settle_time": 0.0,
            "start_wait_time": 0.0,
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
    "plots_per_page": 4,
}
