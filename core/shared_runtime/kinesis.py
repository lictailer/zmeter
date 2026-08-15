"""One lazy, manifest-validated Thorlabs Kinesis runtime per process."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import struct
import threading
import weakref
from pathlib import Path
from typing import Any, Callable


class KinesisRuntimeError(RuntimeError):
    """Base error raised by the shared Kinesis service."""


class KinesisRuntimeInUseError(KinesisRuntimeError):
    """Raised when shutdown is requested while device owners remain."""


class KinesisProcessSelection:
    """Reject conflicting Kinesis directories/releases within one process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runtime_dir: Path | None = None
        self._release: str | None = None

    def claim(self, runtime_dir: Path, release: object) -> None:
        normalized_release = str(release or "unknown")
        with self._lock:
            if self._runtime_dir is None:
                self._runtime_dir = runtime_dir
                self._release = normalized_release
                return
            if self._runtime_dir != runtime_dir or self._release != normalized_release:
                raise KinesisRuntimeError(
                    "Kinesis is already selected for this process at "
                    f"{self._runtime_dir} (release {self._release}); rejected "
                    f"{runtime_dir} (release {normalized_release}). Restart "
                    "Python to select another runtime."
                )


_PROCESS_SELECTION = KinesisProcessSelection()


class KinesisRuntimeLease:
    def __init__(self, runtime: "KinesisRuntime", owner: str) -> None:
        self._runtime_ref = weakref.ref(runtime)
        self.owner = owner
        self._closed = False
        self._lock = threading.Lock()

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        runtime = self._runtime_ref()
        if runtime is not None:
            runtime._release(self)

    def __enter__(self) -> "KinesisRuntimeLease":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class KinesisRuntime:
    """Coordinate native and managed Kinesis bindings from one directory."""

    NATIVE_COMPONENTS = {
        "k10cr1": "Thorlabs.MotionControl.IntegratedStepperMotors.dll",
    }
    MANAGED_COMPONENTS = {
        "bbd30x": (
            "Thorlabs.MotionControl.Tools.Logging.dll",
            "Thorlabs.MotionControl.Tools.Common.dll",
            "Thorlabs.MotionControl.Tools.WPF.dll",
            "Thorlabs.MotionControl.PrivateInternal.dll",
            "Thorlabs.MotionControl.DeviceManagerCLI.dll",
            "Thorlabs.MotionControl.GenericMotorCLI.dll",
            "Thorlabs.MotionControl.Benchtop.BrushlessMotorCLI.dll",
        ),
    }

    def __init__(
        self,
        runtime_dir: str | os.PathLike[str] | None = None,
        manifest_path: str | os.PathLike[str] | None = None,
        native_loader: Callable[[str], Any] | None = None,
        managed_loader: Callable[[Path, tuple[Path, ...]], Any] | None = None,
        dll_directory_loader: Callable[[str], Any] | None = None,
        process_bits: int | None = None,
        selection_guard: KinesisProcessSelection | None = None,
    ) -> None:
        default_dir = Path(__file__).resolve().parent / "vendor" / "thorlabs_kinesis"
        self.runtime_dir = Path(runtime_dir or default_dir).resolve()
        self.manifest_path = Path(manifest_path or self.runtime_dir / "manifest.json").resolve()
        self._native_loader = native_loader or ctypes.CDLL
        self._managed_loader = managed_loader or self._load_managed_default
        self._dll_directory_loader = dll_directory_loader or getattr(os, "add_dll_directory", None)
        self._process_bits = process_bits or struct.calcsize("P") * 8
        self._selection_guard = selection_guard or _PROCESS_SELECTION
        self._lock = threading.RLock()
        self._device_manager_lock = threading.Lock()
        self._owners: dict[int, KinesisRuntimeLease] = {}
        self._native: dict[str, Any] = {}
        self._managed: dict[str, Any] = {}
        self._dll_directory_handles: list[Any] = []
        self._validated_manifest: dict[str, Any] | None = None
        self._failure: str | None = None
        self._shutdown = False

    def acquire(self, owner: str) -> KinesisRuntimeLease:
        owner_key = str(owner).strip()
        if not owner_key:
            raise ValueError("Kinesis owner must be provided")
        with self._lock:
            self._require_usable()
            lease = KinesisRuntimeLease(self, owner_key)
            self._owners[id(lease)] = lease
            return lease

    def load_native(self, component: str) -> Any:
        with self._lock:
            self._require_usable()
            if component in self._native:
                return self._native[component]
            filename = self.NATIVE_COMPONENTS.get(component)
            if filename is None:
                raise KeyError(f"Unknown Kinesis native component: {component}")
            try:
                self._prepare_locked()
                library = self._native_loader(str(self.runtime_dir / filename))
            except Exception as exc:
                self._mark_failed(component, exc)
                raise KinesisRuntimeError(
                    f"Could not load Kinesis native component {component!r}: {exc}. "
                    "Restart Python before retrying with another runtime."
                ) from exc
            self._native[component] = library
            return library

    def load_managed(self, component: str) -> Any:
        with self._lock:
            self._require_usable()
            if component in self._managed:
                return self._managed[component]
            filenames = self.MANAGED_COMPONENTS.get(component)
            if filenames is None:
                raise KeyError(f"Unknown Kinesis managed component: {component}")
            try:
                self._prepare_locked()
                paths = tuple(self.runtime_dir / name for name in filenames)
                bindings = self._managed_loader(self.runtime_dir, paths)
            except Exception as exc:
                self._mark_failed(component, exc)
                raise KinesisRuntimeError(
                    f"Could not load Kinesis managed component {component!r}: {exc}. "
                    "Restart Python before retrying with another runtime."
                ) from exc
            self._managed[component] = bindings
            return bindings

    def initialize_device_manager(self, callback: Callable[[], Any]) -> Any:
        """Serialize Kinesis discovery and BuildDeviceList calls."""
        with self._device_manager_lock:
            return callback()

    def shutdown(self) -> dict[str, Any]:
        """Report ownership and mark an idle runtime closed; never unload DLLs."""
        with self._lock:
            if self._shutdown:
                return self.diagnostics
            if self._owners:
                owners = sorted(lease.owner for lease in self._owners.values())
                raise KinesisRuntimeInUseError(
                    "Cannot shut down Kinesis runtime while leases are active: " + ", ".join(owners)
                )
            self._shutdown = True
            return self.diagnostics

    @property
    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            manifest = self._validated_manifest or {}
            return {
                "runtime_dir": str(self.runtime_dir),
                "release": manifest.get("release"),
                "validated": self._validated_manifest is not None,
                "native_components": sorted(self._native),
                "managed_components": sorted(self._managed),
                "owners": sorted(lease.owner for lease in self._owners.values()),
                "failed": self._failure,
                "shutdown": self._shutdown,
            }

    def _prepare_locked(self) -> None:
        if self._validated_manifest is None:
            self._validated_manifest = self._validate_manifest()
            self._selection_guard.claim(
                self.runtime_dir, self._validated_manifest.get("release")
            )
        if not self._dll_directory_handles and self._dll_directory_loader is not None:
            self._dll_directory_handles.append(self._dll_directory_loader(str(self.runtime_dir)))

    def _validate_manifest(self) -> dict[str, Any]:
        if self._process_bits != 64:
            raise KinesisRuntimeError(
                f"Kinesis runtime requires 64-bit Python; found {self._process_bits}-bit"
            )
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Kinesis manifest is missing: {self.manifest_path}") from exc
        if manifest.get("architecture") != "x64":
            raise KinesisRuntimeError("Kinesis manifest architecture must be x64")
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise KinesisRuntimeError("Kinesis manifest has no required files")
        for entry in files:
            name = entry.get("name")
            expected_hash = str(entry.get("sha256", "")).lower()
            expected_size = entry.get("size")
            path = self.runtime_dir / str(name)
            if not path.is_file():
                raise FileNotFoundError(f"Required Kinesis file is missing: {path}")
            if expected_size is not None and path.stat().st_size != int(expected_size):
                raise KinesisRuntimeError(f"Kinesis file size mismatch: {path}")
            if not expected_hash or _sha256(path) != expected_hash:
                raise KinesisRuntimeError(f"Kinesis file hash mismatch: {path}")
        return manifest

    @staticmethod
    def _load_managed_default(runtime_dir: Path, paths: tuple[Path, ...]) -> Any:
        try:
            import clr
            from System import Convert, Decimal
        except ImportError as exc:
            raise ImportError("BBD30X requires pythonnet to load the shared Kinesis runtime") from exc
        for path in paths:
            clr.AddReference(str(path))
        import Thorlabs.MotionControl.Benchtop.BrushlessMotorCLI as BM
        import Thorlabs.MotionControl.DeviceManagerCLI as DM
        import Thorlabs.MotionControl.GenericMotorCLI as GM
        return DM, GM, BM, Convert, Decimal

    def _mark_failed(self, component: str, exc: Exception) -> None:
        self._failure = f"{component}: {exc}"

    def _release(self, lease: KinesisRuntimeLease) -> None:
        with self._lock:
            self._owners.pop(id(lease), None)

    def _require_usable(self) -> None:
        if self._shutdown:
            raise KinesisRuntimeError("Kinesis runtime has been shut down")
        if self._failure is not None:
            raise KinesisRuntimeError(
                "Kinesis runtime is in a partial-load failure state; restart Python. "
                f"Original failure: {self._failure}"
            )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
