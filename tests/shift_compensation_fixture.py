"""A fake two-device lab for Shift Compensation tests (no hardware).

``rot_angle`` is a waveplate angle.  ``daq_AO0`` / ``daq_AO1`` steer the
beam; ``daq_AI0`` / ``daq_AI1`` read them back (loopback).  Turning the
waveplate moves the spot, so the spot seen on the sample is
``AO - g(angle)``, where ``g`` is the amount to add to the AO to cancel the
shift (the mapping CSV's second column).
"""

from __future__ import annotations

import math

import numpy as np

from core.channel_value_record import ChannelValueRecord
from core.shift_compensation.logic import (
    SOURCE_GROUP,
    TARGET_GROUP,
    ShiftCompensationLogic,
)


def g_x(angle):
    return 0.02 * np.cos(2 * np.pi * np.asarray(angle, dtype=float) / 180.0 + 0.3) + 0.004


def g_y(angle):
    return -0.015 * np.cos(2 * np.pi * np.asarray(angle, dtype=float) / 180.0 - 1.1)


class FakeArtificialChannelLogic:
    artificial_channels = ()

    def has_artificial_channel(self, _channel):
        return False

    def consume_skip_read_for_scan(self):
        return False

    def reset_skip_next_scan_read(self):
        return None


class FakeLab:
    SETTERS = ("rot_angle", "daq_AO0", "daq_AO1")
    GETTERS = ("rot_angle", "daq_AI0", "daq_AI1", "spot_x", "spot_y")

    def __init__(self, readback_noise=0.0, seed=0):
        self.values = {"rot_angle": 0.0, "daq_AO0": 0.0, "daq_AO1": 0.0}
        self.readback_noise = float(readback_noise)
        self._rng = np.random.default_rng(seed)
        self.writes: list[tuple[str, float]] = []
        self.reads: list[str] = []
        self.denied: dict[str, tuple[float, float]] = {}
        self.equips = {"rot": object(), "daq": object(), "spot": object()}
        self.artificial_channel_logic = FakeArtificialChannelLogic()
        self.channel_value_record = ChannelValueRecord()
        self.shift_compensation_logic = ShiftCompensationLogic(
            write_channel=self.write_info,
            read_channel=self.read_info,
            value_record=self.channel_value_record,
        )
        self.shift_compensation_logic.set_available_channels(self.SETTERS, self.GETTERS)

    @property
    def logic(self) -> ShiftCompensationLogic:
        return self.shift_compensation_logic

    # MainWindow.write_info / read_info stand-ins -----------------------
    def write_info(self, value, channel):
        value = float(value)
        if math.isnan(value):
            return False
        if channel.startswith(f"{SOURCE_GROUP}_"):
            ok = self.logic.write_source(channel[len(SOURCE_GROUP) + 1:], value)
        elif channel.startswith(f"{TARGET_GROUP}_"):
            ok = self.logic.write_target(channel[len(TARGET_GROUP) + 1:], value)
        else:
            if channel not in self.values:
                raise KeyError(channel)
            low, high = self.denied.get(channel, (-math.inf, math.inf))
            if not low <= value <= high:
                return False
            self.values[channel] = value
            self.writes.append((channel, value))
            ok = True
        if ok:
            self.channel_value_record.record_write(channel, value)
        return ok

    def read_info(self, channel):
        if channel.startswith(f"{SOURCE_GROUP}_"):
            value = self.logic.read_source(channel[len(SOURCE_GROUP) + 1:])
        elif channel.startswith(f"{TARGET_GROUP}_"):
            value = self.logic.read_target(channel[len(TARGET_GROUP) + 1:])
        else:
            self.reads.append(channel)
            value = self._physical_read(channel)
        self.channel_value_record.record_read(channel, value)
        return value

    def _noise(self):
        if self.readback_noise == 0:
            return 0.0
        return float(self._rng.normal(0.0, self.readback_noise))

    def _physical_read(self, channel):
        angle = self.values["rot_angle"]
        if channel == "rot_angle":
            return angle
        if channel == "daq_AI0":
            return self.values["daq_AO0"] + self._noise()
        if channel == "daq_AI1":
            return self.values["daq_AO1"] + self._noise()
        if channel == "spot_x":
            return self.values["daq_AO0"] - float(g_x(angle))
        if channel == "spot_y":
            return self.values["daq_AO1"] - float(g_y(angle))
        raise KeyError(channel)

    # helpers ---------------------------------------------------------
    def add_fitted_mapping(self, target_set, target_read, shift, *, activate=True, **kwargs):
        angles = np.arange(0.0, 360.0, 15.0)
        mapping = self.logic.add_mapping()
        self.logic.set_points(mapping.mapping_id, angles, shift(angles), csv_name="test.csv")
        self.logic.update_mapping(
            mapping.mapping_id,
            source_set=kwargs.pop("source_set", "rot_angle"),
            source_read=kwargs.pop("source_read", "rot_angle"),
            target_set=target_set,
            target_read=target_read,
            **kwargs,
        )
        self.logic.fit(mapping.mapping_id, model="cosine", options={"period": 180.0})
        if activate:
            self.logic.activate(mapping.mapping_id)
        return mapping

    def add_xy_mappings(self):
        return (
            self.add_fitted_mapping("daq_AO0", "daq_AI0", g_x),
            self.add_fitted_mapping("daq_AO1", "daq_AI1", g_y),
        )

    def reads_of(self, channel):
        return sum(1 for name in self.reads if name == channel)
