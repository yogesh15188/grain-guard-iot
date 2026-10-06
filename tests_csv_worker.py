"""Append-only CSV ingestion checks. Run: python tests_csv_worker.py"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src", "backend"))

from csv_worker import CsvWorker  # noqa: E402
from database import Database  # noqa: E402

HEADER = "timestamp,temp,rh,fork_raw,ldr_raw,distance_cm\n"
NORMAL = "2026-10-06T10:00:00+05:30,27,60,900,20,15\n"
DAMP = "2026-10-06T10:01:00+05:30,28.5,78,900,20,15\n"


class CsvWorkerChecks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "readings.csv")
        self.db = Database(os.path.join(self.temp_dir.name, "storage.db"))
        self.packets = []
        self.worker = CsvWorker(
            self.path, self.db,
            lambda packet, source: self.packets.append((packet, source)),
            interval=0.01,
        )

    def tearDown(self):
        self.db.conn.close()
        self.temp_dir.cleanup()

    def write(self, contents):
        with open(self.path, "w", encoding="utf-8", newline="") as file:
            file.write(contents)

    def test_imports_existing_rows_then_only_new_appended_rows(self):
        self.write(HEADER + NORMAL)
        self.assertEqual(self.worker.read_available(), 1)
        self.assertEqual(self.packets[0][1], "FILE")
        self.assertEqual(self.packets[0][0]["rh"], 60.0)

        with open(self.path, "a", encoding="utf-8", newline="") as file:
            file.write(DAMP)
        self.assertEqual(self.worker.read_available(), 1)
        self.assertEqual(self.packets[1][0]["rh"], 78.0)

        self.db_path = self.db.path
        self.db.conn.close()
        self.db = Database(self.db_path)
        restarted = CsvWorker(self.path, self.db, lambda packet, source: self.fail(
            "already processed rows must not be replayed"))
        self.assertEqual(restarted.read_available(), 0)

    def test_waits_for_newline_before_processing_a_partial_record(self):
        self.write(HEADER + NORMAL.rstrip("\n"))
        self.assertEqual(self.worker.read_available(), 0)
        self.assertEqual(self.packets, [])

        with open(self.path, "a", encoding="utf-8", newline="") as file:
            file.write("\n")
        self.assertEqual(self.worker.read_available(), 1)
        self.assertEqual(len(self.packets), 1)

    def test_invalid_record_is_reported_and_next_valid_row_is_processed(self):
        self.write(HEADER + "not-a-number,hot,60,900,20,15\n" + NORMAL)
        self.assertEqual(self.worker.read_available(), 1)
        self.assertEqual(len(self.packets), 1)
        self.assertIsNone(self.worker.last_error)

    def test_file_replacement_starts_a_new_import(self):
        self.write(HEADER + NORMAL)
        self.assertEqual(self.worker.read_available(), 1)
        replacement = os.path.join(self.temp_dir.name, "replacement.csv")
        with open(replacement, "w", encoding="utf-8", newline="") as file:
            file.write(HEADER + DAMP)
        os.replace(replacement, self.path)

        self.assertEqual(self.worker.read_available(), 1)
        self.assertEqual(self.packets[-1][0]["rh"], 78.0)


if __name__ == "__main__":
    unittest.main()
