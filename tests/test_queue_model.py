import threading
import unittest

from core.queue_model import (
    LiveQueueModel,
    QueueEntry,
    QueueItemState,
    QueueModelInvariantError,
)


class LiveQueueModelTests(unittest.TestCase):
    def setUp(self):
        self.model = LiveQueueModel()

    def test_ids_are_monotonic_and_terminal_entries_are_retained_until_forgotten(self):
        first_item = object()
        first = self.model.add_pending(first_item)
        self.assertIsInstance(first, QueueEntry)
        self.assertEqual(first.entry_id, 1)
        self.assertIs(self.model.entry_for_item(first_item), first)

        self.assertTrue(self.model.begin_run())
        self.assertIs(self.model.claim_next(), first)
        self.assertIs(self.model.finish_current(first.entry_id), first)
        self.assertIsNone(self.model.claim_next())
        self.assertEqual(self.model.run_stop_reason, "completed")
        self.assertEqual(first.state, QueueItemState.COMPLETED)
        self.assertIs(self.model.entry_for_item(first_item), first)

        with self.assertRaisesRegex(ValueError, "already retained"):
            self.model.add_pending(first_item)
        self.assertTrue(self.model.forget_terminal(first.entry_id))
        self.assertIsNone(self.model.entry_for_item(first_item))
        self.assertFalse(self.model.forget_terminal(first.entry_id))

        second = self.model.add_pending(first_item)
        self.assertEqual(second.entry_id, 2)

    def test_claimed_entry_is_current_and_ordered_before_pending(self):
        first = self.model.add_pending("first")
        second = self.model.add_pending("second")
        third = self.model.add_pending("third", index=1)

        self.assertEqual(
            [entry.item for entry in self.model.pending_entries()],
            ["first", "third", "second"],
        )
        self.assertEqual(self.model.pending_count, 3)
        self.assertTrue(self.model.begin_run())
        current = self.model.claim_next()

        self.assertIs(current, first)
        self.assertIs(self.model.current_entry, first)
        self.assertEqual(first.state, QueueItemState.CURRENT)
        self.assertFalse(self.model.can_edit(first.entry_id))
        self.assertEqual(
            [entry.item for entry in self.model.ordered_queue_entries()],
            ["first", "third", "second"],
        )
        with self.assertRaisesRegex(RuntimeError, "while one is current"):
            self.model.claim_next()

    def test_reorder_and_cancel_only_mutate_pending_entries(self):
        first = self.model.add_pending("first")
        second = self.model.add_pending("second")
        third = self.model.add_pending("third")

        self.assertTrue(self.model.reorder_pending(third.entry_id, 0))
        self.assertEqual(
            [entry.item for entry in self.model.pending_entries()],
            ["third", "first", "second"],
        )
        self.assertTrue(self.model.can_edit(first.entry_id))

        cancelled = self.model.cancel_pending(first.entry_id)
        self.assertIs(cancelled, first)
        self.assertEqual(first.state, QueueItemState.CANCELLED)
        self.assertFalse(self.model.can_edit(first.entry_id))
        self.assertIsNone(self.model.cancel_pending(first.entry_id))
        self.assertFalse(self.model.reorder_pending(first.entry_id, 0))
        self.assertEqual(
            [entry.item for entry in self.model.pending_entries()],
            ["third", "second"],
        )
        self.assertTrue(self.model.forget_terminal(first.entry_id))

    def test_live_add_remove_and_reorder_change_the_active_run(self):
        current = self.model.add_pending("A")
        removed = self.model.add_pending("B")
        original_tail = self.model.add_pending("D")
        self.assertTrue(self.model.begin_run())
        self.assertIs(self.model.claim_next(), current)

        added = self.model.add_pending("C")
        self.assertIs(self.model.cancel_pending(removed.entry_id), removed)
        self.assertTrue(self.model.reorder_pending(added.entry_id, 0))
        self.assertEqual(
            [entry.item for entry in self.model.ordered_queue_entries()],
            ["A", "C", "D"],
        )

        self.model.finish_current(current.entry_id)
        self.assertIs(self.model.claim_next(), added)
        self.model.finish_current(added.entry_id)
        self.assertIs(self.model.claim_next(), original_tail)
        self.model.finish_current(original_tail.entry_id)
        self.assertIsNone(self.model.claim_next())
        self.assertEqual(self.model.run_stop_reason, "completed")

    def test_visible_queue_insert_and_reorder_translate_under_the_model_lock(self):
        current = self.model.add_pending("A")
        second = self.model.add_pending("B")
        third = self.model.add_pending("C")
        self.assertTrue(self.model.begin_run())
        self.assertIs(self.model.claim_next(), current)

        inserted = self.model.add_pending_at_queue_index("D", 1)
        self.assertEqual(
            [entry.item for entry in self.model.ordered_queue_entries()],
            ["A", "D", "B", "C"],
        )
        self.assertTrue(
            self.model.reorder_pending_at_queue_indices(
                third.entry_id,
                origin_queue_index=3,
                drop_queue_index=1,
            )
        )
        self.assertEqual(
            [entry.item for entry in self.model.ordered_queue_entries()],
            ["A", "C", "D", "B"],
        )
        self.assertEqual(inserted.item, "D")

    def test_claim_winning_reorder_boundary_is_clamped_without_stale_index_error(self):
        first = self.model.add_pending("A")
        second = self.model.add_pending("B")
        third = self.model.add_pending("C")
        fourth = self.model.add_pending("D")
        self.assertTrue(self.model.begin_run())
        self.assertIs(self.model.claim_next(), first)
        self.model.finish_current(first.entry_id)

        # This claim wins the boundary race.  The drag indices still describe
        # the old A/B/C/D layout observed by the GUI.
        self.assertIs(self.model.claim_next(), second)
        self.assertTrue(
            self.model.reorder_pending_at_queue_indices(
                fourth.entry_id,
                origin_queue_index=3,
                drop_queue_index=1,
            )
        )
        self.assertEqual(
            [entry.item for entry in self.model.ordered_queue_entries()],
            ["B", "D", "C"],
        )
        self.assertFalse(
            self.model.reorder_pending_at_queue_indices(
                second.entry_id,
                origin_queue_index=1,
                drop_queue_index=3,
            )
        )
        self.assertIs(third.state, QueueItemState.PENDING)

    def test_pending_update_and_claim_are_atomic(self):
        item = {"value": 1.0}
        entry = self.model.add_pending(item)
        self.assertTrue(self.model.begin_run())
        operation_entered = threading.Event()
        release_operation = threading.Event()
        claim_finished = threading.Event()
        outcomes = {}

        def update_value(_entry):
            operation_entered.set()
            if not release_operation.wait(1.0):
                outcomes["operation_timed_out"] = True
                return
            item["value"] = 2.0

        def commit_pending_value():
            outcomes["committed"] = self.model.apply_if_pending(
                entry.entry_id,
                update_value,
            )

        def claim_item():
            outcomes["claimed"] = self.model.claim_next()
            outcomes["claimed_value"] = item["value"]
            claim_finished.set()

        commit_thread = threading.Thread(target=commit_pending_value)
        claim_thread = threading.Thread(target=claim_item)
        commit_thread.start()
        self.assertTrue(operation_entered.wait(1.0))
        claim_thread.start()
        self.assertFalse(claim_finished.wait(0.05))
        release_operation.set()
        commit_thread.join(1.0)
        claim_thread.join(1.0)

        self.assertFalse(commit_thread.is_alive())
        self.assertFalse(claim_thread.is_alive())
        self.assertNotIn("operation_timed_out", outcomes)
        self.assertTrue(outcomes["committed"])
        self.assertIs(outcomes["claimed"], entry)
        self.assertEqual(outcomes["claimed_value"], 2.0)
        self.assertFalse(
            self.model.apply_if_pending(
                entry.entry_id,
                lambda _entry: item.update(value=3.0),
            )
        )
        self.assertEqual(item["value"], 2.0)

    def test_current_and_terminal_entries_cannot_be_cancelled_reordered_or_edited(self):
        entry = self.model.add_pending(object())
        self.assertTrue(self.model.begin_run())
        self.assertIs(self.model.claim_next(), entry)

        self.assertIsNone(self.model.cancel_pending(entry.entry_id))
        self.assertFalse(self.model.reorder_pending(entry.entry_id, 0))
        self.assertFalse(self.model.can_edit(entry.entry_id))
        self.assertFalse(self.model.forget_terminal(entry.entry_id))

        self.model.finish_current(entry.entry_id)
        self.assertFalse(self.model.can_edit(entry.entry_id))
        self.assertIsNone(self.model.cancel_pending(entry.entry_id))
        self.assertFalse(self.model.reorder_pending(entry.entry_id, 0))

    def test_stop_now_preserves_unstarted_entries_for_a_later_run(self):
        first = self.model.add_pending("first")
        second = self.model.add_pending("second")
        third = self.model.add_pending("third")

        self.assertTrue(self.model.begin_run())
        self.assertIs(self.model.claim_next(), first)
        self.assertTrue(self.model.request_stop_now())
        self.assertTrue(self.model.stop_now_requested)
        self.assertFalse(self.model.stop_after_current_requested)
        self.model.finish_current(first.entry_id)
        self.assertIsNone(self.model.claim_next())

        self.assertFalse(self.model.is_run_active)
        self.assertFalse(self.model.stop_now_requested)
        self.assertEqual(self.model.run_stop_reason, "stop_requested")
        self.assertEqual(
            [entry.item for entry in self.model.pending_entries()],
            ["second", "third"],
        )

        self.assertTrue(self.model.begin_run())
        self.assertIsNone(self.model.run_stop_reason)
        self.assertIs(self.model.claim_next(), second)
        self.model.finish_current(second.entry_id)
        self.assertIs(self.model.claim_next(), third)
        self.model.finish_current(third.entry_id)
        self.assertIsNone(self.model.claim_next())
        self.assertEqual(self.model.run_stop_reason, "completed")

    def test_stop_now_before_first_claim_preserves_every_entry(self):
        entries = [self.model.add_pending(name) for name in ("a", "b")]
        self.assertTrue(self.model.begin_run())
        self.assertTrue(self.model.request_stop_now())

        self.assertIsNone(self.model.claim_next())
        self.assertEqual(self.model.run_stop_reason, "stop_requested")
        self.assertEqual(self.model.pending_entries(), tuple(entries))

    def test_stop_after_current_requested_before_first_claim_runs_one_item(self):
        first = self.model.add_pending("first")
        second = self.model.add_pending("second")
        self.assertTrue(self.model.begin_run())
        self.assertTrue(self.model.request_stop_after_current())
        self.assertTrue(self.model.stop_after_current_requested)

        self.assertIs(self.model.claim_next(), first)
        self.model.finish_current(first.entry_id)
        self.assertIsNone(self.model.claim_next())
        self.assertEqual(self.model.run_stop_reason, "stop_after_current")
        self.assertEqual(self.model.pending_entries(), (second,))

    def test_stop_now_takes_precedence_over_stop_after_current(self):
        self.model.add_pending("first")
        self.assertTrue(self.model.begin_run())
        self.assertTrue(self.model.request_stop_after_current())
        self.assertTrue(self.model.request_stop_now())
        self.assertFalse(self.model.request_stop_after_current())

        self.assertIsNone(self.model.claim_next())
        self.assertEqual(self.model.run_stop_reason, "stop_requested")

    def test_failed_current_retains_error_and_later_items_can_continue(self):
        first = self.model.add_pending("first")
        second = self.model.add_pending("second")
        self.assertTrue(self.model.begin_run())
        self.assertIs(self.model.claim_next(), first)

        failed = self.model.finish_current(
            first.entry_id,
            failed=True,
            error_message="RuntimeError: injected failure",
        )
        self.assertEqual(failed.state, QueueItemState.FAILED)
        self.assertEqual(failed.error_message, "RuntimeError: injected failure")
        self.assertIs(self.model.claim_next(), second)
        self.model.finish_current(second.entry_id)
        self.assertIsNone(self.model.claim_next())
        self.assertEqual(self.model.run_stop_reason, "completed")

    def test_add_before_empty_claim_joins_current_run(self):
        first = self.model.add_pending("first")
        self.assertTrue(self.model.begin_run())
        self.assertIs(self.model.claim_next(), first)
        self.model.finish_current(first.entry_id)

        added = self.model.add_pending("added-before-close")
        self.assertIs(self.model.claim_next(), added)
        self.model.finish_current(added.entry_id)
        self.assertIsNone(self.model.claim_next())
        self.assertEqual(self.model.run_stop_reason, "completed")

    def test_add_after_empty_claim_stays_pending_for_next_explicit_run(self):
        first = self.model.add_pending("first")
        self.assertTrue(self.model.begin_run())
        self.assertIs(self.model.claim_next(), first)
        self.model.finish_current(first.entry_id)
        self.assertIsNone(self.model.claim_next())

        added = self.model.add_pending("added-after-close")
        self.assertFalse(self.model.is_run_active)
        self.assertEqual(self.model.pending_entries(), (added,))
        self.assertEqual(self.model.run_stop_reason, "completed")
        self.assertTrue(self.model.begin_run())
        self.assertIs(self.model.claim_next(), added)

    def test_concurrent_final_add_and_empty_claim_are_linearizable(self):
        for iteration in range(100):
            model = LiveQueueModel()
            initial = model.add_pending(("initial", iteration))
            self.assertTrue(model.begin_run())
            self.assertIs(model.claim_next(), initial)
            model.finish_current(initial.entry_id)

            gate = threading.Barrier(3)
            outcomes = {}

            def add_final():
                gate.wait()
                outcomes["added"] = model.add_pending(("added", iteration))

            def claim_empty():
                gate.wait()
                outcomes["claimed"] = model.claim_next()

            add_thread = threading.Thread(target=add_final)
            claim_thread = threading.Thread(target=claim_empty)
            add_thread.start()
            claim_thread.start()
            gate.wait()
            add_thread.join(1)
            claim_thread.join(1)
            self.assertFalse(add_thread.is_alive())
            self.assertFalse(claim_thread.is_alive())

            added = outcomes["added"]
            claimed = outcomes["claimed"]
            if claimed is None:
                self.assertFalse(model.is_run_active)
                self.assertEqual(model.pending_entries(), (added,))
            else:
                self.assertIs(claimed, added)
                self.assertTrue(model.is_run_active)
                self.assertEqual(model.pending_entries(), ())
                model.finish_current(added.entry_id)
                self.assertIsNone(model.claim_next())

    def test_invalid_transitions_and_indices_raise_clear_errors(self):
        with self.assertRaisesRegex(RuntimeError, "without an active"):
            self.model.claim_next()
        self.assertFalse(self.model.begin_run())
        self.assertIsNone(self.model.run_stop_reason)
        self.assertFalse(self.model.request_stop_now())
        self.assertFalse(self.model.request_stop_after_current())

        entry = self.model.add_pending("entry")
        with self.assertRaises(TypeError):
            self.model.add_pending("other", index=True)
        with self.assertRaises(TypeError):
            self.model.add_pending_at_queue_index("other", True)
        with self.assertRaises(TypeError):
            self.model.reorder_pending_at_queue_indices(
                entry.entry_id,
                origin_queue_index=0,
                drop_queue_index=1.5,
            )
        with self.assertRaises(TypeError):
            self.model.apply_if_pending(entry.entry_id, None)
        with self.assertRaises(IndexError):
            self.model.reorder_pending(entry.entry_id, 1)
        with self.assertRaises(IndexError):
            self.model.reorder_pending(entry.entry_id, -1)

        self.assertTrue(self.model.begin_run())
        with self.assertRaisesRegex(RuntimeError, "already active"):
            self.model.begin_run()
        self.assertIs(self.model.claim_next(), entry)
        with self.assertRaisesRegex(RuntimeError, "not the current"):
            self.model.finish_current(entry.entry_id + 1)
        with self.assertRaisesRegex(ValueError, "cannot retain an error"):
            self.model.finish_current(entry.entry_id, error_message="unexpected")

    def test_invariant_corruption_is_detected_before_further_mutation(self):
        entry = self.model.add_pending("entry")
        entry.state = QueueItemState.COMPLETED

        with self.assertRaises(QueueModelInvariantError):
            self.model.pending_entries()
        with self.assertRaises(QueueModelInvariantError):
            self.model.add_pending("other")


if __name__ == "__main__":
    unittest.main()
