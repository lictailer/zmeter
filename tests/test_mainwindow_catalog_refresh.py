from __future__ import annotations

import copy
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6 import QtWidgets

import start_zmeter
from devices.autofocus_xuguo.autofocusXZ_hardware import AutoPositionXZHardware
from core.device_catalog import (
    DeviceCatalogBusyError,
    DeviceCatalogError,
    DeviceCatalogReferenceError,
    DeviceCatalogRollbackError,
)
from core.device_command_router import DeviceCommandClient
from core.device_management import DeviceSnapshot
from core.mainWindow import MainWindow
from core.scan_info import ScanInfo
from core.shared_runtime import RuntimeServices


class _CatalogLogic:
    def __init__(self):
        self.alpha = 0.0
        self.shared = 0.0

    def set_alpha(self, value):
        self.alpha = float(value)

    def get_alpha(self):
        return self.alpha

    def set_shared(self, value):
        self.shared = float(value)

    def get_shared(self):
        return self.shared


class _NoChannelLogic:
    pass


class _ExplodingLogic:
    def __init__(self):
        self.property_reads = 0

    def __dir__(self):
        return ["get_boom"]

    @property
    def get_boom(self):
        self.property_reads += 1
        raise RuntimeError("injected discovery failure")


class _BrokenDirectoryLogic:
    def __dir__(self):
        raise RuntimeError("injected discovery failure")


class _CatalogDevice(QtWidgets.QWidget):
    def __init__(self, logic=None):
        super().__init__()
        self.logic = logic or _CatalogLogic()
        self.show_calls = 0
        self.normal_calls = 0
        self.raise_calls = 0
        self.activate_calls = 0
        self.minimized = True

    def show(self):
        self.show_calls += 1

    def isMinimized(self):
        return self.minimized

    def showNormal(self):
        self.normal_calls += 1
        self.minimized = False

    def raise_(self):
        self.raise_calls += 1

    def activateWindow(self):
        self.activate_calls += 1


class _TypeErrorRouterDevice(_CatalogDevice):
    def __init__(self):
        super().__init__()
        self.configure_calls = 0
        self.detach_calls = 0

    def configure_command_router(self, command_router, source_device=None):
        self.configure_calls += 1
        self.command_router = command_router
        self.device_label = source_device
        raise TypeError("injected hook failure")

    def detach_command_router(self):
        self.detach_calls += 1
        self.command_router = None


class _ReferenceProviderDevice(_CatalogDevice):
    def __init__(self, referenced_label):
        super().__init__()
        self.referenced_label = referenced_label
        self.reference_queries = []

    def find_catalog_references(
        self,
        *,
        removed_setters,
        removed_getters,
        removed_device_labels,
    ):
        self.reference_queries.append(
            (
                frozenset(removed_setters),
                frozenset(removed_getters),
                frozenset(removed_device_labels),
            )
        )
        if self.referenced_label in removed_device_labels:
            return (f"provider target: {self.referenced_label}",)
        return ()


class MainWindowCatalogRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.services = RuntimeServices()
        _profile, self.manager = start_zmeter.create_profile_session(
            self.services,
            start_zmeter.REPOSITORY_ROOT / "config" / "profiles" / "mock.json",
        )
        self.window = MainWindow(
            info=copy.deepcopy(ScanInfo),
            save_path=self.temp_directory.name,
            backup_main_path=None,
            device_manager=self.manager,
        )
        self.base_device_snapshot = self.manager.snapshot()
        self.extra_widgets = []

    def tearDown(self):
        if not self.window._session_shutdown_complete:
            self.window.shutdown_session()
        self.window.hide()
        self.window.deleteLater()
        for widget in self.extra_widgets:
            widget.close()
            widget.deleteLater()
        self.app.processEvents()
        self.services.shutdown()
        self.temp_directory.cleanup()

    def _track(self, widget):
        self.extra_widgets.append(widget)
        return widget

    def _snapshot(
        self,
        equipment,
        *,
        setter_filters=None,
        getter_filters=None,
        profile="phase5-test",
    ):
        labels = tuple(equipment)
        setter_filters = setter_filters or {}
        getter_filters = getter_filters or {}
        return DeviceSnapshot(
            profile_name=profile,
            records=(),
            equipment=equipment,
            setter_filters={
                label: setter_filters.get(label)
                for label in labels
            },
            getter_filters={
                label: getter_filters.get(label)
                for label in labels
            },
        )

    def _with_device(self, label, device, *, setters=None, getters=None):
        equipment = dict(self.base_device_snapshot.equipment)
        equipment[label] = device
        setter_filters = dict(self.base_device_snapshot.setter_filters)
        getter_filters = dict(self.base_device_snapshot.getter_filters)
        setter_filters[label] = setters
        getter_filters[label] = getters
        return self._snapshot(
            equipment,
            setter_filters=setter_filters,
            getter_filters=getter_filters,
        )

    def _apply_snapshot(self, snapshot):
        return self.window._apply_device_snapshot_for_testing_or_legacy(snapshot)

    def _template_setter(self, channel):
        info = copy.deepcopy(self.window.scanlist.info)
        info["levels"]["level0"]["setters"]["setter0"]["channel"] = channel
        self.window.scanlist.info = info

    def test_snapshot_is_recursive_immutable_detached_and_repeat_is_idempotent(self):
        first = self.window.catalog_snapshot
        button_ids = [id(button) for button in self.window.open_equipment_buttons]

        with self.assertRaises(TypeError):
            first.setter_channels["mock_device_1"] = ()
        with self.assertRaises(TypeError):
            first.setter_callables["mock_device_1"]["extra"] = lambda _value: None

        second = self._apply_snapshot(self.base_device_snapshot)
        self.assertIsNot(first, second)
        self.assertEqual(
            [id(button) for button in self.window.open_equipment_buttons],
            button_ids,
        )
        self.window.setter_equipment_info["mock_device_1"].append("local mutation")
        self.assertNotIn("local mutation", first.setter_channels["mock_device_1"])
        self.assertNotIn("local mutation", second.setter_channels["mock_device_1"])

    def test_add_remove_rebuilds_all_maps_buttons_router_choices_and_range_visibility(self):
        device = self._track(_CatalogDevice())
        self.window.scan_range_limits[("lab_device", "alpha")] = (-2.0, 2.0)
        old_snapshot = self.window.catalog_snapshot
        added = self._with_device(
            "lab_device",
            device,
            setters=("missing", "alpha"),
            getters=("shared",),
        )

        published = []
        self.window.command_router.sig_catalog_changed.connect(
            lambda catalog: published.append(copy.deepcopy(catalog))
        )
        result = self._apply_snapshot(added)

        self.assertEqual(self.window.setter_equipment_info["lab_device"], ["alpha"])
        self.assertEqual(self.window.getter_equipment_info["lab_device"], ["shared"])
        self.assertIs(
            self.window.setter_equipment_info_for_scanning["lab_device"]["alpha"].__self__,
            device.logic,
        )
        self.assertEqual(
            result.router_catalog["lab_device"],
            {"readable": ("shared",), "writable": ("alpha",)},
        )
        self.assertEqual(published[-1]["lab_device"]["writable"], ["alpha"])
        self.assertEqual(
            [button.text() for button in self.window.open_equipment_buttons][-1],
            "lab_device",
        )
        self.assertIn(
            "lab_device_alpha",
            self.window.artificial_channel_2d.ocx_nested_menu.choice_names,
        )
        self.assertEqual(
            self.window.active_scan_range_limits[("lab_device", "alpha")],
            (-2.0, 2.0),
        )
        self.assertIs(device.command_router, self.window.command_router)
        self.assertEqual(device.device_label, "lab_device")
        self.assertEqual(tuple(old_snapshot.equipment), ("mock_device_1", "mock_device_2"))

        button = self.window.open_equipment_buttons[-1]
        button.click()
        self.assertEqual(
            (device.show_calls, device.normal_calls, device.raise_calls, device.activate_calls),
            (1, 1, 1, 1),
        )

        self._apply_snapshot(self.base_device_snapshot)
        self.assertNotIn("lab_device", self.window.equips)
        self.assertNotIn("lab_device", self.window.get_device_channel_catalog())
        self.assertNotIn(
            "lab_device_alpha",
            self.window.artificial_channel_2d.ocx_nested_menu.choice_names,
        )
        self.assertNotIn(("lab_device", "alpha"), self.window.active_scan_range_limits)
        self.assertIn(("lab_device", "alpha"), self.window.scan_range_limits)
        self.assertFalse(hasattr(device, "command_router"))
        show_calls = device.show_calls
        button.click()
        self.assertEqual(device.show_calls, show_calls)

    def test_template_references_do_not_block_catalog_removal(self):
        device = self._track(_CatalogDevice())
        added = self._with_device("lab_device", device)
        self._apply_snapshot(added)
        self._template_setter("lab_device_alpha")
        filtered = self._with_device(
            "lab_device",
            device,
            setters=("shared",),
            getters=None,
        )
        self._apply_snapshot(filtered)
        self.assertNotIn(
            "alpha", self.window.catalog_snapshot.setter_channels["lab_device"]
        )

        self._template_setter("lab_device_silently_filtered_unknown")
        self._apply_snapshot(self.base_device_snapshot)
        self.assertNotIn("lab_device", self.window.catalog_snapshot.equipment)

    def test_zero_channel_template_reference_does_not_block_removal(self):
        device = self._track(_CatalogDevice(_NoChannelLogic()))
        added = self._with_device("zero_device", device)
        self._apply_snapshot(added)
        self._template_setter("zero_device_unknown")

        self._apply_snapshot(self.base_device_snapshot)
        self.assertNotIn("zero_device", self.window.catalog_snapshot.equipment)

    def test_device_owned_reference_provider_blocks_target_removal(self):
        target = self._track(_CatalogDevice())
        provider = self._track(_ReferenceProviderDevice("target_device"))
        equipment = dict(self.base_device_snapshot.equipment)
        equipment.update(target_device=target, provider_device=provider)
        self._apply_snapshot(self._snapshot(equipment))
        old_snapshot = self.window.catalog_snapshot
        old_button_ids = [id(button) for button in self.window.open_equipment_buttons]

        equipment.pop("target_device")
        with self.assertRaises(DeviceCatalogReferenceError) as caught:
            self._apply_snapshot(self._snapshot(equipment))

        self.assertIn("provider target: target_device", caught.exception.references)
        self.assertEqual(
            provider.reference_queries[-1][2],
            frozenset({"target_device"}),
        )
        self.assertIs(self.window.catalog_snapshot, old_snapshot)
        self.assertEqual(
            [id(button) for button in self.window.open_equipment_buttons],
            old_button_ids,
        )

    def test_busy_and_discovery_failures_leave_every_published_surface_unchanged(self):
        old_snapshot = self.window.catalog_snapshot
        old_router = self.window.get_device_channel_catalog()
        old_button_ids = [id(button) for button in self.window.open_equipment_buttons]
        old_choices = self.window.artificial_channel_2d.ocx_nested_menu.choice_names
        device = self._track(_CatalogDevice(_BrokenDirectoryLogic()))
        staged = self._with_device("bad_device", device)

        with mock.patch.object(
            self.window.scanlist,
            "catalog_mutation_blockers",
            return_value=("queue UI completion",),
        ):
            with self.assertRaises(DeviceCatalogBusyError):
                self._apply_snapshot(staged)

        with self.assertRaisesRegex(RuntimeError, "injected discovery failure"):
            self._apply_snapshot(staged)

        self.assertIs(self.window.catalog_snapshot, old_snapshot)
        self.assertEqual(self.window.get_device_channel_catalog(), old_router)
        self.assertEqual(
            [id(button) for button in self.window.open_equipment_buttons],
            old_button_ids,
        )
        self.assertEqual(
            self.window.artificial_channel_2d.ocx_nested_menu.choice_names,
            old_choices,
        )

    def test_discovery_skips_channel_named_properties_without_evaluating_them(self):
        logic = _ExplodingLogic()
        device = self._track(_CatalogDevice(logic))
        staged = self._with_device("descriptor_device", device)

        first = self._apply_snapshot(staged)
        second = self._apply_snapshot(staged)

        self.assertEqual(logic.property_reads, 0)
        self.assertEqual(first.setter_channels["descriptor_device"], ())
        self.assertEqual(first.getter_channels["descriptor_device"], ())
        self.assertEqual(second.getter_channels["descriptor_device"], ())

    def test_consumer_failure_rolls_back_maps_choices_metadata_and_snapshot(self):
        old_snapshot = self.window.catalog_snapshot
        old_router = self.window.get_device_channel_catalog()
        old_choices = self.window.artificial_channel_2d.ocx_nested_menu.choice_names
        device = self._track(_CatalogDevice())
        staged = self._with_device("new_device", device)
        original_refresh = self.window.scanlist.refresh_catalog
        calls = []

        def fail_once(setters, getters):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("injected catalog consumer failure")
            return original_refresh(setters, getters)

        with mock.patch.object(self.window.scanlist, "refresh_catalog", side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError, "consumer failure"):
                self._apply_snapshot(staged)

        self.assertIs(self.window.catalog_snapshot, old_snapshot)
        self.assertEqual(self.window.get_device_channel_catalog(), old_router)
        self.assertEqual(
            self.window.artificial_channel_2d.ocx_nested_menu.choice_names,
            old_choices,
        )
        self.assertFalse(hasattr(device, "command_router"))
        self.assertNotIn("new_device", self.window.equips)

    def test_button_commit_exception_after_mutation_restores_previous_layout(self):
        old_snapshot = self.window.catalog_snapshot
        old_button_ids = [id(button) for button in self.window.open_equipment_buttons]
        old_labels = [button.text() for button in self.window.open_equipment_buttons]
        device = self._track(_CatalogDevice())
        staged = self._with_device("new_device", device)
        original_commit = self.window._commit_device_button_reconciliation

        def commit_then_fail(plan):
            original_commit(plan)
            raise RuntimeError("injected post-commit failure")

        with mock.patch.object(
            self.window,
            "_commit_device_button_reconciliation",
            side_effect=commit_then_fail,
        ):
            with self.assertRaisesRegex(RuntimeError, "post-commit failure"):
                self._apply_snapshot(staged)

        self.assertIs(self.window.catalog_snapshot, old_snapshot)
        self.assertEqual(
            [id(button) for button in self.window.open_equipment_buttons],
            old_button_ids,
        )
        self.assertEqual(
            [button.text() for button in self.window.open_equipment_buttons],
            old_labels,
        )
        self.assertFalse(hasattr(device, "command_router"))

    def test_router_publication_failure_rolls_back_committed_buttons_and_metadata(self):
        old_snapshot = self.window.catalog_snapshot
        old_button_ids = [id(button) for button in self.window.open_equipment_buttons]
        device = self._track(_CatalogDevice())
        staged = self._with_device("new_device", device)
        original_publish = self.window.command_router.publish_catalog
        calls = []

        def fail_once(catalog):
            calls.append(copy.deepcopy(catalog))
            if len(calls) == 1:
                raise RuntimeError("injected router publication failure")
            return original_publish(catalog)

        with mock.patch.object(
            self.window.command_router,
            "publish_catalog",
            side_effect=fail_once,
        ):
            with self.assertRaisesRegex(RuntimeError, "publication failure"):
                self._apply_snapshot(staged)

        self.assertEqual(len(calls), 2)
        self.assertIs(self.window.catalog_snapshot, old_snapshot)
        self.assertEqual(
            [id(button) for button in self.window.open_equipment_buttons],
            old_button_ids,
        )
        self.assertFalse(hasattr(device, "command_router"))
        self.assertNotIn("new_device", self.window.equips)

    def test_removal_failure_reattaches_device_and_restores_its_button(self):
        device = self._track(_CatalogDevice())
        added = self._with_device("removal_target", device)
        self._apply_snapshot(added)
        old_snapshot = self.window.catalog_snapshot
        old_router = self.window.get_device_channel_catalog()
        button = self.window._equipment_buttons_by_label["removal_target"]
        old_buttons = tuple(self.window.open_equipment_buttons)
        original_publish = self.window.command_router.publish_catalog
        published = []

        def fail_once(catalog):
            published.append(copy.deepcopy(catalog))
            if len(published) == 1:
                raise RuntimeError("injected removal publication failure")
            return original_publish(catalog)

        with mock.patch.object(
            self.window.command_router,
            "publish_catalog",
            side_effect=fail_once,
        ):
            with self.assertRaisesRegex(RuntimeError, "removal publication failure"):
                self._apply_snapshot(self.base_device_snapshot)

        self.assertEqual(len(published), 2)
        self.assertNotIn("removal_target", published[0])
        self.assertEqual(published[1], old_router)
        self.assertIs(self.window.catalog_snapshot, old_snapshot)
        self.assertIs(self.window.equips["removal_target"], device)
        self.assertIs(
            self.window._equipment_buttons_by_label["removal_target"],
            button,
        )
        self.assertEqual(
            tuple(self.window.open_equipment_buttons),
            old_buttons,
        )
        for expected_index, restored_button in enumerate(old_buttons):
            layout_index = self.window.devices_grid_layout.indexOf(restored_button)
            self.assertGreaterEqual(layout_index, 0)
            row, column, _row_span, _column_span = (
                self.window.devices_grid_layout.getItemPosition(layout_index)
            )
            self.assertEqual((row, column), (expected_index // 6, expected_index % 6))
        self.assertFalse(button.isHidden())
        self.assertIs(device.command_router, self.window.command_router)
        self.assertEqual(device.device_label, "removal_target")
        self.assertIs(device.logic.command_router, self.window.command_router)
        self.assertEqual(device.logic.device_label, "removal_target")
        show_calls = device.show_calls
        button.click()
        self.assertEqual(device.show_calls, show_calls + 1)

    def test_router_round_trip_uses_added_catalog_then_rejects_removed_device(self):
        device = self._track(_CatalogDevice())
        self._apply_snapshot(self._with_device("routed_device", device))

        write_response = self.window.command_router.route_command(
            {
                "request_id": "write-added",
                "source_device": "catalog-test",
                "action": "write",
                "target_device": "routed_device",
                "channel": "alpha",
                "value": 4.25,
            }
        )
        read_response = self.window.command_router.route_command(
            {
                "request_id": "read-added",
                "source_device": "catalog-test",
                "action": "read",
                "target_device": "routed_device",
                "channel": "alpha",
                "value": None,
            }
        )

        self.assertTrue(write_response["ok"])
        self.assertEqual(write_response["value"], 4.25)
        self.assertTrue(read_response["ok"])
        self.assertEqual(read_response["value"], 4.25)
        self.assertEqual(device.logic.alpha, 4.25)

        self._apply_snapshot(self.base_device_snapshot)
        removed_response = self.window.command_router.route_command(
            {
                "request_id": "read-removed",
                "source_device": "catalog-test",
                "action": "read",
                "target_device": "routed_device",
                "channel": "alpha",
                "value": None,
            }
        )
        self.assertFalse(removed_response["ok"])
        self.assertEqual(removed_response["error_code"], "unknown_device")

    def test_rollback_failure_is_aggregated_and_later_restoration_still_runs(self):
        old_snapshot = self.window.catalog_snapshot
        old_router = self.window.get_device_channel_catalog()
        old_button_ids = [id(button) for button in self.window.open_equipment_buttons]
        device = self._track(_CatalogDevice())
        staged = self._with_device("new_device", device)
        original_publish = self.window.command_router.publish_catalog
        original_button_rollback = self.window._rollback_device_button_reconciliation
        published = []

        def fail_first_publish(catalog):
            published.append(copy.deepcopy(catalog))
            if len(published) == 1:
                raise RuntimeError("injected publication failure")
            return original_publish(catalog)

        def restore_buttons_then_raise(plan):
            original_button_rollback(plan)
            raise RuntimeError("injected button rollback failure")

        with mock.patch.object(
            self.window.command_router,
            "publish_catalog",
            side_effect=fail_first_publish,
        ), mock.patch.object(
            self.window,
            "_rollback_device_button_reconciliation",
            side_effect=restore_buttons_then_raise,
        ):
            with self.assertRaises(DeviceCatalogRollbackError) as caught:
                self._apply_snapshot(staged)

        self.assertIsInstance(caught.exception.apply_error, RuntimeError)
        self.assertEqual(caught.exception.failures[0][0], "restore device buttons")
        self.assertEqual(published[-1], old_router)
        self.assertIs(self.window.catalog_snapshot, old_snapshot)
        self.assertEqual(self.window.get_device_channel_catalog(), old_router)
        self.assertEqual(
            [id(button) for button in self.window.open_equipment_buttons],
            old_button_ids,
        )
        self.assertFalse(hasattr(device, "command_router"))
        self.assertNotIn("new_device", self.window.equips)

    def test_artificial_rename_preflight_and_post_apply_failure_restore_exact_state(self):
        artificial = self.window.artificial_channel_2d
        logic = self.window.artificial_channel_logic
        available_scan = self.window.scanlist.list_available.get_widgets()[0].scan
        available_info = copy.deepcopy(
            available_scan.all_level_setting.all_level_info
        )
        available_info["level0"]["setters"]["setter0"]["channel"] = (
            "artificial_channel_n"
        )
        available_scan.all_level_setting.all_level_info = available_info
        checkpoint = logic.capture_configuration_state()
        old_catalog = self.window.catalog_snapshot
        old_equations = dict(self.window.equations)
        targets = []
        states = []
        logic.sig_target_changed.connect(lambda value: targets.append(dict(value)))
        logic.sig_state_changed.connect(lambda value: states.append(dict(value)))
        artificial.artificialchannelnamex_textEdit.setPlainText("renamed_n")

        with mock.patch.object(QtWidgets.QMessageBox, "warning"):
            self.assertFalse(artificial._on_set_config_clicked())
        self.assertIs(self.window.catalog_snapshot, old_catalog)
        self.assertEqual(logic.artificial_channel_x_name, checkpoint["artificial_channel_x_name"])
        self.assertEqual(logic.equations, checkpoint["equations"])
        np.testing.assert_array_equal(
            logic._original_to_artificial_matrix,
            checkpoint["_original_to_artificial_matrix"],
        )
        self.assertEqual(self.window.equations, old_equations)
        self.assertEqual(targets, [])
        self.assertEqual(states, [])

        available_info["level0"]["setters"]["setter0"]["channel"] = "none"
        available_scan.all_level_setting.all_level_info = available_info
        artificial.artificialchannelnamex_textEdit.setPlainText("renamed_n")
        with mock.patch.object(
            self.window,
            "apply_device_snapshot",
            side_effect=RuntimeError("forced post-apply failure"),
        ), mock.patch.object(QtWidgets.QMessageBox, "warning"):
            self.assertFalse(artificial._on_set_config_clicked())
        self.assertEqual(logic.artificial_channel_x_name, checkpoint["artificial_channel_x_name"])
        self.assertEqual(logic.equations, checkpoint["equations"])
        self.assertIs(self.window.catalog_snapshot, old_catalog)
        self.assertEqual(self.window.equations, old_equations)
        self.assertEqual(targets, [])
        self.assertEqual(states, [])

    def test_successful_artificial_rename_updates_equations_and_immutable_catalog(self):
        self._template_setter("none")
        artificial = self.window.artificial_channel_2d
        logic = self.window.artificial_channel_logic
        observed_target_catalogs = []
        observed_state_catalogs = []
        logic.sig_target_changed.connect(
            lambda _value: observed_target_catalogs.append(
                self.window.catalog_snapshot
            )
        )
        logic.sig_state_changed.connect(
            lambda _value: observed_state_catalogs.append(
                self.window.catalog_snapshot
            )
        )
        artificial.artificialchannelnamex_textEdit.setPlainText("renamed_n")

        self.assertTrue(artificial._on_set_config_clicked())

        self.assertIn(
            "renamed_n",
            self.window.catalog_snapshot.setter_channels["artificial_channel"],
        )
        self.assertNotIn(
            "n",
            self.window.catalog_snapshot.setter_channels["artificial_channel"],
        )
        self.assertEqual(
            self.window.equations,
            self.window.artificial_channel_logic.equations,
        )
        self.assertEqual(len(observed_target_catalogs), 1)
        self.assertEqual(len(observed_state_catalogs), 1)
        self.assertIn(
            "renamed_n",
            observed_target_catalogs[0].setter_channels["artificial_channel"],
        )
        self.assertIs(observed_target_catalogs[0], observed_state_catalogs[0])

    def test_artificial_config_preflight_rejects_catalog_reentrancy_before_mutation(self):
        artificial = self.window.artificial_channel_2d
        logic = self.window.artificial_channel_logic
        checkpoint = logic.capture_configuration_state()
        targets = []
        states = []
        logic.sig_target_changed.connect(lambda value: targets.append(dict(value)))
        logic.sig_state_changed.connect(lambda value: states.append(dict(value)))
        artificial.artificialchannelnamex_textEdit.setPlainText("renamed_n")

        self.window._catalog_mutation_in_progress = True
        try:
            with mock.patch.object(QtWidgets.QMessageBox, "warning"):
                self.assertFalse(artificial._on_set_config_clicked())
        finally:
            self.window._catalog_mutation_in_progress = False

        self.assertEqual(logic.artificial_channel_x_name, checkpoint["artificial_channel_x_name"])
        self.assertEqual(logic.equations, checkpoint["equations"])
        self.assertEqual(targets, [])
        self.assertEqual(states, [])

    def test_router_hook_typeerror_runs_once_and_stable_label_rekey_is_rejected(self):
        device = self._track(_TypeErrorRouterDevice())
        staged = self._with_device("typed_device", device)
        old_snapshot = self.window.catalog_snapshot

        with self.assertRaisesRegex(TypeError, "injected hook failure"):
            self._apply_snapshot(staged)
        self.assertEqual(device.configure_calls, 1)
        self.assertGreaterEqual(device.detach_calls, 1)
        self.assertIs(self.window.catalog_snapshot, old_snapshot)

        existing = self.base_device_snapshot.equipment["mock_device_1"]
        rekeyed_equipment = dict(self.base_device_snapshot.equipment)
        del rekeyed_equipment["mock_device_1"]
        rekeyed_equipment["renamed_mock"] = existing
        with self.assertRaisesRegex(DeviceCatalogError, "labels are stable"):
            self._apply_snapshot(self._snapshot(rekeyed_equipment))

    def test_reentrant_catalog_publication_is_refused_without_disturbing_outer_apply(self):
        reentrant_errors = []

        def reenter(_catalog):
            try:
                self._apply_snapshot(self.base_device_snapshot)
            except Exception as exc:
                reentrant_errors.append(exc)

        self.window.command_router.sig_catalog_changed.connect(reenter)
        result = self._apply_snapshot(self.base_device_snapshot)

        self.assertIs(result, self.window.catalog_snapshot)
        self.assertEqual(len(reentrant_errors), 1)
        self.assertIsInstance(reentrant_errors[0], DeviceCatalogBusyError)
        self.assertFalse(self.window._catalog_mutation_in_progress)

    def test_command_client_and_autofocus_shape_detach_are_idempotent(self):
        hardware = AutoPositionXZHardware()
        hardware.configure_command_router(
            self.window.command_router,
            source_device="feature_autoposition",
        )
        client = hardware._ensure_client()
        self.assertIsInstance(client, DeviceCommandClient)

        hardware.detach_command_router()
        hardware.detach_command_router()
        self.assertIsNone(hardware.command_router)
        self.assertIsNone(hardware._client)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            client.request_catalog()
        forwarded_catalogs = []
        late_responses = []
        client.sig_catalog_changed.connect(forwarded_catalogs.append)
        client.sig_response.connect(late_responses.append)
        client._forward_catalog_changed({"late": {}})
        client._handle_response({"request_id": "late"})
        self.assertEqual(forwarded_catalogs, [])
        self.assertEqual(late_responses, [])

        hardware.set_position_channels(
            "mock_device_1",
            "channel_A",
            "mock_device_2",
            "channel_B",
        )
        hardware.set_reference_channel("mock_device_1", "random_channel")
        references = hardware.find_catalog_references(
            removed_setters={"mock_device_1_channel_A"},
            removed_getters={"mock_device_1_random_channel"},
        )
        self.assertEqual(
            references,
            (
                "autoposition x setter: mock_device_1_channel_A",
                "autoposition reference getter: mock_device_1_random_channel",
            ),
        )


if __name__ == "__main__":
    unittest.main()
