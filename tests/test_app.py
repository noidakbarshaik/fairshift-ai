import os
import sys
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
TEST_DB = PROJECT / "tests" / "fairshift-test.db"
TEST_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["FAIRSHIFT_SECRET"] = "test-only-secret-key-not-for-production"
os.environ["ENVIRONMENT"] = "test"
sys.path.insert(0, str(PROJECT))

import main
from fastapi.testclient import TestClient


class FairShiftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(main.app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)
        main.engine.dispose(close=True)

    def setUp(self):
        self.client.cookies.clear()

    def login(self, email="worker@fairshift.demo"):
        response = self.client.post("/api/login", json={"email": email, "password": "FairShiftDemo26!"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["user"]

    def test_static_dashboard_is_served(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("FairShift", page.text)
        self.assertEqual(self.client.get("/static/app.js").status_code, 200)

    def test_health_and_login(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertEqual(self.login()["role"], "worker")

    def test_attendance_duplicate_checkin_and_checkout(self):
        self.login()
        start = datetime.now(timezone.utc) - timedelta(hours=10)
        with patch("main.now_utc", return_value=start):
            self.assertEqual(self.client.post("/api/worker/check-in", json={}).status_code, 200)
        self.assertEqual(self.client.post("/api/worker/check-in", json={}).status_code, 409)
        with patch("main.now_utc", return_value=start + timedelta(hours=10)):
            result = self.client.post("/api/worker/check-out", json={"break_minutes": 0})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["hours"], 10.0)
        self.assertEqual(result.json()["pay"]["estimated_gross_pay"], 1980.0)
        self.assertEqual(self.client.post("/api/worker/check-out", json={"break_minutes": 0}).status_code, 409)

    def test_deterministic_overtime_pay_and_missing_rate(self):
        result = main.pay_breakdown(10, 100, 8, 1.5)
        self.assertEqual(result["regular_pay"], 800)
        self.assertEqual(result["overtime_pay"], 300)
        self.assertEqual(result["estimated_gross_pay"], 1100)
        self.assertEqual(main.pay_breakdown(6, 100, 8, 1.5)["overtime_hours"], 0)
        self.assertFalse(main.pay_breakdown(6, None, 8, 1.5)["available"])

    def test_overnight_duration_and_bad_time(self):
        from datetime import datetime, timezone, timedelta
        start = datetime(2026, 10, 26, 22, tzinfo=timezone.utc)
        end = datetime(2026, 10, 27, 6, tzinfo=timezone.utc)
        self.assertEqual(main.duration_hours(start, end, 30), 7.5)
        with self.assertRaises(ValueError):
            main.duration_hours(end, start)

    def test_worker_cannot_open_admin_dashboard(self):
        self.login()
        self.assertEqual(self.client.get("/api/admin/dashboard").status_code, 403)

    def test_anonymous_report_does_not_expose_worker_identity(self):
        self.login()
        created = self.client.post("/api/worker/reports", json={
            "category": "Electrical hazard", "description": "Loose wire cover beside the walkway.",
            "location": "North Site", "severity": "High", "anonymous": True
        })
        self.assertEqual(created.status_code, 200, created.text)
        ref = created.json()["reference"]
        code = created.json()["anonymous_access_token"]
        self.client.post("/api/logout")
        self.login("admin@fairshift.demo")
        dash = self.client.get("/api/admin/dashboard?org_id=construction").json()
        row = next(r for r in dash["reports"] if r["reference"] == ref)
        self.assertEqual(row["reporter"], "Anonymous")
        self.assertNotIn("worker_id", row)
        self.assertNotIn("email", row)
        self.assertEqual(self.client.patch(f"/api/admin/reports/{ref}", json={"status": "Under Review"}).status_code, 200)
        self.assertEqual(self.client.get(f"/api/reports/track/{ref}").status_code, 403)
        tracked = self.client.get(f"/api/reports/track/{ref}?access_code={code}")
        self.assertEqual(tracked.status_code, 200, tracked.text)
        self.assertEqual(tracked.json()["status"], "Under Review")

    def test_ai_summary_falls_back_when_service_is_unavailable(self):
        self.login("admin@fairshift.demo")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-placeholder"}), patch("urllib.request.urlopen", side_effect=OSError("offline")):
            response = self.client.post("/api/admin/insights?org_id=construction", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["summary"])
        self.assertTrue(response.json()["ai_enabled"])
        self.assertFalse(response.json()["ai_used"])

    def test_organization_scenarios_and_db_backed_metrics(self):
        self.login("admin@fairshift.demo")
        campus = self.client.get("/api/admin/dashboard?org_id=campus")
        self.assertEqual(campus.status_code, 200)
        self.assertEqual(campus.json()["organization"]["industry"], "College & University Facilities")
        self.assertEqual(campus.json()["metrics"]["workers"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
