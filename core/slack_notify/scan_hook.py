"""The Slack notifier as a scan-finished hook."""

from __future__ import annotations

from ..scan_hooks import ScanFinished, ScanHooks
from .notifier import SlackNotifier

HOOK_NAME = "Slack"


def register_slack_scan_hook(hooks: ScanHooks, notifier: SlackNotifier):
    """Send each finished scan to ``notifier``; returns the unregister function.

    The plot screenshot is wanted only while Slack is on.  While Slack is off
    the notifier is not called at all, so a queued scan leaves no result for
    the queue-end message.  The notifier queues the message and returns at
    once.
    """

    def send(event: ScanFinished) -> None:
        if not notifier.active:
            return
        notifier.scan_finished(
            name=event.name,
            status=event.status,
            elapsed_seconds=event.elapsed_seconds,
            completed_points=event.completed_points,
            total_points=event.total_points,
            png=event.plot_png,
            error_message=event.error_message,
            queue_run=event.queue_run,
        )

    return hooks.register_scan_finished(
        send,
        wants_plot_png=lambda: bool(notifier.active),
        name=HOOK_NAME,
    )
