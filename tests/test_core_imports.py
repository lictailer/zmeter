"""Every module under ``core/``, ``zcore/`` and ``zui/`` imports in a fresh interpreter.

The imports run in a child process so that nothing the test runner or other
tests imported earlier can hide a missing import. The child hides
``HIDDEN_MODULES`` first, so the test also fails on a PC that has them
installed. Importing a module does not construct devices or touch hardware.

``zcore/`` is imported with PyQt6 hidden as well, and also with ``core``,
``devices`` and ``zui`` hidden, so it cannot lean on the rest of the
application. ``zui/`` is imported with ``devices`` hidden.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# No core module may need these at import time: tkinter, python-pptx and PIL
# are no longer used by core, pywin32 is Windows-only and imported only when a
# slide is appended, and the optional vendor libraries load on first use.
HIDDEN_MODULES = (
    "tkinter",
    "pptx",
    "PIL",
    "win32com",
    "pythoncom",
    "openai",
    "cv2",
    "pylablib",
    "zhinst",
    "skimage",
    "PyDAQmx",
    "nidaqmx",
    "clr",
    "sshtunnel",
)


def _modules(package):
    modules = []
    for path in sorted((REPO_ROOT / package).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(REPO_ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules.append(".".join(parts))
    return modules


def _core_modules():
    return _modules("core")


def _run_child(code):
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"child interpreter failed ({completed.returncode}):\n{completed.stderr}"
        )
    # The last stdout line is the JSON result; earlier lines are module prints.
    return json.loads(completed.stdout.strip().splitlines()[-1])


_IMPORT_ALL = """
import importlib, json, sys, traceback
for hidden in %r:
    sys.modules[hidden] = None  # import of a hidden module raises ImportError
failures = {}
for name in %r:
    try:
        importlib.import_module(name)
    except BaseException:
        failures[name] = traceback.format_exc(limit=3)
print(json.dumps(failures))
"""

# Hidden for every new package: the rest of the application must not be needed.
ZCORE_HIDDEN_MODULES = HIDDEN_MODULES + ("PyQt6", "core", "devices", "zui")
ZUI_HIDDEN_MODULES = HIDDEN_MODULES + ("devices",)

_AXIS_ORDER = """
import importlib, json
import pyqtgraph as pg
before = pg.getConfigOption("imageAxisOrder")
importlib.import_module(%r)
print(json.dumps([before, pg.getConfigOption("imageAxisOrder")]))
"""


class CoreImportTests(unittest.TestCase):
    def test_module_list_is_not_empty(self):
        modules = _core_modules()
        self.assertIn("core.scan", modules)
        self.assertIn("core.mainWindow", modules)
        self.assertIn("core.device_management.registry", modules)

    def assert_package_imports(self, package, hidden):
        modules = _modules(package)
        self.assertIn(package, modules)
        failures = _run_child(_IMPORT_ALL % (hidden, modules))
        self.assertEqual(
            failures,
            {},
            f"{package} modules that fail to import:\n"
            + "\n".join(f"{name}:\n{trace}" for name, trace in failures.items()),
        )

    def test_every_core_module_imports_in_a_fresh_process(self):
        self.assert_package_imports("core", HIDDEN_MODULES)

    def test_every_zcore_module_imports_without_qt_or_the_application(self):
        self.assert_package_imports("zcore", ZCORE_HIDDEN_MODULES)
        for module in ("zcore.data", "zcore.devices", "zcore.devices.device", "zcore.results"):
            self.assertIn(module, _modules("zcore"))

    def test_every_zui_module_imports_without_devices(self):
        self.assert_package_imports("zui", ZUI_HIDDEN_MODULES)

    def test_scan_info_is_only_the_template(self):
        result = _run_child(
            "import json, sys\n"
            "import core.scan_info as s\n"
            "print(json.dumps([sorted(n for n in vars(s) if not n.startswith('_')),"
            " 'PyQt6' in sys.modules, 'pyqtgraph' in sys.modules]))\n"
        )
        names, qt_loaded, pyqtgraph_loaded = result
        self.assertEqual(names, ["ScanInfo", "np"])
        self.assertFalse(qt_loaded)
        self.assertFalse(pyqtgraph_loaded)

    def test_plot_modules_configure_row_major_images(self):
        for module in ("core.all_plots", "core.mainWindow"):
            with self.subTest(module=module):
                before, after = _run_child(_AXIS_ORDER % (module,))
                self.assertEqual(before, "col-major")
                self.assertEqual(after, "row-major")


if __name__ == "__main__":
    unittest.main()
