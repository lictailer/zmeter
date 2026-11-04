"""zcore.events: EventBus and the frozen device events (Qt-free)."""

import dataclasses
import threading
import unittest

from zcore.events import (
    ERROR,
    INFO,
    WARNING,
    EventBus,
    LogEntry,
    Progress,
    StateChanged,
    ValueChanged,
)


class EventTypeTests(unittest.TestCase):
    def test_events_are_frozen(self):
        events = [
            ValueChanged("dev", "bias", 1.0, "panel"),
            StateChanged("dev", "idle"),
            LogEntry("dev", INFO, "hello"),
            Progress("dev", "bias", 0.5, 0.25),
        ]
        for event in events:
            with self.subTest(event=type(event).__name__):
                with self.assertRaises(dataclasses.FrozenInstanceError):
                    event.device = "other"

    def test_log_entry_levels(self):
        for level in (INFO, WARNING, ERROR):
            self.assertEqual(LogEntry("dev", level, "m").level, level)
        with self.assertRaises(ValueError):
            LogEntry("dev", "debug", "m")


class EventBusTests(unittest.TestCase):
    def test_subscribers_get_every_event_in_order(self):
        bus = EventBus()
        first, second = [], []
        bus.subscribe(first.append)
        bus.subscribe(second.append)
        events = [StateChanged("dev", "idle"), ValueChanged("dev", "x", 1, "scan")]
        for event in events:
            bus.publish(event)
        self.assertEqual(first, events)
        self.assertEqual(second, events)

    def test_type_filter(self):
        bus = EventBus()
        values = []
        bus.subscribe(values.append, ValueChanged, LogEntry)
        bus.publish(StateChanged("dev", "idle"))
        bus.publish(ValueChanged("dev", "x", 1, "scan"))
        bus.publish(LogEntry("dev", INFO, "m"))
        self.assertEqual([type(e) for e in values], [ValueChanged, LogEntry])

    def test_subscribing_again_replaces_the_filter(self):
        bus = EventBus()
        got = []
        bus.subscribe(got.append, ValueChanged)
        bus.subscribe(got.append, StateChanged)
        bus.publish(ValueChanged("dev", "x", 1, "scan"))
        bus.publish(StateChanged("dev", "idle"))
        self.assertEqual([type(e) for e in got], [StateChanged])

    def test_unsubscribe(self):
        bus = EventBus()
        got = []
        bus.subscribe(got.append)
        bus.unsubscribe(got.append)
        bus.unsubscribe(got.append)  # twice is harmless
        bus.publish(StateChanged("dev", "idle"))
        self.assertEqual(got, [])

    def test_failing_subscriber_is_logged_and_isolated(self):
        bus = EventBus()
        got = []

        def broken(event):
            raise RuntimeError("panel is gone")

        bus.subscribe(broken)
        bus.subscribe(got.append)
        event = StateChanged("dev", "idle")
        with self.assertLogs("zcore.events", "ERROR") as logs:
            bus.publish(event)  # must not raise
        self.assertEqual(got, [event])
        self.assertIn("panel is gone", "\n".join(logs.output))

    def test_rejects_bad_arguments(self):
        bus = EventBus()
        with self.assertRaises(TypeError):
            bus.subscribe("not callable")
        with self.assertRaises(TypeError):
            bus.subscribe(print, "ValueChanged")

    def test_concurrent_publish_and_subscribe(self):
        bus = EventBus()
        counts = []
        lock = threading.Lock()
        stable = []
        bus.subscribe(stable.append, ValueChanged)
        start = threading.Barrier(9)

        def publisher(index):
            start.wait()
            for i in range(200):
                bus.publish(ValueChanged("dev", f"p{index}", i, "test"))

        def churner():
            start.wait()
            for _ in range(200):
                handler = lambda event: None  # noqa: E731
                bus.subscribe(handler)
                bus.unsubscribe(handler)
            with lock:
                counts.append(1)

        threads = [threading.Thread(target=publisher, args=(i,)) for i in range(8)]
        threads.append(threading.Thread(target=churner))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(stable), 8 * 200)
        self.assertEqual(counts, [1])
        for index in range(8):
            values = [e.value for e in stable if e.name == f"p{index}"]
            self.assertEqual(values, list(range(200)))  # per-publisher order kept


if __name__ == "__main__":
    unittest.main()
