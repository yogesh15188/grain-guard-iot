"""PDF audit export tests. Run: python tests_audit_pdf.py"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src", "backend"))

from audit_pdf import build_audit_pdf  # noqa: E402


class AuditPdfChecks(unittest.TestCase):
    def test_pdf_contains_a_valid_report_for_live_telemetry_and_alerts(self):
        result = {
            "state": "S2_MOISTURE_RISK",
            "risk": "HIGH",
            "rule": "Relative humidity threshold exceeded",
            "evidence": ["RH 81% exceeds limit 75%"],
            "facts": {"emc_estimate": 18.2},
            "alerts": {"alerts": [{
                "severity": "danger",
                "title": "Moisture ingress risk",
                "evidence": "Humidity is elevated",
                "actions": ["Inspect the roof", "Check the grain surface"],
            }]},
        }
        snapshot = {
            "telemetry_total": 1,
            "event_total": 1,
            "acknowledgment_total": 1,
            "telemetry": [{
                "id": 1, "ts": "2026-10-06T10:00:00+00:00", "source": "LIVE",
                "temp": 28.0, "rh": 81.0, "fork_raw": 268, "ldr_raw": 1022,
                "distance_cm": 9.5, "state": result["state"], "risk": result["risk"],
                "rule": result["rule"], "result_json": json.dumps(result),
            }],
            "events": [{
                "id": 1, "ts": "2026-10-06T10:00:01+00:00",
                "kind": "ALERT_RAISED", "state": result["state"], "risk": result["risk"],
                "rule": result["rule"],
                "detail_json": json.dumps({"alert": result["alerts"]["alerts"][0]}),
            }],
            "acknowledgments": [{
                "id": 1, "ts": "2026-10-06T10:00:02+00:00", "operator": "Judge",
                "event_id": 1, "verified": 1, "note": "Inspected roof",
            }],
            "chain": {
                "telemetry": True, "events": True, "acknowledgments": True,
                "detail": "",
            },
        }
        pdf = build_audit_pdf(snapshot, {
            "name": "Demo Rice Storage", "commodity": "Rice", "bin": "Bin 1",
        }).read()

        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))
        self.assertGreater(len(pdf), 1500)


if __name__ == "__main__":
    unittest.main()
