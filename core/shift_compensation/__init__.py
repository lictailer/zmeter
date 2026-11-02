"""Shift Compensation: cancel reproducible cross-talk between scan channels.

A mapping relates a source channel (for example a waveplate angle) to the
shift it causes on a target channel (for example a galvo voltage).  Active
mappings publish ``compensated_source_<channel>`` and
``compensated_target_<channel>`` scan channels.  See
``documents/shift_compensation.md``.
"""
