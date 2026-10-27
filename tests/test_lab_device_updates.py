"""Offline regression contracts for the imported SMU/lock-in/power-meter changes."""
from types import SimpleNamespace
import unittest
from unittest import mock

from devices.keithley24xx.keithley24xx_hardware import Keithly24xxHardware
from devices.sr860.sr860_hardware import SR860_Hardware
from devices.sr860.sr860_logic import SR860_Logic, SR860RampAbortedError
from devices.tlpm.tlpm_logic import TLPMLogic


class IntegrationTimeTests(unittest.TestCase):
    def test_nplc_programs_both_functions_and_returns_readbacks(self):
        hardware = Keithly24xxHardware.__new__(Keithly24xxHardware)
        hardware.inst = mock.Mock()
        hardware.inst.query.side_effect = ['1', '1']
        self.assertEqual(hardware.set_measurement_nplc(1), (1, 1))
        self.assertEqual(hardware.inst.write.call_args_list,
                         [mock.call(':SENS:VOLT:NPLC 1'), mock.call(':SENS:CURR:NPLC 1')])
        self.assertEqual(hardware.inst.query.call_args_list,
                         [mock.call(':SENS:VOLT:NPLC?'), mock.call(':SENS:CURR:NPLC?')])

    def test_invalid_nplc_is_rejected_before_writing(self):
        hardware = Keithly24xxHardware.__new__(Keithly24xxHardware)
        hardware.inst = mock.Mock()
        for value in (True, float('nan'), float('inf'), 0, 11, 'bad'):
            with self.assertRaises(ValueError): hardware.set_measurement_nplc(value)
        hardware.inst.write.assert_not_called()
        self.assertEqual(Keithly24xxHardware.validate_nplc(0.01), 0.01)
        self.assertEqual(Keithly24xxHardware.validate_nplc(10), 10)


class LockinTransactionTests(unittest.TestCase):
    def hardware(self):
        hardware = SR860_Hardware.__new__(SR860_Hardware)
        hardware._vi = mock.Mock(timeout=100)
        hardware._visa_lease = None
        return hardware

    def test_waypoint_program_and_query_is_one_transaction(self):
        hardware = self.hardware()
        hardware._vi.query.return_value = '0.15'
        self.assertEqual(hardware.program_amplitude_and_readback(0.15), 0.15)
        hardware._vi.query.assert_called_once_with('SLVL 0.15;SLVL?')
        self.assertEqual(hardware._vi.timeout, 100)
        hardware._vi.write.assert_not_called()

    def test_dc_programming_and_readback_keep_millivolt_units(self):
        hardware = self.hardware()
        hardware._vi.query.return_value = '0.025'
        self.assertEqual(hardware.program_dc_level_and_readback(25), 25)
        hardware._vi.query.assert_called_once_with('SOFF 25 MV;SOFF?')

    def test_uncertain_waypoint_is_not_retried_and_restores_timeout(self):
        hardware = self.hardware()
        hardware._vi.query.side_effect = TimeoutError('synthetic')
        with self.assertRaises(RuntimeError): hardware.program_amplitude_and_readback(0.1)
        self.assertEqual(hardware._vi.query.call_count, 1)
        self.assertEqual(hardware._vi.timeout, 100)

    def test_output_validation_precedes_io(self):
        hardware = self.hardware()
        for value in (True, -1, 3, float('nan')):
            with self.assertRaises(ValueError): hardware.program_amplitude_and_readback(value)
        for value in (True, -5001, 5001, float('inf')):
            with self.assertRaises(ValueError): hardware.program_dc_level_and_readback(value)
        hardware._vi.query.assert_not_called()
        hardware._vi.write.assert_not_called()


class SimulatedClockEvent:
    def __init__(self):
        self.now, self.stopped = 0.0, False
    def is_set(self): return self.stopped
    def set(self): self.stopped = True
    def clear(self): self.stopped = False
    def wait(self, seconds):
        self.now += max(0.0, seconds)
        return self.stopped


class LockinRampTests(unittest.TestCase):
    def logic(self):
        logic, event = SR860_Logic(), SimulatedClockEvent()
        logic._ramp_stop_event = event
        logic._monotonic = lambda: event.now
        state = SimpleNamespace(amplitude=0.0, dc_mv=0.0, commands=[], stop_after_first=False)
        def program(name, value):
            setattr(state, name, value)
            state.commands.append((name, value))
            if state.stop_after_first: logic.request_force_stop('synthetic stop')
            return value
        logic.hardware = SimpleNamespace(get_amplitude=lambda: state.amplitude,
            dc_level=lambda **kwargs: state.dc_mv / 1000,
            program_amplitude_and_readback=lambda value: program('amplitude', value),
            program_dc_level_and_readback=lambda value: program('dc_mv', value))
        logic.configure_amplitude_ramp_rate(1)
        return logic, state

    def test_ramps_finish_with_confirmed_endpoint_in_both_units(self):
        logic, state = self.logic()
        self.assertEqual(logic.set_amplitude(0.2), 0.2)
        self.assertGreater(len(state.commands), 1)
        self.assertAlmostEqual(state.commands[0][1], 0.05)
        state.commands.clear()
        self.assertEqual(logic.set_dc_level(20), 20)
        self.assertEqual(state.dc_mv, 20)
        self.assertGreater(len(state.commands), 1)
        self.assertFalse(logic.ramp_active)

    def test_stop_keeps_last_confirmed_waypoint_without_endpoint_jump(self):
        logic, state = self.logic()
        state.stop_after_first = True
        with self.assertRaises(SR860RampAbortedError): logic.set_amplitude(0.2)
        self.assertEqual(len(state.commands), 1)
        self.assertAlmostEqual(logic.setpoint_amplitude, 0.05)
        self.assertAlmostEqual(state.amplitude, 0.05)
        self.assertFalse(logic.ramp_active)

    def test_combined_output_and_invalid_rate_do_not_write(self):
        logic, state = self.logic()
        state.dc_mv = 5000
        with self.assertRaisesRegex(ValueError, 'output limit'): logic.set_amplitude(2)
        with self.assertRaises(ValueError): logic.configure_amplitude_ramp_rate(float('nan'))
        self.assertEqual(state.commands, [])


class PowerMeterSetterTests(unittest.TestCase):
    def test_scan_wavelength_setter_writes_synchronously_in_nm(self):
        logic = TLPMLogic()
        logic.hardware = mock.Mock()
        logic.is_connected = True
        self.assertEqual(logic.set_wavelength(780), 780)
        self.assertEqual(logic.hardware.setWavelength.call_args.args[0].value, 780)
        self.assertFalse(logic.isRunning())

    def test_queued_target_and_validation_do_not_write(self):
        logic = TLPMLogic()
        logic.hardware = mock.Mock()
        logic.queue_wavelength(800)
        self.assertEqual(logic.target, 800)
        logic.hardware.setWavelength.assert_not_called()
        with self.assertRaises(RuntimeError): logic.set_wavelength(800)
        for value in (float('nan'), float('inf')):
            with self.assertRaises(ValueError): logic.set_wavelength(value)


if __name__ == '__main__':
    unittest.main()
