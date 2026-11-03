"""Text of every Slack message ZMeter sends.

Kept in one place so the wording is easy to change.  The emoji are Slack
codes; Slack shows them as icons.
"""

from __future__ import annotations

import datetime as _dt
from typing import Sequence

ICON_OK = ":white_check_mark:"
ICON_STOPPED = ":black_square_for_stop:"
ICON_PROBLEM = ":warning:"
ICON_BELL = ":bell:"

SEP = " · "
ERROR_LINE_LIMIT = 200

SCAN_STATUSES = ("completed", "stopped", "error")


def duration_text(seconds) -> str:
    """``1:42:10`` style; ``unknown`` when the time was not measured."""

    if seconds is None:
        return "unknown"
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def clock_text(when: _dt.datetime) -> str:
    return when.strftime("%H:%M")


def _count(number: int, word: str) -> str:
    return f"{number} {word}" if number == 1 else f"{number} {word}s"


def scan_text(
    *,
    status: str,
    name: str,
    elapsed_seconds,
    completed_points,
    total_points,
    ended: _dt.datetime,
    pc_name: str,
    error_message: str | None = None,
) -> str:
    """Message for a scan that ended (``completed``, ``stopped`` or ``error``)."""

    if status == "completed":
        head = f"{ICON_OK} Scan completed: {name}"
    elif status == "stopped":
        head = f"{ICON_STOPPED} Scan stopped: {name}"
    else:
        head = f"{ICON_PROBLEM} Scan error: {name}"
    lines = [
        head,
        SEP.join(
            (
                duration_text(elapsed_seconds),
                f"{completed_points}/{total_points} points",
                f"ended {clock_text(ended)}",
                pc_name,
            )
        ),
    ]
    if status == "error" and error_message:
        first = str(error_message).strip().splitlines()[0] if str(error_message).strip() else ""
        if first:
            if len(first) > ERROR_LINE_LIMIT:
                first = first[: ERROR_LINE_LIMIT - 3] + "..."
            lines.append(f"Error: {first}")
    return "\n".join(lines)


def notification_text(*, count: int, when: _dt.datetime, pc_name: str) -> str:
    """Message for writes to ``default_slack_notification``.

    ``count`` above 1 means several writes were merged by the burst guard.
    """

    title = "ZMeter notification" if count <= 1 else f"ZMeter notification ×{count}"
    return f"{ICON_BELL} {title}{SEP}{clock_text(when)}{SEP}{pc_name}"


def queue_text(
    *,
    reason: str,
    done: int,
    total: int,
    failed: Sequence[str],
    elapsed_seconds,
    pc_name: str,
    last_scan: tuple[str, str] | None = None,
) -> str:
    """Message for the end of a queue run.

    ``reason`` is the queue stop reason (``completed``,
    ``stop_after_current``, ``stop_requested`` or another word).
    ``last_scan`` is ``(name, status)`` of the last scan the queue ran.
    """

    failed = [str(item) for item in failed]
    failed_text = f"{len(failed)} failed"
    if reason == "completed":
        counts = f"{_count(done, 'item')}, {failed_text}"
        head = (
            f"{ICON_PROBLEM} Queue completed with failures"
            if failed
            else f"{ICON_OK} Queue completed"
        )
    else:
        if reason == "stop_requested":
            what = "Queue stopped by request"
        elif reason == "stop_after_current":
            what = "Queue stopped after current item"
        else:
            what = f"Queue stopped ({reason})"
        head = f"{ICON_STOPPED} {what}"
        counts = f"{done} of {_count(total, 'item')} done, {failed_text}"
    lines = [SEP.join((head, counts, duration_text(elapsed_seconds), pc_name))]
    if failed:
        lines.append("Failed: " + "; ".join(failed))
    if last_scan is not None:
        lines.append(f"Last scan: {last_scan[0]} ({last_scan[1]})")
    return "\n".join(lines)


def check_text(pc_name: str) -> str:
    return f"ZMeter test message from {pc_name}. Scan notifications will arrive here."
