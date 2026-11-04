"""zcore.results.Result: statuses and constructors (Qt-free)."""

import dataclasses
import unittest

from zcore.results import Result, Status


class ResultTests(unittest.TestCase):
    def test_constructors_set_status_value_and_reason(self):
        cases = [
            (Result.ok(1.5), Status.OK, 1.5, ""),
            (Result.ok(), Status.OK, None, ""),
            (Result.timeout("no reply in 2 s"), Status.TIMEOUT, None, "no reply in 2 s"),
            (Result.cancelled(0.3, "force stop"), Status.CANCELLED, 0.3, "force stop"),
            (Result.cancelled(), Status.CANCELLED, None, ""),
            (Result.failed("outside device limit"), Status.FAILED, None, "outside device limit"),
            (Result.unknown("late reply discarded"), Status.UNKNOWN, None, "late reply discarded"),
        ]
        for result, status, value, reason in cases:
            with self.subTest(status=status):
                self.assertIs(result.status, status)
                self.assertEqual(result.value, value)
                self.assertEqual(result.reason, reason)
                self.assertEqual(result.is_ok, status is Status.OK)

    def test_status_values_are_the_adr_names(self):
        self.assertEqual(
            [status.value for status in Status],
            ["ok", "timeout", "cancelled", "failed", "unknown"],
        )

    def test_plain_string_status_is_accepted_and_unknown_string_is_not(self):
        self.assertIs(Result("ok", 2).status, Status.OK)
        self.assertEqual(Result("cancelled"), Result.cancelled())
        with self.assertRaises(ValueError):
            Result("done")

    def test_failed_needs_a_reason(self):
        with self.assertRaises(ValueError):
            Result.failed("")
        with self.assertRaises(ValueError):
            Result(Status.FAILED)

    def test_reason_must_be_text(self):
        with self.assertRaises(TypeError):
            Result(Status.TIMEOUT, None, 5)

    def test_result_is_frozen(self):
        result = Result.ok(1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.value = 2

    def test_ok_zero_is_still_ok(self):
        # A read of 0.0 is data, not a failure: callers test is_ok, never truth.
        self.assertTrue(Result.ok(0.0).is_ok)


if __name__ == "__main__":
    unittest.main()
