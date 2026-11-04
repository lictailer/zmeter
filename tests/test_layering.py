"""Layering rules for the v2 transition, checked by parsing imports with ast.

Nothing is imported: the checks read source files only, so they need no Qt and
no vendor libraries and cannot touch hardware.

Rules:
1. Nothing under ``zcore/`` imports PyQt6, core, devices or zui, including
   relative imports that leave the package and ``import_module("core...")``
   style strings.
2. Nothing under ``core/``, ``zcore/`` or ``zui/`` imports an optional vendor
   library at module top level (imports inside functions are allowed).
3. ``core/device_management/registry.py`` does not import ``devices``, not even
   inside a function or through an ``import_module`` string; device
   registrations, the mock device's included, live in ``registrations.py``.
4. Nothing under ``zui/`` imports ``devices``, and only ``zui/bridge/`` may
   import ``core``.
5. A device package that imports ``zcore.devices`` (a declarative device)
   imports nothing from ``core``, ``zui``, ``PyQt6`` or another device package.
   Its ``tests/`` directory is exempt, because tests may use Qt and the
   bridge.
"""

import ast
import unittest
import warnings
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

ZCORE_FORBIDDEN = ("PyQt6", "core", "devices", "zui")
ZUI_FORBIDDEN = ("devices",)
ZUI_BRIDGE_DIR = Path("zui/bridge")
DECLARATIVE_SDK = "zcore.devices"
DEVICE_PACKAGE_FORBIDDEN = ("core", "zui", "PyQt6")
OPTIONAL_VENDOR = (
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


def _matches(name, roots):
    return any(name == root or name.startswith(root + ".") for root in roots)


def _parse(source):
    """Parse a source file; escape-sequence warnings in old files are not our concern."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(source)


def _iter_imports(tree, top_level_only):
    """Yield ``(lineno, level, module, names)`` for each import statement.

    With ``top_level_only`` the bodies of functions and lambdas are skipped;
    class bodies, ``if`` and ``try`` blocks still count as module level.
    """

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if top_level_only and isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
            ):
                continue
            if isinstance(child, ast.Import):
                for alias in child.names:
                    yield child.lineno, 0, alias.name, ()
            elif isinstance(child, ast.ImportFrom):
                yield (
                    child.lineno,
                    child.level,
                    child.module or "",
                    tuple(alias.name for alias in child.names),
                )
            yield from walk(child)

    yield from walk(tree)


def _package_parts(rel_path):
    """Package of a module as dotted parts, from its path relative to the repo."""
    return list(rel_path.with_suffix("").parts)[:-1]


def _absolute_targets(rel_path, level, module, names):
    """Absolute dotted names an import statement refers to.

    Returns ``(targets, leaves_package)``. A relative import that climbs above
    the top-level package of the file reports ``leaves_package``.
    """
    if level == 0:
        return [module], False
    package = _package_parts(rel_path)
    keep = len(package) - (level - 1)
    if keep < 1:
        return [], True
    base = ".".join(package[:keep])
    if module:
        return [base + "." + module], False
    return [base + "." + name for name in names], False


def _import_call_strings(tree):
    """Yield ``(lineno, name)`` for literal absolute names given to
    ``import_module(...)`` or ``__import__(...)``."""
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name not in ("import_module", "__import__"):
            continue
        first = node.args[0]
        if (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and not first.value.startswith(".")
        ):
            yield node.lineno, first.value


def _check_imports(source, rel_path, is_forbidden):
    """Violations for one file; ``is_forbidden(target)`` says which absolute
    names may not be imported. Covers import statements at any depth, relative
    imports that leave the package, and ``import_module("...")`` strings."""
    rel_path = Path(rel_path)
    tree = _parse(source)
    problems = []
    for lineno, level, module, names in _iter_imports(tree, False):
        targets, leaves = _absolute_targets(rel_path, level, module, names)
        if leaves:
            problems.append(f"{rel_path}:{lineno}: relative import leaves the package")
        for target in targets:
            if is_forbidden(target):
                problems.append(f"{rel_path}:{lineno}: forbidden import {target}")
    for lineno, name in _import_call_strings(tree):
        if is_forbidden(name):
            problems.append(f"{rel_path}:{lineno}: forbidden import string {name!r}")
    return problems


def check_zcore_source(source, rel_path):
    """Violations of rule 1 for one file; ``rel_path`` is relative to the repo."""
    return _check_imports(
        source, rel_path, lambda target: _matches(target, ZCORE_FORBIDDEN)
    )


def check_zui_source(source, rel_path):
    """Violations of rule 4 for one file; ``rel_path`` is relative to the repo."""
    rel_path = Path(rel_path)
    in_bridge = ZUI_BRIDGE_DIR in rel_path.parents
    forbidden = ZUI_FORBIDDEN if in_bridge else ZUI_FORBIDDEN + ("core",)
    return _check_imports(
        source, rel_path, lambda target: _matches(target, forbidden)
    )


def imports_declarative_sdk(source):
    """True when a source file imports ``zcore.devices`` in any form."""
    tree = _parse(source)
    for lineno, level, module, names in _iter_imports(tree, False):
        if level:
            continue
        candidates = [module] + [module + "." + name for name in names]
        if any(_matches(candidate, (DECLARATIVE_SDK,)) for candidate in candidates):
            return True
    return any(
        _matches(name, (DECLARATIVE_SDK,)) for _, name in _import_call_strings(tree)
    )


def check_device_package_sources(sources):
    """Violations of rule 5 for one device package.

    ``sources`` maps each non-test source file (path relative to the repo, as
    ``devices/<package>/...``) to its text. A package in which no file imports
    ``zcore.devices`` is an old-style device and has no violations here.
    """
    if not any(imports_declarative_sdk(text) for text in sources.values()):
        return []
    problems = []
    for rel_path, text in sources.items():
        rel_path = Path(rel_path)
        own = f"devices.{rel_path.parts[1]}"

        def forbidden(target, own=own):
            return _matches(target, DEVICE_PACKAGE_FORBIDDEN) or (
                _matches(target, ("devices",)) and not _matches(target, (own,))
            )

        problems.extend(_check_imports(text, rel_path, forbidden))
    return problems


def check_top_level_vendor_source(source, rel_path):
    """Violations of rule 2 for one file; ``rel_path`` is relative to the repo."""
    rel_path = Path(rel_path)
    problems = []
    for lineno, level, module, names in _iter_imports(_parse(source), True):
        if level:
            continue
        if _matches(module, OPTIONAL_VENDOR):
            problems.append(
                f"{rel_path}:{lineno}: optional vendor library {module} "
                "imported at module top level"
            )
    return problems


REGISTRY_PATH = Path("core/device_management/registry.py")


def check_registry_source(source, rel_path=REGISTRY_PATH):
    """Violations of rule 3 for the core registry module."""
    rel_path = Path(rel_path)
    tree = _parse(source)
    problems = []
    for lineno, level, module, names in _iter_imports(tree, False):
        targets, leaves = _absolute_targets(rel_path, level, module, names)
        if leaves:
            problems.append(f"{rel_path}:{lineno}: relative import leaves the package")
        for target in targets:
            if _matches(target, ("devices",)):
                problems.append(f"{rel_path}:{lineno}: imports {target}")
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _matches(node.value, ("devices",))
        ):
            problems.append(
                f"{rel_path}:{node.lineno}: names device module {node.value!r}"
            )
    return problems


def _python_files(subdir):
    root = REPO_ROOT / subdir
    if not root.is_dir():
        return []
    return sorted(root.rglob("*.py"))


def _collect(subdirs, checker):
    problems = []
    for subdir in subdirs:
        for path in _python_files(subdir):
            rel = path.relative_to(REPO_ROOT)
            problems.extend(checker(path.read_text(encoding="utf-8"), rel))
    return problems


def _device_packages():
    """Map each device package directory to its non-test source files."""
    root = REPO_ROOT / "devices"
    packages = {}
    if not root.is_dir():
        return packages
    for package in sorted(path for path in root.iterdir() if path.is_dir()):
        sources = {}
        for path in sorted(package.rglob("*.py")):
            rel = path.relative_to(REPO_ROOT)
            if "tests" in rel.parts or "__pycache__" in rel.parts:
                continue
            sources[rel] = path.read_text(encoding="utf-8")
        if sources:
            packages[package.name] = sources
    return packages


class LayeringRulesOnRepository(unittest.TestCase):
    def test_zcore_does_not_import_ui_core_or_devices(self):
        self.assertEqual(_collect(["zcore"], check_zcore_source), [])

    def test_zui_does_not_import_devices_and_only_the_bridge_imports_core(self):
        self.assertEqual(_collect(["zui"], check_zui_source), [])

    def test_no_optional_vendor_import_at_top_level(self):
        self.assertEqual(
            _collect(["core", "zcore", "zui"], check_top_level_vendor_source), []
        )

    def test_declarative_devices_import_only_the_sdk_and_their_own_package(self):
        problems = []
        for sources in _device_packages().values():
            problems.extend(check_device_package_sources(sources))
        self.assertEqual(problems, [])

    def test_core_registry_does_not_import_devices(self):
        path = REPO_ROOT / REGISTRY_PATH
        self.assertEqual(check_registry_source(path.read_text(encoding="utf-8")), [])

    def test_new_packages_exist(self):
        for name in ("zcore/__init__.py", "zcore/data/__init__.py", "zui/__init__.py"):
            self.assertTrue((REPO_ROOT / name).is_file(), name)


class LayeringRulesDetectViolations(unittest.TestCase):
    """The checks must fail on synthetic violations, so a broken rule cannot pass."""

    def zcore(self, source, path="zcore/mod.py"):
        return check_zcore_source(source, path)

    def vendor(self, source, path="core/mod.py"):
        return check_top_level_vendor_source(source, path)

    def test_zcore_forbidden_absolute_imports(self):
        for line in (
            "import PyQt6",
            "from PyQt6 import QtCore",
            "from PyQt6.QtWidgets import QWidget",
            "import core.scan",
            "from core import scan",
            "import devices.mockDevice",
            "from devices.mockDevice import x",
            "import zui",
            "from zui.widgets import y",
        ):
            with self.subTest(line=line):
                self.assertEqual(len(self.zcore(line)), 1)

    def test_zcore_allowed_imports(self):
        for line in (
            "import os",
            "import numpy as np",
            "from zcore.data import x",
            "from . import sibling",
            "from .sibling import thing",
            "import corelib",
            "import devices_helper",
        ):
            with self.subTest(line=line):
                self.assertEqual(self.zcore(line, "zcore/pkg/mod.py"), [])

    def test_zcore_relative_import_leaving_package(self):
        self.assertEqual(len(self.zcore("from .. import core", "zcore/mod.py")), 1)
        self.assertEqual(
            len(self.zcore("from ... import anything", "zcore/data/mod.py")), 1
        )
        self.assertEqual(self.zcore("from .. import sibling", "zcore/data/mod.py"), [])

    def test_zcore_forbidden_import_inside_function_is_still_reported(self):
        source = "def f():\n    import PyQt6\n"
        self.assertEqual(len(self.zcore(source)), 1)

    def test_zcore_import_strings_are_reported(self):
        for source in (
            "import importlib\nimportlib.import_module('core.scan')\n",
            "from importlib import import_module\nimport_module('devices.mockDevice')\n",
            "__import__('PyQt6.QtCore')\n",
            "def f():\n    return __import__('zui')\n",
        ):
            with self.subTest(source=source):
                self.assertEqual(len(self.zcore(source)), 1)

    def test_zcore_harmless_strings_and_relative_import_strings_are_allowed(self):
        for source in (
            "x = 'core.scan'\nd = {'devices': []}\n",
            "from importlib import import_module\nimport_module('numpy')\nimport_module('.sibling', 'zcore')\n",
            "import_module(name)\n",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.zcore(source), [])

    def test_zui_forbids_devices_everywhere_and_core_outside_the_bridge(self):
        for line in ("import devices.mockDevice", "from devices import x", "import devices"):
            for path in ("zui/panel.py", "zui/bridge/facade.py"):
                with self.subTest(line=line, path=path):
                    self.assertEqual(len(check_zui_source(line, path)), 1)
        for line in ("import core.scan", "from core import device_log", "from core.device_management import registry"):
            with self.subTest(line=line):
                self.assertEqual(len(check_zui_source(line, "zui/panel.py")), 1)
                self.assertEqual(len(check_zui_source(line, "zui/widgets/panel.py")), 1)
                self.assertEqual(check_zui_source(line, "zui/bridge/facade.py"), [])
                self.assertEqual(check_zui_source(line, "zui/bridge/sub/x.py"), [])

    def test_zui_import_strings_and_allowed_imports(self):
        source = "from importlib import import_module\nimport_module('devices.sim_device')\n"
        self.assertEqual(len(check_zui_source(source, "zui/bridge/registration.py")), 1)
        source = "from importlib import import_module\nimport_module('core.scan')\n"
        self.assertEqual(len(check_zui_source(source, "zui/panel.py")), 1)
        self.assertEqual(check_zui_source(source, "zui/bridge/registration.py"), [])
        for line in (
            "from PyQt6 import QtWidgets",
            "import pyqtgraph",
            "from zcore.devices import Parameter",
            "from . import device_log",
            "from .. import sibling",
            "import corelib",
        ):
            with self.subTest(line=line):
                self.assertEqual(check_zui_source(line, "zui/bridge/x.py"), [])

    def test_zui_relative_import_leaving_the_package(self):
        self.assertEqual(len(check_zui_source("from .. import core", "zui/mod.py")), 1)

    def test_declarative_sdk_detection(self):
        for source in (
            "import zcore.devices",
            "from zcore.devices import Device",
            "from zcore.devices.parameters import Parameter",
            "from zcore import devices",
            "from importlib import import_module\nimport_module('zcore.devices')\n",
        ):
            with self.subTest(source=source):
                self.assertTrue(imports_declarative_sdk(source))
        for source in ("import zcore", "from zcore.data import x", "from . import devices", "import zcore.devices_helper"):
            with self.subTest(source=source):
                self.assertFalse(imports_declarative_sdk(source))

    def device_package(self, **modules):
        base = "devices/sample_device/"
        return {Path(base + name + ".py"): text for name, text in modules.items()}

    def test_old_style_device_package_is_not_checked_by_rule_5(self):
        sources = self.device_package(
            main="from PyQt6 import QtWidgets\nfrom core.scan import Scan\nimport devices.other_device\n",
        )
        self.assertEqual(check_device_package_sources(sources), [])

    def test_declarative_device_package_forbidden_imports(self):
        declaration = "from zcore.devices import Device\n"
        for line in (
            "from core.scan import Scan",
            "import core",
            "from zui import auto_panel",
            "from PyQt6 import QtCore",
            "import devices.other_device",
            "from devices.other_device import x",
            "from devices import other_device",
            "from .. import other_device",
            "from importlib import import_module\nimport_module('core.scan')\n",
        ):
            with self.subTest(line=line):
                sources = self.device_package(device=declaration, driver=line + "\n")
                self.assertEqual(len(check_device_package_sources(sources)), 1)

    def test_declarative_device_package_forbidden_import_in_declaring_file(self):
        sources = self.device_package(
            device="from zcore.devices import Device\nfrom PyQt6 import QtCore\n",
        )
        self.assertEqual(len(check_device_package_sources(sources)), 1)

    def test_declarative_device_package_allowed_imports(self):
        sources = self.device_package(
            device="import time\nfrom zcore.devices import Device, Parameter\nfrom .driver import Driver\nfrom devices.sample_device import driver\n",
            driver="import pyvisa\nimport numpy as np\nfrom . import simulator\nfrom .simulator import Sim\n",
            simulator="import random\n",
        )
        self.assertEqual(check_device_package_sources(sources), [])

    def test_vendor_top_level_imports(self):
        for line in (
            "import openai",
            "import cv2",
            "import pylablib.devices.Andor",
            "from zhinst.core import ziDAQServer",
            "from skimage import io",
            "import PyDAQmx",
            "import nidaqmx",
            "import clr",
            "import sshtunnel",
        ):
            with self.subTest(line=line):
                self.assertEqual(len(self.vendor(line)), 1)

    def test_vendor_import_in_top_level_block_is_reported(self):
        self.assertEqual(len(self.vendor("try:\n    import cv2\nexcept ImportError:\n    pass\n")), 1)
        self.assertEqual(len(self.vendor("if True:\n    import openai\n")), 1)
        self.assertEqual(len(self.vendor("class C:\n    import clr\n")), 1)

    def test_vendor_import_inside_function_is_allowed(self):
        self.assertEqual(self.vendor("def f():\n    import cv2\n"), [])
        self.assertEqual(
            self.vendor("class C:\n    def m(self):\n        from openai import OpenAI\n"),
            [],
        )
        self.assertEqual(self.vendor("f = lambda: __import__('cv2')\n"), [])

    def test_registry_device_imports_are_reported(self):
        for source in (
            "import devices.mockDevice.mock_device_main",
            "from devices.mockDevice.mock_device_main import MockDevice",
            "def f():\n    from devices.mockDevice import mock_device_main\n",
            "def f():\n    import_module('devices.mockDevice.mock_device_main')\n",
            "from ... import devices",
        ):
            with self.subTest(source=source):
                self.assertTrue(check_registry_source(source))

    def test_registry_allowed_sources(self):
        for source in (
            "from .registrations import mock_device_registration",
            "from .models import DeviceConfig",
            "import devices_helper",
            "x = 'Return registrations without importing any device package.'",
        ):
            with self.subTest(source=source):
                self.assertEqual(check_registry_source(source), [])

    def test_vendor_rule_covers_zui(self):
        self.assertEqual(len(self.vendor("import cv2", "zui/panel.py")), 1)
        self.assertEqual(self.vendor("def f():\n    import cv2\n", "zui/panel.py"), [])

    def test_vendor_look_alike_names_are_allowed(self):
        self.assertEqual(self.vendor("import cv2helper\nimport clrx\n"), [])
        self.assertEqual(self.vendor("from . import openai\n"), [])


if __name__ == "__main__":
    unittest.main()
