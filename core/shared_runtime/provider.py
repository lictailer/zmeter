"""Composition root for independent shared runtime services."""

from __future__ import annotations

from typing import Any

from .kinesis import KinesisRuntime, KinesisRuntimeInUseError
from .visa import VisaRuntime


class RuntimeServices:
    """Hold typed runtime services without coupling their implementations."""

    def __init__(self, visa: VisaRuntime | None = None, kinesis: KinesisRuntime | None = None) -> None:
        self.visa = visa or VisaRuntime()
        self.kinesis = kinesis or KinesisRuntime()

    def shutdown(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        try:
            self.visa.shutdown()
            result["visa"] = self.visa.diagnostics
        except Exception as exc:
            result["visa_error"] = str(exc)
        try:
            result["kinesis"] = self.kinesis.shutdown()
        except KinesisRuntimeInUseError as exc:
            result["kinesis_error"] = str(exc)
            result["kinesis"] = self.kinesis.diagnostics
        return result
