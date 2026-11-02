import unittest

from core.channel_value_record import (
    ORIGIN_READ,
    ORIGIN_SNAPSHOT,
    ORIGIN_WRITE,
    ChannelValueRecord,
)


class ChannelValueRecordTests(unittest.TestCase):
    def test_latest_write_and_reading_are_kept_apart(self):
        record = ChannelValueRecord()
        record.record_write("dev_x", 1)
        record.record_read("dev_x", 1.5)
        self.assertEqual(record.latest("dev_x").value, 1.5)
        self.assertEqual(record.latest("dev_x").origin, ORIGIN_READ)
        self.assertEqual(record.latest_write("dev_x").value, 1.0)
        self.assertEqual(record.latest_write("dev_x").origin, ORIGIN_WRITE)
        self.assertEqual(record.latest_reading("dev_x").value, 1.5)

    def test_fresh_reading_rules(self):
        record = ChannelValueRecord()
        self.assertIsNone(record.fresh_reading("dev_angle_read", "dev_angle"))
        record.record_read("dev_angle_read", 10.0)
        self.assertEqual(record.fresh_reading("dev_angle_read", "dev_angle").value, 10.0)
        record.record_write("dev_angle", 20.0)
        self.assertIsNone(record.fresh_reading("dev_angle_read", "dev_angle"))
        record.record_read("dev_angle_read", 20.0)
        self.assertEqual(record.fresh_reading("dev_angle_read", "dev_angle").value, 20.0)
        record.record_write("other", 1.0)
        self.assertIsNotNone(record.fresh_reading("dev_angle_read", "dev_angle"))

    def test_invalidate_marks_older_readings_stale(self):
        record = ChannelValueRecord()
        record.record_read("a", 1.0)
        record.invalidate(["a"])
        self.assertIsNone(record.fresh_reading("a"))
        record.record_read("a", 2.0)
        self.assertEqual(record.fresh_reading("a").value, 2.0)

    def test_snapshot_records_numeric_fields_only(self):
        record = ChannelValueRecord()
        count = record.record_snapshot(
            {
                "devices": {
                    "k10cr1_0": {"fields": {"angle": 45.0, "name": "QWP", "bad": {"error": "x"}}},
                    "nidaq": {"fields": {"AO0": "0.25", "inf": "inf"}},
                    "skipped": {"skipped": "live monitor"},
                }
            }
        )
        self.assertEqual(count, 2)
        self.assertEqual(record.latest("k10cr1_0_angle").origin, ORIGIN_SNAPSHOT)
        self.assertEqual(record.latest("nidaq_AO0").value, 0.25)
        self.assertIsNone(record.latest("k10cr1_0_name"))
        self.assertEqual(record.record_snapshot(None), 0)
        self.assertEqual(record.record_snapshot({"devices": []}), 0)

    def test_parallel_writers_keep_a_consistent_order(self):
        import threading

        record = ChannelValueRecord()

        def worker(name):
            for value in range(500):
                record.record_write(name, value)
                record.record_read(name, value)

        threads = [threading.Thread(target=worker, args=(f"c{i}",)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        seqs = [entry.seq for entry in record.entries()]
        self.assertEqual(len(set(seqs)), 4)
        for index in range(4):
            name = f"c{index}"
            self.assertEqual(record.latest_write(name).value, 499.0)
            self.assertGreater(record.latest_reading(name).seq, record.latest_write(name).seq)
            self.assertIsNotNone(record.fresh_reading(name, name))

    def test_entries_and_clear(self):
        record = ChannelValueRecord()
        record.record_write("b", 1)
        record.record_read("a", "text")
        self.assertEqual([e.channel for e in record.entries()], ["a", "b"])
        self.assertEqual(record.latest("a").value, "text")
        record.clear()
        self.assertEqual(record.entries(), [])


if __name__ == "__main__":
    unittest.main()
