from __future__ import annotations

import unittest

from core.shared_runtime.visa import (
    VisaAddressInUseError,
    VisaRuntime,
    VisaRuntimeError,
)


class FakeResource:
    def __init__(self, address: str) -> None:
        self.address = address
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeManager:
    def __init__(self) -> None:
        self.open_calls = []
        self.resources = []
        self.close_calls = 0
        self.open_error = None
        self.list_calls = []

    def open_resource(self, address, **kwargs):
        self.open_calls.append((address, kwargs))
        if self.open_error is not None:
            raise self.open_error
        resource = FakeResource(address)
        self.resources.append(resource)
        return resource

    def list_resources(self, query="?*::INSTR"):
        self.list_calls.append(query)
        return ("GPIB0::1::INSTR", "USB0::2::INSTR")

    def close(self) -> None:
        self.close_calls += 1


class VisaRuntimeTests(unittest.TestCase):
    def test_manager_is_lazy_and_created_once(self):
        manager = FakeManager()
        calls = []
        runtime = VisaRuntime(manager_factory=lambda: calls.append(1) or manager)
        self.assertFalse(runtime.diagnostics["manager_created"])
        first = runtime.open_resource("one", "GPIB0::1::INSTR")
        second = runtime.open_resource("two", "GPIB0::2::INSTR")
        self.assertEqual(calls, [1])
        self.assertIsNot(first.resource, second.resource)
        first.close()
        self.assertEqual(first.resource.close_calls, 1)
        self.assertEqual(second.resource.close_calls, 0)
        self.assertEqual(manager.close_calls, 0)

    def test_duplicate_normalized_address_is_rejected(self):
        runtime = VisaRuntime(manager_factory=FakeManager)
        lease = runtime.open_resource("owner-a", " gpib0::1::instr ")
        with self.assertRaisesRegex(VisaAddressInUseError, "owner-a"):
            runtime.open_resource("owner-b", "GPIB0::1::INSTR")
        lease.close()
        replacement = runtime.open_resource("owner-b", "GPIB0::1::INSTR")
        replacement.close()

    def test_failed_open_releases_reservation(self):
        manager = FakeManager()
        manager.open_error = RuntimeError("open failed")
        runtime = VisaRuntime(manager_factory=lambda: manager)
        with self.assertRaisesRegex(RuntimeError, "open failed"):
            runtime.open_resource("one", "GPIB0::1::INSTR")
        self.assertEqual(runtime.diagnostics["owners"], {})
        manager.open_error = None
        runtime.open_resource("two", "GPIB0::1::INSTR").close()

    def test_discovery_is_explicit_and_uses_shared_manager(self):
        manager = FakeManager()
        runtime = VisaRuntime(manager_factory=lambda: manager)
        self.assertEqual(manager.list_calls, [])
        self.assertEqual(runtime.list_resources(), ("GPIB0::1::INSTR", "USB0::2::INSTR"))
        self.assertEqual(manager.list_calls, ["?*::INSTR"])

    def test_shutdown_closes_sessions_then_manager_and_is_idempotent(self):
        manager = FakeManager()
        runtime = VisaRuntime(manager_factory=lambda: manager)
        first = runtime.open_resource("one", "GPIB0::1::INSTR")
        second = runtime.open_resource("two", "GPIB0::2::INSTR")
        runtime.shutdown()
        runtime.shutdown()
        self.assertEqual(first.resource.close_calls, 1)
        self.assertEqual(second.resource.close_calls, 1)
        self.assertEqual(manager.close_calls, 1)
        with self.assertRaises(VisaRuntimeError):
            runtime.list_resources()

    def test_backend_is_forwarded_only_to_factory(self):
        seen = []
        runtime = VisaRuntime("@py", manager_factory=lambda backend: seen.append(backend) or FakeManager())
        runtime.list_resources()
        self.assertEqual(seen, ["@py"])


if __name__ == "__main__":
    unittest.main()
