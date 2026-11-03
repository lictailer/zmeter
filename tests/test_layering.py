"""Layering rules for the v2 transition, checked by parsing imports with ast.

Nothing is imported: the checks read source files only, so they need no Qt and
no vendor libraries and cannot touch hardware.

Rules:
1. Nothing under ``zcore/`` imports PyQt6, core, devices or zui, including
   relative imports that leave the package.
2. Nothing under ``core/`` or ``zcore/`` imports an optional vendor library at
   module top level (imports inside functions are allowed).
3. ``core/device_management/registry.py`` does not import ``devices``, not even
   inside a function or through an ``import_module`` string; device
   registrations, the mock device's included, live in ``registrations.py``.
"""

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

ZCORE_FORBIDDEN = ("PyQt6", "core", "devices", "zui")
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
    parts = list(rel_path.with_suffix("").parts)
    if parts[-1] == "__init__":
        return parts[:-1]
    return parts[:-1]


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


def check_zcore_source(source, rel_path):
    """Violations of rule 1 for one file; ``rel_path`` is relative to the repo."""
    rel_path = Path(rel_path)
    problems = []
    for lineno, level, module, names in _iter_imports(ast.parse(source), False):
        targets, leaves = _absolute_targets(rel_path, level, module, names)
        if leaves:
            problems.append(f"{rel_path}:{lineno}: relative import leaves the package")
        for target in targets:
            if _matches(target, ZCORE_FORBIDDEN):
                problems.append(f"{rel_path}:{lineno}: forbidden import {target}")
    return problems


def check_top_level_vendor_source(source, rel_path):
    """Violations of rule 2 for one file; ``rel_path`` is relative to the repo."""
    rel_path = Path(rel_path)
    problems = []
    for lineno, level, module, names in _iter_imports(ast.parse(source), True):
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
    tree = ast.parse(source)
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


class LayeringRulesOnRepository(unittest.TestCase):
    def test_zcore_does_not_import_ui_core_or_devices(self):
        self.assertEqual(_collect(["zcore"], check_zcore_source), [])

    def test_no_optional_vendor_import_at_top_level(self):
        self.assertEqual(
            _collect(["core", "zcore"], check_top_level_vendor_source), []
        )

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

    def test_vendor_look_alike_names_are_allowed(self):
        self.assertEqual(self.vendor("import cv2helper\nimport clrx\n"), [])
        self.assertEqual(self.vendor("from . import openai\n"), [])


if __name__ == "__main__":
    unittest.main()
