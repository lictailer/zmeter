"""Result of one call to a device (ADR 004, decision 4).

Every call that goes through the device Runner returns a ``Result`` instead of
raising or returning ``None``. Callers that need data (the scan bridge) turn
every non-ok result into an exception that names the status, so a failed read
is never stored as a measured value.

Qt-free and hardware-free, like the rest of ``zcore``.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Status(str, Enum):
    """Outcome of a device call."""

    OK = "ok"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Result:
    """Outcome of one device call.

    ``value`` is the value read or written for ``ok``; for ``cancelled`` it is
    the last value actually written (an interrupted ramp), otherwise usually
    ``None``. ``reason`` explains a non-ok status in words a user can act on.

    Use the constructors (``Result.ok(...)``, ``Result.failed(...)``, ...)
    rather than spelling the status.
    """

    status: Status
    value: Any = None
    reason: str = ""

    def __post_init__(self):
        # Accept the plain string ("ok") as well as the enum member.
        object.__setattr__(self, "status", Status(self.status))
        if not isinstance(self.reason, str):
            raise TypeError(f"Result reason must be a string, got {self.reason!r}")
        if self.status is Status.FAILED and not self.reason:
            raise ValueError("A failed Result needs a reason")

    @property
    def is_ok(self) -> bool:
        return self.status is Status.OK

    @classmethod
    def ok(cls, value: Any = None) -> "Result":
        return cls(Status.OK, value)

    @classmethod
    def timeout(cls, reason: str = "") -> "Result":
        return cls(Status.TIMEOUT, None, reason)

    @classmethod
    def cancelled(cls, value: Any = None, reason: str = "") -> "Result":
        return cls(Status.CANCELLED, value, reason)

    @classmethod
    def failed(cls, reason: str) -> "Result":
        return cls(Status.FAILED, None, reason)

    @classmethod
    def unknown(cls, reason: str = "") -> "Result":
        return cls(Status.UNKNOWN, None, reason)
