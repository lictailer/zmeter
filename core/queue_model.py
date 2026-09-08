"""Thread-safe live queue state independent of Qt widgets and threads."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import RLock


class QueueItemState(Enum):
    """Lifecycle state for one item retained by :class:`LiveQueueModel`."""

    PENDING = "pending"
    CURRENT = "current"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class QueueEntry:
    """Stable queue identity plus its current lifecycle state."""

    entry_id: int
    item: object
    state: QueueItemState
    error_message: str = ""


class QueueModelInvariantError(RuntimeError):
    """Raised when retained queue state no longer satisfies model invariants."""


class LiveQueueModel:
    """One authoritative, thread-safe queue with live pending mutation.

    A run claims pending entries one at a time. Entries added before an atomic
    empty claim are visible to that run; entries added after the empty claim
    remain pending for the next explicit run. Terminal entries stay available
    for UI history until :meth:`forget_terminal` is called.
    """

    COMPLETED_REASON = "completed"
    STOP_REQUESTED_REASON = "stop_requested"
    STOP_AFTER_CURRENT_REASON = "stop_after_current"
    _STOP_REASONS = frozenset(
        {
            COMPLETED_REASON,
            STOP_REQUESTED_REASON,
            STOP_AFTER_CURRENT_REASON,
        }
    )
    _TERMINAL_STATES = frozenset(
        {
            QueueItemState.COMPLETED,
            QueueItemState.FAILED,
            QueueItemState.CANCELLED,
        }
    )

    def __init__(self) -> None:
        self._lock = RLock()
        self._next_entry_id = 1
        self._entries: dict[int, QueueEntry] = {}
        self._entry_id_by_item_identity: dict[int, int] = {}
        self._pending_ids: list[int] = []
        self._current_id: int | None = None
        self._run_active = False
        self._stop_now_requested = False
        self._stop_after_current_requested = False
        self._claimed_in_run = 0
        self._run_stop_reason: str | None = None

    def add_pending(self, item: object, index: int | None = None) -> QueueEntry:
        """Add one new pending item at a zero-based pending-list index."""

        with self._lock:
            self._assert_invariants_locked()
            if self._entry_for_item_locked(item) is not None:
                raise ValueError("queue item is already retained by this model")

            if index is None:
                insert_index = len(self._pending_ids)
            else:
                insert_index = self._validate_index(
                    index,
                    upper_bound=len(self._pending_ids),
                    allow_endpoint=True,
                    name="pending insertion index",
                )

            entry = QueueEntry(
                entry_id=self._next_entry_id,
                item=item,
                state=QueueItemState.PENDING,
            )
            self._next_entry_id += 1
            self._entries[entry.entry_id] = entry
            self._entry_id_by_item_identity[id(item)] = entry.entry_id
            self._pending_ids.insert(insert_index, entry.entry_id)
            self._assert_invariants_locked()
            return entry

    def add_pending_at_queue_index(
        self,
        item: object,
        queue_index: int,
    ) -> QueueEntry:
        """Insert at a clamped visible queue index under one model lock.

        The visible queue consists of the current entry, when present,
        followed by pending entries.  Computing that offset and committing the
        insertion under the same lock prevents a claim at an item boundary from
        invalidating a drag/drop index.
        """

        if isinstance(queue_index, bool) or not isinstance(queue_index, int):
            raise TypeError("queue insertion index must be an integer")
        with self._lock:
            self._assert_invariants_locked()
            current_offset = 1 if self._current_id is not None else 0
            pending_index = max(
                0,
                min(len(self._pending_ids), queue_index - current_offset),
            )
            return self.add_pending(item, index=pending_index)

    def entry_for_item(self, item: object) -> QueueEntry | None:
        """Return the retained entry for the exact object identity, if any."""

        with self._lock:
            self._assert_invariants_locked()
            return self._entry_for_item_locked(item)

    def pending_entries(self) -> tuple[QueueEntry, ...]:
        """Return pending entries in their authoritative execution order."""

        with self._lock:
            self._assert_invariants_locked()
            return tuple(self._entries[entry_id] for entry_id in self._pending_ids)

    def ordered_queue_entries(self) -> tuple[QueueEntry, ...]:
        """Return the current entry first, followed by ordered pending entries."""

        with self._lock:
            self._assert_invariants_locked()
            ordered: list[QueueEntry] = []
            if self._current_id is not None:
                ordered.append(self._entries[self._current_id])
            ordered.extend(self._entries[entry_id] for entry_id in self._pending_ids)
            return tuple(ordered)

    @property
    def pending_count(self) -> int:
        with self._lock:
            self._assert_invariants_locked()
            return len(self._pending_ids)

    @property
    def current_entry(self) -> QueueEntry | None:
        with self._lock:
            self._assert_invariants_locked()
            if self._current_id is None:
                return None
            return self._entries[self._current_id]

    @property
    def is_run_active(self) -> bool:
        with self._lock:
            self._assert_invariants_locked()
            return self._run_active

    @property
    def stop_now_requested(self) -> bool:
        with self._lock:
            self._assert_invariants_locked()
            return self._stop_now_requested

    @property
    def stop_after_current_requested(self) -> bool:
        with self._lock:
            self._assert_invariants_locked()
            return self._stop_after_current_requested

    @property
    def run_stop_reason(self) -> str | None:
        with self._lock:
            self._assert_invariants_locked()
            return self._run_stop_reason

    def begin_run(self) -> bool:
        """Begin a run when pending work exists, resetting prior run controls."""

        with self._lock:
            self._assert_invariants_locked()
            if self._run_active:
                raise RuntimeError("queue run is already active")
            if self._current_id is not None:
                raise QueueModelInvariantError(
                    "inactive queue unexpectedly retains a current entry"
                )

            self._stop_now_requested = False
            self._stop_after_current_requested = False
            self._claimed_in_run = 0
            self._run_stop_reason = None
            if not self._pending_ids:
                self._assert_invariants_locked()
                return False

            self._run_active = True
            self._assert_invariants_locked()
            return True

    def request_stop_now(self) -> bool:
        """Request closure before the next claim, preserving pending entries."""

        with self._lock:
            self._assert_invariants_locked()
            if not self._run_active:
                return False
            self._stop_now_requested = True
            self._stop_after_current_requested = False
            self._assert_invariants_locked()
            return True

    def request_stop_after_current(self) -> bool:
        """Request one current/next item, then close before another claim."""

        with self._lock:
            self._assert_invariants_locked()
            if not self._run_active or self._stop_now_requested:
                return False
            self._stop_after_current_requested = True
            self._assert_invariants_locked()
            return True

    def claim_next(self) -> QueueEntry | None:
        """Claim the next pending entry or atomically close the active run."""

        with self._lock:
            self._assert_invariants_locked()
            if not self._run_active:
                raise RuntimeError("cannot claim an item without an active queue run")
            if self._current_id is not None:
                raise RuntimeError("cannot claim another item while one is current")

            if self._stop_now_requested:
                self._close_run_locked(self.STOP_REQUESTED_REASON)
                self._assert_invariants_locked()
                return None
            if self._stop_after_current_requested and self._claimed_in_run > 0:
                self._close_run_locked(self.STOP_AFTER_CURRENT_REASON)
                self._assert_invariants_locked()
                return None
            if not self._pending_ids:
                self._close_run_locked(self.COMPLETED_REASON)
                self._assert_invariants_locked()
                return None

            entry_id = self._pending_ids.pop(0)
            entry = self._entries[entry_id]
            if entry.state is not QueueItemState.PENDING:
                raise QueueModelInvariantError(
                    f"pending entry {entry_id} has state {entry.state!r}"
                )
            entry.state = QueueItemState.CURRENT
            entry.error_message = ""
            self._current_id = entry_id
            self._claimed_in_run += 1
            self._assert_invariants_locked()
            return entry

    def finish_current(
        self,
        entry_id: int,
        failed: bool = False,
        error_message: str = "",
    ) -> QueueEntry:
        """Move the exact current entry to a completed or failed state."""

        with self._lock:
            self._assert_invariants_locked()
            if not self._run_active:
                raise RuntimeError("cannot finish an item without an active queue run")
            if self._current_id is None:
                raise RuntimeError("queue run has no current item to finish")
            if entry_id != self._current_id:
                raise RuntimeError(
                    f"entry {entry_id} is not the current queue entry "
                    f"{self._current_id}"
                )

            failed = bool(failed)
            normalized_error = "" if error_message is None else str(error_message)
            if not failed and normalized_error:
                raise ValueError(
                    "a successful queue entry cannot retain an error message"
                )

            entry = self._entries[entry_id]
            if entry.state is not QueueItemState.CURRENT:
                raise QueueModelInvariantError(
                    f"current entry {entry_id} has state {entry.state!r}"
                )
            entry.state = (
                QueueItemState.FAILED if failed else QueueItemState.COMPLETED
            )
            entry.error_message = normalized_error if failed else ""
            self._current_id = None
            self._assert_invariants_locked()
            return entry

    def cancel_pending(self, entry_id: int) -> QueueEntry | None:
        """Cancel and retain one pending entry, or return ``None`` if ineligible."""

        with self._lock:
            self._assert_invariants_locked()
            entry = self._entries.get(entry_id)
            if entry is None or entry.state is not QueueItemState.PENDING:
                return None

            try:
                self._pending_ids.remove(entry_id)
            except ValueError as exc:
                raise QueueModelInvariantError(
                    f"pending entry {entry_id} is absent from pending order"
                ) from exc
            entry.state = QueueItemState.CANCELLED
            entry.error_message = ""
            self._assert_invariants_locked()
            return entry

    def reorder_pending(self, entry_id: int, new_index: int) -> bool:
        """Move one pending entry to a zero-based index among pending entries."""

        with self._lock:
            self._assert_invariants_locked()
            entry = self._entries.get(entry_id)
            if entry is None or entry.state is not QueueItemState.PENDING:
                return False

            target_index = self._validate_index(
                new_index,
                upper_bound=len(self._pending_ids) - 1,
                allow_endpoint=True,
                name="pending reorder index",
            )
            old_index = self._pending_ids.index(entry_id)
            if old_index != target_index:
                self._pending_ids.pop(old_index)
                self._pending_ids.insert(target_index, entry_id)
            self._assert_invariants_locked()
            return True

    def reorder_pending_at_queue_indices(
        self,
        entry_id: int,
        origin_queue_index: int,
        drop_queue_index: int,
    ) -> bool:
        """Reorder from visible drag indices under one model lock.

        Qt reports a drop position in the pre-removal visible layout.  The
        visible queue consists of the current entry, when present, followed by
        pending entries.  Rechecking eligibility, translating the drop index,
        and committing the reorder under the same lock prevents an item-boundary
        claim from invalidating a previously observed pending-list length.
        """

        for value, name in (
            (origin_queue_index, "queue reorder origin index"),
            (drop_queue_index, "queue reorder drop index"),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")

        with self._lock:
            self._assert_invariants_locked()
            entry = self._entries.get(entry_id)
            if entry is None or entry.state is not QueueItemState.PENDING:
                return False

            current_offset = 1 if self._current_id is not None else 0
            target_queue_index = drop_queue_index
            if origin_queue_index < target_queue_index:
                target_queue_index -= 1
            target_queue_index = max(
                current_offset,
                min(
                    current_offset + len(self._pending_ids) - 1,
                    target_queue_index,
                ),
            )
            target_pending_index = target_queue_index - current_offset
            old_pending_index = self._pending_ids.index(entry_id)
            if old_pending_index != target_pending_index:
                self._pending_ids.pop(old_pending_index)
                self._pending_ids.insert(target_pending_index, entry_id)
            self._assert_invariants_locked()
            return True

    def apply_if_pending(self, entry_id: int, operation) -> bool:
        """Apply a short item update only while the entry is still pending.

        The operation and :meth:`claim_next` share the model lock, so either
        the edit commits before the immutable work item is claimed or the edit
        is rejected.  The callback must not block or call user/device code.
        """

        if not callable(operation):
            raise TypeError("pending-entry operation must be callable")
        with self._lock:
            self._assert_invariants_locked()
            entry = self._entries.get(entry_id)
            if entry is None or entry.state is not QueueItemState.PENDING:
                return False
            operation(entry)
            self._assert_invariants_locked()
            return True

    def can_edit(self, entry_id: int) -> bool:
        """Return whether an entry is still pending and therefore editable."""

        with self._lock:
            self._assert_invariants_locked()
            entry = self._entries.get(entry_id)
            return entry is not None and entry.state is QueueItemState.PENDING

    def forget_terminal(self, entry_id: int) -> bool:
        """Forget a completed, failed, or cancelled entry."""

        with self._lock:
            self._assert_invariants_locked()
            entry = self._entries.get(entry_id)
            if entry is None or entry.state not in self._TERMINAL_STATES:
                return False

            del self._entries[entry_id]
            item_identity = id(entry.item)
            retained_id = self._entry_id_by_item_identity.get(item_identity)
            if retained_id != entry_id:
                raise QueueModelInvariantError(
                    f"entry {entry_id} has an inconsistent item identity index"
                )
            del self._entry_id_by_item_identity[item_identity]
            self._assert_invariants_locked()
            return True

    @staticmethod
    def _validate_index(
        index: int,
        *,
        upper_bound: int,
        allow_endpoint: bool,
        name: str,
    ) -> int:
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError(f"{name} must be an integer")
        maximum = upper_bound if allow_endpoint else upper_bound - 1
        if index < 0 or index > maximum:
            raise IndexError(f"{name} {index} is outside [0, {maximum}]")
        return index

    def _entry_for_item_locked(self, item: object) -> QueueEntry | None:
        entry_id = self._entry_id_by_item_identity.get(id(item))
        if entry_id is None:
            return None
        entry = self._entries.get(entry_id)
        if entry is None or entry.item is not item:
            raise QueueModelInvariantError("item identity index is inconsistent")
        return entry

    def _close_run_locked(self, reason: str) -> None:
        if reason not in self._STOP_REASONS:
            raise ValueError(f"unknown queue stop reason: {reason!r}")
        if self._current_id is not None:
            raise RuntimeError("cannot close a queue run while an item is current")
        self._run_active = False
        self._stop_now_requested = False
        self._stop_after_current_requested = False
        self._claimed_in_run = 0
        self._run_stop_reason = reason

    def _assert_invariants_locked(self) -> None:
        entry_ids = set(self._entries)
        if self._next_entry_id < 1 or any(
            entry_id >= self._next_entry_id for entry_id in entry_ids
        ):
            raise QueueModelInvariantError("queue entry IDs are not monotonic")

        if len(self._pending_ids) != len(set(self._pending_ids)):
            raise QueueModelInvariantError("pending queue contains duplicate IDs")
        unknown_pending = set(self._pending_ids).difference(entry_ids)
        if unknown_pending:
            raise QueueModelInvariantError(
                f"pending queue contains unknown IDs: {sorted(unknown_pending)}"
            )

        pending_state_ids = {
            entry_id
            for entry_id, entry in self._entries.items()
            if entry.state is QueueItemState.PENDING
        }
        if pending_state_ids != set(self._pending_ids):
            raise QueueModelInvariantError(
                "pending entry states do not match pending execution order"
            )

        current_state_ids = {
            entry_id
            for entry_id, entry in self._entries.items()
            if entry.state is QueueItemState.CURRENT
        }
        expected_current_ids = (
            set() if self._current_id is None else {self._current_id}
        )
        if current_state_ids != expected_current_ids:
            raise QueueModelInvariantError(
                "current entry state does not match the current queue ID"
            )
        if self._current_id is not None:
            if self._current_id not in entry_ids:
                raise QueueModelInvariantError("current queue ID is unknown")
            if not self._run_active:
                raise QueueModelInvariantError(
                    "inactive queue cannot retain a current entry"
                )

        item_identity_ids: dict[int, int] = {}
        for entry_id, entry in self._entries.items():
            if entry.entry_id != entry_id:
                raise QueueModelInvariantError(
                    f"entry key {entry_id} disagrees with entry ID {entry.entry_id}"
                )
            if not isinstance(entry.state, QueueItemState):
                raise QueueModelInvariantError(
                    f"entry {entry_id} has invalid state {entry.state!r}"
                )
            item_identity = id(entry.item)
            if item_identity in item_identity_ids:
                raise QueueModelInvariantError(
                    "the same item object is retained by multiple queue entries"
                )
            item_identity_ids[item_identity] = entry_id
            if entry.state in {
                QueueItemState.PENDING,
                QueueItemState.CURRENT,
                QueueItemState.COMPLETED,
                QueueItemState.CANCELLED,
            } and entry.error_message:
                raise QueueModelInvariantError(
                    f"non-failed entry {entry_id} retains an error message"
                )

        if item_identity_ids != self._entry_id_by_item_identity:
            raise QueueModelInvariantError("item identity index does not match entries")

        if self._run_active:
            if self._run_stop_reason is not None:
                raise QueueModelInvariantError(
                    "active queue run cannot have a terminal stop reason"
                )
        else:
            if self._current_id is not None:
                raise QueueModelInvariantError(
                    "inactive queue cannot retain a current entry"
                )
            if self._stop_now_requested or self._stop_after_current_requested:
                raise QueueModelInvariantError(
                    "inactive queue cannot retain stop-request flags"
                )
            if self._claimed_in_run != 0:
                raise QueueModelInvariantError(
                    "inactive queue cannot retain an in-progress claim count"
                )
            if (
                self._run_stop_reason is not None
                and self._run_stop_reason not in self._STOP_REASONS
            ):
                raise QueueModelInvariantError(
                    f"invalid queue stop reason {self._run_stop_reason!r}"
                )
