from __future__ import annotations

import os
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from core.device_management.manager import (
    CatalogMutationProposal,
    DeviceCatalogDesynchronizedError,
    DeviceManager,
    DeviceManagerThreadError,
    DeviceMutationBusyError,
    DeviceMutationHooksError,
    DeviceState,
    DeviceUnavailableError,
    DuplicateDeviceIdError,
    StaleDeviceGenerationError,
)
from core.device_management.models import (
    ChannelFilters,
    DeviceConfig,
    DriverConfigSpec,
    ProfileConfig,
    ProfilePaths,
)
from core.device_management.registry import DriverRegistration, DriverRegistry


def make_config(
    device_id: str,
    *,
    connect_on_start: bool = False,
) -> DeviceConfig:
    return DeviceConfig(
        id=device_id,
        driver="runtime_fake",
        enabled=True,
        connect_on_start=connect_on_start,
        connection={},
        scan_channels=ChannelFilters(setters=None, getters=None),
    )


def make_profile(*configs: DeviceConfig) -> ProfileConfig:
    root = Path(__file__).resolve().parents[1]
    return ProfileConfig(
        schema_version=1,
        profile="runtime-test",
        paths=ProfilePaths(save=root / "data", backup=None),
        devices=tuple(configs),
        source_path=root / "runtime-test-profile.json",
        repository_root=root,
    )


class RuntimeWidget(QtWidgets.QWidget):
    def __init__(self, label: str, events: list[tuple]) -> None:
        super().__init__()
        self.label = label
        self.events = events
        self.connected = False
        self.busy = False
        self.busy_error: Exception | None = None
        self.fail_force: Exception | None = None
        self.fail_stop: Exception | None = None
        self.fail_terminate: Exception | None = None
        self.fail_delete_count = 0
        self.delete_calls = 0
        self.events.append(("construct", label, threading.get_ident()))

    def deleteLater(self) -> None:  # noqa: N802 - Qt spelling
        self.delete_calls += 1
        self.events.append(("delete", self.label, threading.get_ident()))
        if self.fail_delete_count:
            self.fail_delete_count -= 1
            raise RuntimeError("injected deleteLater failure")
        # Deliberately do not destroy the C++ wrapper; tests inspect affinity.


class RuntimeDriver:
    def __init__(self, labels: list[str]) -> None:
        self.labels = iter(labels)
        self.events: list[tuple] = []
        self.instances: dict[str, RuntimeWidget] = {}
        self.connect_entered: threading.Event | None = None
        self.connect_release: threading.Event | None = None
        self.terminate_entered: threading.Event | None = None
        self.terminate_release: threading.Event | None = None

    def factory(self) -> RuntimeWidget:
        label = next(self.labels)
        widget = RuntimeWidget(label, self.events)
        self.instances[label] = widget
        return widget

    def record(self, action: str, widget: RuntimeWidget) -> None:
        self.events.append((action, widget.label, threading.get_ident()))

    def connect(
        self,
        widget: RuntimeWidget,
        _connection: dict,
        _timeout_ms: int,
    ) -> bool:
        self.record("connect", widget)
        if self.connect_entered is not None:
            self.connect_entered.set()
        if self.connect_release is not None:
            if not self.connect_release.wait(2):
                raise TimeoutError("test did not release connection callback")
        widget.connected = True
        return True

    def disconnect(self, widget: RuntimeWidget) -> None:
        self.record("disconnect", widget)
        widget.connected = False

    def force_stop(self, widget: RuntimeWidget) -> None:
        self.record("force", widget)
        if widget.fail_force is not None:
            raise widget.fail_force

    def stop_scan(self, widget: RuntimeWidget) -> None:
        self.record("stop", widget)
        if widget.fail_stop is not None:
            raise widget.fail_stop

    def terminate(self, widget: RuntimeWidget) -> None:
        self.record("terminate", widget)
        if self.terminate_entered is not None:
            self.terminate_entered.set()
        if self.terminate_release is not None:
            if not self.terminate_release.wait(2):
                raise TimeoutError("test did not release termination callback")
        if widget.fail_terminate is not None:
            raise widget.fail_terminate

    def close(self, widget: RuntimeWidget) -> None:
        self.record("close", widget)

    @staticmethod
    def is_connected(widget: RuntimeWidget) -> bool:
        return widget.connected

    @staticmethod
    def is_busy(widget: RuntimeWidget) -> bool:
        if widget.busy_error is not None:
            raise widget.busy_error
        return widget.busy

    def registration(self) -> DriverRegistration:
        return DriverRegistration(
            config_spec=DriverConfigSpec(
                driver_id="runtime_fake",
                connection_fields={},
            ),
            factory=self.factory,
            connect=self.connect,
            disconnect=self.disconnect,
            stop_scan=self.stop_scan,
            force_stop=self.force_stop,
            terminate=self.terminate,
            close_widget=self.close,
            is_busy=self.is_busy,
            is_connected=self.is_connected,
            runtime_mutation_allowed=True,
        )


class RuntimeHooks:
    def __init__(self, manager: DeviceManager) -> None:
        self.manager = manager
        self.applied = manager.snapshot()
        self.active_operation = None
        self.latest_token = None
        self.events: list[tuple] = []
        self.blockers: tuple[str, ...] = ()
        self.commit_failures = 0
        self.unseal_error: Exception | None = None
        self.prepare_calls: list[CatalogMutationProposal] = []

    def install(self) -> None:
        self.manager.set_runtime_hooks(
            self.get_blockers,
            self.prepare,
            self.commit,
            self.seal,
            self.unseal,
        )

    def get_blockers(self):
        return self.blockers

    def seal(self, operation) -> None:
        if self.active_operation is not None:
            raise RuntimeError("test UI is already sealed")
        self.active_operation = operation
        self.events.append(("seal", operation.operation))

    def prepare(self, proposal: CatalogMutationProposal):
        self.manager.validate_active_proposal(proposal)
        if self.active_operation is None:
            raise RuntimeError("proposal prepared without an active UI seal")
        if proposal.operation_id != self.active_operation.operation_id:
            raise RuntimeError("proposal operation mismatch")
        if proposal.operation_nonce is not self.active_operation.operation_nonce:
            raise RuntimeError("proposal nonce mismatch")
        if proposal.base_generation != self.applied.generation:
            raise RuntimeError("proposal does not extend the acknowledged catalog")
        token = object()
        self.latest_token = token
        self.prepare_calls.append(proposal)
        self.events.append(("prepare", proposal.operation))
        return token

    def commit(self, token, snapshot) -> None:
        if token is not self.latest_token:
            raise RuntimeError("stale prepared catalog token")
        self.latest_token = None
        self.events.append(("commit", snapshot.generation))
        if self.commit_failures:
            self.commit_failures -= 1
            raise RuntimeError("injected catalog commit failure")
        if tuple(snapshot.records) != tuple(self.manager.snapshot().records):
            raise RuntimeError("commit is not authoritative manager state")
        self.applied = snapshot

    def unseal(self, result) -> None:
        self.events.append(("unseal", result.operation))
        self.active_operation = None
        if self.unseal_error is not None:
            raise self.unseal_error


class DeviceManagerRuntimeMutationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_manager(
        self,
        labels: list[str],
        *configs: DeviceConfig,
    ) -> tuple[DeviceManager, RuntimeDriver, RuntimeHooks, ProfileConfig]:
        driver = RuntimeDriver(labels)
        manager = DeviceManager(
            DriverRegistry((driver.registration(),)),
            SimpleNamespace(),
        )
        profile = make_profile(*configs)
        manager.load_profile(profile)
        hooks = RuntimeHooks(manager)
        hooks.install()
        return manager, driver, hooks, profile

    def wait_operation(self, operation, timeout_ms: int = 3000):
        if not operation.done:
            loop = QtCore.QEventLoop()
            operation.sig_finished.connect(lambda _result: loop.quit())
            timer = QtCore.QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(timeout_ms)
            loop.exec()
            timer.stop()
        self.assertTrue(operation.done, "device operation did not complete")
        return operation.result

    def test_runtime_registration_requires_explicit_reviewed_busy_probe(self):
        with self.assertRaisesRegex(ValueError, "explicit reviewed is_busy probe"):
            DriverRegistration(
                config_spec=DriverConfigSpec(
                    driver_id="runtime_fake",
                    connection_fields={},
                ),
                factory=lambda: object(),
                terminate=lambda _instance: None,
                runtime_mutation_allowed=True,
            )

    def test_duplicate_add_is_side_effect_free_and_add_order_is_stable(self):
        manager, driver, hooks, profile = self.make_manager(
            ["existing", "second", "third"],
            make_config("existing"),
        )
        original_profile = repr(profile)
        original_generation = manager.generation
        original_events = tuple(driver.events)
        catalog_publications = []
        manager.sig_catalog_changed.connect(catalog_publications.append)

        with self.assertRaises(DuplicateDeviceIdError):
            manager.add_device(make_config("existing"))

        self.assertEqual(manager.generation, original_generation)
        self.assertEqual(tuple(driver.events), original_events)
        self.assertEqual(hooks.events, [])
        self.assertEqual(catalog_publications, [])
        self.assertEqual(repr(profile), original_profile)

        self.assertTrue(
            self.wait_operation(manager.add_device(make_config("second"))).succeeded
        )
        self.assertTrue(
            self.wait_operation(manager.add_device(make_config("third"))).succeeded
        )
        self.assertEqual(
            tuple(record.device_id for record in manager.snapshot().records),
            ("existing", "second", "third"),
        )

    def test_runtime_config_is_detached_and_malformed_input_never_seals(self):
        manager, driver, hooks, _profile = self.make_manager([])
        driver.labels = iter(["detached", "proposal-failure"])
        caller_setters = ["channel_A"]
        detached_config = DeviceConfig(
            id="detached",
            driver="runtime_fake",
            enabled=True,
            connect_on_start=False,
            connection={},
            scan_channels=ChannelFilters(
                setters=caller_setters,
                getters=None,
            ),
        )
        detached = self.wait_operation(manager.add_device(detached_config))
        self.assertTrue(detached.succeeded)
        generation = manager.generation
        caller_setters.append("channel_B")
        self.assertEqual(manager.generation, generation)
        self.assertEqual(
            detached.snapshot.setter_filters["detached"],
            ("channel_A",),
        )
        self.assertEqual(
            manager.snapshot().setter_filters["detached"],
            ("channel_A",),
        )

        malformed = make_config("malformed")
        object.__setattr__(malformed, "scan_channels", None)
        event_count = len(driver.events)
        hook_count = len(hooks.events)
        malformed_generation = manager.generation
        with self.assertRaisesRegex(TypeError, "scan_channels"):
            manager.add_device(malformed)
        self.assertEqual(len(driver.events), event_count)
        self.assertEqual(len(hooks.events), hook_count)
        self.assertEqual(manager.generation, malformed_generation)
        self.assertFalse(manager.mutation_in_progress)

        with mock.patch.object(
            manager,
            "_proposal_locked",
            side_effect=RuntimeError("injected proposal failure"),
        ):
            proposal_failure = self.wait_operation(
                manager.add_device(make_config("proposal-failure"))
            )
        self.assertFalse(proposal_failure.succeeded)
        self.assertFalse(proposal_failure.committed)
        self.assertFalse(proposal_failure.quarantined)
        self.assertFalse(manager.mutation_in_progress)
        failed_widget = driver.instances["proposal-failure"]
        self.assertEqual(failed_widget.delete_calls, 1)
        self.assertTrue(
            any(
                action == "terminate" and label == "proposal-failure"
                for action, label, _thread in driver.events
            )
        )

    def test_add_disconnect_remove_preserve_creation_generations_and_profile(self):
        manager, driver, hooks, profile = self.make_manager(
            ["retained", "added", "added-again"],
            make_config("retained"),
        )
        original_profile = repr(profile)
        retained_view = manager.snapshot().records[0]
        retained_call = manager.bind_call(
            "retained",
            retained_view.generation,
            lambda: "retained-ok",
        )
        publications = []
        manager.sig_catalog_changed.connect(
            lambda snapshot: publications.append(("catalog", snapshot.generation))
        )
        manager.sig_operation_finished.connect(
            lambda result: publications.append(("finished", result.generation))
        )

        added = self.wait_operation(manager.add_device(make_config("added")))
        self.assertTrue(added.succeeded)
        self.assertEqual(retained_call(), "retained-ok")
        added_view = next(v for v in added.snapshot.records if v.device_id == "added")
        added_call = manager.bind_call("added", added_view.generation, lambda: "old")

        disconnected = self.wait_operation(manager.disconnect_device("added"))
        self.assertTrue(disconnected.succeeded)
        disconnected_view = next(
            v for v in disconnected.snapshot.records if v.device_id == "added"
        )
        self.assertEqual(disconnected_view.generation, added_view.generation)
        self.assertEqual(added_call(), "old")

        removed = self.wait_operation(manager.remove_device("added"))
        self.assertTrue(removed.succeeded)
        self.assertEqual(retained_call(), "retained-ok")
        self.assertIs(manager.remove_device("added"), manager.remove_device("added"))
        with self.assertRaises(DeviceUnavailableError):
            added_call()

        readded = self.wait_operation(manager.add_device(make_config("added")))
        self.assertTrue(readded.succeeded)
        with self.assertRaises(StaleDeviceGenerationError):
            added_call()
        self.assertEqual(repr(profile), original_profile)
        self.assertEqual(hooks.applied, manager.snapshot())
        self.assertEqual(
            [name for name, _generation in publications],
            ["catalog", "finished"] * 4,
        )
        self.assertFalse(
            any(
                action == "stop" and label == "added"
                for action, label, _thread in driver.events
            )
        )

    def test_slow_connect_keeps_event_loop_live_and_retires_worker_before_finish(self):
        manager, driver, _hooks, _profile = self.make_manager([],)
        driver.labels = iter(["slow"])
        driver.connect_entered = threading.Event()
        driver.connect_release = threading.Event()
        ticks: list[int] = []
        heartbeat = QtCore.QTimer()
        heartbeat.setInterval(1)
        heartbeat.timeout.connect(lambda: ticks.append(len(ticks)))
        heartbeat.start()
        QtCore.QTimer.singleShot(30, driver.connect_release.set)

        operation = manager.add_device(make_config("slow", connect_on_start=True))
        self.assertTrue(driver.connect_entered.wait(1))
        with self.assertRaises(DeviceMutationBusyError):
            manager.begin_shutdown()
        with self.assertRaises(DeviceManagerThreadError):
            operation.wait(0.01)
        observed_worker_counts = []
        operation.sig_finished.connect(
            lambda _result: observed_worker_counts.append(len(manager._worker_threads))
        )
        result = self.wait_operation(operation)
        heartbeat.stop()

        self.assertTrue(result.succeeded)
        self.assertGreater(len(ticks), 0)
        self.assertEqual(observed_worker_counts, [0])

    def test_slow_async_teardown_keeps_event_loop_live(self):
        manager, driver, _hooks, _profile = self.make_manager(
            ["slow-teardown"],
            make_config("slow-teardown", connect_on_start=True),
        )
        driver.terminate_entered = threading.Event()
        driver.terminate_release = threading.Event()
        ticks: list[int] = []
        heartbeat = QtCore.QTimer()
        heartbeat.setInterval(1)
        heartbeat.timeout.connect(lambda: ticks.append(len(ticks)))
        heartbeat.start()
        QtCore.QTimer.singleShot(30, driver.terminate_release.set)
        guard = manager.begin_shutdown()

        operation = manager.teardown_all_async(guard)
        result = self.wait_operation(operation)
        heartbeat.stop()

        self.assertTrue(driver.terminate_entered.is_set())
        self.assertTrue(result.succeeded)
        self.assertGreater(len(ticks), 0)
        self.assertEqual(manager._worker_threads, {})

    def test_leases_activity_busy_probe_and_shutdown_reservation_are_serialized(self):
        manager, driver, _hooks, _profile = self.make_manager(
            ["only"],
            make_config("only"),
        )
        view = manager.snapshot().records[0]
        callback_entered = threading.Event()
        callback_release = threading.Event()
        call_errors: list[Exception] = []

        guarded = manager.bind_call(
            "only",
            view.generation,
            lambda: (callback_entered.set(), callback_release.wait(2)),
        )
        caller = threading.Thread(
            target=lambda: self._capture_call(guarded, call_errors),
        )
        caller.start()
        self.assertTrue(callback_entered.wait(1))
        with self.assertRaises(DeviceMutationBusyError):
            manager.remove_device("only")
        callback_release.set()
        caller.join(1)
        self.assertFalse(caller.is_alive())
        self.assertEqual(call_errors, [])

        scan = manager.reserve_activity("scan", "active scan")
        queue = manager.reserve_activity("queue", "queued scan")
        with manager.session_call():
            with self.assertRaises(DeviceMutationBusyError):
                manager.begin_shutdown()
        guard = manager.begin_shutdown()
        with self.assertRaises(DeviceUnavailableError):
            guarded()
        with self.assertRaises(DeviceUnavailableError):
            manager.reserve_activity("scan")
        guard.release()
        scan.release()
        queue.release()

        widget = driver.instances["only"]
        widget.busy = True
        with self.assertRaises(DeviceMutationBusyError):
            manager.begin_shutdown()
        refused_teardown = self.wait_operation(manager.teardown_all_async())
        self.assertFalse(refused_teardown.succeeded)
        self.assertFalse(refused_teardown.committed)
        self.assertFalse(manager.mutation_in_progress)
        self.assertFalse(any(event[0] == "terminate" for event in driver.events))

        result = self.wait_operation(manager.remove_device("only"))
        self.assertFalse(result.succeeded)
        self.assertFalse(result.committed)
        self.assertIn("only", manager.snapshot().equipment)
        self.assertFalse(any(event[0] == "terminate" for event in driver.events))

    def test_pretermination_failure_acknowledges_error_state_and_disables_calls(self):
        manager, driver, hooks, _profile = self.make_manager(
            ["target", "other"],
            make_config("target"),
            make_config("other"),
        )
        target_view, other_view = manager.snapshot().records
        target_call = manager.bind_call("target", target_view.generation, lambda: 1)
        other_call = manager.bind_call("other", other_view.generation, lambda: 2)
        driver.instances["target"].fail_force = RuntimeError("cannot stop target")

        result = self.wait_operation(manager.remove_device("target"))

        self.assertFalse(result.succeeded)
        self.assertTrue(result.committed)
        self.assertTrue(result.acknowledged)
        self.assertEqual(hooks.applied, manager.snapshot())
        target = next(v for v in result.snapshot.records if v.device_id == "target")
        self.assertEqual(target.state, DeviceState.ERROR)
        with self.assertRaises(DeviceUnavailableError):
            target_call()
        self.assertEqual(other_call(), 2)
        self.assertFalse(any(event[0] == "terminate" for event in driver.events))

    def test_termination_failure_quarantines_without_delete_and_is_rereported(self):
        manager, driver, _hooks, _profile = self.make_manager(
            ["target"],
            make_config("target"),
        )
        widget = driver.instances["target"]
        widget.fail_terminate = RuntimeError("termination uncertain")

        removed = self.wait_operation(manager.remove_device("target"))
        self.assertFalse(removed.succeeded)
        self.assertTrue(removed.quarantined)
        self.assertNotIn("target", manager.snapshot().equipment)
        self.assertEqual(widget.delete_calls, 0)

        teardown = self.wait_operation(manager.teardown_all_async())
        self.assertFalse(teardown.succeeded)
        self.assertTrue(
            any(f.action == "termination" for f in teardown.failures),
            teardown.failures,
        )
        self.assertEqual(widget.delete_calls, 0)
        self.assertIs(manager.teardown_all_async(), manager.teardown_all_async())

    def test_commit_failure_reconciles_removed_topology_and_releases_label(self):
        manager, driver, hooks, _profile = self.make_manager(
            ["target", "replacement"],
            make_config("target"),
        )
        hooks.commit_failures = 1

        removed = self.wait_operation(manager.remove_device("target"))

        self.assertFalse(removed.succeeded)
        self.assertTrue(removed.committed)
        self.assertTrue(removed.acknowledged)
        self.assertEqual(hooks.applied, manager.snapshot())
        self.assertNotIn("target", manager.snapshot().equipment)
        self.assertNotIn("target", manager.quarantined_device_ids)
        self.assertGreaterEqual(driver.instances["target"].delete_calls, 1)

        added = self.wait_operation(manager.add_device(make_config("target")))
        self.assertTrue(added.succeeded)

    def test_failed_auto_reconcile_can_retry_and_forged_proposals_are_rejected(self):
        manager, _driver, hooks, _profile = self.make_manager(
            ["target", "replacement"],
            make_config("target"),
        )
        hooks.commit_failures = 2
        removed = self.wait_operation(manager.remove_device("target"))
        self.assertFalse(removed.acknowledged)
        self.assertIn("target", manager.quarantined_device_ids)
        with self.assertRaises(DeviceCatalogDesynchronizedError):
            manager.add_device(make_config("target"))

        reconciled = self.wait_operation(manager.reconcile_catalog())
        self.assertTrue(reconciled.succeeded)
        self.assertNotIn("target", manager.quarantined_device_ids)
        self.assertTrue(
            self.wait_operation(manager.add_device(make_config("target"))).succeeded
        )

        exact = hooks.prepare_calls[-1]
        forged = CatalogMutationProposal(
            operation=exact.operation,
            device_id=exact.device_id,
            base_generation=exact.base_generation,
            proposed_generation=exact.proposed_generation,
            before=exact.before,
            proposed=exact.proposed,
            operation_id=exact.operation_id,
            operation_nonce=exact.operation_nonce,
        )
        with self.assertRaises(DeviceMutationHooksError):
            manager.validate_active_proposal(forged)
        with self.assertRaises(DeviceMutationHooksError):
            manager.validate_active_proposal(exact)

    def test_delete_scheduling_failure_is_quarantined_and_retried_at_teardown(self):
        manager, driver, _hooks, _profile = self.make_manager(
            ["target"],
            make_config("target"),
        )
        widget = driver.instances["target"]
        widget.fail_delete_count = 1

        removed = self.wait_operation(manager.remove_device("target"))
        self.assertFalse(removed.succeeded)
        self.assertTrue(removed.quarantined)
        self.assertIn("target", manager.quarantined_device_ids)
        self.assertTrue(
            any(f.action == "widget delete scheduling" for f in removed.failures)
        )

        teardown = self.wait_operation(manager.teardown_all_async())
        self.assertTrue(teardown.succeeded)
        self.assertEqual(widget.delete_calls, 2)

    def test_quarantined_and_current_records_keep_global_ownership_order(self):
        manager, driver, _hooks, _profile = self.make_manager(
            ["first", "second"],
            make_config("first"),
            make_config("second", connect_on_start=True),
        )
        first = driver.instances["first"]
        first.fail_delete_count = 1
        self.assertTrue(
            self.wait_operation(manager.remove_device("first")).quarantined
        )
        driver.events.clear()

        result = self.wait_operation(manager.teardown_all_async())

        self.assertTrue(result.succeeded)
        actions = [(action, label) for action, label, _thread in driver.events]
        self.assertLess(
            actions.index(("delete", "first")),
            actions.index(("terminate", "second")),
        )

    def test_worker_dispatch_and_thread_cleanup_failures_cannot_wedge_gate(self):
        manager, driver, hooks, _profile = self.make_manager(
            ["target"],
            make_config("target"),
        )
        with mock.patch.object(
            QtCore.QThread,
            "start",
            side_effect=RuntimeError("injected thread start failure"),
        ):
            remove = manager.remove_device("target")
        self.assertTrue(remove.done)
        self.assertFalse(remove.result.succeeded)
        self.assertTrue(remove.result.committed)
        self.assertTrue(remove.result.acknowledged)
        self.assertFalse(manager.mutation_in_progress)
        self.assertIsNone(hooks.active_operation)
        self.assertEqual(manager.snapshot().records[0].state, DeviceState.ERROR)
        self.assertEqual(hooks.applied, manager.snapshot())
        self.assertEqual(manager._worker_threads, {})

        add_manager, add_driver, add_hooks, _profile = self.make_manager([])
        add_driver.labels = iter(["staged"])
        with mock.patch.object(
            QtCore.QThread,
            "start",
            side_effect=RuntimeError("injected add dispatch failure"),
        ):
            add = add_manager.add_device(make_config("staged"))
        self.assertTrue(add.done)
        self.assertTrue(add.result.quarantined)
        self.assertIn("staged", add_manager.quarantined_device_ids)
        self.assertFalse(add_manager.mutation_in_progress)
        self.assertIsNone(add_hooks.active_operation)
        staged = add_driver.instances["staged"]
        self.assertEqual(staged.delete_calls, 0)
        self.assertTrue(self.wait_operation(add_manager.teardown_all_async()).succeeded)
        self.assertEqual(staged.delete_calls, 1)

        committed_manager, committed_driver, committed_hooks, _profile = (
            self.make_manager([])
        )
        committed_driver.labels = iter(["committed-staged"])
        committed_hooks.commit_failures = 1
        original_start = QtCore.QThread.start
        dispatch_count = 0

        def fail_committed_cleanup_dispatch(thread):
            nonlocal dispatch_count
            dispatch_count += 1
            if dispatch_count == 2:
                raise RuntimeError("injected committed-add cleanup dispatch failure")
            return original_start(thread)

        with mock.patch.object(
            QtCore.QThread,
            "start",
            new=fail_committed_cleanup_dispatch,
        ):
            committed_add = self.wait_operation(
                committed_manager.add_device(make_config("committed-staged"))
            )
        self.assertFalse(committed_add.succeeded)
        self.assertTrue(committed_add.committed)
        self.assertTrue(committed_add.acknowledged)
        self.assertTrue(committed_add.quarantined)
        self.assertIn(
            "committed-staged",
            committed_manager.quarantined_device_ids,
        )
        self.assertNotIn("committed-staged", committed_manager.snapshot().equipment)
        self.assertTrue(
            self.wait_operation(committed_manager.teardown_all_async()).succeeded
        )

        cleanup_manager, _driver, _hooks, _profile = self.make_manager(
            ["only"],
            make_config("only"),
        )
        with mock.patch.object(
            QtCore.QThread,
            "deleteLater",
            side_effect=RuntimeError("injected thread delete failure"),
        ):
            disconnected = self.wait_operation(
                cleanup_manager.disconnect_device("only")
            )
        self.assertFalse(disconnected.succeeded)
        self.assertTrue(disconnected.acknowledged)
        self.assertTrue(
            any(f.action == "worker thread cleanup" for f in disconnected.failures)
        )
        self.assertFalse(cleanup_manager.mutation_in_progress)

    def test_unseal_failure_preserves_catalog_acknowledgement(self):
        manager, driver, hooks, _profile = self.make_manager([])
        driver.labels = iter(["added"])
        hooks.unseal_error = RuntimeError("injected UI restore failure")

        result = self.wait_operation(manager.add_device(make_config("added")))

        self.assertFalse(result.succeeded)
        self.assertTrue(result.committed)
        self.assertTrue(result.acknowledged)
        self.assertEqual(manager.snapshot(), hooks.applied)
        self.assertFalse(manager.mutation_in_progress)

    def test_async_teardown_preserves_global_order_and_owner_close_affinity(self):
        manager, driver, _hooks, _profile = self.make_manager(
            ["first", "second"],
            make_config("first", connect_on_start=True),
            make_config("second", connect_on_start=True),
        )
        driver.events.clear()
        owner = threading.get_ident()

        result = self.wait_operation(manager.teardown_all_async())

        self.assertTrue(result.succeeded)
        self.assertEqual(
            [(action, label) for action, label, _thread in driver.events],
            [
                ("force", "first"),
                ("force", "second"),
                ("stop", "first"),
                ("stop", "second"),
                ("terminate", "first"),
                ("close", "first"),
                ("delete", "first"),
                ("terminate", "second"),
                ("close", "second"),
                ("delete", "second"),
            ],
        )
        close_threads = [
            thread
            for action, _label, thread in driver.events
            if action in {"close", "delete"}
        ]
        worker_threads = [
            thread
            for action, _label, thread in driver.events
            if action in {"force", "stop", "terminate"}
        ]
        self.assertTrue(all(thread == owner for thread in close_threads))
        self.assertTrue(all(thread != owner for thread in worker_threads))

    def test_async_teardown_dispatch_failures_report_and_never_close_unterminated(self):
        original_start = QtCore.QThread.start

        preamble_manager, preamble_driver, _hooks, _profile = self.make_manager(
            ["preamble-target"],
            make_config("preamble-target"),
        )
        preamble_calls = 0

        def fail_preamble_once(thread):
            nonlocal preamble_calls
            preamble_calls += 1
            if preamble_calls == 1:
                raise RuntimeError("injected teardown preamble dispatch failure")
            return original_start(thread)

        shutdown_guard = preamble_manager.begin_shutdown()
        with mock.patch.object(
            QtCore.QThread,
            "start",
            new=fail_preamble_once,
        ):
            preamble_result = self.wait_operation(
                preamble_manager.teardown_all_async(shutdown_guard)
            )
        self.assertFalse(preamble_result.succeeded)
        self.assertTrue(
            any(
                f.device_id == "manager" and f.action == "worker execution"
                for f in preamble_result.failures
            )
        )
        self.assertFalse(
            any(
                action in {"force", "stop", "terminate", "close", "delete"}
                for action, _label, _thread in preamble_driver.events
            )
        )
        self.assertFalse(preamble_result.committed)
        self.assertIsNone(preamble_manager.teardown_report)
        self.assertTrue(preamble_manager.loaded)
        self.assertFalse(preamble_manager.mutation_in_progress)
        self.assertFalse(shutdown_guard.released)
        with self.assertRaises(DeviceUnavailableError):
            with preamble_manager.session_call():
                pass
        with self.assertRaises(DeviceUnavailableError):
            preamble_manager.reserve_activity("scan")
        with self.assertRaises(DeviceMutationBusyError):
            preamble_manager.add_device(make_config("blocked-during-retry"))
        self.assertEqual(
            preamble_manager.snapshot().records[0].state,
            DeviceState.DISCONNECTED,
        )
        retry_result = self.wait_operation(
            preamble_manager.teardown_all_async(shutdown_guard)
        )
        self.assertTrue(retry_result.succeeded)
        self.assertEqual(preamble_driver.instances["preamble-target"].delete_calls, 1)

        terminate_manager, terminate_driver, _hooks, _profile = self.make_manager(
            ["terminate-target"],
            make_config("terminate-target"),
        )
        terminate_calls = 0

        def fail_termination_dispatch(thread):
            nonlocal terminate_calls
            terminate_calls += 1
            if terminate_calls == 2:
                raise RuntimeError("injected termination dispatch failure")
            return original_start(thread)

        with mock.patch.object(
            QtCore.QThread,
            "start",
            new=fail_termination_dispatch,
        ):
            terminate_result = self.wait_operation(
                terminate_manager.teardown_all_async()
            )
        self.assertFalse(terminate_result.succeeded)
        self.assertTrue(
            any(
                f.device_id == "terminate-target"
                and f.action == "worker execution"
                for f in terminate_result.failures
            )
        )
        self.assertFalse(
            any(
                action in {"terminate", "close", "delete"}
                for action, _label, _thread in terminate_driver.events
            )
        )
        self.assertEqual(terminate_driver.instances["terminate-target"].delete_calls, 0)

    @staticmethod
    def _capture_call(callback, errors: list[Exception]) -> None:
        try:
            callback()
        except Exception as exc:  # pragma: no cover - assertion reports payload
            errors.append(exc)


if __name__ == "__main__":
    unittest.main()
