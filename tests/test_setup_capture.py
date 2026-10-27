import copy
import json
import os
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from core.scan import Scan
from core.scan_info import ScanInfo
from core.setup_capture import profile
from core.setup_capture import questionnaire as qn
from core.setup_capture import runtime
from core.setup_capture.controller import SetupCaptureController
from core.setup_capture.queue_session import merge_busy_devices, queue_plan
from core.setup_capture.snapshot import (
    SnapshotTarget,
    changed_fields,
    json_safe,
    load_snapshot_overrides,
    resolve_getter_names,
    scan_setter_channels,
    take_snapshot,
)

REPO = Path(__file__).resolve().parents[1]
FAKE_KEY = "sk-ant-test-key-never-saved"


class SnapshotFunctionTests(unittest.TestCase):
    def test_reads_values_records_errors_and_skips_scan_setters(self):
        def broken():
            raise IOError("bus timeout")

        targets = [
            SnapshotTarget(
                "SR860_0",
                "sr860",
                {"frequency": lambda: np.float64(17.0), "amplitude": lambda: 0.1, "phase": broken},
            ),
            SnapshotTarget("Keithley_bg", "keithley24xx", {}, "no snapshot getters defined"),
        ]
        snapshot = take_snapshot(targets, skip_channels={"SR860_0_amplitude"})
        sr860 = snapshot["devices"]["SR860_0"]
        self.assertEqual(sr860["driver"], "sr860")
        self.assertEqual(sr860["fields"]["frequency"], 17.0)
        self.assertNotIn("amplitude", sr860["fields"])
        self.assertIn("bus timeout", sr860["fields"]["phase"]["error"])
        self.assertEqual(
            snapshot["devices"]["Keithley_bg"]["skipped"], "no snapshot getters defined"
        )
        json.dumps(snapshot)

    def test_slow_device_times_out_without_blocking(self):
        targets = [
            SnapshotTarget("slow", "x", {"value": lambda: time.sleep(2) or 1}),
            SnapshotTarget("fast", "y", {"value": lambda: 2}),
        ]
        started = time.monotonic()
        snapshot = take_snapshot(targets, total_timeout_s=0.3)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertIn("timeout", snapshot["devices"]["slow"]["skipped"])
        self.assertEqual(snapshot["devices"]["fast"]["fields"]["value"], 2)

    def test_changed_fields_ignores_errors(self):
        start = {"devices": {"a": {"fields": {"x": 1, "y": 2, "z": {"error": "e"}}}}}
        end = {"devices": {"a": {"fields": {"x": 1, "y": 3, "z": 5}}}}
        self.assertEqual(changed_fields(start, end), ["a.y"])
        self.assertEqual(changed_fields(None, end), [])

    def test_overrides_add_and_remove_by_driver_then_device(self):
        overrides = {
            "sr860": {"add": ["aux_out"], "remove": ["phase"]},
            "SR860_1": {"remove": ["aux_out"]},
        }
        self.assertEqual(
            resolve_getter_names("sr860", "SR860_0", ("frequency", "phase"), overrides),
            ["frequency", "aux_out"],
        )
        self.assertEqual(
            resolve_getter_names("sr860", "SR860_1", ("frequency", "phase"), overrides),
            ["frequency"],
        )

    def test_broken_override_file_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "snapshot_channels.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertIn("_error", load_snapshot_overrides(path))
            self.assertEqual(load_snapshot_overrides(Path(folder) / "missing.json"), {})

    def test_json_safe_handles_numpy_and_nan(self):
        self.assertEqual(json_safe(np.array([1, 2])), [1, 2])
        self.assertEqual(json_safe(float("nan")), "nan")
        self.assertEqual(json_safe({"a": (np.int64(3),)}), {"a": [3]})

    def test_scan_setter_channels_include_manual_sets(self):
        levels = {
            "level0": {
                "setters": {"setter0": {"channel": "SR860_0_amplitude"}},
                "manual_set_before": [{"Keithley_bg_voltage": 1.0}],
                "manual_set_after": [],
                "getters": ["SR860_0_X"],
            }
        }
        self.assertEqual(
            scan_setter_channels(levels), {"SR860_0_amplitude", "Keithley_bg_voltage"}
        )

    def test_reviewed_getter_lists_exist_on_logic_classes(self):
        from devices.k10cr1.k10cr1_logic import K10CR1Logic
        from devices.ni6423.ni6423_logic import NI6423Logic
        from devices.sr830.sr830_logic import SR830_Logic
        from devices.sr860.sr860_logic import SR860_Logic

        for cls in (SR830_Logic, SR860_Logic, K10CR1Logic, NI6423Logic):
            for name in cls.SNAPSHOT_GETTERS:
                self.assertTrue(callable(getattr(cls, f"get_{name}", None)), (cls, name))


class _FakeTimer:
    def __init__(self, active):
        self._active = active

    def isActive(self):
        return self._active


class _FakeLogic:
    SNAPSHOT_GETTERS = ("frequency", "missing")

    def get_frequency(self):
        return 13.7


class SnapshotRunTests(unittest.TestCase):
    def _main_window(self, monitor_active=False):
        record = lambda device_id, state="connected": SimpleNamespace(
            device_id=device_id,
            driver_id="sr860",
            state=SimpleNamespace(value=state),
            instance=None,
            generation=4,
        )
        equips = {
            "SR860_0": SimpleNamespace(logic=_FakeLogic(), timer=_FakeTimer(False)),
            "SR860_1": SimpleNamespace(logic=_FakeLogic(), timer=_FakeTimer(monitor_active)),
            "SR860_2": SimpleNamespace(logic=_FakeLogic(), timer=_FakeTimer(False)),
            "OFF": SimpleNamespace(logic=_FakeLogic()),
        }
        bound = []

        def bind(label, generation, method):
            bound.append((label, generation))
            return method

        return SimpleNamespace(
            _applied_device_snapshot=SimpleNamespace(
                records=(
                    record("SR860_0"),
                    record("SR860_1"),
                    record("SR860_2"),
                    record("OFF", "disconnected"),
                )
            ),
            equips=equips,
            _bind_manager_device_call=bind,
            bound=bound,
        )

    def test_connected_devices_only_with_lease_and_skip_rules(self):
        main_window = self._main_window(monitor_active=True)
        with tempfile.TemporaryDirectory() as folder:
            runtime.register_scan_devices("other", ["SR860_2"])
            self.addCleanup(runtime.release_scan_devices, "other")
            run = runtime.SnapshotRun(
                main_window, ["SR860_0"], {}, scan_key="me", lab_folder=Path(folder)
            )
            snapshot = run.take()
        devices = snapshot["devices"]
        self.assertEqual(set(devices), {"SR860_0", "SR860_1", "SR860_2"})
        self.assertEqual(devices["SR860_0"]["fields"]["frequency"], 13.7)
        self.assertIn("no get_missing", devices["SR860_0"]["fields"]["missing"]["error"])
        self.assertEqual(devices["SR860_1"]["skipped"], runtime.SKIP_LIVE_MONITOR)
        self.assertEqual(devices["SR860_2"]["skipped"], runtime.SKIP_OTHER_SCAN)
        self.assertIn(("SR860_0", 4), main_window.bound)

    def test_merge_busy_devices_uses_first_scan_snapshot(self):
        queue_snapshot = {
            "devices": {"a": {"driver": "x", "fields": {}, "skipped": runtime.SKIP_OTHER_SCAN}}
        }
        scan_snapshot = {"devices": {"a": {"driver": "x", "fields": {"v": 1}}}}
        merged = merge_busy_devices(queue_snapshot, scan_snapshot)
        self.assertEqual(merged["devices"]["a"]["fields"], {"v": 1})
        self.assertTrue(merged["devices"]["a"]["from_scan_start_snapshot"])


class QuestionnaireLogicTests(unittest.TestCase):
    def test_shipped_lab_files_parse(self):
        folder = REPO / "lab_context"
        items = qn.parse_suggestions(profile.suggested_questions_text(folder))
        self.assertGreaterEqual(len(items), 5)
        self.assertLessEqual(len(items), qn.MAX_QUESTIONS)
        self.assertFalse(any("(often)" in item["text"] for item in items))
        self.assertTrue(profile.lab_context_version(profile.lab_context_text(folder)).startswith("ZMeter lab context"))
        overrides = json.loads((folder / "snapshot_channels.example.json").read_text(encoding="utf-8"))
        self.assertIn("sr860", overrides)

    def test_normalize_prefills_from_previous_answers_and_caps_count(self):
        raw = [{"id": "laser_wavelength", "text": "Laser wavelength?", "kind": "number"}]
        raw += [{"text": f"Q{i}"} for i in range(40)]
        previous = [{"id": "laser_wavelength", "text": "x", "answer": "1064 nm", "status": "answered"}]
        items = qn.normalize_items(raw, origin="agent", previous_items=previous)
        self.assertEqual(len(items), qn.MAX_QUESTIONS)
        self.assertEqual(items[0]["answer"], "1064 nm")
        self.assertEqual(items[0]["status"], qn.STATUS_PREFILLED)

    def test_generate_falls_back_to_suggestions_without_key(self):
        def no_model(*_args, **_kwargs):
            raise qn.QuestionnaireUnavailable("no API key set")

        record = qn.generate(
            mode="scan",
            plan=[],
            snapshot=None,
            description={},
            previous_items=[],
            api_key="",
            model="m",
            lab_folder=REPO / "lab_context",
            model_call=no_model,
        )
        self.assertEqual(record["source"], "suggestions")
        self.assertIn("no API key", record["error"])
        self.assertTrue(record["items"])

    def test_generate_uses_model_output_and_never_puts_key_in_prompt(self):
        seen = {}

        def fake_model(api_key, model, system, user):
            seen.update(api_key=api_key, system=system, user=user)
            return [{"id": "a", "text": "Which contact?", "kind": "text", "unit": "",
                     "options": [], "prefill": "", "reason": "guess"}]

        info = copy.deepcopy(ScanInfo)
        record = qn.generate(
            mode="scan",
            plan=[qn.summarize_scan(info)],
            snapshot={"devices": {}},
            description={"device": "TXT15"},
            previous_items=[],
            api_key=FAKE_KEY,
            model="claude-haiku-5-5",
            lab_folder=REPO / "lab_context",
            model_call=fake_model,
        )
        self.assertEqual(record["source"], "agent")
        self.assertEqual(record["items"][0]["text"], "Which contact")
        self.assertIn("Driver types and their usual roles", seen["system"])
        self.assertIn("TXT15", seen["user"])
        self.assertNotIn(FAKE_KEY, seen["system"] + seen["user"])
        self.assertNotIn(FAKE_KEY, json.dumps(record))

    def test_inferences_are_stored_and_medium_ones_are_not_asked(self):
        def fake_model(api_key, model, system, user):
            self.assertIn("NLH = nonlinear Hall", system)
            self.assertIn("previous_corrections", user)
            self.assertIn("SHG_xx_3p4K", user)
            return {
                "inferences": [
                    {"field": "measurement_type", "value": "SHG", "basis": "scan name",
                     "confidence": "high", "scope": "scan"},
                    {"field": "role:Keithley_bg", "value": "back gate", "basis": "name",
                     "confidence": "medium", "scope": "scan"},
                    {"field": "", "value": "dropped", "basis": "", "confidence": "high", "scope": "scan"},
                ],
                "questions": [
                    {"id": "laser", "text": "Laser power at sample?", "section": "scan"},
                    {"id": "objective", "text": "Objective", "section": "setup"},
                ],
            }

        info = copy.deepcopy(ScanInfo)
        info["name"] = "SHG_xx_3p4K"
        record = qn.generate(
            mode="scan", plan=[qn.summarize_scan(info)], snapshot=None, description={},
            previous_items=[], api_key=FAKE_KEY, model="m",
            lab_folder=REPO / "lab_context", model_call=fake_model,
            previous_inferences=[{"field": "temperature", "model_value": "4 K",
                                  "value": "3.4 K", "status": qn.INFERENCE_CORRECTED}],
        )
        self.assertEqual([i["field"] for i in record["inferences"]],
                         ["measurement_type", "role:Keithley_bg"])
        self.assertEqual([i["text"] for i in record["items"]], ["Laser power at sample", "Objective"])
        self.assertEqual([i["section"] for i in record["items"]], ["scan", "setup"])
        medium = record["inferences"][1]
        self.assertTrue(qn.needs_check(medium))

        qn.set_inference_value(medium, "back gate", confirmed=True)
        self.assertEqual(medium["status"], qn.INFERENCE_CONFIRMED)
        self.assertFalse(qn.needs_check(medium))
        qn.set_inference_value(medium, "top gate", confirmed=True)
        self.assertEqual(medium["status"], qn.INFERENCE_CORRECTED)
        self.assertEqual(medium["model_value"], "back gate")

    def test_model_output_saved_as_markdown_and_kept_out_of_record(self):
        def fake_model(api_key, model, system, user):
            return {"inferences": [], "questions": [{"id": "goal", "text": "Goal"}],
                    "_raw": '{"questions": [{"id": "goal"}]}'}

        record = qn.generate(
            mode="scan", plan=[], snapshot=None, description={}, previous_items=[],
            api_key=FAKE_KEY, model="m", lab_folder=REPO / "lab_context", model_call=fake_model,
        )
        with tempfile.TemporaryDirectory() as folder:
            path = qn.save_model_output(record, folder, "SHG map/1")
            text = Path(path).read_text(encoding="utf-8")
        self.assertTrue(Path(path).name.startswith("SHG_map_1_questionnaire_"))
        self.assertIn("## Raw model reply", text)
        self.assertIn('{"questions": [{"id": "goal"}]}', text)
        self.assertIn("**Goal**", text)
        self.assertNotIn(FAKE_KEY, text)
        self.assertNotIn(qn.DEBUG_KEY, record)

        no_key = qn.generate(
            mode="scan", plan=[], snapshot=None, description={}, previous_items=[],
            api_key="", model="m", lab_folder=REPO / "lab_context",
            model_call=lambda *a: (_ for _ in ()).throw(qn.QuestionnaireUnavailable("no API key set")),
        )
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(qn.save_model_output(no_key, folder, "x"))
        self.assertNotIn(qn.DEBUG_KEY, no_key)

    def test_previous_answers_drop_stale_and_duplicate_entries(self):
        items = [
            {"id": "laser_power", "text": "Laser power at sample", "answer": "5", "status": "answered"},
            {"id": "confirm_inf_axis_x", "text": "Confirm: Swept axis x", "answer": "galvo", "status": "prefilled"},
            {"id": "laser_power_old", "text": "Laser power at sample?", "answer": "7", "status": "answered"},
            {"id": "laser_power", "text": "Laser power", "answer": "9", "status": "answered"},
            {"id": "goal", "text": "Goal", "answer": None, "status": "not_answered"},
        ]
        self.assertEqual(qn.previous_answers(items),
                         [{"id": "laser_power", "text": "Laser power at sample", "answer": "5"}])

    def test_suggestions_offer_answers_and_setup_section(self):
        items = qn.parse_suggestions(
            "## this scan\n- Polarization: parallel / crossed / other\n"
            "## setup\n- Objective (often)\n"
        )
        self.assertEqual(items[0]["text"], "Polarization")
        self.assertEqual(items[0]["options"], ["parallel", "crossed", "other"])
        self.assertEqual(items[0]["section"], "scan")
        self.assertEqual(items[1]["section"], "setup")

    def test_queue_inferences_split_per_scan(self):
        inferences = qn.normalize_inferences([
            {"field": "temperature", "value": "3-30 K series", "basis": "", "confidence": "high", "scope": "queue"},
            {"field": "temperature", "value": "10 K", "basis": "", "confidence": "high", "scope": "scan_b"},
            {"field": "temperature", "value": "3 K", "basis": "", "confidence": "high", "scope": "scan_a"},
        ])
        self.assertEqual([i["value"] for i in qn.inferences_for_scan(inferences, "scan_a")],
                         ["3-30 K series", "3 K"])

    def test_queue_plan_lists_scans_and_manual_sets(self):
        scan = SimpleNamespace(info={"name": "map", "levels": {}})
        manual = SimpleNamespace(channel_name="opticool_temperature", value_text=lambda: "10")
        plan = queue_plan([SimpleNamespace(scan=scan), manual])
        self.assertEqual(plan[0]["type"], "scan")
        self.assertEqual(plan[1], {"type": "manual_set", "channel": "opticool_temperature", "value": "10"})


class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_old_settings_migrate_and_each_provider_keeps_its_model(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "settings.json").write_text(
                json.dumps({"description": {}, "model": "claude-sonnet-5-5"}), encoding="utf-8"
            )
            settings = profile.SetupCaptureSettings(Path(folder))
            self.assertEqual(settings.provider, profile.PROVIDER_ANTHROPIC)
            self.assertEqual(settings.model, "claude-sonnet-5-5")
            self.assertEqual(settings.model_for(profile.PROVIDER_DEEPSEEK), "deepseek-v4-pro")
            self.assertEqual(settings.effort, "low")
            settings.set_provider_model(profile.PROVIDER_DEEPSEEK, "deepseek-reasoner")
            again = profile.SetupCaptureSettings(Path(folder))
            self.assertEqual(again.provider, profile.PROVIDER_DEEPSEEK)
            self.assertEqual(again.model, "deepseek-reasoner")
            self.assertEqual(again.model_for(profile.PROVIDER_ANTHROPIC), "claude-sonnet-5-5")

    def test_keys_are_separate_per_provider(self):
        keys = profile.ApiKeyStore()
        keys.keyring_available = False
        keys.set("a-key", profile.PROVIDER_ANTHROPIC)
        keys.set("d-key", profile.PROVIDER_DEEPSEEK)
        self.assertEqual(keys.get(profile.PROVIDER_ANTHROPIC), "a-key")
        self.assertEqual(keys.get(profile.PROVIDER_DEEPSEEK), "d-key")

    def test_deepseek_call_uses_json_mode_and_parses_reply(self):
        import openai

        reply = {"inferences": [], "questions": [{"id": "q", "text": "Laser power?"}]}
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content="```json\n" + json.dumps(reply) + "\n```"),
            )]
        )
        with mock.patch.object(openai, "OpenAI") as client_cls:
            create = client_cls.return_value.chat.completions.create
            create.return_value = fake_response
            result = qn.call_model(FAKE_KEY, "deepseek-chat", "sys", "user",
                                   provider=profile.PROVIDER_DEEPSEEK)
        self.assertEqual(result["questions"][0]["text"], "Laser power?")
        self.assertEqual(client_cls.call_args.kwargs["base_url"], "https://api.deepseek.com")
        request = create.call_args.kwargs
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertEqual(request["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertIn('"inferences"', request["messages"][0]["content"])

        fake_response.choices[0].finish_reason = "length"
        with mock.patch.object(openai, "OpenAI") as client_cls:
            client_cls.return_value.chat.completions.create.return_value = fake_response
            with self.assertRaises(qn.QuestionnaireUnavailable):
                qn.call_model(FAKE_KEY, "deepseek-reasoner", "s", "u",
                              provider=profile.PROVIDER_DEEPSEEK)
            sent = client_cls.return_value.chat.completions.create.call_args.kwargs
            self.assertNotIn("response_format", sent)

    def test_claude_goes_through_openai_sdk_with_low_effort_and_fallback(self):
        import openai

        reply = json.dumps({"inferences": [], "questions": [{"id": "q", "text": "x?"}]})
        response = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=reply))])
        # Built without __init__ so the test does not depend on the SDK's HTTP types.
        refused = openai.BadRequestError.__new__(openai.BadRequestError)
        with mock.patch.object(openai, "OpenAI") as client_cls:
            create = client_cls.return_value.chat.completions.create
            create.side_effect = [refused, response]
            result = qn.call_model(FAKE_KEY, "claude-sonnet-5-5", "s", "u")
        self.assertEqual(result["questions"][0]["text"], "x?")
        self.assertEqual(client_cls.call_args.kwargs["base_url"], "https://api.anthropic.com/v1/")
        first, second = create.call_args_list
        self.assertEqual(first.kwargs["extra_body"], {"output_config": {"effort": "low"}})
        self.assertNotIn("response_format", first.kwargs)
        self.assertNotIn("extra_body", second.kwargs)
        self.assertEqual(second.kwargs["model"], "claude-sonnet-5-5")

    def test_other_provider_needs_base_url_and_uses_it(self):
        import openai

        with self.assertRaises(qn.QuestionnaireUnavailable):
            qn.call_model(FAKE_KEY, "m", "s", "u", provider=profile.PROVIDER_OPENAI_COMPATIBLE)
        reply = json.dumps({"inferences": [], "questions": [{"id": "q", "text": "x?"}]})
        response = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=reply))])
        with mock.patch.object(openai, "OpenAI") as client_cls:
            client_cls.return_value.chat.completions.create.return_value = response
            qn.call_model(FAKE_KEY, "qwen-max", "s", "u",
                          provider=profile.PROVIDER_OPENAI_COMPATIBLE,
                          base_url="https://example.invalid/v1")
        self.assertEqual(client_cls.call_args.kwargs["base_url"], "https://example.invalid/v1")

    def test_dialog_switches_provider_model_and_saves(self):
        from core.setup_capture.widgets import SetupCaptureDialog

        with tempfile.TemporaryDirectory() as folder:
            keys = profile.ApiKeyStore()
            keys.keyring_available = False
            controller = SetupCaptureController(
                settings=profile.SetupCaptureSettings(Path(folder)), keys=keys,
                lab_folder=REPO / "lab_context",
            )
            dialog = SetupCaptureDialog(controller)
            self.assertEqual(dialog.model_lineEdit.text(), "claude-sonnet-5-5")
            self.assertEqual(dialog.effort_comboBox.currentText(), "low")
            dialog.provider_comboBox.setCurrentIndex(
                dialog.provider_comboBox.findData(profile.PROVIDER_DEEPSEEK)
            )
            self.assertEqual(dialog.model_lineEdit.text(), "deepseek-v4-pro")
            self.assertTrue(dialog.effort_comboBox.isHidden())
            dialog.key_lineEdit.setText("d-key")
            dialog._save()
            self.assertEqual(controller.provider, profile.PROVIDER_DEEPSEEK)
            self.assertEqual(keys.get(profile.PROVIDER_DEEPSEEK), "d-key")
            self.assertEqual(keys.get(profile.PROVIDER_ANTHROPIC), "")
            dialog.deleteLater()


class _MainWindow(QtWidgets.QWidget):
    def __init__(self, output_root, controller_folder):
        super().__init__()
        self.save_info_path = QtWidgets.QPlainTextEdit(str(output_root), self)
        self.ppt_path = QtWidgets.QPlainTextEdit("", self)
        self.backup_path = QtWidgets.QPlainTextEdit("", self)
        self.scanlist = SimpleNamespace(serial=QtWidgets.QSpinBox(self))
        self.scanlist.serial.setRange(0, 9999)
        keys = SimpleNamespace(get=lambda provider="anthropic": "", keyring_available=False)
        self.setup_capture = SetupCaptureController(
            main_window=self,
            parent=self,
            settings=profile.SetupCaptureSettings(controller_folder),
            keys=keys,
            lab_folder=REPO / "lab_context",
        )


class ScanQuestionnaireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zmeter_setup_")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.output_root = root / "data"
        self.output_root.mkdir()
        self.main_window = _MainWindow(self.output_root, root / "settings")
        info = copy.deepcopy(ScanInfo)
        info["plots"] = {"line_plots": {}, "image_plots": {}}
        self.scan = Scan(
            name="probe",
            info=info,
            setter_equipment_info={},
            getter_equipment_info={},
            main_window=self.main_window,
        )
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.scan.close()
        self.scan.deleteLater()
        self.main_window.close()
        self.main_window.deleteLater()
        self.app.processEvents()

    @contextmanager
    def _no_external_outputs(self):
        real_exists = os.path.exists
        with (
            mock.patch(
                "core.scan.os.path.exists",
                side_effect=lambda p: False if str(p).upper().startswith("Z:") else real_exists(p),
            ),
            mock.patch("core.scan.QFileDialog.getSaveFileName", side_effect=AssertionError),
        ):
            yield

    def _record(self):
        return {
            "generated_at": "2026-10-21T12:00:00",
            "model": "claude-haiku-5-5",
            "source": "agent",
            "error": None,
            "items": qn.normalize_items(
                [{"id": "laser", "text": "Laser wavelength?"}, {"id": "spot", "text": "Same spot?"}],
                origin="agent",
            ),
        }

    def _wait_for(self, predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def test_tab_sits_before_plots_and_is_off_by_default(self):
        tabs = self.scan.ScanTab
        index = tabs.indexOf(self.scan.questionnaire_tab)
        self.assertEqual(index + 1, tabs.indexOf(self.scan.Plots1Tab))
        self.assertFalse(self.scan.questionnaire_tab.enabled_checkBox.isChecked())
        self.assertNotIn("questionnaire", self.scan.info)

    def test_answers_round_trip_through_scan_json(self):
        self.scan.questionnaire_tab.enabled_checkBox.setChecked(True)
        self.scan.questionnaire_tab.set_record(self._record())
        items = self.scan.questionnaire_tab.items()
        items[0]["answer"] = "1064 nm"
        items[0]["status"] = qn.STATUS_ANSWERED
        items[1]["answer"] = "unknown"
        items[1]["status"] = qn.STATUS_UNKNOWN
        self.scan._on_questionnaire_edited()
        self.scan.info["setup"] = {"snapshot_start": {"devices": {}}, "changed_during_scan": []}
        self.scan.info["format_version"] = 2

        with self._no_external_outputs():
            self.scan.when_save_clicked()
        saved_path = Path(self.scan.last_saved_json_path)
        saved = json.loads(saved_path.read_text(encoding="utf-8"))
        self.assertTrue(saved["questionnaire"]["enabled"])
        self.assertEqual(saved["questionnaire"]["record"]["items"][0]["answer"], "1064 nm")
        self.assertEqual(saved["setup"]["snapshot_start"], {"devices": {}})
        self.assertEqual(saved["format_version"], 2)

        other = Scan(name="other", info=copy.deepcopy(ScanInfo), setter_equipment_info={},
                     getter_equipment_info={}, main_window=self.main_window)
        self.addCleanup(other.deleteLater)
        with mock.patch("core.scan.QFileDialog.getOpenFileName", return_value=(str(saved_path), "")):
            other.when_load_clicked()
        self.assertTrue(other.questionnaire_tab.enabled_checkBox.isChecked())
        self.assertEqual(other.questionnaire_tab.items()[1]["status"], qn.STATUS_UNKNOWN)
        self.assertEqual(len(other.questionnaire_tab.question_list._rows), 2)

    def test_save_answers_writes_sidecar_and_never_rewrites_scan_file(self):
        self.scan.questionnaire_tab.set_record(self._record())
        self.assertFalse(self.scan.when_save_answers_clicked())
        with self._no_external_outputs():
            self.scan.when_save_clicked()
        scan_file = Path(self.scan.last_saved_json_path)
        before = scan_file.read_text(encoding="utf-8")
        self.scan.questionnaire_tab.items()[0]["answer"] = "750 nm"
        self.scan.questionnaire_tab.items()[0]["status"] = qn.STATUS_ANSWERED
        self.assertTrue(self.scan.when_save_answers_clicked())
        sidecar = scan_file.with_name(scan_file.stem + ".setup.json")
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(payload["scan_file"], scan_file.name)
        self.assertEqual(payload["questionnaire"]["record"]["items"][0]["answer"], "750 nm")
        self.assertEqual(scan_file.read_text(encoding="utf-8"), before)

    def test_start_snapshot_triggers_generation_with_suggestion_fallback(self):
        self.scan.questionnaire_tab.enabled_checkBox.setChecked(True)
        self.scan._on_setup_snapshot("start", {"time": "t", "devices": {}})
        self.assertTrue(self._wait_for(lambda: bool(self.scan.questionnaire_tab.items())))
        record = self.scan.info["questionnaire"]["record"]
        self.assertEqual(record["source"], "suggestions")
        self.assertIn("API key", record["error"])

    def test_queue_questionnaire_suppresses_per_scan_generation(self):
        self.scan.questionnaire_tab.enabled_checkBox.setChecked(True)
        self.scan.queue_questionnaire_active = True
        with mock.patch.object(self.main_window.setup_capture, "generate_async") as generate:
            self.scan._on_setup_snapshot("start", {"devices": {}})
        generate.assert_not_called()

    def test_queue_copy_is_independent_per_scan(self):
        other = Scan(name="other", info=copy.deepcopy(ScanInfo), setter_equipment_info={},
                     getter_equipment_info={}, main_window=self.main_window)
        self.addCleanup(other.deleteLater)
        record = self._record()
        meta = {"queue_id": "queue_1", "submitted_at": "now", "questions": [], "snapshot": None}
        self.scan.apply_queue_questionnaire(record, meta)
        other.apply_queue_questionnaire(record, meta)
        self.scan.questionnaire_tab.items()[0]["answer"] = "changed"
        self.assertNotEqual(other.questionnaire_tab.items()[0]["answer"], "changed")
        self.assertTrue(other.info["questionnaire"]["enabled"])
        self.assertEqual(other.info["questionnaire"]["queue"]["queue_id"], "queue_1")

    def test_conclusions_edit_and_wrong_round_trip(self):
        record = self._record()
        record["inferences"] = qn.normalize_inferences([
            {"field": "measurement_type", "value": "SHG", "basis": "name", "confidence": "high", "scope": "scan"},
            {"field": "polarization_config", "value": "parallel", "basis": "xx", "confidence": "high", "scope": "scan"},
        ])
        self.scan.questionnaire_tab.enabled_checkBox.setChecked(True)
        self.scan.questionnaire_tab.set_record(record)
        conclusions = self.scan.questionnaire_tab.conclusion_list
        self.assertFalse(conclusions.isHidden())
        _inf, line, _wrong = conclusions._rows[0]
        line.setText("reflection")
        line.textEdited.emit("reflection")
        conclusions._rows[1][2].setChecked(True)
        with self._no_external_outputs():
            self.scan.when_save_clicked()
        saved = json.loads(Path(self.scan.last_saved_json_path).read_text(encoding="utf-8"))
        stored = saved["questionnaire"]["record"]["inferences"]
        self.assertEqual(stored[0]["value"], "reflection")
        self.assertEqual(stored[0]["status"], qn.INFERENCE_CORRECTED)
        self.assertEqual(stored[0]["model_value"], "SHG")
        self.assertEqual(stored[1]["status"], qn.INFERENCE_REJECTED)

    def test_medium_conclusion_shows_check_and_chips_fill_answers(self):
        record = self._record()
        record["items"] = qn.normalize_items(
            [{"id": "pol", "text": "Polarization", "options": ["parallel", "crossed"]},
             {"id": "obj", "text": "Objective", "section": "setup"}],
            origin="agent",
        )
        record["inferences"] = qn.normalize_inferences([
            {"field": "sample", "value": "TXT15", "basis": "name", "confidence": "high", "scope": "scan"},
            {"field": "temperature", "value": "3.4 K", "basis": "3p4K", "confidence": "medium", "scope": "scan"},
        ])
        tab = self.scan.questionnaire_tab
        tab.set_record(record)
        self.assertIn("1 to check", tab.status_label.text())
        inference, _line, _wrong = tab.conclusion_list._rows[0]
        self.assertEqual(inference["field"], "temperature")  # checks come first
        correct = [b for b in tab.conclusion_list.findChildren(QtWidgets.QToolButton)
                   if b.text() == "Correct"]
        self.assertEqual(len(correct), 1)
        correct[0].setChecked(True)
        self.assertEqual(inference["status"], qn.INFERENCE_CONFIRMED)
        self.assertNotIn("to check", tab.status_label.text())

        chip = [b for b in tab.question_list.findChildren(QtWidgets.QToolButton)
                if b.text() == "crossed"][0]
        chip.click()
        self.assertEqual(tab.items()[0]["answer"], "crossed")
        self.assertEqual(tab.items()[0]["status"], qn.STATUS_ANSWERED)

    def test_end_snapshot_lists_changed_settings(self):
        self.scan.info["setup"] = {}
        self.scan._on_setup_snapshot("start", {"devices": {"a": {"fields": {"f": 1}}}})
        self.scan._on_setup_snapshot("end", {"devices": {"a": {"fields": {"f": 2}}}})
        self.assertEqual(self.scan.info["setup"]["changed_during_scan"], ["a.f"])


if __name__ == "__main__":
    unittest.main()
