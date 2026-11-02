"""Find and replace scan channels that are missing from the device catalog.

A channel name is the flattened catalog path, as NestedMenu offers it, e.g.
"SR860_0_X". A use is one place a scan or queue item names a channel:

    ChannelUse(kind="setter", channel="SR860_0_X", place="level0 setter A")

kind is the catalog the channel must be in: "setter" for setter channels and
manual sets, "getter" for recorded getters. Nothing here touches hardware.
"""

import re
from collections import namedtuple

import numpy as np

from .array_levels import is_fixed_level

ChannelUse = namedtuple("ChannelUse", "kind channel place")

_SENTINELS = {"", "none", "void"}
_AVERAGE_TOKEN = re.compile(r"^level(\d+)_average_(.+)$")
_PLOT_TOKEN = re.compile(r"^(L\d+)([SG])(\d+_)(.+)$")


def catalog_leaf_names(value, path=()):
    """Yield the channel names a catalog menu offers (see create_menu_for_setter)."""
    if isinstance(value, (list, tuple)):
        for entry in value:
            yield from catalog_leaf_names(entry, path)
        return
    if isinstance(value, dict):
        for key, child in value.items():
            next_path = (*path, str(key))
            if isinstance(child, int):
                yield "_".join(next_path)
            else:
                yield from catalog_leaf_names(child, next_path)
        return
    if value is not None:
        yield "_".join((*path, str(value)))


def catalog_names(catalog):
    return set(catalog_leaf_names(catalog or {}))


def _is_sentinel(channel):
    return not isinstance(channel, str) or channel.strip().lower() in _SENTINELS


def _ordered_levels(info):
    levels = info.get("levels") or {}
    return sorted(levels.items(), key=lambda item: int(re.sub(r"\D", "", item[0]) or 0))


def _direct_getters(level_info):
    return {
        getter
        for getter in level_info.get("getters") or []
        if not _is_sentinel(getter) and not _AVERAGE_TOKEN.match(getter)
    }


def find_unresolved(info, setter_names, getter_names):
    """Return the ChannelUse of every channel in info missing from the catalog.

    An average getter levelN_average_<ch> is resolved when <ch> is a getter of
    the lower level N, as in the level's getter menu.
    """
    levels = _ordered_levels(info)
    direct = {index: _direct_getters(level) for index, (_key, level) in enumerate(levels)}
    uses = []
    for index, (level_key, level) in enumerate(levels):
        for letter, setter in zip(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ", (level.get("setters") or {}).values()
        ):
            channel = setter.get("channel")
            if not _is_sentinel(channel) and channel not in setter_names:
                uses.append(ChannelUse("setter", channel, f"{level_key} setter {letter}"))
        for getter in level.get("getters") or []:
            if _is_sentinel(getter):
                continue
            average = _AVERAGE_TOKEN.match(getter)
            if average:
                source = int(average.group(1))
                resolved = source < index and average.group(2) in direct.get(source, ())
            else:
                resolved = getter in getter_names
            if not resolved:
                uses.append(ChannelUse("getter", getter, f"{level_key} getter"))
        for key in ("manual_set_before", "manual_set_after"):
            for mapping in level.get(key) or []:
                for channel in mapping:
                    if not _is_sentinel(channel) and channel not in setter_names:
                        place = f"{level_key} {key.replace('_', ' ')}"
                        uses.append(ChannelUse("setter", channel, place))
    return uses


def queue_uses(items, setter_names, getter_names, first_position=1):
    """Unresolved uses in queue items, as (queue position, scan name or None, use).

    items are {"scan": info} or {"manual_set": {"channel": ...}}, in queue order.
    """
    found = []
    for position, item in enumerate(items, start=first_position):
        if "scan" in item:
            name = item["scan"].get("name") or "scan"
            for use in find_unresolved(item["scan"], setter_names, getter_names):
                found.append((position, name, use))
        else:
            channel = item["manual_set"]["channel"]
            if not _is_sentinel(channel) and channel not in setter_names:
                found.append((position, None, ChannelUse("setter", channel, "manual set")))
    return found


def where_text(position, name, use):
    """Where a use is, for the fix window: "#4 gate_sweep, level0 setter A"."""
    if name is None:
        return f"#{position} {use.place}"
    return f"#{position} {name}, {use.place}"


def use_line(position, name, use):
    """One log line: '  #4 "gate_sweep" level0 setter A: SR860_0_X'."""
    if name is None:
        return f"  #{position} {use.place}: {use.channel}"
    return f'  #{position} "{name}" {use.place}: {use.channel}'


def group_uses(found):
    """Map (kind, channel) to its where texts, each missing channel once, in order."""
    groups = {}
    for position, name, use in found:
        groups.setdefault((use.kind, use.channel), []).append(
            where_text(position, name, use)
        )
    return groups


def count_text(count, noun):
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _replace_getter(token, getter_map):
    average = _AVERAGE_TOKEN.match(token)
    if average and average.group(2) in getter_map:
        return f"level{average.group(1)}_average_{getter_map[average.group(2)]}"
    return getter_map.get(token, token)


def replace_channels(info, setter_map, getter_map):
    """Rename channels in info in place: setters, getters, averages, manual sets, plots."""
    for _key, level in _ordered_levels(info):
        for setter in (level.get("setters") or {}).values():
            setter["channel"] = setter_map.get(setter.get("channel"), setter.get("channel"))
        level["getters"] = [
            _replace_getter(getter, getter_map) if isinstance(getter, str) else getter
            for getter in level.get("getters") or []
        ]
        for key in ("manual_set_before", "manual_set_after"):
            level[key] = [
                {setter_map.get(channel, channel): value for channel, value in mapping.items()}
                for mapping in level.get(key) or []
            ]
    for plots in (info.get("plots") or {}).values():
        for plot in plots.values():
            for field, token in plot.items():
                match = _PLOT_TOKEN.match(token) if isinstance(token, str) else None
                if match is None:
                    continue
                level, direction, index, channel = match.groups()
                if direction == "S":
                    channel = setter_map.get(channel, channel)
                else:
                    channel = _replace_getter(channel, getter_map)
                plot[field] = f"{level}{direction}{index}{channel}"


def level_problems(info):
    """Return (place, problem) for levels that cannot run: no setter channel or no points.

    A 'none' setter is skipped by the scan engine, so a level whose setters are
    all 'none' would step through its points without setting anything. Use
    default_count or default_wait for a level that only repeats or waits.
    """
    levels = _ordered_levels(info)
    if not levels:
        return [("scan", "has no levels")]
    problems = []
    for level_key, level in levels:
        channels = [s.get("channel") for s in (level.get("setters") or {}).values()]
        # A fixed array-axis level is filled by one array read; it never sets.
        if is_fixed_level(level):
            pass
        elif all(_is_sentinel(channel) for channel in channels):
            problems.append((level_key, "no setter channel"))
        array = np.asarray(level.get("setting_array", []), dtype=float)
        if array.ndim != 2 or array.shape[1] == 0:
            problems.append((level_key, "setting array is empty"))
    problems.extend(array_size_problems(levels))
    return problems


# Above this many stored array values a scan JSON passes ~1 GB.
MAX_ARRAY_SCAN_VALUES = 100_000_000


def array_size_problems(levels):
    """A scan whose array getters would store too many values for JSON."""
    point_counts = []
    for _level_key, level in levels:
        array = np.asarray(level.get("setting_array", []), dtype=float)
        if array.ndim != 2 or array.shape[1] == 0:
            return []
        point_counts.append(int(array.shape[1]))
    if not levels or not is_fixed_level(levels[0][1]):
        return []
    getters = [g for g in levels[0][1].get("getters", []) if g != "none"]
    values = len(getters) * int(np.prod(point_counts, dtype=np.int64))
    if values <= MAX_ARRAY_SCAN_VALUES:
        return []
    return [(
        "scan",
        f"array getters would store {values:,} values (about {values * 10 / 1e9:.1f} GB "
        "of JSON); use fewer points, binning or a smaller read area",
    )]
