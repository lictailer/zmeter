"""Fake-only checks for global amplitude/DC ramping; vendor imports are guarded."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from devices.MFLI_temp.tests.test_mfli_layers import OfflineCase
from devices.mfli.MFLI_hardware import TransportError


class RampTests(OfflineCase):
    def writes(self):
        return [call for call in self.api.calls if call[0] == 'syncSetDouble']

    def test_all_five_channels_ramp_in_both_directions_at_fixed_cadence(self):
        self.connect_hardware()
        channels = [(f'sigouts/0/amplitudes/{i - 1}',
                     lambda value, i=i: self.hardware.write_amplitude(i, value))
                    for i in range(1, 5)]
        channels.append(('sigouts/0/offset', self.hardware.write_offset))
        for node, write in channels:
            for start, target in [(.24, -.015), (-.24, .015)]:
                with self.subTest(node=node, start=start):
                    self.api.settings[node] = start
                    self.api.calls.clear()
                    with patch.object(self.hardware.cancel, 'wait', return_value=False) as wait:
                        result = write(target)
                    values = [c[2] for c in self.writes()]
                    direction = 1 if target > start else -1
                    self.assertEqual(len(values), 3)
                    for actual, expected in zip(values, [start + direction * .1,
                                                        start + direction * .2, target]):
                        self.assertAlmostEqual(actual, expected)
                    self.assertEqual(result, target)
                    self.assertEqual([c.args for c in wait.call_args_list], [(0.01,)] * 3)
                    self.assertEqual({c[1] for c in self.writes()}, {'/dev12345/' + node})
                    self.api.settings[node] = 0.

    def test_equal_setpoint_is_noop_and_phase_stays_direct(self):
        self.connect_hardware()
        with patch.object(self.hardware.cancel, 'wait', return_value=False) as wait:
            self.assertEqual(self.hardware.write_offset(0.), 0.)
            self.assertEqual(self.hardware.write_amplitude(1, .01), .01)
            self.assertFalse(self.writes())
            self.assertEqual(self.hardware.write_phase(1, 120.), 120.)
            wait.assert_not_called()
        self.assertEqual(len(self.writes()), 1)

    def test_small_final_step_returns_instrument_acknowledgement(self):
        self.connect_hardware()
        with patch.object(self.hardware.cancel, 'wait', return_value=False) as wait:
            self.assertEqual(self.hardware.write_offset(.2156789), .215679)
        self.assertEqual([c[2] for c in self.writes()], [.1, .2, .2156789])
        self.assertEqual(wait.call_count, 3)

    def test_invalid_target_or_failed_start_read_never_writes(self):
        self.connect_hardware()
        with self.assertRaises(ValueError):
            self.hardware.write_offset(1.)
        self.api.fail = '/dev12345/sigouts/0/offset'
        with self.assertRaises(TransportError):
            self.hardware.write_offset(.3)
        self.assertFalse(self.writes())

    def test_each_step_rechecks_current_range(self):
        self.connect_hardware()
        ticks = []
        def wait(_):
            ticks.append(1)
            if len(ticks) == 2:
                self.api.settings['sigouts/0/range'] = .15
            return False
        with patch.object(self.hardware.cancel, 'wait', side_effect=wait):
            with self.assertRaisesRegex(ValueError, 'Combined'):
                self.hardware.write_offset(.3)
        self.assertEqual([c[2] for c in self.writes()], [.1])
        self.assertEqual(self.api.settings['sigouts/0/offset'], .1)

    def test_cancel_during_wait_preserves_last_applied_step(self):
        self.connect_hardware()
        def wait(_):
            if self.writes():
                self.hardware.cancel.set()
            return self.hardware.cancel.is_set()
        with patch.object(self.hardware.cancel, 'wait', side_effect=wait):
            with self.assertRaisesRegex(InterruptedError, 'last acknowledged value 0.1 V'):
                self.hardware.write_offset(.5)
        self.assertEqual([c[2] for c in self.writes()], [.1])
        with self.assertRaises(InterruptedError):
            self.hardware.write_amplitude(1, .2)
        self.assertEqual(len(self.writes()), 1)

    def test_failed_step_is_not_retried(self):
        self.connect_hardware()
        original = self.api.syncSetDouble
        def fail_second(path, value):
            if self.writes():
                self.api.fail = 'syncSetDouble'
            return original(path, value)
        with patch.object(self.hardware.cancel, 'wait', return_value=False), \
                patch.object(self.api, 'syncSetDouble', side_effect=fail_second):
            with self.assertRaisesRegex(TransportError, 'may have applied'):
                self.hardware.write_offset(.5)
        self.assertEqual([c[2] for c in self.writes()], [.1, .2])
        self.assertEqual(self.api.settings['sigouts/0/offset'], .1)

    def test_scan_setter_and_panel_request_share_ramp(self):
        logic = self.make_logic()
        self.connect_logic(logic)
        with ThreadPoolExecutor(1) as pool:
            self.assertEqual(pool.submit(logic.set_output_DCoffset, .25).result(2), .25)
        self.assertEqual([c[2] for c in self.writes()], [.1, .2, .25])
        self.api.calls.clear()
        self.assertEqual(logic.request('amplitude', 4, .26).result(2), .26)
        for actual, expected in zip([c[2] for c in self.writes()], [.11, .21, .26]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(len(self.writes()), 3)
        self.assertEqual(len(self.api.threads), 1)

    def test_force_stop_interrupts_active_ramp_without_writing_target(self):
        logic = self.make_logic()
        self.connect_logic(logic)
        self.api.delay_write = True
        ramp = logic.request('offset', .5)
        self.assertTrue(self.api.delay_started.wait(1))
        logic.force_stop()
        self.api.release.set()
        with self.assertRaises(InterruptedError):
            ramp.result(1)
        self.assertEqual([c[2] for c in self.writes()], [.1])
        self.assertEqual(self.api.settings['sigouts/0/offset'], .1)
