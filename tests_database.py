"""Persistent storage and ledger integrity checks. Run: python tests_database.py"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src", "backend"))

from database import Database  # noqa: E402


class DatabaseChecks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.temp_dir.name, "storage.db"))

    def tearDown(self):
        self.db.conn.close()
        self.temp_dir.cleanup()

    def test_ledger_verifies_and_detects_payload_tampering(self):
        result = {"state": "S1_ATMOSPHERIC_INGRESS", "risk": "HIGH",
                  "rule": "rh over limit"}
        packet = {"timestamp": "2026-10-06T10:00:00+05:30",
                  "temp": 28.5, "rh": 78.0}
        self.db.log_telemetry(packet, result, "FILE")
        event_id = self.db.log_event("STATE_CHANGE", result, {"source": "FILE"})
        self.db.log_ack("operator", event_id, 1, "checked")
        self.assertTrue(self.db.verify_chain()["telemetry"])
        self.assertTrue(self.db.verify_chain()["events"])
        self.assertTrue(self.db.verify_chain()["acknowledgments"])

        self.db.conn.execute("UPDATE telemetry SET raw_json='{}' WHERE id=1")
        self.db.conn.commit()
        report = self.db.verify_chain()
        self.assertFalse(report["telemetry"])
        self.assertIn("row 1", report["detail"])

    def test_result_and_audit_snapshot_are_persisted(self):
        result = {"state": "S0_IDLE_SAFE", "risk": "LOW",
                  "facts": {"moisture_stress_hours": 1.25,
                            "thermal_stress_hours": 0.5}}
        self.db.log_telemetry(
            {"timestamp": "2026-10-06T10:00:00+05:30", "rh": 60.0},
            result, "LIVE")
        event_id = self.db.log_event("STATE_CHANGE", result, {"source": "LIVE"})
        self.db.log_ack("operator", event_id, 1, "checked")

        snapshot = self.db.audit_snapshot()
        self.assertEqual(snapshot["telemetry_total"], 1)
        self.assertEqual(snapshot["event_total"], 1)
        self.assertEqual(snapshot["acknowledgment_total"], 1)
        self.assertEqual(snapshot["telemetry"][0]["result_json"],
                         json.dumps(result, sort_keys=True, default=str))
        self.assertEqual(snapshot["telemetry"][0]["source"], "LIVE")
        self.assertTrue(all(snapshot["chain"][table] for table in (
            "telemetry", "events", "acknowledgments")))


if __name__ == "__main__":
    unittest.main()
