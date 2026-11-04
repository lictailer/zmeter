"""format_version and software stamped into scan JSON files (core/scan_file_info.py).

Hardware-free: the software checks read fake manifests and fake .git folders in
temporary directories; nothing runs git.
"""

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from core import scan_file_info
from core.scan import _write_json_payload, read_scan_file
from core.scan_file_info import (
    MANIFEST_NAME,
    SCAN_FORMAT_VERSION,
    read_software_info,
    scan_format_version,
    software_info,
    stamp_scan_payload,
)

SHA_A = "a" * 40
SHA_B = "b" * 40

# A scan file as written before format_version existed (shape of release/beta
# output in 2026-11): no format_version, no software.
LEGACY_SCAN = {
    "levels": {
        "level0": {
            "setters": {
                "setter0": {
                    "channel": "mock_device_0_x",
                    "explicit": False,
                    "linear_setting": {
                        "start": 0,
                        "end": 1,
                        "step": 0.5,
                        "mid": 0.5,
                        "span": 1,
                        "points": 3,
                        "destinations": [0, 0.5, 1],
                    },
                    "explicit_setting": [0, 1],
                    "destinations": [0, 0.5, 1],
                }
            },
            "setting_method": "A+B,C",
            "getters": ["mock_device_0_y"],
            "setting_array": [[0, 0.5, 1]],
            "settle_time": 0.0,
            "start_wait_time": 0.0,
            "manual_set_before": [],
            "manual_set_after": [],
        }
    },
    "data": {"L0G0_mock_device_0_y": [1.0, "NaN", 3.0]},
    "plots": {"line_plots": {}, "image_plots": {}},
    "name": "legacy",
    "plots_per_page": "4",
    "comments": "",
    "scan_log": ["old log"],
}


class _TempRoot(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, relative, text, encoding="utf-8"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=encoding)
        return path


class SoftwareInfoTests(_TempRoot):
    def test_release_manifest(self):
        manifest = {
            "schema_version": 1,
            "version": "1.4.0",
            "tag": "v1.4.0-beta.2",
            "channel": "beta",
            "commit": SHA_A,
            "environment_file": "zmeter_Sept2026_environment.yml",
            "environment_sha256": "0" * 64,
        }
        # PowerShell may write a byte order mark.
        self.write(MANIFEST_NAME, json.dumps(manifest), encoding="utf-8-sig")
        self.assertEqual(
            read_software_info(self.root),
            {
                "source": "release",
                "version": "1.4.0",
                "tag": "v1.4.0-beta.2",
                "channel": "beta",
                "commit": SHA_A,
            },
        )

    def test_manifest_wins_over_git(self):
        self.write(MANIFEST_NAME, json.dumps({"version": "1.0.0", "commit": SHA_A}))
        self.write(".git/HEAD", "ref: refs/heads/release/beta\n")
        info = read_software_info(self.root)
        self.assertEqual(info["source"], "release")
        self.assertIsNone(info["tag"])

    def test_git_branch_with_loose_ref(self):
        self.write(".git/HEAD", "ref: refs/heads/release/beta\n")
        self.write(".git/refs/heads/release/beta", SHA_A + "\n")
        self.assertEqual(
            read_software_info(self.root),
            {"source": "git", "branch": "release/beta", "commit": SHA_A},
        )

    def test_git_branch_with_packed_refs(self):
        self.write(".git/HEAD", "ref: refs/heads/release/main\n")
        self.write(
            ".git/packed-refs",
            "# pack-refs with: peeled fully-peeled sorted\n"
            f"{SHA_B} refs/heads/other\n"
            f"{SHA_A} refs/heads/release/main\n"
            f"^{SHA_B}\n",
        )
        self.assertEqual(
            read_software_info(self.root),
            {"source": "git", "branch": "release/main", "commit": SHA_A},
        )

    def test_git_branch_without_commits(self):
        self.write(".git/HEAD", "ref: refs/heads/new\n")
        self.assertEqual(
            read_software_info(self.root),
            {"source": "git", "branch": "new", "commit": None},
        )

    def test_git_detached_head(self):
        self.write(".git/HEAD", SHA_B + "\n")
        self.assertEqual(
            read_software_info(self.root),
            {"source": "git", "branch": None, "commit": SHA_B},
        )

    def test_git_worktree_file(self):
        common = self.root / "main.git"
        worktree_git = common / "worktrees" / "wt"
        self.write("main.git/worktrees/wt/HEAD", "ref: refs/heads/feature\n")
        self.write("main.git/worktrees/wt/commondir", "../..\n")
        self.write("main.git/refs/heads/feature", SHA_A + "\n")
        checkout = self.root / "checkout"
        checkout.mkdir()
        (checkout / ".git").write_text(f"gitdir: {worktree_git}\n", encoding="utf-8")
        self.assertEqual(
            read_software_info(checkout),
            {"source": "git", "branch": "feature", "commit": SHA_A},
        )

    def test_nothing_is_unknown(self):
        self.assertEqual(read_software_info(self.root), {"source": "unknown"})

    def test_read_errors_fall_back_to_unknown(self):
        cases = (
            (MANIFEST_NAME, "{not json"),
            (MANIFEST_NAME, "[1, 2]"),
            (".git/HEAD", "garbage\n"),
        )
        for index, (name, text) in enumerate(cases):
            with self.subTest(name=name, text=text):
                self.write(f"case{index}/{name}", text)
                self.assertEqual(
                    read_software_info(self.root / f"case{index}"),
                    {"source": "unknown"},
                )

    def test_software_info_is_cached_and_returns_copies(self):
        with mock.patch.object(scan_file_info, "_cached_software_info", None):
            with mock.patch.object(
                scan_file_info,
                "read_software_info",
                return_value={"source": "git", "branch": "b", "commit": SHA_A},
            ) as reader:
                first = software_info()
                first["branch"] = "changed"
                second = software_info()
        reader.assert_called_once_with()
        self.assertEqual(second["branch"], "b")

    def test_this_checkout_has_a_known_shape(self):
        self.assertIn(software_info()["source"], ("release", "git", "unknown"))


class StampTests(unittest.TestCase):
    def test_stamp_puts_fields_first_and_leaves_payload_alone(self):
        payload = {"name": "x", "data": {}, "format_version": 7, "software": {"old": 1}}
        before = copy.deepcopy(payload)
        stamped = stamp_scan_payload(payload)
        self.assertEqual(payload, before)
        self.assertEqual(list(stamped), ["format_version", "software", "name", "data"])
        self.assertEqual(stamped["format_version"], SCAN_FORMAT_VERSION)
        self.assertEqual(stamped["software"], software_info())

    def test_stamp_is_shallow(self):
        data = {"result": np.array([1.0, 2.0])}
        stamped = stamp_scan_payload({"data": data})
        self.assertIs(stamped["data"], data)

    def test_format_version_of_loaded_files(self):
        self.assertEqual(SCAN_FORMAT_VERSION, 2)
        self.assertEqual(scan_format_version({}), 1)
        self.assertEqual(scan_format_version({"format_version": 1}), 1)
        # v1.0-beta.5 already wrote format_version 2 into scans that ran.
        self.assertEqual(scan_format_version({"format_version": 2}), 2)
        for bad in (0, -1, True, "1", 1.0, None):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    scan_format_version({"format_version": bad})
        with self.assertRaisesRegex(ValueError, "newer ZMeter"):
            scan_format_version({"format_version": SCAN_FORMAT_VERSION + 1})


class ScanFileRoundTripTests(_TempRoot):
    def test_legacy_file_without_fields_loads_as_version_1(self):
        path = self.write("legacy.json", json.dumps(LEGACY_SCAN))
        info = read_scan_file(path)
        self.assertNotIn("format_version", info)
        self.assertEqual(scan_format_version(info), 1)
        self.assertEqual(info["name"], "legacy")
        self.assertTrue(math.isnan(info["data"]["L0G0_mock_device_0_y"][1]))

    def test_stamped_file_round_trip(self):
        path = self.root / "stamped.json"
        payload = copy.deepcopy(LEGACY_SCAN)
        payload["data"] = {"L0G0_mock_device_0_y": np.array([1.0, np.nan])}
        _write_json_payload(path, stamp_scan_payload(payload))
        info = read_scan_file(path)
        self.assertEqual(info["format_version"], SCAN_FORMAT_VERSION)
        self.assertEqual(info["software"], software_info())
        self.assertEqual(info["levels"], LEGACY_SCAN["levels"])
        self.assertTrue(math.isnan(info["data"]["L0G0_mock_device_0_y"][1]))

    def test_v1_0_beta_5_file_with_format_version_2_loads(self):
        beta5 = dict(
            LEGACY_SCAN,
            format_version=2,
            setup={"snapshot_start": None, "snapshot_end": None,
                   "changed_during_scan": [], "description": {}},
        )
        path = self.write("beta5.json", json.dumps(beta5))
        info = read_scan_file(path)
        self.assertEqual(scan_format_version(info), 2)
        self.assertIn("setup", info)

    def test_newer_file_is_refused(self):
        newer = dict(LEGACY_SCAN, format_version=SCAN_FORMAT_VERSION + 1)
        path = self.write("newer.json", json.dumps(newer))
        with self.assertRaisesRegex(ValueError, "newer ZMeter"):
            read_scan_file(path)


if __name__ == "__main__":
    unittest.main()
