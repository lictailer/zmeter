"""Opt-in, unique run bundles. No Qt, hardware, pyplot or lab path defaults.

Each file is atomically replaced only inside a newly reserved unique run folder.
Matplotlib rendering is serialized across coordinators and uses the Agg canvas.
"""
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import threading
import uuid

import numpy as np

_render_lock = threading.RLock()


class RunRecord:
    def __init__(self, directory, kind):
        if not str(directory).strip():
            raise ValueError("Choose a results directory")
        root = Path(directory).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        self.path = root / f"{kind}-{stamp}-{uuid.uuid4().hex[:8]}"
        self.path.mkdir(exist_ok=False)
        self.json("run.json", {"status": "started", "kind": kind, "created_utc": stamp})

    def bytes(self, name, payload):
        if Path(name).name != name:
            raise ValueError("Run filenames must not contain directory components")
        target = self.path / name
        temporary = self.path / f".{name}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def json(self, name, payload):
        self.bytes(name, json.dumps(payload, indent=2, allow_nan=False).encode("utf-8"))

    def array(self, name, data):
        stream = io.BytesIO()
        np.save(stream, np.asarray(data), allow_pickle=False)
        self.bytes(name, stream.getvalue())

    def figure(self, name, draw):
        with _render_lock:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            figure = Figure(figsize=(7, 5), layout="constrained")
            FigureCanvasAgg(figure)
            draw(figure)
            stream = io.BytesIO()
            figure.savefig(stream, format="png", dpi=140)
            self.bytes(name, stream.getvalue())
            figure.clear()

    def curve(self, samples, unit, fit=None):
        if not samples:
            return
        def draw(figure):
            ax = figure.add_subplot()
            points = sorted((s.position, s.score) for s in samples)
            x, y = zip(*points)
            ax.plot(x, y, "o-", label="Measured score")
            if fit is not None:
                xs = np.linspace(min(x), max(x), 401)
                ax.plot(xs, fit.values(xs), label="Gaussian fit")
                ax.axvline(fit.center, color="tab:orange", linestyle="--", label="Fitted center")
            ax.set(xlabel=f"Z ({unit})", ylabel="Focus score / mean input signal", title="Autofocus: score versus Z")
            ax.legend()
        self.figure("focus_curve.png", draw)

    def map(self, name, image, xs=None, ys=None, point=None, title="Measured map", units=("X", "Y")):
        image = np.asarray(image)
        if image.ndim == 3:
            image = image[:, :, :3].mean(axis=2)
        def draw(figure):
            ax = figure.add_subplot()
            if xs is None:
                artist = ax.imshow(image, origin="lower", aspect="auto")
            else:
                artist = ax.pcolormesh(xs, ys, image, shading="nearest")
            if point is not None:
                ax.plot(*point, "r+", markersize=12, markeredgewidth=2)
            ax.set(xlabel=units[0], ylabel=units[1], title=title)
            figure.colorbar(artist, ax=ax, label="Input signal")
        self.figure(name, draw)
