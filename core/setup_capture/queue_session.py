"""One questionnaire for a whole queue.

When the queue's Questionnaire box is checked, starting the queue opens a
non-modal pop-up.  A worker takes one instrument snapshot and asks the model
for one questionnaire covering every queued scan and manual-set step.  The
queue does not wait.  On Submit every scan in the queue receives its own
copy of the answers:

* scans that have not saved yet keep the copy in their scan file;
* scans that already saved get a ``NNNN_name.setup.json`` file beside it;
* scans added to the queue after Submit get a copy marked as added later.

While a queue questionnaire is active the scans in that queue skip their
own per-scan model call.
"""

from __future__ import annotations

import copy
import datetime as _dt
import time
from typing import Callable, Iterable

from . import questionnaire as qn
from .runtime import SKIP_OTHER_SCAN, SnapshotRun, data_folder
from .widgets import QueueQuestionnaireDialog

FIRST_SCAN_SNAPSHOT_WAIT_S = 10.0


def queue_plan(items: Iterable[object]) -> list[dict]:
    """Model-readable run order: scans and manual-set steps."""

    plan = []
    for item in items:
        scan = getattr(item, "scan", None)
        if scan is not None:
            snapshot_info = getattr(item, "snapshot_info", None)
            info = snapshot_info() if callable(snapshot_info) else scan.info
            plan.append({"type": "scan", **qn.summarize_scan(info)})
            continue
        channel = getattr(item, "channel_name", None)
        if channel:
            value_text = getattr(item, "value_text", None)
            plan.append(
                {
                    "type": "manual_set",
                    "channel": channel,
                    "value": value_text() if callable(value_text) else None,
                }
            )
    return plan


def merge_busy_devices(queue_snapshot: dict, scan_snapshot: dict | None) -> dict:
    """Fill devices the queue snapshot could not read (in use by the first
    scan) from that scan's own start snapshot."""

    if not isinstance(scan_snapshot, dict):
        return queue_snapshot
    merged = copy.deepcopy(queue_snapshot)
    scan_devices = scan_snapshot.get("devices", {}) or {}
    for device_id, entry in (merged.get("devices", {}) or {}).items():
        if entry.get("skipped") == SKIP_OTHER_SCAN and device_id in scan_devices:
            replacement = copy.deepcopy(scan_devices[device_id])
            replacement["from_scan_start_snapshot"] = True
            merged["devices"][device_id] = replacement
    return merged


def _new_queue_id() -> str:
    return "queue_" + _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


class QueueQuestionnaireSession:
    def __init__(self, scanlist, controller, items: list[object]):
        self.scanlist = scanlist
        self.controller = controller
        self.queue_id = _new_queue_id()
        self.items = list(items)
        self.scans = [item.scan for item in self.items if getattr(item, "scan", None) is not None]
        self.queue_running = True
        self.submitted_record: dict | None = None
        self.meta: dict | None = None
        self.snapshot: dict | None = None
        self.dialog: QueueQuestionnaireDialog | None = None
        self.main_window = None
        self._runs_at_start = {}
        for scan in self.scans:
            self._mark(scan)

    def _mark(self, scan) -> None:
        scan.queue_questionnaire_active = True
        self._runs_at_start[id(scan)] = int(getattr(scan, "setup_run_count", 0))

    def _saved_during_queue(self, scan) -> bool:
        """True when the scan ran and saved after this session began."""

        ran = int(getattr(scan, "setup_run_count", 0)) > self._runs_at_start.get(id(scan), 0)
        return ran and bool(getattr(scan, "_saved_this_run", False)) and not scan.logic.isRunning()

    # ------------------------------------------------------------- start --
    def start(self, main_window) -> None:
        self.main_window = main_window
        self.dialog = QueueQuestionnaireDialog(parent=None)
        self.dialog.setWindowTitle(f"Queue questionnaire ({len(self.scans)} scans)")
        self.dialog.sig_submitted.connect(self.submit)
        self.dialog.show()

        plan = copy.deepcopy(queue_plan(self.items))
        run = SnapshotRun(main_window, (), None, scan_key=self.queue_id, lab_folder=self.controller.lab_folder)
        first_scan = self.scans[0] if self.scans else None

        def first_scan_snapshot() -> dict | None:
            if first_scan is None:
                return None
            deadline = time.monotonic() + FIRST_SCAN_SNAPSHOT_WAIT_S
            while time.monotonic() < deadline:
                setup = first_scan.info.get("setup")
                if isinstance(setup, dict) and setup.get("snapshot_start"):
                    return setup["snapshot_start"]
                time.sleep(0.2)
            return None

        def snapshot_job() -> dict:
            taken = run.take()
            return merge_busy_devices(taken, first_scan_snapshot())

        self.controller.generate_async(
            mode="queue",
            plan=plan,
            snapshot=None,
            previous_items=self.controller.previous_items_for([]),
            callback=self._on_record,
            snapshot_job=snapshot_job,
        )

    def _on_record(self, record: dict) -> None:
        self.snapshot = record.pop("snapshot", None)
        try:
            qn.save_model_output(record, data_folder(self.main_window), self.queue_id)
        except Exception:  # noqa: BLE001 - a review copy must never break the queue
            record.pop(qn.DEBUG_KEY, None)
        try:
            if self.dialog is not None:
                self.dialog.set_record(record)
        except RuntimeError:
            pass

    # ------------------------------------------------------------ submit --
    def submit(self, record: dict) -> None:
        self.submitted_record = record
        self.meta = {
            "queue_id": self.queue_id,
            "submitted_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "questions": copy.deepcopy(record.get("items") or []),
            "inferences": copy.deepcopy(record.get("inferences") or []),
            "snapshot": copy.deepcopy(self.snapshot),
            "scans": [str(scan.info.get("name", "")) for scan in self.scans],
        }
        self.controller.remember_answers(record.get("items") or [])
        for scan in self.scans:
            self._apply(scan, added_after_submit=False)

    def _apply(self, scan, *, added_after_submit: bool) -> None:
        meta = dict(self.meta)
        if added_after_submit:
            meta["added_after_submit"] = True
        try:
            already_saved = self._saved_during_queue(scan)
            scan.apply_queue_questionnaire(
                self.submitted_record, meta, write_sidecar=already_saved
            )
        except RuntimeError:
            pass  # scan window was deleted

    # ------------------------------------------------------- queue events --
    def item_added(self, item: object) -> None:
        scan = getattr(item, "scan", None)
        if scan is None or not self.queue_running or scan in self.scans:
            return
        self.scans.append(scan)
        self._mark(scan)
        if self.submitted_record is not None:
            self._apply(scan, added_after_submit=True)

    def queue_finished(self) -> None:
        self.queue_running = False
        for scan in self.scans:
            try:
                scan.queue_questionnaire_active = False
            except RuntimeError:
                pass

    @property
    def finished(self) -> bool:
        """True when nothing more can happen in this session."""

        if self.queue_running:
            return False
        if self.submitted_record is not None:
            return True
        try:
            return self.dialog is None or not self.dialog.isVisible()
        except RuntimeError:
            return True
