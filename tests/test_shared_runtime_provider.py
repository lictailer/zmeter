from __future__ import annotations

import unittest

from core.shared_runtime.provider import RuntimeServices


class FakeRuntime:
    def __init__(self, name):
        self.name = name
        self.shutdown_calls = 0
        self.diagnostics = {"name": name}

    def shutdown(self):
        self.shutdown_calls += 1
        return self.diagnostics


class RuntimeServicesTests(unittest.TestCase):
    def test_services_are_independent_and_shutdown_separately(self):
        visa = FakeRuntime("visa")
        kinesis = FakeRuntime("kinesis")
        provider = RuntimeServices(visa=visa, kinesis=kinesis)
        result = provider.shutdown()
        self.assertEqual(visa.shutdown_calls, 1)
        self.assertEqual(kinesis.shutdown_calls, 1)
        self.assertEqual(result["visa"], {"name": "visa"})
        self.assertEqual(result["kinesis"], {"name": "kinesis"})


if __name__ == "__main__":
    unittest.main()
