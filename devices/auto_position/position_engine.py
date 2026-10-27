"""Pure reference-map settings and translation registration. Coordinates are native."""
from dataclasses import asdict, dataclass, field
import math
import uuid

import numpy as np
from core.measurement_io import Channel, count, finite


class PositionStopped(RuntimeError):
    pass


def checkpoint(stop):
    if stop.is_set():
        raise PositionStopped("Auto-position stopped; outputs remain at their last completed commands")


@dataclass(frozen=True)
class MapSettings:
    x: Channel = field(default_factory=lambda: Channel("nidaq", "AO0"))
    y: Channel = field(default_factory=lambda: Channel("nidaq", "AO1"))
    signal: Channel = field(default_factory=lambda: Channel("nidaq", "AI0"))
    x_unit: str = "V"
    y_unit: str = "V"
    x_min: float = -0.05
    x_max: float = 0.05
    y_min: float = -0.05
    y_max: float = 0.05
    x_points: int = 51
    y_points: int = 51
    settle_s: float = 0.01
    samples: int = 1
    sample_interval_s: float = 0.01

    @property
    def xs(self):
        return np.linspace(self.x_min, self.x_max, self.x_points)

    @property
    def ys(self):
        return np.linspace(self.y_min, self.y_max, self.y_points)

    def validate(self):
        for ref in (self.x, self.y, self.signal):
            ref.validate()
        if self.x == self.y or self.signal in (self.x, self.y):
            raise ValueError("X, Y and the measured input must be distinct channels")
        for name in ("x", "y"):
            if finite(getattr(self, name + "_min"), name + " minimum") >= finite(getattr(self, name + "_max"), name + " maximum"):
                raise ValueError("Each map minimum must be below its maximum")
            if not getattr(self, name + "_unit").strip():
                raise ValueError("Specify X and Y native units")
            count(getattr(self, name + "_points"), name + " pixels", 7, 512)
        count(self.samples, "Input readings per pixel", 1, 1000)
        for name in ("settle_s", "sample_interval_s"):
            if finite(getattr(self, name), name) < 0:
                raise ValueError("Wait times must be nonnegative")

    def point(self, point):
        x, y = (finite(v, "Point coordinate") for v in point)
        if not self.x_min <= x <= self.x_max or not self.y_min <= y <= self.y_max:
            raise ValueError("The point must lie within the measured map rectangle")
        return x, y

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        for name in ("x", "y", "signal"):
            data[name] = Channel(**data[name])
        result = cls(**data)
        result.validate()
        return result


@dataclass(frozen=True)
class RegistrationSettings:
    method: str = "phase"
    upsample: int = 20
    preprocessing: str = "intensity"
    smoothing_sigma: float = 0.0
    hann_window: bool = False
    max_shift_x: float = 0.02
    max_shift_y: float = 0.02
    minimum_overlap: float = 0.5
    minimum_correlation: float = 0.6
    minimum_peak_margin: float = 0.01  # Bounded normalized-correlation method.

    def validate(self, geometry):
        if self.method not in ("phase", "intensity", "normalized"):
            raise ValueError("Unknown translation registration method")
        if self.preprocessing not in ("intensity", "gradient"):
            raise ValueError("Unknown registration preprocessing")
        count(self.upsample, "Subpixel upsample factor", 1, 100)
        if type(self.hann_window) is not bool or not 0 <= finite(self.smoothing_sigma, "Smoothing sigma") <= 20:
            raise ValueError("Invalid smoothing/window option")
        for name in ("x", "y"):
            maximum = finite(getattr(self, "max_shift_" + name), "Maximum shift")
            span = getattr(geometry, name + "_max") - getattr(geometry, name + "_min")
            if not 0 < maximum < span / 2:
                raise ValueError("Maximum accepted X/Y shifts must be positive and smaller than half the map span")
        if self.method == "normalized":
            lx = math.floor(self.max_shift_x / ((geometry.x_max - geometry.x_min) / (geometry.x_points - 1)) + 1e-9)
            ly = math.floor(self.max_shift_y / ((geometry.y_max - geometry.y_min) / (geometry.y_points - 1)) + 1e-9)
            if (2 * ly + 1) * (2 * lx + 1) > 10000:
                raise ValueError("Normalized search exceeds 10000 candidates; reduce shift bounds or map resolution")
        for name in ("minimum_overlap", "minimum_correlation", "minimum_peak_margin"):
            if not 0 <= finite(getattr(self, name), name) <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.minimum_overlap == 0:
            raise ValueError("Minimum overlap must be positive")


@dataclass(frozen=True)
class PositionSettings:
    map: MapSettings = field(default_factory=MapSettings)
    registration: RegistrationSettings = field(default_factory=RegistrationSettings)
    point: tuple[float, float] = (0.0, 0.0)
    directory: str = ""

    def validate(self):
        self.map.validate()
        self.registration.validate(self.map)
        self.map.point(self.point)
        if not isinstance(self.directory, str):
            raise ValueError("Results directory must be text")

    def to_dict(self):
        return {"schema_version": 1, **asdict(self)}

    @classmethod
    def from_dict(cls, data):
        if data.get("schema_version") != 1 or set(data) != {"schema_version", "map", "registration", "point", "directory"}:
            raise ValueError("Auto-position setup schema 1 is required")
        result = cls(MapSettings.from_dict(data["map"]), RegistrationSettings(**data["registration"]),
                     tuple(data["point"]), data["directory"])
        result.validate()
        return result


@dataclass(frozen=True)
class ReferenceMap:
    geometry: MapSettings
    point: tuple[float, float]
    image: np.ndarray
    reference_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def validate(self):
        self.geometry.validate()
        self.geometry.point(self.point)
        image = valid_image(self.image)
        if image.shape != (self.geometry.y_points, self.geometry.x_points):
            raise ValueError("Reference image dimensions do not match its map geometry")

    def to_dict(self):
        return {"schema_version": 1, "reference_id": self.reference_id,
                "map": asdict(self.geometry), "point": list(self.point), "image": self.image.tolist()}

    @classmethod
    def from_dict(cls, data):
        if data.get("schema_version") != 1 or set(data) != {"schema_version", "reference_id", "map", "point", "image"}:
            raise ValueError("Reference map schema 1 is required; old MAT prototype files are not imported")
        image = np.asarray(data["image"], dtype=float)
        result = cls(MapSettings.from_dict(data["map"]), tuple(data["point"]), image, str(data["reference_id"]))
        result.validate()
        image.setflags(write=False)
        return result


def valid_image(data):
    image = np.asarray(data, dtype=float)
    if image.ndim != 2 or min(image.shape) < 7 or not np.isfinite(image).all():
        raise ValueError("Registration needs finite 2D maps of at least 7 by 7 pixels")
    if np.ptp(image) == 0 or image.std() == 0:
        raise ValueError("The map is flat; there are no features to register")
    return image


def _preprocess(image, settings):
    from scipy.ndimage import gaussian_filter
    image = valid_image(image).copy()
    if settings.smoothing_sigma:
        image = gaussian_filter(image, settings.smoothing_sigma)
    if settings.preprocessing == "gradient":
        dy, dx = np.gradient(image)
        image = np.hypot(dx, dy)
    valid_image(image)
    return (image - image.mean()) / image.std()


def _correlation(reference, moving):
    a, b = reference - reference.mean(), moving - moving.mean()
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denominator) if denominator > 0 else -1.0


def _overlap_score(reference, moving, sy, sx):
    from scipy.ndimage import shift
    aligned = shift(moving, (sy, sx), order=1, mode="constant", cval=np.nan, prefilter=False)
    mask = np.isfinite(aligned)
    overlap = float(mask.mean())
    correlation = _correlation(reference[mask], aligned[mask]) if mask.sum() >= 9 else -1.0
    return correlation, overlap


def _normalized_search(reference, moving, limits, settings, stop):
    ly, lx = limits
    if (2 * ly + 1) * (2 * lx + 1) > 10000:
        raise ValueError("Normalized search exceeds 10000 candidate translations; reduce shift bounds or map resolution")
    scores = np.full((2 * ly + 1, 2 * lx + 1), -np.inf)
    ny, nx = reference.shape
    for row, sy in enumerate(range(-ly, ly + 1)):
        checkpoint(stop)
        ry, my = slice(max(0, sy), min(ny, ny + sy)), slice(max(0, -sy), min(ny, ny - sy))
        for col, sx in enumerate(range(-lx, lx + 1)):
            checkpoint(stop)
            rx, mx = slice(max(0, sx), min(nx, nx + sx)), slice(max(0, -sx), min(nx, nx - sx))
            a, b = reference[ry, rx], moving[my, mx]
            if a.size / reference.size >= settings.minimum_overlap:
                scores[row, col] = _correlation(a.ravel(), b.ravel())
    row, col = np.unravel_index(np.argmax(scores), scores.shape)
    others = scores.copy()
    others[max(0, row - 1):row + 2, max(0, col - 1):col + 2] = -np.inf
    if np.isfinite(others).any() and scores[row, col] - np.max(others) < settings.minimum_peak_margin:
        raise ValueError("Normalized correlation peak is ambiguous; review features, preprocessing or peak margin")
    def refine(values, index):
        if not 0 < index < len(values) - 1:
            return 0.0
        a, b, c = values[index - 1:index + 2]
        denominator = a - 2 * b + c
        return float(np.clip(0.5 * (a - c) / denominator, -0.5, 0.5)) if np.isfinite([a, b, c]).all() and denominator < 0 else 0.0
    return row - ly + refine(scores[:, col], row), col - lx + refine(scores[row], col)


@dataclass(frozen=True)
class PositionResult:
    alignment_y_pixels: float
    alignment_x_pixels: float
    shift_x: float
    shift_y: float
    point: tuple[float, float]
    correlation: float
    overlap: float


def register_maps(reference, current, settings, stop):
    reference.validate()
    geometry = reference.geometry
    settings.validate(geometry)
    if np.shape(current) != reference.image.shape:
        raise ValueError("Current and reference maps must have identical grids")
    a, b = _preprocess(reference.image, settings), _preprocess(current, settings)
    dx = (geometry.x_max - geometry.x_min) / (geometry.x_points - 1)
    dy = (geometry.y_max - geometry.y_min) / (geometry.y_points - 1)
    checkpoint(stop)
    if settings.method == "normalized":
        sy, sx = _normalized_search(a, b, (math.floor(settings.max_shift_y / dy + 1e-9),
                                         math.floor(settings.max_shift_x / dx + 1e-9)), settings, stop)
    else:
        from skimage.registration import phase_cross_correlation
        aa, bb = a, b
        if settings.hann_window:
            window = np.hanning(a.shape[0])[:, None] * np.hanning(a.shape[1])[None, :]
            aa, bb = a * window, b * window
        (sy, sx), _, _ = phase_cross_correlation(aa, bb, upsample_factor=settings.upsample,
                                               normalization="phase" if settings.method == "phase" else None)
    sy, sx = finite(sy, "Y alignment shift"), finite(sx, "X alignment shift")
    checkpoint(stop)
    # Registration reports the shift APPLIED TO THE IMAGE to align it. Feature
    # drift, and hence the required native-coordinate target change, is opposite.
    shift_x, shift_y = -sx * dx, -sy * dy
    if abs(shift_x) > settings.max_shift_x + 1e-12 or abs(shift_y) > settings.max_shift_y + 1e-12:
        raise ValueError("Detected translation exceeds the configured maximum shift")
    correlation, overlap = _overlap_score(a, b, sy, sx)
    if overlap < settings.minimum_overlap or correlation < settings.minimum_correlation:
        raise ValueError(f"Registration rejected: correlation {correlation:.4g}, overlap {overlap:.4g}")
    point = geometry.point((reference.point[0] + shift_x, reference.point[1] + shift_y))
    return PositionResult(sy, sx, shift_x, shift_y, point, correlation, overlap)
