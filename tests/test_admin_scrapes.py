import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

_IMPORT_DATABASE = tempfile.TemporaryDirectory(prefix="yardscout-test-import-")
_ORIGINAL_DATABASE_PATH = os.environ.get("DATABASE_PATH")
_ORIGINAL_DATABASE_URL = os.environ.pop("DATABASE_URL", None)
os.environ["DATABASE_PATH"] = os.path.join(_IMPORT_DATABASE.name, "import.sqlite")

import app
import scraper

if _ORIGINAL_DATABASE_PATH is None:
    os.environ.pop("DATABASE_PATH", None)
else:
    os.environ["DATABASE_PATH"] = _ORIGINAL_DATABASE_PATH
if _ORIGINAL_DATABASE_URL is not None:
    os.environ["DATABASE_URL"] = _ORIGINAL_DATABASE_URL


class AdminScrapeTests(unittest.TestCase):
    def _connect(self):
        conn = sqlite3.connect(app.DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def setUp(self):
        self.database = tempfile.TemporaryDirectory(prefix="yardscout-admin-test-")
        app.DATABASE_PATH = os.path.join(self.database.name, "test.sqlite")
        app.USE_SQLITE = True
        app.init_db()
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()
        with self.client.session_transaction() as session:
            session["user"] = {"email": app.ADMIN_EMAIL}
        self.addCleanup(self._release_lock)
        self.addCleanup(self.database.cleanup)

    @staticmethod
    def _release_lock():
        if app.scrape_lock.locked():
            app.scrape_lock.release()

    def test_starting_regional_scan_is_admin_only_and_persists_job(self):
        with patch.object(app.threading.Thread, "start", autospec=True):
            response = self.client.post(
                "/api/admin/scrapes",
                json={"scope": "north_america"},
            )

        self.assertEqual(response.status_code, 202)
        result = response.get_json()
        self.assertEqual(result["job_type"], "north_america")
        self.assertEqual(result["total_steps"], 70)

        conn = self._connect()
        job = conn.execute(
            "SELECT job_type, status, progress, total_steps FROM scrape_jobs WHERE id = ?",
            (result["id"],),
        ).fetchone()
        conn.close()
        self.assertEqual(
            dict(job),
            {
                "job_type": "north_america",
                "status": "running",
                "progress": 0,
                "total_steps": 70,
            },
        )

        anonymous_client = app.app.test_client()
        denied = anonymous_client.post(
            "/api/admin/scrapes",
            json={"scope": "north_america"},
        )
        self.assertEqual(denied.status_code, 403)

    def test_admin_backup_download_is_authenticated_and_contains_both_tables(self):
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO sales
                (title, date, lat, lng, user_email, user_name, source_name, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Community yard sale",
                "2030-06-01",
                49.8,
                -99.9,
                "seller@example.test",
                "Community member",
                "Admin-entered",
                "https://example.test/sale",
            ),
        )
        conn.execute(
            "INSERT INTO scrape_jobs (location, status) VALUES (?, ?)",
            ("Brandon, Manitoba", "completed"),
        )
        conn.commit()
        conn.close()

        response = self.client.get("/api/admin/backup")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment; filename=", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        backup = json.loads(response.get_data(as_text=True))
        self.assertEqual(backup["format"], "yardscout-json-backup")
        self.assertEqual(backup["format_version"], 1)
        self.assertEqual(backup["tables"]["sales"][0]["source_url"], "https://example.test/sale")
        self.assertEqual(backup["tables"]["scrape_jobs"][0]["location"], "Brandon, Manitoba")

        denied = app.app.test_client().get("/api/admin/backup")
        self.assertEqual(denied.status_code, 403)

    def test_legacy_scrape_jobs_table_migrates_progress_columns(self):
        legacy_path = os.path.join(self.database.name, "legacy.sqlite")
        conn = sqlite3.connect(legacy_path)
        conn.execute(
            """
            CREATE TABLE scrape_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location TEXT NOT NULL,
                status TEXT NOT NULL,
                result_count INTEGER NOT NULL DEFAULT 0,
                message TEXT,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT
            )
            """
        )
        conn.commit()
        conn.close()

        app.DATABASE_PATH = legacy_path
        app.init_db()
        conn = self._connect()
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(scrape_jobs)").fetchall()
        }
        conn.close()

        self.assertTrue({"job_type", "progress", "total_steps"} <= columns)

    def test_interrupted_regional_scan_resumes_and_saves_progress(self):
        with patch.object(app.threading.Thread, "start", autospec=True):
            started = self.client.post(
                "/api/admin/scrapes",
                json={"scope": "north_america"},
            )
        job_id = started.get_json()["id"]
        app.scrape_lock.release()

        conn = self._connect()
        conn.execute(
            """
            UPDATE scrape_jobs
            SET status = 'interrupted', progress = 68, result_count = 5
            WHERE id = ?
            """,
            (job_id,),
        )
        conn.commit()
        conn.close()

        with patch.object(app.threading.Thread, "start", autospec=True):
            resumed = self.client.post(f"/api/admin/scrapes/{job_id}/resume")
        self.assertEqual(resumed.status_code, 202)

        def finish_remaining(callback, start_index, initial_count):
            self.assertEqual((start_index, initial_count), (68, 5))
            callback(69, 70, 6, "Whitehorse, Yukon, Canada")
            callback(70, 70, 7, "Saskatoon, Saskatchewan, Canada")
            return 7

        with patch.object(scraper, "run_north_america_scan", side_effect=finish_remaining):
            app.execute_north_america_scan(job_id, 68, 5)

        conn = self._connect()
        job = conn.execute(
            "SELECT status, progress, total_steps, result_count FROM scrape_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(
            dict(job),
            {
                "status": "completed",
                "progress": 70,
                "total_steps": 70,
                "result_count": 7,
            },
        )


if __name__ == "__main__":
    unittest.main()
