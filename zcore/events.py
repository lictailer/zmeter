"""Thread-safe event bus and the device events (ADR 004, decision 6).

The device Runner publishes what happens on a device (a value read or written,
a state change, a log line, ramp progress) as frozen events. Subscribers are
called on the publisher's thread, in subscription order. A subscriber that
raises is logged with Python ``logging`` and never affects the publisher or the
other subscribers, so a broken panel cannot stop a scan.

The Qt layer (``zui``) re-emits these events to the GUI thread; nothing here
knows about Qt. Subscribers must return quickly and must not wait on the
Runner, because the Runner delivers events from its own threads between two
device calls.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Levels of a LogEntry, lowest first.
INFO = "info"
WARNING = "warning"
ERROR = "error"
LOG_LEVELS = (INFO, WARNING, ERROR)


@dataclass(frozen=True)
class ValueChanged:
    """A parameter was read or written. ``source`` says who asked (``scan``,
    ``panel``, ``poll``, ``test`` or ``runner``)."""

    device: str
    name: str
    value: Any
    source: str


@dataclass(frozen=True)
class StateChanged:
    """The device state changed (see ``zcore.runner.DeviceState``)."""

    device: str
    state: str
    reason: str = ""


@dataclass(frozen=True)
class LogEntry:
    """One line for the device log. ``level`` is ``info``, ``warning`` or
    ``error``."""

    device: str
    level: str
    message: str

    def __post_init__(self):
        if self.level not in LOG_LEVELS:
            raise ValueError(f"LogEntry level must be one of {LOG_LEVELS}, got {self.level!r}")


@dataclass(frozen=True)
class Progress:
    """Progress of a long operation on one parameter (a ramp step): the value
    reached and the fraction done, from 0 to 1."""

    device: str
    name: str
    value: Any
    fraction: float


Handler = Callable[[Any], None]


class EventBus:
    """Publish events to subscribers; safe to use from any thread.

    ``subscribe(handler)`` receives every event; ``subscribe(handler,
    ValueChanged, LogEntry)`` only events of those types (subclasses
    included). Subscribing the same handler again replaces its event types.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._handlers: dict[Handler, tuple[type, ...]] = {}

    def subscribe(self, handler: Handler, *event_types: type) -> Handler:
        if not callable(handler):
            raise TypeError(f"EventBus handler must be callable, got {handler!r}")
        for event_type in event_types:
            if not isinstance(event_type, type):
                raise TypeError(f"EventBus event types must be classes, got {event_type!r}")
        with self._lock:
            self._handlers[handler] = tuple(event_types)
        return handler

    def unsubscribe(self, handler: Handler) -> None:
        """Remove ``handler``; doing so twice is harmless. An event being
        published at the same moment may still reach it once."""
        with self._lock:
            self._handlers.pop(handler, None)

    def publish(self, event: Any) -> None:
        """Call every matching subscriber on this thread. Never raises because
        of a subscriber."""
        with self._lock:
            handlers = list(self._handlers.items())
        for handler, event_types in handlers:
            if event_types and not isinstance(event, event_types):
                continue
            try:
                handler(event)
            except Exception:
                logger.exception("Event subscriber %r failed on %r", handler, event)
