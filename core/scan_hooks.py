"""Hooks that run when a scan has finished (saved, devices restored).

``MainWindow.scan_hooks`` owns one ``ScanHooks`` object; the Slack notifier is
its first hook (``core/slack_notify/scan_hook.py``).  ``Scan`` emits one
``ScanFinished`` record per finished scan from the UI thread, after the scan
files are written and before the scan is marked finalized, so a waiting queue
sees the result first.  A scan "stopped for restart" emits nothing.

Every callback runs on its own: a failing hook is reported as a warning with
the hook's name and never affects saving, device restore or the queue.
Callbacks run on the UI thread and must return quickly; slow work (network)
belongs on the hook's own worker, as the Slack notifier does.

Imports only the standard library.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class ScanFinished:
    """One finished scan, as handed to every scan-finished hook."""

    # Serial and scan name, as in the JSON file name: "0007_gate_map".
    name: str
    # "completed", "stopped" or "error".
    status: str
    elapsed_seconds: float
    completed_points: int
    total_points: int
    # Primary JSON file, or None when it was not written.
    json_path: Optional[str]
    error_message: Optional[str]
    # True while the scan runs as a queue item (the queue reports its own end).
    queue_run: bool
    # Plot screenshot (PNG bytes); captured only when a hook wants it.
    plot_png: Optional[bytes] = None


@dataclass(frozen=True)
class _Hook:
    name: str
    callback: Callable[[ScanFinished], object]
    wants_plot_png: Optional[Callable[[], bool]]


def _hook_name(callback) -> str:
    return str(
        getattr(callback, "__qualname__", None)
        or getattr(callback, "__name__", None)
        or type(callback).__name__
    )


class ScanHooks:
    """Registered scan-finished hooks of one main window."""

    def __init__(self):
        self._scan_finished = []

    def register_scan_finished(
        self,
        callback: Callable[[ScanFinished], object],
        *,
        wants_plot_png: Optional[Callable[[], bool]] = None,
        name: Optional[str] = None,
    ) -> Callable[[], None]:
        """Call ``callback(ScanFinished)`` after every finished scan.

        ``wants_plot_png`` is asked when the scan starts finalizing, on the UI
        thread; the plot screenshot is captured only if some hook answers
        True.  ``name`` labels the hook in warnings (default: the callback's
        qualified name).  Returns a function that unregisters the hook.
        """
        if not callable(callback):
            raise TypeError("scan-finished hook must be callable")
        if wants_plot_png is not None and not callable(wants_plot_png):
            raise TypeError("wants_plot_png must be callable or None")
        hook = _Hook(name or _hook_name(callback), callback, wants_plot_png)
        self._scan_finished.append(hook)

        def unregister():
            if hook in self._scan_finished:
                self._scan_finished.remove(hook)

        return unregister

    @property
    def has_scan_finished_hooks(self) -> bool:
        return bool(self._scan_finished)

    def wants_plot_png(self, log_warning: Callable[[str], object]) -> bool:
        """True when at least one hook wants the plot screenshot now."""
        wanted = False
        for hook in tuple(self._scan_finished):
            if hook.wants_plot_png is None:
                continue
            try:
                if hook.wants_plot_png():
                    wanted = True
            except Exception as exc:
                log_warning(
                    f"Scan-finished hook '{hook.name}' failed to answer whether "
                    f"it wants the plot screenshot: {type(exc).__name__}: {exc}"
                )
        return wanted

    def emit_scan_finished(
        self, event: ScanFinished, log_warning: Callable[[str], object]
    ) -> None:
        """Call every hook in registration order; failures become warnings."""
        for hook in tuple(self._scan_finished):
            try:
                hook.callback(event)
            except Exception as exc:
                log_warning(
                    f"Scan-finished hook '{hook.name}' failed: "
                    f"{type(exc).__name__}: {exc}"
                )
