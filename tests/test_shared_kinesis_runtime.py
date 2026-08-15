from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path

from core.shared_runtime.kinesis import (
    KinesisProcessSelection,
    KinesisRuntime,
    KinesisRuntimeError,
    KinesisRuntimeInUseError,
)


BBD30X_TRANSITIVE_FILES = (
    "Thorlabs.MotionControl.Tools.Logging.dll",
    "Thorlabs.MotionControl.Tools.Common.dll",
    "Thorlabs.MotionControl.Tools.WPF.dll",
    "Thorlabs.MotionControl.PrivateInternal.dll",
)
BBD30X_MANAGED_FILES = BBD30X_TRANSITIVE_FILES + (
    "Thorlabs.MotionControl.DeviceManagerCLI.dll",
    "Thorlabs.MotionControl.GenericMotorCLI.dll",
    "Thorlabs.MotionControl.Benchtop.BrushlessMotorCLI.dll",
)


def make_runtime_dir(root: Path, names: tuple[str, ...] | None = None) -> Path:
    names = names or (
        "Thorlabs.MotionControl.DeviceManager.dll",
        *BBD30X_MANAGED_FILES,
        "Thorlabs.MotionControl.Benchtop.BrushlessMotor.dll",
        "Thorlabs.MotionControl.IntegratedStepperMotors.dll",
        "ftd2xx.dll",
        "BBD_Stages.xml",
        "ThorlabsDefaultSettings.xml",
    )
    files = []
    for index, name in enumerate(names):
        data = f"fake-{index}-{name}".encode()
        (root / name).write_bytes(data)
        files.append({
            "name": name,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    (root / "manifest.json").write_text(json.dumps({
        "runtime": "fake Kinesis",
        "release": "test",
        "architecture": "x64",
        "files": files,
    }), encoding="utf-8")
    return root


class KinesisRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runtime_dir = make_runtime_dir(Path(self.temp.name))

    def make_runtime(self, **kwargs):
        native_calls = []
        managed_calls = []
        directory_calls = []
        runtime = KinesisRuntime(
            runtime_dir=self.runtime_dir,
            native_loader=kwargs.pop("native_loader", lambda path: native_calls.append(path) or object()),
            managed_loader=kwargs.pop("managed_loader", lambda base, paths: managed_calls.append((base, paths)) or (1, 2, 3, 4, 5)),
            dll_directory_loader=kwargs.pop("dll_directory_loader", lambda path: directory_calls.append(path) or object()),
            selection_guard=kwargs.pop("selection_guard", KinesisProcessSelection()),
            **kwargs,
        )
        return runtime, native_calls, managed_calls, directory_calls

    def test_construction_and_acquire_do_not_validate_or_load(self):
        runtime, native, managed, directories = self.make_runtime()
        lease = runtime.acquire("K10CR1:one")
        self.assertFalse(runtime.diagnostics["validated"])
        self.assertEqual((native, managed, directories), ([], [], []))
        lease.close()

    def test_native_and_managed_use_one_directory_and_cache(self):
        runtime, native, managed, directories = self.make_runtime()
        first = runtime.load_native("k10cr1")
        self.assertIs(first, runtime.load_native("k10cr1"))
        second = runtime.load_managed("bbd30x")
        self.assertIs(second, runtime.load_managed("bbd30x"))
        self.assertEqual(len(native), 1)
        self.assertEqual(len(managed), 1)
        self.assertEqual(directories, [str(self.runtime_dir.resolve())])
        managed_base, managed_paths = managed[0]
        self.assertEqual(managed_base, self.runtime_dir.resolve())
        self.assertEqual(
            tuple(path.name for path in managed_paths),
            BBD30X_MANAGED_FILES,
        )

    def test_both_load_orders_work_with_one_time_loading(self):
        for order in (("native", "managed"), ("managed", "native")):
            runtime, native, managed, _ = self.make_runtime()
            for item in order:
                runtime.load_native("k10cr1") if item == "native" else runtime.load_managed("bbd30x")
            self.assertEqual((len(native), len(managed)), (1, 1))

    def test_missing_file_hash_bitness_and_manifest_errors_are_actionable(self):
        missing = self.runtime_dir / "ftd2xx.dll"
        missing.unlink()
        runtime, *_ = self.make_runtime()
        with self.assertRaisesRegex(KinesisRuntimeError, "missing"):
            runtime.load_native("k10cr1")

        make_runtime_dir(self.runtime_dir)
        (self.runtime_dir / "ftd2xx.dll").write_bytes(b"changed")
        runtime, *_ = self.make_runtime()
        with self.assertRaisesRegex(KinesisRuntimeError, "mismatch"):
            runtime.load_native("k10cr1")

        make_runtime_dir(self.runtime_dir)
        runtime, *_ = self.make_runtime(process_bits=32)
        with self.assertRaisesRegex(KinesisRuntimeError, "64-bit"):
            runtime.load_native("k10cr1")

    def test_each_managed_dependency_is_required_and_hash_checked(self):
        for filename in BBD30X_TRANSITIVE_FILES:
            for failure, pattern in (("missing", "missing"), ("altered", "mismatch")):
                with self.subTest(filename=filename, failure=failure):
                    with tempfile.TemporaryDirectory() as temp:
                        runtime_dir = make_runtime_dir(Path(temp))
                        target = runtime_dir / filename
                        if failure == "missing":
                            target.unlink()
                        else:
                            target.write_bytes(b"changed")
                        runtime = KinesisRuntime(
                            runtime_dir=runtime_dir,
                            native_loader=lambda _path: object(),
                            managed_loader=lambda _base, _paths: (1, 2, 3, 4, 5),
                            dll_directory_loader=lambda _path: object(),
                            selection_guard=KinesisProcessSelection(),
                        )
                        with self.assertRaisesRegex(KinesisRuntimeError, pattern):
                            runtime.load_managed("bbd30x")

    def test_checked_in_vendor_manifest_validates_without_loading_dlls(self):
        vendor_dir = (
            Path(__file__).resolve().parents[1]
            / "core"
            / "shared_runtime"
            / "vendor"
            / "thorlabs_kinesis"
        )
        managed_calls = []
        runtime = KinesisRuntime(
            runtime_dir=vendor_dir,
            native_loader=lambda _path: self.fail("native loader must not run"),
            managed_loader=lambda base, paths: managed_calls.append((base, paths))
            or (1, 2, 3, 4, 5),
            dll_directory_loader=lambda _path: object(),
            selection_guard=KinesisProcessSelection(),
        )

        self.assertEqual(runtime.load_managed("bbd30x"), (1, 2, 3, 4, 5))
        self.assertEqual(len(managed_calls), 1)
        self.assertEqual(
            tuple(path.name for path in managed_calls[0][1]),
            BBD30X_MANAGED_FILES,
        )
        self.assertTrue(runtime.diagnostics["validated"])

    def test_partial_load_failure_is_terminal(self):
        runtime, *_ = self.make_runtime(native_loader=lambda _path: (_ for _ in ()).throw(OSError("bad dll")))
        with self.assertRaisesRegex(KinesisRuntimeError, "Restart Python"):
            runtime.load_native("k10cr1")
        with self.assertRaisesRegex(KinesisRuntimeError, "partial-load"):
            runtime.load_managed("bbd30x")

    def test_conflicting_process_directory_is_rejected(self):
        guard = KinesisProcessSelection()
        first, *_ = self.make_runtime(selection_guard=guard)
        first.load_native("k10cr1")
        with tempfile.TemporaryDirectory() as other_temp:
            other_dir = make_runtime_dir(Path(other_temp))
            second = KinesisRuntime(
                runtime_dir=other_dir,
                native_loader=lambda _path: object(),
                managed_loader=lambda _base, _paths: (1, 2, 3, 4, 5),
                dll_directory_loader=lambda _path: object(),
                selection_guard=guard,
            )
            with self.assertRaisesRegex(KinesisRuntimeError, "already selected"):
                second.load_managed("bbd30x")

    def test_active_owner_blocks_shutdown_and_release_is_idempotent(self):
        runtime, *_ = self.make_runtime()
        lease = runtime.acquire("BBD30X:stage")
        with self.assertRaisesRegex(KinesisRuntimeInUseError, "BBD30X:stage"):
            runtime.shutdown()
        lease.close()
        lease.close()
        self.assertTrue(runtime.shutdown()["shutdown"])
        self.assertTrue(runtime.shutdown()["shutdown"])

    def test_device_manager_initialization_is_serialized(self):
        runtime, *_ = self.make_runtime()
        active = 0
        maximum = 0
        guard = threading.Lock()
        barrier = threading.Barrier(3)

        def callback():
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(maximum, active)
            with guard:
                active -= 1

        def run():
            barrier.wait()
            runtime.initialize_device_manager(callback)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertEqual(maximum, 1)


if __name__ == "__main__":
    unittest.main()
