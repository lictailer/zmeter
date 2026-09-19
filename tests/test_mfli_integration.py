"""MFLI integration with strictly injected fake I/O; no vendor imports allowed."""
import builtins
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from devices.MFLI_temp.tests.test_mfli_layers import OfflineCase
from devices.mfli.MFLI_hardware import MFLIHardware, parse_address
from devices.mfli.MFLI_main import MFLI
from core.device_management import DeviceManager, build_default_registry
from core.device_management.models import ChannelFilters, DeviceConfig, ProfileConfig, ProfilePaths
from core.device_management.registry import DriverRegistry
from core.device_management.registrations import mfli_registration
from core.mainWindow import MainWindow
from core.scan_info import ScanInfo
from core.scan_logic import ScanLogic
from core.shared_runtime import RuntimeServices


class AddressTests(unittest.TestCase):
    def test_address_forms(self):
        for address in ('DEV30037, 192.168.141.54', '  dev30037 , 192.168.141.54  '):
            self.assertEqual(parse_address(address), ('dev30037', '192.168.141.54', 8004))
        self.assertEqual(parse_address(' DeV30037 '), ('dev30037', 'mf-dev30037', 8004))

    def test_invalid_addresses(self):
        for address in ('', '12345', 'DEV', 'DEV12,', 'DEV12,host',
                        'DEV12,999.1.1.1', '[DEV12]', '[DEV12, 127.0.0.1]',
                        '[DEV12, [127.0.0.1]]',
                        '[DEV12', 'DEV12,127.0.0.1,8004', None, '__import__("os")'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                parse_address(address)

    def test_registry_is_lazy_in_fresh_interpreter(self):
        code = ('import sys; from core.device_management import build_default_registry; '
                'r=build_default_registry(); assert "mfli" in r.config_specs; '
                'assert not any(n.startswith(("devices.", "zhinst")) for n in sys.modules)')
        result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class IntegratedTests(OfflineCase):
    def make_session(self, *, address='DEV12345', filters=None, startup=False):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        services = RuntimeServices()
        self.addCleanup(services.shutdown)
        logic = self.make_logic()
        panel = MFLI(logic)
        registration = replace(mfli_registration(), factory=lambda **kwargs: panel)
        manager = DeviceManager(DriverRegistry([registration]), services)
        root = Path(folder.name)
        profile = ProfileConfig(1, 'fake-mfli', ProfilePaths(root, None), (
            DeviceConfig('mfli_0', 'mfli', True, startup, {'address': address},
                         filters or ChannelFilters(None, None)),), root / 'fake.xlsx', root)
        manager.load_profile(profile)
        window = MainWindow(info=ScanInfo, save_path=folder.name,
                            backup_main_path=None, device_manager=manager)

        def cleanup():
            self.api.fail = None
            self.api.release.set()
            logic.monitoring_request(False)
            self.pump_until(lambda: not logic.busy())
            if not window._session_shutdown_complete:
                window.shutdown_session()
            window.hide()
            window.deleteLater()
            self.app.processEvents()
        self.addCleanup(cleanup)
        return manager, window, panel, logic

    def test_catalog_scalar_scan_range_and_panel_lifecycle(self):
        manager, window, panel, logic = self.make_session()
        catalog = window.get_device_channel_catalog()['mfli_0']
        self.assertEqual(len(catalog['writable']), 9)
        self.assertEqual(len(catalog['readable']), 16)
        self.assertFalse(self.api.calls)
        with ThreadPoolExecutor(1) as pool:
            self.assertTrue(pool.submit(panel.connect, 'DEV12345').result(2))
            # Worker state is authoritative even before any queued Qt signals run.
            self.assertTrue(logic.connected)
            window.active_scan_range_limits = {('mfli_0', 'OSC1_amplitude'): (0., .1)}
            pool.submit(window.write_info, .2, 'mfli_0_OSC1_amplitude').result(2)
            self.assertEqual(self.api.settings['sigouts/0/amplitudes/0'], .01)
            pool.submit(window.write_info, .05, 'mfli_0_OSC1_amplitude').result(2)
            self.assertEqual(self.api.settings['sigouts/0/amplitudes/0'], .05)
            scan = SimpleNamespace(main_window=window, _current_index_snapshot=lambda: [0])
            scan._raise_scan_io_error = lambda **kw: ScanLogic._raise_scan_io_error(scan, **kw)
            result = pool.submit(ScanLogic.read_single_device_all_channels, scan,
                                 'mfli_0', ['DEMOD1_X', 'DEMOD1_R'], 0, 0).result(2)
            self.assertEqual(result, {'mfli_0_DEMOD1_X': 3., 'mfli_0_DEMOD1_R': 5.})
            self.api.missing_y = True
            with self.assertRaisesRegex(RuntimeError, 'channel=mfli_0_DEMOD1_X'):
                pool.submit(ScanLogic.read_single_device_all_channels, scan,
                            'mfli_0', ['DEMOD1_X'], 0, 0).result(2)
            self.api.missing_y = False
            response = pool.submit(window.command_router.route_command, {
                'request_id': 'fake', 'source_device': 'test', 'action': 'read',
                'target_device': 'mfli_0', 'channel': 'DEMOD4_R', 'value': None}).result(2)
            self.assertTrue(response['ok'], response)
        panel.show()
        panel.close()
        self.assertFalse(panel.isVisible())
        self.assertTrue(logic.connected)
        self.assertTrue(logic._worker.isRunning())
        panel.show()
        self.assertTrue(panel.isVisible())
        logic.monitoring_request(True)
        manager.stop_for_scan()
        self.assertTrue(logic.scan_active)
        self.assertFalse(logic.monitoring)
        for action, args in [('amplitude', (1, .02)), ('disconnect', ()), ('connect', ('DEV12345', '', 8004))]:
            with self.assertRaisesRegex(RuntimeError, 'suspended'):
                logic.request(action, *args)
        with self.assertRaises(RuntimeError):
            logic.monitoring_request(True)
        with self.assertRaises(RuntimeError):
            logic.disconnect_device()
        with ThreadPoolExecutor(1) as pool:
            self.assertEqual(pool.submit(logic.set_OSC4_phase, 20.).result(2), 20.)
        manager.start_after_scan()
        self.pump_until(lambda: not logic.scan_active and logic.monitoring)
        logic.monitoring_request(False)
        with ThreadPoolExecutor(1) as pool:
            pool.submit(panel.disconnect).result(2)
            self.assertFalse(logic.connected)
            self.assertTrue(pool.submit(panel.connect, 'DEV12345').result(2))
        self.assertEqual(self.api.closed, 1)

    def test_filters_and_invalid_address_are_local(self):
        _, window, panel, logic = self.make_session(address='bad address', filters=ChannelFilters(
            ('OSC2_phase', 'unknown'), ('DEMOD3_R',)))
        self.assertEqual(window.get_device_channel_catalog()['mfli_0'],
                         {'writable': ['OSC2_phase'], 'readable': ['DEMOD3_R']})
        self.assertIn('serial', panel.log_window.toPlainText())
        self.assertFalse(logic.connected)
        self.assertFalse(self.api.calls)

    def test_async_startup(self):
        manager, _, panel, logic = self.make_session(startup=True)
        manager.request_startup_connections()
        self.pump_until(lambda: logic.connected and not logic.busy())
        self.assertEqual(panel.serial.text(), 'DEV12345')

    def test_signal_router_is_responsive_and_respects_scan_gate(self):
        manager, window, _, logic = self.make_session()
        self.connect_logic(logic)
        responses = []
        window.command_router.sig_command_responded.connect(responses.append)
        self.api.delay_write = True
        request = {'request_id': 'signal', 'source_device': 'test', 'action': 'write',
                   'target_device': 'mfli_0', 'channel': 'OSC1_phase', 'value': 12.}
        window.command_router.sig_command_requested.emit(request)
        self.pump_until(self.api.delay_started.is_set)
        self.assertFalse(responses)
        self.api.release.set()
        self.pump_until(lambda: bool(responses))
        self.assertTrue(responses[0]['ok'], responses)
        manager.stop_for_scan()
        window.command_router.sig_command_requested.emit(request)
        self.pump_until(lambda: len(responses) == 2)
        self.assertFalse(responses[1]['ok'])
        self.assertIn('suspended', responses[1]['error_message'])
        manager.start_after_scan()
        self.pump_until(lambda: not logic.scan_active)

    def test_abort_cancels_sample_wait_without_resetting_outputs(self):
        manager, _, _, logic = self.make_session()
        self.connect_logic(logic)
        logic.monitoring_request(True)
        manager.stop_for_scan()
        self.api.stale = True
        before = dict(self.api.settings)
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(logic.get_DEMOD1_X)
            self.pump_until(lambda: any(c[0] == 'getSample' for c in self.api.calls))
            manager.force_stop_for_scan(('mfli_0',))
            with self.assertRaises(InterruptedError):
                pending.result(1)
        self.assertEqual(self.api.settings, before)
        manager.start_after_scan()
        self.pump_until(lambda: not logic.scan_active)
        self.assertTrue(logic.monitoring)

    def test_late_connection_is_closed_and_never_published(self):
        logic = self.make_logic()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def factory(*args, **kwargs):
            entered.set()
            if not release.wait(2):
                raise RuntimeError('Fake connection not released')
            return self.api.factory(*args, **kwargs)
        self.hardware._factory = factory
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(logic.connect_device, 'DEV12345', '', 8004, 30)
            self.assertTrue(entered.wait(1))
            with self.assertRaises(TimeoutError):
                pending.result(1)
            self.assertFalse(logic.connected)
            release.set()
        self.pump_until(lambda: not logic.busy())
        self.assertFalse(logic.connected)
        self.assertFalse(logic.cleanup_needed)
        self.assertEqual(self.api.closed, 1)

    def test_blocked_native_call_retains_worker_until_late_cleanup(self):
        logic = self.make_logic()
        self.connect_logic(logic)
        self.api.delay_write = True
        write = logic.request('phase', 1, 30.)
        self.assertTrue(self.api.delay_started.wait(1))
        with self.assertRaises(TimeoutError):
            logic.terminate(timeout_ms=20)
        with self.assertRaises(RuntimeError):
            logic.assert_terminated()
        self.assertTrue(logic._worker.isRunning())
        self.api.release.set()
        self.pump_until(lambda: not logic._worker.isRunning())
        self.assertEqual(write.result(), 30.)
        logic.assert_terminated()
        self.assertEqual(self.api.closed, 1)

    def test_cleanup_failure_is_visible_and_retryable(self):
        logic = self.make_logic()
        self.connect_logic(logic)
        self.api.fail = 'disconnect'
        with self.assertRaisesRegex(RuntimeError, 'cleanup'):
            logic.terminate(500)
        self.assertTrue(logic.cleanup_needed)
        self.assertTrue(logic._worker.isRunning())
        self.api.fail = None
        self.assertTrue(logic.terminate(500))

    def test_missing_dependency_does_not_affect_construction(self):
        original = builtins.__import__
        def missing(name, *args, **kwargs):
            if name.startswith('zhinst'):
                raise ModuleNotFoundError('injected missing Core')
            return original(name, *args, **kwargs)
        hardware = MFLIHardware()
        with patch('builtins.__import__', side_effect=missing):
            with self.assertRaisesRegex(RuntimeError, 'zhinst-core==26.7.1.4'):
                hardware.connect('DEV12345', '', 8004)
        self.assertFalse(hardware.connected)

    def test_scan_barrier_finishes_active_write_and_cancels_pending_panel_work(self):
        logic = self.make_logic()
        self.connect_logic(logic)
        self.api.delay_write = True
        active = logic.request('phase', 1, 10.)
        self.assertTrue(self.api.delay_started.wait(1))
        queued = logic.request('offset', .1)
        logic.stop_scan()
        self.assertTrue(queued.cancelled())
        self.assertTrue(logic.scan_active)
        with ThreadPoolExecutor(1) as pool:
            scan_write = pool.submit(logic.set_OSC2_phase, 25.)
            self.api.release.set()
            self.assertEqual(active.result(1), 10.)
            self.assertEqual(scan_write.result(1), 25.)
        self.assertEqual(self.api.settings['sigouts/0/offset'], 0.)
        logic.start_scan()
        self.pump_until(lambda: not logic.scan_active)
        self.assertFalse(logic.monitoring)  # Originally paused.

    def test_manager_reports_cleanup_failure_and_retains_panel(self):
        services = RuntimeServices()
        self.addCleanup(services.shutdown)
        logic = self.make_logic()
        panel = MFLI(logic)
        registry = DriverRegistry([replace(mfli_registration(), factory=lambda **kw: panel)])
        manager = DeviceManager(registry, services)
        root = Path(__file__).parent
        manager.load_profile(ProfileConfig(1, 'fake', ProfilePaths(root, None), (
            DeviceConfig('mfli_0', 'mfli', True, False, {'address': 'DEV12345'},
                         ChannelFilters(None, None)),), root / 'fake.xlsx', root))
        self.connect_logic(logic)
        self.api.fail = 'disconnect'
        report = manager.teardown_all()
        self.assertTrue(report.failures)
        self.assertTrue(any('cleanup' in failure.describe() for failure in report.failures))
        self.assertTrue(logic._worker.isRunning())
        self.assertTrue(logic.cleanup_needed)
        with self.assertRaises(RuntimeError):
            panel.close_managed()
        self.api.fail = None
        logic.terminate(500)
        panel.close_managed()

    def test_application_shutdown_waits_responsively_for_active_monitor(self):
        _, window, _, logic = self.make_session()
        self.connect_logic(logic)
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = self.api.getSample
        def blocked_sample(path):
            entered.set()
            if not release.wait(2):
                raise RuntimeError('Fake monitor not released')
            return original(path)
        self.api.getSample = blocked_sample
        logic.monitoring_request(True)
        logic.request('monitor')
        self.assertTrue(entered.wait(1))
        self.assertTrue(logic.busy())
        self.assertFalse(logic.lifecycle_busy())
        operation = window._start_async_shutdown()
        self.assertFalse(operation.done)
        self.app.processEvents()
        self.assertTrue(logic._worker.isRunning())
        release.set()
        self.pump_until(lambda: window._session_shutdown_complete)
        self.assertTrue(operation.result.succeeded)
        self.assertFalse(logic._worker.isRunning())
        self.assertEqual(self.api.closed, 1)


if __name__ == '__main__':
    unittest.main()
