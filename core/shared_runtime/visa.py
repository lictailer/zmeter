"""Shared PyVISA manager ownership with exclusive per-address leases."""

from __future__ import annotations

import threading
import weakref
from typing import Any, Callable


class VisaRuntimeError(RuntimeError):
    """Base error raised by the shared VISA service."""


class VisaAddressInUseError(VisaRuntimeError):
    """Raised when a second owner requests an already leased address."""


class VisaResourceLease:
    """Own one instrument session opened by :class:`VisaRuntime`."""

    def __init__(self, runtime: "VisaRuntime", owner: str, address_key: str, resource: Any) -> None:
        self._runtime_ref = weakref.ref(runtime)
        self.owner = owner
        self.address = address_key
        self.resource = resource
        self._closed = False
        self._lock = threading.Lock()

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Close this session and release its address reservation once."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        runtime = self._runtime_ref()
        if runtime is None:
            _safe_close(self.resource)
            return
        runtime._release(self.address, self.resource, self)

    def __enter__(self) -> "VisaResourceLease":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class VisaRuntime:
    """Own one lazy ResourceManager and independent instrument sessions."""

    def __init__(self, backend: str = "", manager_factory: Callable[..., Any] | None = None) -> None:
        self.backend = str(backend).strip()
        self._manager_factory = manager_factory
        self._manager: Any | None = None
        self._leases: dict[str, VisaResourceLease | None] = {}
        self._lock = threading.RLock()
        self._shutdown = False

    def open_resource(self, owner: str, address: str, **kwargs: Any) -> VisaResourceLease:
        owner_key = _required_text(owner, "VISA owner")
        raw_address = _required_text(address, "VISA address")
        address_key = self.normalize_address(raw_address)
        with self._lock:
            self._require_active()
            if address_key in self._leases:
                existing = self._leases[address_key]
                existing_owner = existing.owner if existing is not None else "another connection"
                raise VisaAddressInUseError(
                    f"VISA address {raw_address!r} is already owned by {existing_owner!r}"
                )
            self._leases[address_key] = None
            try:
                resource = self._get_manager_locked().open_resource(raw_address, **kwargs)
                lease = VisaResourceLease(self, owner_key, address_key, resource)
                self._leases[address_key] = lease
                return lease
            except Exception:
                self._leases.pop(address_key, None)
                raise

    def list_resources(self, query: str = "?*::INSTR") -> tuple[str, ...]:
        """Explicitly enumerate VISA resources through the shared manager."""
        with self._lock:
            self._require_active()
            manager = self._get_manager_locked()
            try:
                resources = manager.list_resources(query)
            except TypeError:
                if query != "?*::INSTR":
                    raise
                resources = manager.list_resources()
            return tuple(str(item) for item in resources)

    def shutdown(self) -> None:
        """Close every remaining session, then the shared manager, once."""
        with self._lock:
            if self._shutdown:
                return
            leases = [lease for lease in self._leases.values() if lease is not None]
        for lease in leases:
            lease.close()
        with self._lock:
            manager = self._manager
            self._manager = None
            self._shutdown = True
        _safe_close(manager)

    @property
    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            owners = {address: lease.owner for address, lease in self._leases.items() if lease is not None}
            return {
                "backend": self.backend or "default",
                "manager_created": self._manager is not None,
                "owners": owners,
                "shutdown": self._shutdown,
            }

    @staticmethod
    def normalize_address(address: str) -> str:
        return _required_text(address, "VISA address").upper()

    def _get_manager_locked(self) -> Any:
        if self._manager is not None:
            return self._manager
        if self._manager_factory is not None:
            self._manager = self._manager_factory(self.backend) if self.backend else self._manager_factory()
        else:
            import pyvisa
            self._manager = pyvisa.ResourceManager(self.backend) if self.backend else pyvisa.ResourceManager()
        return self._manager

    def _release(self, address_key: str, resource: Any, lease: VisaResourceLease) -> None:
        try:
            _safe_close(resource)
        finally:
            with self._lock:
                if self._leases.get(address_key) is lease:
                    self._leases.pop(address_key, None)

    def _require_active(self) -> None:
        if self._shutdown:
            raise VisaRuntimeError("VISA runtime has been shut down")


def _required_text(value: object, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} must be provided")
    return text


def _safe_close(value: Any | None) -> None:
    if value is None:
        return
    try:
        value.close()
    except Exception:
        pass
