#!/usr/bin/env python3
"""Write and check zmeter Shift Compensation mapping CSVs.

Standard library only (the optional --plot needs matplotlib).

A mapping CSV has one header row and two numeric columns:

    column 1: source value, in the units of the source readback
    column 2: amount to ADD to the target channel so the target stays on the
              same physical position when the source sits at that value

Write one CSV per source -> target pair from a shift table:

    python write_mapping_csv.py --table 0066_reflection_shift_vs_QWP.csv \
        --source-column angle --source-name k10cr1_0_angle \
        --map dx_V:qwp_to_ni6423_AO0.csv:-1:ni6423_AO0 \
        --map dy_V:qwp_to_ni6423_AO1.csv:-1:ni6423_AO1

``--map COLUMN:OUTPUT[:FACTOR[:TARGET_NAME]]`` multiplies COLUMN by FACTOR
(default 1).  Use -1 when the table holds the shift applied to align an
image (the correction is the opposite sign), -0.001 when it is also in mV.

Check an existing file:

    python write_mapping_csv.py --check qwp_to_ni6423_AO0.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
import tempfile

MIN_POINTS = 2


class MappingError(ValueError):
    pass


def _number(text):
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _open_table(path):
    handle = open(path, "r", encoding="utf-8-sig", newline="")
    sample = handle.read(4096)
    handle.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return handle, csv.reader(handle, dialect)


def read_table_columns(path, columns):
    """Return {column: [float, ...]} for the named header columns."""

    handle, reader = _open_table(path)
    with handle:
        rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise MappingError(f"{path}: empty table")
    header = [cell.strip() for cell in rows[0]]
    missing = [name for name in columns if name not in header]
    if missing:
        raise MappingError(
            f"{path}: column(s) {missing} not found; header is {header}"
        )
    index = {name: header.index(name) for name in columns}
    result = {name: [] for name in columns}
    skipped = 0
    for line, row in enumerate(rows[1:], start=2):
        values = {}
        for name, position in index.items():
            values[name] = _number(row[position]) if position < len(row) else None
        if any(value is None for value in values.values()):
            skipped += 1
            continue
        for name, value in values.items():
            result[name].append(value)
    if skipped:
        print(f"note: {path}: skipped {skipped} row(s) with missing or non-numeric values")
    return result


def validate_points(source, shift):
    if len(source) != len(shift):
        raise MappingError("source and shift have different lengths")
    if len(source) < MIN_POINTS:
        raise MappingError(f"a mapping needs at least {MIN_POINTS} points")
    for value in list(source) + list(shift):
        if not isinstance(value, float) or not math.isfinite(value):
            raise MappingError(f"non-finite value {value!r}")
    warnings = []
    if len(set(source)) != len(source):
        warnings.append("repeated source values (fine for fitting, check it is intended)")
    if list(source) != sorted(source):
        warnings.append("source values are not sorted")
    return warnings


def write_mapping_csv(path, source, shift, source_name="source", target_name="target"):
    """Write the two-column file atomically and return validation warnings."""

    source = [float(v) for v in source]
    shift = [float(v) for v in shift]
    warnings = validate_points(source, shift)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=".mapping_", suffix=".csv", dir=folder)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow([source_name, f"add_to_{target_name}"])
            for x, y in zip(source, shift):
                writer.writerow([repr(x), repr(y)])
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
    return warnings


def read_mapping_csv(path):
    """Read a mapping CSV with the same rules as zmeter's loader."""

    handle, reader = _open_table(path)
    source, shift = [], []
    with handle:
        first = True
        for line, row in enumerate(reader, start=1):
            cells = [cell.strip() for cell in row]
            if not any(cells):
                continue
            values = [_number(cell) for cell in cells[:2]]
            numeric = len(values) == 2 and None not in values
            if first:
                first = False
                if not numeric:
                    continue
            if not numeric:
                raise MappingError(f"{path}: line {line}: expected two numbers, got {row!r}")
            source.append(values[0])
            shift.append(values[1])
    validate_points(source, shift)
    return source, shift


def summary(source, shift):
    return (
        f"{len(source)} points, source {min(source):g} to {max(source):g}, "
        f"shift {min(shift):.6g} to {max(shift):.6g} "
        f"(peak to peak {max(shift) - min(shift):.6g})"
    )


def parse_map(text):
    parts = text.split(":")
    # Allow Windows drive letters in OUTPUT (C:\...).
    if len(parts) >= 3 and len(parts[1]) == 1 and parts[2].startswith(("\\", "/")):
        parts = [parts[0], parts[1] + ":" + parts[2], *parts[3:]]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise argparse.ArgumentTypeError(
            "use COLUMN:OUTPUT[:FACTOR[:TARGET_NAME]]"
        )
    factor = 1.0
    if len(parts) >= 3 and parts[2] != "":
        factor = _number(parts[2])
        if factor is None or factor == 0:
            raise argparse.ArgumentTypeError(f"bad factor {parts[2]!r}")
    target_name = parts[3] if len(parts) >= 4 and parts[3] else parts[0]
    return parts[0], parts[1], factor, target_name


def plot(paths, image):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"note: no plot ({exc})")
        return
    fig, ax = plt.subplots(figsize=(6, 4))
    for path in paths:
        source, shift = read_mapping_csv(path)
        ax.plot(source, shift, "o-", ms=3, label=os.path.basename(path))
    ax.set_xlabel("source value")
    ax.set_ylabel("amount added to target")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(image, dpi=120)
    print(f"plot: {image}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--table", help="input shift table (CSV with a header row)")
    parser.add_argument("--source-column", help="table column with the source value")
    parser.add_argument("--source-name", help="header for column 1 (default: source column)")
    parser.add_argument(
        "--map",
        action="append",
        type=parse_map,
        default=[],
        metavar="COLUMN:OUTPUT[:FACTOR[:TARGET_NAME]]",
        help="one mapping CSV per target column; repeat for several targets",
    )
    parser.add_argument("--check", nargs="+", metavar="CSV", help="validate mapping CSVs")
    parser.add_argument("--plot", metavar="PNG", help="save a check plot of the written or checked files")
    args = parser.parse_args(argv)

    written = []
    try:
        if args.check:
            for path in args.check:
                source, shift = read_mapping_csv(path)
                print(f"ok: {path}: {summary(source, shift)}")
            written = list(args.check)
        elif args.table and args.source_column and args.map:
            columns = [args.source_column] + [column for column, *_ in args.map]
            table = read_table_columns(args.table, list(dict.fromkeys(columns)))
            source = table[args.source_column]
            source_name = args.source_name or args.source_column
            for column, output, factor, target_name in args.map:
                shift = [factor * value for value in table[column]]
                warnings = write_mapping_csv(output, source, shift, source_name, target_name)
                print(f"wrote: {output}: {column} x {factor:g}: {summary(source, shift)}")
                for warning in warnings:
                    print(f"warning: {output}: {warning}")
                written.append(output)
        else:
            parser.error("give --check FILES, or --table, --source-column and --map")
    except (OSError, MappingError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.plot and written:
        plot(written, args.plot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
