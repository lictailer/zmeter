from __future__ import annotations

import os
import tempfile
import threading
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

import start_zmeter
from core.device_catalog import DeviceCatalogBusyError, DeviceCatalogError
from core.device_management import (
    CatalogMutationProposal,
    ChannelFilters,
    DeviceConfig,
    DeviceMutationBusyError,
    DeviceMutationHooksError,
    DeviceState,
    DeviceUnavailableError,
)
from core.mainWindow import MainWindow
from core.scan import Scan
from core.scan_info import ScanInfo
from core.scanlist import ManualSetItem, ScanList
from core.shared_runtime import RuntimeServices


class RuntimeDeviceUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.services = RuntimeServices()
        self.profile, self.manager = start_zmeter.create_profile_session(
            self.services
        )
        self.window = MainWindow(
            info=ScanInfo,
            save_path=self.temp_directory.name,
            backup_main_path=None,
            device_manager=self.manager,
        )

    def tearDown(self):
        try:
            if not self.window._session_shutdown_complete:
                self.window.shutdown_session(timeout_ms=5_000)
        finally:
            self.window.hide()
            self.window.deleteLater()
            for _ in range(4):
                self.app.processEvents()
            self.services.shutdown()
            self.temp_directory.cleanup()

    @staticmethod
    def _config(device_id="runtime_mock", *, connect=True):
        return DeviceConfig(
            id=device_id,
            driver="mock_device",
            enabled=True,
            connect_on_start=connect,
            connection={"address": f"MOCK::{device_id}"},
            scan_channels=ChannelFilters(setters=None, getters=None),
        )

    def _wait_operation(self, operation, timeout_ms=5_000):
        timer = QtCore.QElapsedTimer()
        timer.start()
        while not operation.done and timer.elapsed() < timeout_ms:
            self.app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 25)
            QtCore.QThread.msleep(1)
        self.assertTrue(
            operation.done,
            f"operation {operation.operation!r} did not finish in {timeout_ms} ms",
        )
        for _ in range(4):
            self.app.processEvents()
        return operation.result

    @staticmethod
    def _request(action, target=None, channel=None, value=None):
        return {
            "request_id": f"request-{action}",
            "source_device": "runtime-ui-test",
            "action": action,
            "target_device": target,
            "channel": channel,
            "value": value,
        }

    def test_add_disconnect_remove_refreshes_every_consumer_once_and_stales_calls(self):
        profile_bytes = self.profile.source_path.read_bytes()
        self.window.scan_range_limits[("runtime_mock", "channel_A")] = (-2.0, 2.0)
        publications = []
        reentrant_observations = []
        self.window.command_router.sig_catalog_changed.connect(publications.append)

        def observe_manager_catalog(_snapshot):
            rejected = None
            try:
                self.manager.reserve_activity("test", "catalog signal reentry")
            except Exception as exc:  # the concrete manager error is asserted below
                rejected = exc
            reentrant_observations.append(
                (
                    self.window._runtime_mutation_operation is not None,
                    self.window.scanlist.runtime_mutation_sealed,
                    rejected,
                )
            )

        self.manager.sig_catalog_changed.connect(observe_manager_catalog)

        add_result = self._wait_operation(
            self.window.request_add_device(self._config())
        )
        self.assertTrue(add_result.succeeded)
        self.assertEqual(len(publications), 1)
        self.assertIn("runtime_mock", self.window.equips)
        self.assertEqual(
            self.window.open_equipment_buttons[-1].text(), "runtime_mock"
        )
        self.assertIn(
            "runtime_mock_channel_A",
            self.window.scanlist.manual_set_menu.choice_names,
        )
        self.assertEqual(
            self.window.active_scan_range_limits[("runtime_mock", "channel_A")],
            (-2.0, 2.0),
        )

        listed = self.window.command_router.route_command(
            self._request("list_catalog")
        )
        self.assertTrue(listed["ok"])
        self.assertIn("runtime_mock", listed["catalog"])
        written = self.window.command_router.route_command(
            self._request("write", "runtime_mock", "channel_A", 1.25)
        )
        self.assertTrue(written["ok"])
        stale_setter = self.window.setter_equipment_info_for_scanning[
            "runtime_mock"
        ]["channel_A"]
        added_record_generation = next(
            record.generation
            for record in self.manager.snapshot().records
            if record.device_id == "runtime_mock"
        )

        disconnect_result = self._wait_operation(
            self.window.request_disconnect_device("runtime_mock")
        )
        self.assertTrue(disconnect_result.succeeded)
        self.assertEqual(len(publications), 2)
        disconnected_record = next(
            record
            for record in self.manager.snapshot().records
            if record.device_id == "runtime_mock"
        )
        self.assertEqual(disconnected_record.state, DeviceState.DISCONNECTED)
        self.assertEqual(disconnected_record.generation, added_record_generation)
        self.assertTrue(
            self.window._equipment_buttons_by_label["runtime_mock"].isEnabled()
        )

        remove_result = self._wait_operation(
            self.window.request_remove_device("runtime_mock")
        )
        self.assertTrue(remove_result.succeeded)
        self.assertEqual(len(publications), 3)
        self.assertNotIn("runtime_mock", self.window.equips)
        self.assertNotIn("runtime_mock", self.window._equipment_buttons_by_label)
        self.assertNotIn(
            "runtime_mock_channel_A",
            self.window.scanlist.manual_set_menu.choice_names,
        )
        self.assertNotIn(
            ("runtime_mock", "channel_A"),
            self.window.active_scan_range_limits,
        )
        with self.assertRaises(DeviceUnavailableError):
            stale_setter(2.0)

        removed_response = self.window.command_router.route_command(
            self._request("read", "runtime_mock", "channel_A")
        )
        self.assertFalse(removed_response["ok"])
        self.assertEqual(removed_response["error_code"], "unknown_device")
        self.assertEqual(self.profile.source_path.read_bytes(), profile_bytes)
        self.assertIsNone(self.window._operator_pending_mutation)

        self.assertEqual(len(reentrant_observations), 3)
        for operation_visible, ui_sealed, rejection in reentrant_observations:
            self.assertTrue(operation_visible)
            self.assertTrue(ui_sealed)
            self.assertIsNotNone(rejection)

    def test_router_lease_spans_catalog_lookup_and_response_construction(self):
        observations = []
        original_catalog = self.window.get_device_channel_catalog
        original_success = self.window.command_router._make_success_response

        def catalog_probe():
            observations.append(self.manager.runtime_mutation_blockers())
            return original_catalog()

        def response_probe(**kwargs):
            observations.append(self.manager.runtime_mutation_blockers())
            return original_success(**kwargs)

        with (
            mock.patch.object(
                self.window,
                "get_device_channel_catalog",
                side_effect=catalog_probe,
            ),
            mock.patch.object(
                self.window.command_router,
                "_make_success_response",
                side_effect=response_probe,
            ),
        ):
            response = self.window.command_router.route_command(
                self._request("list_catalog")
            )

        self.assertTrue(response["ok"])
        self.assertEqual(len(observations), 2)
        for blockers in observations:
            self.assertTrue(
                any("in-flight session call" in blocker for blocker in blockers),
                blockers,
            )
        self.assertFalse(
            any(
                "in-flight session call" in blocker
                for blocker in self.manager.runtime_mutation_blockers()
            )
        )

    def test_public_snapshot_apply_rejects_missing_and_spoofed_records(self):
        authoritative = self.manager.snapshot()
        with self.assertRaises(DeviceCatalogError):
            self.window.apply_device_snapshot(
                replace(authoritative, records=())
            )

        first, *remaining = authoritative.records
        spoofed = replace(
            authoritative,
            records=(
                replace(first, generation=first.generation + 100),
                *remaining,
            ),
        )
        with self.assertRaises(DeviceCatalogError):
            self.window.apply_device_snapshot(spoofed)

    def test_shutdown_seal_rejects_programmatic_catalog_and_editor_changes(self):
        self.window._session_shutdown_in_progress = True
        try:
            with self.assertRaises(DeviceMutationBusyError):
                self.manager.add_device(
                    self._config("shutdown_race", connect=False)
                )
            with self.assertRaises(DeviceCatalogBusyError):
                self.window.apply_device_snapshot(self.manager.snapshot())
            with self.assertRaises(DeviceCatalogBusyError):
                self.window.preflight_artificial_channel_config(
                    original_channel_x_name="mock_device_1_channel_A",
                    original_channel_y_name="mock_device_2_channel_A",
                    artificial_channel_x_name="n",
                    artificial_channel_y_name="E",
                )
        finally:
            self.window._session_shutdown_in_progress = False

    def test_forged_prepare_is_refused_and_committed_token_cannot_replay(self):
        current = self.manager.snapshot()
        forged = CatalogMutationProposal(
            operation="add",
            device_id="forged",
            base_generation=current.generation,
            proposed_generation=current.generation,
            before=current,
            proposed=current,
            operation_id=999,
            operation_nonce=object(),
        )
        with self.assertRaises(DeviceMutationHooksError):
            self.window.prepare_device_snapshot(forged)

        prepared_tokens = []
        manager_proposals = []

        def capture_prepare(proposal):
            manager_proposals.append(proposal)
            token = self.window.prepare_device_snapshot(proposal)
            prepared_tokens.append(token)
            return token

        self.manager.set_runtime_hooks(
            blockers=self.window.runtime_mutation_blockers,
            prepare=capture_prepare,
            commit=self.window.commit_prepared_device_snapshot,
            seal=self.window.begin_runtime_mutation,
            unseal=self.window.finish_runtime_mutation,
        )
        operation = self.manager.add_device(
            self._config("token_mock", connect=False)
        )
        self.assertEqual(len(manager_proposals), 2)
        forged_during_operation = replace(manager_proposals[-1])
        self.assertIsNot(forged_during_operation, manager_proposals[-1])
        with self.assertRaises(DeviceMutationHooksError):
            self.window.prepare_device_snapshot(forged_during_operation)

        result = self._wait_operation(operation)
        self.assertTrue(result.succeeded)
        self.assertEqual(len(prepared_tokens), 2)
        with self.assertRaises(DeviceCatalogError):
            self.window.commit_prepared_device_snapshot(
                prepared_tokens[-1], self.manager.snapshot()
            )

    def test_seal_failure_rolls_back_ui_and_starts_no_lifecycle(self):
        first_widget = self.window.equips["mock_device_1"]
        failing_widget = self.window.equips["mock_device_2"]
        first_enabled = first_widget.isEnabled()
        scan = self.window.scanlist.list_available.get_widgets()[0].scan
        prior_shutdown_requested = scan._shutdown_requested
        original_set_enabled = failing_widget.setEnabled
        adapter = self.manager._records["mock_device_1"].adapter

        def fail_disable(enabled):
            if not enabled:
                raise RuntimeError("injected device-widget seal failure")
            return original_set_enabled(enabled)

        with (
            mock.patch.object(
                failing_widget,
                "setEnabled",
                side_effect=fail_disable,
            ),
            mock.patch.object(adapter, "terminate", wraps=adapter.terminate) as terminate,
        ):
            operation = self.manager.remove_device("mock_device_1")

        self.assertTrue(operation.done)
        self.assertIsNotNone(operation.result.error)
        terminate.assert_not_called()
        self.assertEqual(first_widget.isEnabled(), first_enabled)
        self.assertFalse(self.window.scanlist.runtime_mutation_sealed)
        self.assertEqual(scan._shutdown_requested, prior_shutdown_requested)
        self.assertFalse(self.manager.mutation_in_progress)

    def test_unseal_restoration_is_best_effort_across_later_surfaces(self):
        first_widget = self.window.equips["mock_device_1"]
        later_widget = self.window.equips["mock_device_2"]
        original_set_enabled = first_widget.setEnabled
        self.window._set_runtime_mutation_ui_sealed(True, "test mutation")

        def fail_restore(enabled):
            if enabled:
                raise ValueError("injected restore failure")
            return original_set_enabled(enabled)

        try:
            with mock.patch.object(
                first_widget,
                "setEnabled",
                side_effect=fail_restore,
            ):
                with self.assertRaisesRegex(RuntimeError, "restoration failed"):
                    self.window._set_runtime_mutation_ui_sealed(False)

            self.assertTrue(later_widget.isEnabled())
            self.assertTrue(
                all(
                    button.isEnabled()
                    for button in self.window.open_equipment_buttons
                )
            )
            self.assertFalse(self.window.scanlist.runtime_mutation_sealed)
        finally:
            original_set_enabled(True)

    def test_busy_refusal_shows_one_warning_and_clears_operator_intent(self):
        adapter = self.manager._records["mock_device_1"].adapter
        with (
            mock.patch.object(adapter, "busy", return_value=True),
            mock.patch.object(QtWidgets.QMessageBox, "warning") as warning,
            mock.patch.object(adapter, "terminate", wraps=adapter.terminate) as terminate,
        ):
            operation = self.window.request_remove_device("mock_device_1")

        self.assertIsNotNone(operation)
        self.assertTrue(operation.done)
        self.assertIsNotNone(operation.result.error)
        warning.assert_called_once()
        self.assertIn("active work", warning.call_args.args[2])
        self.assertIsNone(self.window._operator_pending_mutation)
        terminate.assert_not_called()
        self.assertFalse(self.window.scanlist.runtime_mutation_sealed)

    def test_remove_pretermination_failure_reconciles_error_state_and_inert_target(self):
        target_widget = self.window.equips["mock_device_1"]
        target_button = self.window._equipment_buttons_by_label["mock_device_1"]
        other_widget = self.window.equips["mock_device_2"]
        other_button = self.window._equipment_buttons_by_label["mock_device_2"]
        publications = []
        self.window.command_router.sig_catalog_changed.connect(publications.append)
        adapter = self.manager._records["mock_device_1"].adapter

        with mock.patch.object(
            adapter,
            "force_stop",
            side_effect=RuntimeError("injected force-stop failure"),
        ):
            result = self._wait_operation(
                self.manager.remove_device("mock_device_1")
            )

        self.assertFalse(result.succeeded)
        self.assertTrue(result.committed)
        self.assertTrue(result.acknowledged)
        self.assertEqual(len(publications), 1)
        manager_snapshot = self.manager.snapshot()
        self.assertEqual(
            manager_snapshot.generation,
            self.window._applied_device_snapshot.generation,
        )
        self.assertEqual(
            tuple(manager_snapshot.records),
            tuple(self.window._applied_device_snapshot.records),
        )
        target_record = next(
            record
            for record in manager_snapshot.records
            if record.device_id == "mock_device_1"
        )
        self.assertEqual(target_record.state, DeviceState.ERROR)
        self.assertFalse(target_widget.isEnabled())
        self.assertFalse(target_button.isEnabled())
        self.assertTrue(other_widget.isEnabled())
        self.assertTrue(other_button.isEnabled())

        response = self.window.command_router.route_command(
            self._request("read", "mock_device_1", "channel_A")
        )
        self.assertFalse(response["ok"])
        self.assertEqual(response["error_code"], "device_unavailable")

        # Exact authoritative refresh and the artificial-channel refresh path
        # must remain usable without re-enabling the uncertain target.
        self.window.apply_device_snapshot(manager_snapshot)
        self.window.on_artificial_channel_config_applied()
        self.assertFalse(target_widget.isEnabled())
        self.assertFalse(target_button.isEnabled())
        self.assertEqual(
            tuple(self.manager.snapshot().records),
            tuple(self.window._applied_device_snapshot.records),
        )

    def test_failed_commit_and_recovery_stay_sealed_until_typed_reconcile_retry(self):
        publications = []
        self.window.command_router.sig_catalog_changed.connect(publications.append)

        def fail_commit(_prepared, _snapshot):
            raise RuntimeError("injected catalog acknowledgement failure")

        self.manager.set_runtime_hooks(
            blockers=self.window.runtime_mutation_blockers,
            prepare=self.window.prepare_device_snapshot,
            commit=fail_commit,
            seal=self.window.begin_runtime_mutation,
            unseal=self.window.finish_runtime_mutation,
        )
        failed = self._wait_operation(
            self.manager.disconnect_device("mock_device_1")
        )

        self.assertTrue(failed.committed)
        self.assertFalse(failed.acknowledged)
        self.assertIsNotNone(failed.error)
        self.assertEqual(publications, [])
        self.assertTrue(self.window.scanlist.runtime_mutation_sealed)
        self.assertTrue(self.window._runtime_mutation_widget_states)
        self.assertTrue(
            all(not widget.isEnabled() for widget in self.window.equips.values())
        )
        self.assertTrue(
            all(
                not button.isEnabled()
                for button in self.window.open_equipment_buttons
            )
        )

        self.manager.set_runtime_hooks(
            blockers=self.window.runtime_mutation_blockers,
            prepare=self.window.prepare_device_snapshot,
            commit=self.window.commit_prepared_device_snapshot,
            seal=self.window.begin_runtime_mutation,
            unseal=self.window.finish_runtime_mutation,
        )
        retry = self.manager.reconcile_catalog()
        retried = self._wait_operation(retry)

        self.assertTrue(retried.succeeded)
        self.assertEqual(len(publications), 1)
        self.assertFalse(self.window.scanlist.runtime_mutation_sealed)
        self.assertFalse(self.window._runtime_mutation_widget_states)
        self.assertTrue(
            all(widget.isEnabled() for widget in self.window.equips.values())
        )
        self.assertTrue(
            all(button.isEnabled() for button in self.window.open_equipment_buttons)
        )
        self.assertEqual(
            self.manager.snapshot().generation,
            self.window._applied_device_snapshot.generation,
        )

    def test_scan_reservation_precedes_device_stop_and_releases_on_start_failure(self):
        scan = self.window.scanlist.list_available.get_widgets()[0].scan
        observations = []

        def fail_stop():
            observations.append(self.manager.runtime_mutation_blockers())
            raise RuntimeError("injected stop failure")

        with (
            mock.patch.object(scan, "_focus_plot_tab_1_for_scan_start"),
            mock.patch.object(scan, "_start_new_scan_log_session"),
            mock.patch.object(
                self.window,
                "stop_equipments_for_scanning",
                side_effect=fail_stop,
            ),
            mock.patch.object(scan.logic, "start") as logic_start,
        ):
            with self.assertRaisesRegex(RuntimeError, "injected stop failure"):
                Scan._start_scan_now(scan)

        logic_start.assert_not_called()
        self.assertEqual(len(observations), 1)
        self.assertTrue(
            any("scan activity" in blocker for blocker in observations[0]),
            observations[0],
        )
        self.assertFalse(
            any(
                "scan activity" in blocker
                for blocker in self.manager.runtime_mutation_blockers()
            )
        )
        self.assertIsNone(scan._runtime_activity_reservation)

    def test_shutdown_refusal_for_session_lease_has_no_ui_side_effect(self):
        entered = threading.Event()
        release = threading.Event()
        thread_errors = []

        def hold_session():
            try:
                with self.manager.session_call():
                    entered.set()
                    release.wait(5)
            except Exception as exc:
                thread_errors.append(exc)

        worker = threading.Thread(target=hold_session, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(2))
        try:
            with (
                mock.patch.object(self.window.scanlist, "shutdown") as scan_shutdown,
                mock.patch.object(
                    self.window.artificial_channel_2d, "close"
                ) as artificial_close,
                mock.patch.object(
                    self.window.scan_range_window, "close"
                ) as range_close,
            ):
                with self.assertRaises(DeviceMutationBusyError):
                    self.window._start_async_shutdown()
            scan_shutdown.assert_not_called()
            artificial_close.assert_not_called()
            range_close.assert_not_called()
            self.assertFalse(self.window._session_shutdown_in_progress)
            self.assertFalse(self.window.scanlist._shutdown_sealed)
            self.assertIsNone(self.window._shutdown_guard)
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(thread_errors, [])

    def test_shutdown_ui_seal_failure_precedes_every_irreversible_side_effect(self):
        with (
            mock.patch.object(self.window.scanlist, "shutdown") as scan_shutdown,
            mock.patch.object(
                self.window.artificial_channel_2d, "close"
            ) as artificial_close,
            mock.patch.object(
                self.window.scan_range_window, "close"
            ) as range_close,
            mock.patch.object(
                self.window,
                "_set_runtime_mutation_ui_sealed",
                side_effect=RuntimeError("injected shutdown seal failure"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "shutdown seal failure"):
                self.window._start_async_shutdown()

        scan_shutdown.assert_not_called()
        artificial_close.assert_not_called()
        range_close.assert_not_called()
        self.assertFalse(self.window._session_shutdown_in_progress)
        self.assertIsNone(self.window._shutdown_guard)
        retry_probe = self.manager.reserve_activity("test", "retry admission")
        retry_probe.release()

    def test_failed_shutdown_does_not_undo_scanlist_shutdown_seal(self):
        scans = tuple(
            item.scan for item in self.window.scanlist.iter_scan_items()
        )
        self.window.scanlist.set_runtime_mutation_sealed(
            True,
            "application shutdown",
        )
        self.window.scanlist._shutdown_sealed = True
        try:
            self.window.scanlist.set_runtime_mutation_sealed(False)
            self.assertFalse(self.window.scanlist.isEnabled())
            self.assertTrue(
                all(scan._shutdown_requested for scan in scans)
            )
            self.assertIn(
                "scan-list shutdown retry pending",
                self.window.runtime_mutation_blockers(),
            )
            with self.assertRaises(DeviceMutationBusyError):
                self.manager.add_device(
                    self._config("refused_after_shutdown_timeout", connect=False)
                )
        finally:
            self.window.scanlist._shutdown_sealed = False
            self.window.scanlist.setEnabled(True)
            for scan in scans:
                scan._shutdown_requested = False
                scan.setEnabled(True)

    def test_async_teardown_dispatch_failure_keeps_admission_closed_until_retry(self):
        guarded_setter = self.window.setter_equipment_info_for_scanning[
            "mock_device_1"
        ]["channel_A"]
        original_thread_start = QtCore.QThread.start
        starts = 0

        def fail_first_thread_start(thread):
            nonlocal starts
            starts += 1
            if starts == 1:
                raise RuntimeError("injected teardown thread start failure")
            return original_thread_start(thread)

        with (
            mock.patch.object(
                QtCore.QThread,
                "start",
                new=fail_first_thread_start,
            ),
            mock.patch.object(QtWidgets.QMessageBox, "critical") as critical,
        ):
            operation = self.window._start_async_shutdown()
            failed = self._wait_operation(operation)

        self.assertFalse(failed.succeeded)
        self.assertFalse(failed.committed)
        critical.assert_called_once()
        retained_guard = self.window._shutdown_guard
        self.assertIsNotNone(retained_guard)
        self.assertFalse(retained_guard.released)
        self.assertTrue(self.window._shutdown_retry_required)
        self.assertTrue(self.window.scanlist._shutdown_sealed)
        self.assertTrue(self.window.scanlist._shutdown_complete)
        self.assertTrue(self.window.scanlist.runtime_mutation_sealed)
        self.assertTrue(self.window._runtime_mutation_widget_states)
        self.assertIn(
            "application shutdown retry required",
            self.window.runtime_mutation_blockers(),
        )

        with self.assertRaises(DeviceMutationBusyError):
            self.manager.add_device(
                self._config("refused_after_async_shutdown", connect=False)
            )
        with self.assertRaises(DeviceUnavailableError):
            with self.manager.session_call():
                pass
        with self.assertRaises(DeviceUnavailableError):
            self.manager.reserve_activity("test", "late activity")
        with self.assertRaises(DeviceUnavailableError):
            guarded_setter(1.0)
        with self.assertRaises(DeviceCatalogBusyError):
            self.window.apply_device_snapshot(self.manager.snapshot())

        with (
            mock.patch.object(
                self.manager,
                "begin_shutdown",
                wraps=self.manager.begin_shutdown,
            ) as begin_shutdown,
            mock.patch.object(
                self.manager,
                "teardown_all_async",
                wraps=self.manager.teardown_all_async,
            ) as teardown,
        ):
            retry = self.window._start_async_shutdown()
            retried = self._wait_operation(retry)

        begin_shutdown.assert_not_called()
        self.assertIs(teardown.call_args.args[0], retained_guard)
        self.assertTrue(retried.succeeded)
        self.assertTrue(self.window._session_shutdown_complete)
        self.assertFalse(self.window._shutdown_retry_required)
        self.assertIsNone(self.window._shutdown_guard)

    def test_sync_teardown_failure_keeps_admission_closed_until_retry(self):
        guarded_setter = self.window.setter_equipment_info_for_scanning[
            "mock_device_1"
        ]["channel_A"]
        with mock.patch.object(
            self.manager,
            "teardown_all",
            side_effect=RuntimeError("injected synchronous teardown failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "synchronous teardown failure"):
                self.window.shutdown_session()

        retained_guard = self.window._shutdown_guard
        self.assertIsNotNone(retained_guard)
        self.assertFalse(retained_guard.released)
        self.assertTrue(self.window._shutdown_retry_required)
        self.assertTrue(self.window.scanlist._shutdown_sealed)
        self.assertTrue(self.window.scanlist._shutdown_complete)
        self.assertTrue(self.window.scanlist.runtime_mutation_sealed)
        self.assertTrue(self.window._runtime_mutation_widget_states)
        self.assertIn(
            "application shutdown retry required",
            self.window.runtime_mutation_blockers(),
        )

        with self.assertRaises(DeviceMutationBusyError):
            self.manager.add_device(
                self._config("refused_after_sync_shutdown", connect=False)
            )
        with self.assertRaises(DeviceUnavailableError):
            guarded_setter(1.0)
        with self.assertRaises(DeviceCatalogBusyError):
            self.window.preflight_artificial_channel_config(
                original_channel_x_name="mock_device_1_channel_A",
                original_channel_y_name="mock_device_2_channel_A",
                artificial_channel_x_name="n",
                artificial_channel_y_name="E",
            )

        with mock.patch.object(
            self.manager,
            "begin_shutdown",
            wraps=self.manager.begin_shutdown,
        ) as begin_shutdown:
            report = self.window.shutdown_session()

        begin_shutdown.assert_not_called()
        self.assertTrue(report.succeeded)
        self.assertTrue(self.window._session_shutdown_complete)
        self.assertFalse(self.window._shutdown_retry_required)
        self.assertIsNone(self.window._shutdown_guard)

    def test_active_queue_reservation_is_quiesced_before_async_teardown(self):
        reservation = self.manager.reserve_activity("queue", "test queue")
        original_shutdown = self.window.scanlist.shutdown

        def quiesce_queue(*, timeout_ms):
            reservation.release()
            return original_shutdown(timeout_ms=timeout_ms)

        with mock.patch.object(
            self.window.scanlist,
            "shutdown",
            side_effect=quiesce_queue,
        ) as scan_shutdown:
            operation = self.window._start_async_shutdown()
            result = self._wait_operation(operation)

        self.assertTrue(result.succeeded)
        scan_shutdown.assert_called_once()
        self.assertTrue(self.window._session_shutdown_complete)


class RuntimeManualSealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_queued_manual_slot_silently_skips_after_shutdown_seal(self):
        scan_list = SimpleNamespace(
            _shutdown_sealed=False,
            runtime_mutation_sealed=False,
            _log_warning=mock.Mock(),
        )
        main_window = SimpleNamespace(
            scanlist=scan_list,
            reserve_runtime_activity=mock.Mock(),
            write_info=mock.Mock(),
        )
        item = ManualSetItem("default_wait", 0.0, main_window=main_window)
        try:
            QtCore.QTimer.singleShot(0, item._run_manual_set_from_queue)
            scan_list._shutdown_sealed = True
            self.app.processEvents()
            main_window.reserve_runtime_activity.assert_not_called()
            main_window.write_info.assert_not_called()
            scan_list._log_warning.assert_called_once()
        finally:
            item.deleteLater()
            self.app.processEvents()

    def test_queue_reservation_releases_on_prestart_setup_failure(self):
        reservation = mock.Mock()
        logic = SimpleNamespace(
            isRunning=lambda: False,
            reset_control_flags=mock.Mock(
                side_effect=RuntimeError("injected queue setup failure")
            ),
            start=mock.Mock(),
        )
        target = SimpleNamespace(
            _shutdown_sealed=False,
            _runtime_mutation_sealed=False,
            logic=logic,
            list_queue=SimpleNamespace(get_widgets=lambda: [object()]),
            main_window=SimpleNamespace(
                reserve_runtime_activity=mock.Mock(return_value=reservation)
            ),
            _queue_activity_reservation=None,
            _queue_run_started=False,
            _queue_completion_delivered=True,
            _log_warning=mock.Mock(),
            _log_info=mock.Mock(),
        )

        with self.assertRaisesRegex(RuntimeError, "queue setup failure"):
            ScanList.start_queue(target)

        reservation.release.assert_called_once_with()
        logic.start.assert_not_called()
        self.assertIsNone(target._queue_activity_reservation)
