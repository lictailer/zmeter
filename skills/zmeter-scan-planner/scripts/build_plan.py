"""Check a compact scan plan and write ZMeter scan setting files.

    python build_plan.py plan.json --system zmeter_system.md [--out FOLDER] [--check]

plan.json is the compact plan described in references/plan_format.md.
zmeter_system.md is the export from ZMeter's Setup capture window; its JSON
block lists the channels and range limits the plan is checked against.

One scan and nothing else is written as scan_setting_<name>.json (open it with
Load in a scan window). Anything else is written as a queue folder holding
queue.json and one scan setting file per scan (open it with Load queue in the
Scan List). Any problem stops the script before anything is written, and an
existing file or folder is never overwritten.

Array getters (spectra, camera images; listed under array_getters in the
export) may only be getters of plan level0. The written file then starts with
ZMeter's locked fixed levels, one per array axis, and every plan level moves up
by that many levels, exactly as picking the getter in a scan window does.

Standard library only: this copies ZMeter's file format instead of importing
it. The zmeter repository's tests load this script's output with ZMeter's own
code, so the copy is checked against the real format.
"""

import argparse
import datetime
import json
import math
import os
import re
import shutil
import sys

EXPORT_FORMAT = "zmeter_system"
QUEUE_FILE = "queue.json"
QUEUE_FORMAT = "zmeter_queue"
QUEUE_VERSION = 1
SCAN_SETTING_PREFIX = "scan_setting_"
PLOTS_PER_PAGE = "4"
MAX_ARRAY_DIMS = 2
FIXED_AXIS_KEY = "fixed_axis"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
NAN = float("nan")

_AVERAGE_TOKEN = re.compile(r"^level(\d+)_average_(.+)$")
_METHOD_TEXT = re.compile(r"^[A-Za-z+,\s]*$")
_UNSAFE_FILE_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class PlanError(Exception):
    """The plan cannot be written; args[0] is the list of problems."""


# ------------------------------------------------------------------ export --

def read_system(path):
    """The JSON block of a ZMeter system export."""
    with open(path, "r", encoding="utf-8") as file:
        text = file.read()
    for block in re.findall(r"```json\s*\n(.*?)\n```", text, re.DOTALL):
        try:
            info = json.loads(block)
        except ValueError:
            continue
        if isinstance(info, dict) and info.get("format") == EXPORT_FORMAT:
            return info
    raise ValueError(f"{path} has no ZMeter system JSON block; export it again from Setup capture")


def _names(channels):
    return {name for names in (channels or {}).values() for name in names}


def array_getters(system):
    """{channel: {"axes": [...], "shape": [...], "units": str}} from the export."""
    output = {}
    for entry in system.get("array_getters") or []:
        if isinstance(entry, dict) and entry.get("channel"):
            output[entry["channel"]] = entry
    return output


def _shape(entry):
    shape = entry.get("shape") if isinstance(entry, dict) else None
    if (
        isinstance(shape, list)
        and 1 <= len(shape) <= MAX_ARRAY_DIMS
        and all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in shape)
    ):
        return tuple(shape)
    return None


def scan_array_getters(scan, arrays):
    """The array getters of the scan's level0, in plan order."""
    levels = scan.get("levels") or []
    first = levels[0] if levels and isinstance(levels[0], dict) else {}
    getters = first.get("getters") or []
    return [g for g in getters if isinstance(g, str) and g in arrays] if isinstance(getters, list) else []


# ------------------------------------------------------------------ checks --

def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _setter_values(setter):
    """The setter's destinations as floats (linear: start to end in points)."""
    if "values" in setter:
        return [float(value) for value in setter["values"]]
    start, end, points = float(setter["start"]), float(setter["end"]), int(setter["points"])
    if points == 1:
        return [start]
    # As numpy.linspace, which ZMeter uses: start + i * step, last point exactly end.
    step = (end - start) / (points - 1)
    return [start + index * step for index in range(points - 1)] + [end]


def _check_setter(setter, where, setter_names, problems):
    if not isinstance(setter, dict):
        problems.append(f"{where}: must be an object")
        return False
    channel = setter.get("channel")
    if channel not in setter_names:
        problems.append(f"{where}: channel {channel!r} is not a setter channel in the export")
    if "values" in setter:
        values = setter["values"]
        if not isinstance(values, list) or not values or not all(_number(v) for v in values):
            problems.append(f"{where}: values must be a non-empty list of numbers")
            return False
    else:
        if not (_number(setter.get("start")) and _number(setter.get("end"))):
            problems.append(f"{where}: needs numeric start and end, or a values list")
            return False
        points = setter.get("points")
        if not isinstance(points, int) or isinstance(points, bool) or points < 1:
            problems.append(f"{where}: points must be a whole number of at least 1")
            return False
    return True


def _check_limits(channel, values, where, limits, problems):
    bounds = limits.get(channel)
    if bounds is None:
        return
    low, high = bounds
    outside = [v for v in values if (low is not None and v < low) or (high is not None and v > high)]
    if outside:
        problems.append(
            f"{where}: {channel} value {outside[0]:g} is outside the range limit "
            f"[{'-inf' if low is None else f'{low:g}'}, {'+inf' if high is None else f'{high:g}'}]"
        )


def _check_manual_set(entry, where, setter_names, limits, problems):
    if not isinstance(entry, dict) or entry.get("channel") not in setter_names:
        channel = entry.get("channel") if isinstance(entry, dict) else entry
        problems.append(f"{where}: channel {channel!r} is not a setter channel in the export")
    elif not _number(entry.get("value")):
        problems.append(f"{where}: value must be a number")
    else:
        _check_limits(entry["channel"], [float(entry["value"])], where, limits, problems)


def _check_manual_sets(entries, where, setter_names, limits, problems):
    if not isinstance(entries, list):
        problems.append(f"{where}: must be a list")
        return
    for index, entry in enumerate(entries):
        _check_manual_set(entry, f"{where} #{index + 1}", setter_names, limits, problems)


def _check_scan(scan, where, setter_names, getter_names, limits, problems, arrays=None):
    arrays = arrays or {}
    if not str(scan.get("name") or "").strip():
        problems.append(f"{where}: needs a name")
    levels = scan.get("levels")
    if not isinstance(levels, list) or not levels:
        problems.append(f"{where}: needs at least one level")
        return
    direct = []
    for number, level in enumerate(levels):
        place = f"{where} level{number}"
        if not isinstance(level, dict):
            problems.append(f"{place}: must be an object")
            direct.append(set())
            continue
        setters = level.get("setters")
        if not isinstance(setters, list) or not setters:
            problems.append(f"{place}: needs at least one setter (use default_count to repeat or default_wait to wait)")
            setters = []
        if len(setters) > len(LETTERS):
            problems.append(f"{place}: at most {len(LETTERS)} setters")
        for index, setter in enumerate(setters[: len(LETTERS)]):
            setter_place = f"{place} setter {LETTERS[index]}"
            if _check_setter(setter, setter_place, setter_names, problems):
                _check_limits(setter.get("channel"), _setter_values(setter), setter_place, limits, problems)
        method = level.get("setting_method") or ""
        if not isinstance(method, str) or not _METHOD_TEXT.match(method):
            problems.append(f"{place}: setting_method may hold only setter letters, '+' and ','")
        else:
            unknown = sorted({c.upper() for c in method if c.isalpha()} - set(LETTERS[: len(setters)]))
            if unknown:
                problems.append(f"{place}: setting_method names setter(s) {', '.join(unknown)} that the level does not have")
        getters = level.get("getters", [])
        if not isinstance(getters, list):
            problems.append(f"{place}: getters must be a list")
            getters = []
        own = set()
        for getter in getters:
            average = _AVERAGE_TOKEN.match(getter) if isinstance(getter, str) else None
            if average:
                source = int(average.group(1))
                if average.group(2) in arrays:
                    problems.append(
                        f"{place}: {getter} averages an array getter; the planner does not write "
                        "array averages (add it in the scan window after loading)"
                    )
                elif source >= number or average.group(2) not in direct[source]:
                    problems.append(
                        f"{place}: {getter} needs {average.group(2)} as a getter of a lower level{source}"
                    )
            elif getter not in getter_names:
                problems.append(f"{place}: getter {getter!r} is not a getter channel in the export")
            elif getter in arrays and number != 0:
                problems.append(
                    f"{place}: {getter} is an array getter; it can only be a getter of level0 "
                    "(the innermost level)"
                )
            else:
                own.add(getter)
        direct.append(own)
        for key in ("settle_time", "start_wait_time"):
            value = level.get(key, 0)
            if not _number(value) or value < 0:
                problems.append(f"{place}: {key} must be a number of seconds, 0 or more")
        for key in ("manual_set_before", "manual_set_after"):
            _check_manual_sets(level.get(key, []), f"{place} {key}", setter_names, limits, problems)
    shapes = {}
    for getter in scan_array_getters(scan, arrays):
        shape = _shape(arrays[getter])
        if shape is None:
            problems.append(
                f"{where}: the export has no usable shape for array getter {getter} "
                f"(at most {MAX_ARRAY_DIMS} axes; connect the device and export again)"
            )
        else:
            shapes[getter] = shape
    if len(set(shapes.values())) > 1:
        listed = ", ".join(f"{g} {list(s)}" for g, s in shapes.items())
        problems.append(f"{where}: array getters of one scan must share one shape ({listed})")
    for index, plot in enumerate(scan.get("plots", []) or []):
        _check_plot(plot, f"{where} plot {index}", levels, problems, arrays)


def _check_plot(plot, where, levels, problems, arrays=None):
    arrays = arrays or {}
    if not isinstance(plot, dict) or plot.get("type") not in ("line", "image"):
        problems.append(f"{where}: type must be 'line' or 'image'")
        return
    number = plot.get("level")
    if not isinstance(number, int) or not 0 <= number < len(levels) or not isinstance(levels[number], dict):
        problems.append(f"{where}: level must be a level number of this scan")
        return
    level = levels[number]
    getters = level.get("getters") or []
    channel = plot.get("y") if plot["type"] == "line" else plot.get("z")
    if channel in arrays:
        if number != 0 or channel not in getters:
            problems.append(f"{where}: {channel} is an array getter; plot it at level 0, where it is a getter")
        elif plot["type"] == "line" and plot.get("x") not in ("axis", "level"):
            problems.append(f"{where}: x of an array line plot must be 'axis' (its axis values) or 'level' (index)")
        return
    if plot["type"] == "line":
        channels = [s.get("channel") for s in level.get("setters") or [] if isinstance(s, dict)]
        if plot.get("x") != "level" and plot.get("x") not in channels:
            problems.append(f"{where}: x must be 'level' or a setter channel of level{number}")
        if plot.get("y") not in getters:
            problems.append(f"{where}: y must be a getter of level{number}")
    else:
        if number + 1 >= len(levels):
            problems.append(f"{where}: an image plot needs a level above level{number}")
        if plot.get("z") not in getters:
            problems.append(f"{where}: z must be a getter of level{number}")


def check_plan(plan, system):
    """Return the list of problems; empty means the plan can be written."""
    setter_names = _names(system.get("setter_channels"))
    getter_names = _names(system.get("getter_channels"))
    limits = {
        limit["channel"]: (limit.get("low"), limit.get("high"))
        for limit in system.get("limits", [])
    }
    arrays = array_getters(system)
    problems = []
    items = plan.get("items") if isinstance(plan, dict) else None
    if not isinstance(items, list) or not items:
        return ["the plan needs a non-empty items list"]
    for position, item in enumerate(items, start=1):
        where = f"item {position}"
        kind = item.get("type") if isinstance(item, dict) else None
        if kind == "scan":
            _check_scan(
                item, f"{where} ({item.get('name') or 'scan'})",
                setter_names, getter_names, limits, problems, arrays,
            )
        elif kind == "manual_set":
            _check_manual_set(item, f"{where} (manual set)", setter_names, limits, problems)
        else:
            problems.append(f"{where}: type must be 'scan' or 'manual_set'")
    return problems


# --------------------------------------------------------------- building --

def _parse_method(text):
    """'A+B,C' -> [['A', 'B'], 'C'] (as ZMeter's Brakets)."""
    out = []
    for chunk in re.split(r"\s*,\s*", text.strip()):
        if not chunk:
            continue
        parts = [part.upper() for part in re.split(r"\s*\+\s*", chunk) if part]
        out.append(parts if len(parts) > 1 else parts[0])
    return out


def setting_array(method, destinations):
    """Rows = setters A, B, ...; columns = points.  Segments separated by ','
    run one after another; letters joined by '+' move together.  Without a
    method every setter runs in its own segment (A,B,C).  Unused cells are NaN.
    """
    letters = list(destinations)
    tree = _parse_method(method if method else ",".join(letters))

    def length(node, parallel):
        if isinstance(node, list):
            sizes = [length(sub, not parallel and isinstance(sub, list)) for sub in node]
            return (max(sizes, default=0)) if parallel else sum(sizes)
        return len(destinations.get(node, []))

    rows = [[NAN] * length(tree, False) for _ in letters]

    def fill(node, start, parallel):
        if isinstance(node, list):
            if parallel:
                for sub in node:
                    fill(sub, start, False)
            else:
                column = start
                for sub in node:
                    fill(sub, column, isinstance(sub, list))
                    column += length(sub, isinstance(sub, list))
            return
        values = destinations.get(node)
        if values:
            rows[letters.index(node)][start:start + len(values)] = values

    fill(tree, 0, False)
    return rows


def _setter_entry(setter):
    values = _setter_values(setter)
    explicit = "values" in setter
    start, end = (values[0], values[-1]) if explicit else (float(setter["start"]), float(setter["end"]))
    points = len(values)
    linear = values if not explicit else _setter_values({"start": start, "end": end, "points": points})
    return {
        "channel": setter["channel"],
        "explicit": explicit,
        "linear_setting": {
            "start": start,
            "end": end,
            "step": (end - start) / (points - 1) if points > 1 else 0,
            "mid": (start + end) / 2,
            "span": end - start,
            "points": points,
            "destinations": linear,
        },
        "explicit_setting": values if explicit else [start, end],
        "destinations": values,
    }


def _shift_getter(getter, shift):
    average = _AVERAGE_TOKEN.match(getter)
    if average is None or not shift:
        return getter
    return f"level{int(average.group(1)) + shift}_average_{average.group(2)}"


def _level_getters(level, arrays, shift):
    """A user level's getters without array getters, averages moved up by shift."""
    getters = [_shift_getter(g, shift) for g in level.get("getters") or [] if g not in arrays]
    return getters or ["none"]


def _fixed_level(channel, axis, name, count, units, getters):
    """One locked fixed level (as ZMeter's core/array_levels.build_fixed_level).

    Its values are pixel indices; ZMeter replaces them with the device's axis
    calibration (for example wavelengths) when the scan starts.
    """
    values = [float(i) for i in range(count)]
    last = max(count - 1, 0)
    return {
        "setters": {
            "setter0": {
                "channel": "none",
                "explicit": True,
                "linear_setting": {
                    "start": 0,
                    "end": last,
                    "step": 1,
                    "mid": last / 2,
                    "span": last,
                    "points": count,
                    "destinations": list(range(count)),
                },
                "explicit_setting": list(values),
                "destinations": list(values),
            }
        },
        "setting_method": "",
        "getters": list(getters),
        "setting_array": [list(values)],
        "settle_time": 0.0,
        "start_wait_time": 0.0,
        "manual_set_before": [],
        "manual_set_after": [],
        FIXED_AXIS_KEY: {"channel": channel, "axis": axis, "name": name, "units": units},
    }


def fixed_levels(scan, arrays):
    """The fixed levels a scan's array getters need (lowest first)."""
    tokens = scan_array_getters(scan, arrays)
    if not tokens:
        return []
    entry = arrays[tokens[0]]
    shape = _shape(entry)
    axes = list(entry.get("axes") or [])
    axes += [f"axis{i}" for i in range(len(axes), len(shape))]
    output = []
    for level_index in range(len(shape)):
        axis = len(shape) - 1 - level_index
        getters = tokens if level_index == 0 else ["none"]
        output.append(_fixed_level(tokens[0], axis, axes[axis], shape[axis], str(entry.get("units") or ""), getters))
    return output


def _level_entry(level, arrays=None, shift=0):
    setters = level["setters"]
    method = (level.get("setting_method") or "").replace(" ", "")
    destinations = {LETTERS[i]: _setter_values(setter) for i, setter in enumerate(setters)}
    return {
        "setters": {f"setter{i}": _setter_entry(setter) for i, setter in enumerate(setters)},
        "setting_method": method,
        "getters": _level_getters(level, arrays or {}, shift),
        "setting_array": setting_array(method, destinations),
        "settle_time": float(level.get("settle_time", 0.0)),
        "start_wait_time": float(level.get("start_wait_time", 0.0)),
        "manual_set_before": [{m["channel"]: float(m["value"])} for m in level.get("manual_set_before") or []],
        "manual_set_after": [{m["channel"]: float(m["value"])} for m in level.get("manual_set_after") or []],
    }


def _plots(scan, arrays=None):
    arrays = arrays or {}
    line_plots, image_plots = {}, {}
    levels = scan["levels"]
    array_tokens = scan_array_getters(scan, arrays)
    shift = len(fixed_levels(scan, arrays))
    for plot in scan.get("plots") or []:
        channel = plot["y"] if plot["type"] == "line" else plot["z"]
        if channel in arrays:
            token = f"L0G{array_tokens.index(channel)}_{channel}"
            if plot["type"] == "line":
                x = "L0S0_none" if plot["x"] == "axis" else "level0"
                line_plots[str(len(line_plots))] = {"x": x, "y": token}
            else:
                image_plots[str(len(image_plots))] = {"x": "level0", "y": "level1", "z": token}
            continue
        number = plot["level"]
        level = number + shift
        getters = _level_getters(levels[number], arrays, shift)
        if plot["type"] == "line":
            if plot["x"] == "level":
                x = f"level{level}"
            else:
                channels = [s["channel"] for s in levels[number]["setters"]]
                x = f"L{level}S{channels.index(plot['x'])}_{plot['x']}"
            y_token = _shift_getter(plot["y"], shift)
            y = f"L{level}G{getters.index(y_token)}_{y_token}"
            line_plots[str(len(line_plots))] = {"x": x, "y": y}
        else:
            z_token = _shift_getter(plot["z"], shift)
            z = f"L{level}G{getters.index(z_token)}_{z_token}"
            image_plots[str(len(image_plots))] = {"x": f"level{level}", "y": f"level{level + 1}", "z": z}
    return {"line_plots": line_plots, "image_plots": image_plots}


def scan_setting(scan, arrays=None):
    """A scan in the form ZMeter's Save setting writes (no data, empty log).

    ``arrays`` is ``array_getters(system)``; array getters of level0 become
    fixed levels below the plan's levels.
    """
    arrays = arrays or {}
    fixed = fixed_levels(scan, arrays)
    user = [_level_entry(level, arrays, len(fixed)) for level in scan["levels"]]
    comments = str(scan.get("comments") or "").strip()
    minutes = scan.get("estimated_minutes")
    if _number(minutes):
        comments = (comments + "\n" if comments else "") + f"Estimated duration: about {minutes:g} min (planner estimate)."
    return {
        "levels": {f"level{i}": level for i, level in enumerate(fixed + user)},
        "data": {},
        "plots": _plots(scan, arrays),
        "name": str(scan["name"]).strip(),
        "plots_per_page": PLOTS_PER_PAGE,
        "comments": comments,
        "scan_log": [],
    }


# ---------------------------------------------------------------- writing --

def _file_stem(name):
    stem = _UNSAFE_FILE_CHARACTERS.sub("_", str(name or "")).strip(" .")
    return stem or "scan"


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, separators=(",", ":"))


def write_plan(plan, out_folder, system=None):
    """Write the plan's files into out_folder; returns the path written."""
    items = plan["items"]
    arrays = array_getters(system or {})
    if len(items) == 1 and items[0]["type"] == "scan":
        payload = scan_setting(items[0], arrays)
        path = os.path.join(out_folder, f"{SCAN_SETTING_PREFIX}{_file_stem(payload['name'])}.json")
        if os.path.exists(path):
            raise FileExistsError(f"{path} already exists")
        temporary = f"{path}.{os.getpid()}.tmp"
        try:
            _write_json(temporary, payload)
            os.replace(temporary, path)
        except BaseException:
            if os.path.exists(temporary):
                os.remove(temporary)
            raise
        return path

    name = plan.get("name") or datetime.datetime.now().strftime("%Y%m%d_%H%M")
    folder = os.path.join(out_folder, f"queue_{_file_stem(name)}")
    if os.path.exists(folder):
        raise FileExistsError(f"{folder} already exists")
    width = max(2, len(str(len(items))))
    temporary = f"{folder}.{os.getpid()}.tmp"
    os.makedirs(temporary)
    try:
        entries = []
        for position, item in enumerate(items, start=1):
            if item["type"] == "scan":
                payload = scan_setting(item, arrays)
                file_name = f"{position:0{width}d}_{_file_stem(payload['name'])}.json"
                _write_json(os.path.join(temporary, file_name), payload)
                entries.append({"scan": file_name})
            else:
                entries.append({"manual_set": {"channel": item["channel"], "value": float(item["value"])}})
        _write_json(
            os.path.join(temporary, QUEUE_FILE),
            {"format": QUEUE_FORMAT, "version": QUEUE_VERSION, "items": entries},
        )
        os.replace(temporary, folder)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return folder


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("plan", help="compact plan JSON file")
    parser.add_argument("--system", required=True, help="zmeter_system.md exported by ZMeter")
    parser.add_argument("--out", help="folder to write into (default: the export's data folder if it exists, else the current folder)")
    parser.add_argument("--check", action="store_true", help="only check the plan; write nothing")
    args = parser.parse_args(argv)

    with open(args.plan, "r", encoding="utf-8") as file:
        plan = json.load(file)
    system = read_system(args.system)
    problems = check_plan(plan, system)
    if problems:
        print(f"Plan not written: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    if args.check:
        print("Plan OK (nothing written).")
        return 0
    out_folder = args.out
    if not out_folder:
        exported = system.get("data_folder") or ""
        out_folder = exported if exported and os.path.isdir(exported) else os.getcwd()
    path = write_plan(plan, out_folder, system)
    print(f"Written: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
