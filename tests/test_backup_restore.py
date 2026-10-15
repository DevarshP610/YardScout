import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RESTORE_SCRIPT = ROOT / "scripts" / "restore_backup.py"


class BackupRestoreTests(unittest.TestCase):
    def test_restore_recovers_backup_and_refuses_to_overwrite_without_flag(self):
        with tempfile.TemporaryDirectory(prefix="yardscout-restore-test-") as temp:
            root = Path(temp)
            backup_path = root / "backup.json"
            database_path = root / "restored.sqlite"
            backup_path.write_text(
                json.dumps({
                    "format": "yardscout-json-backup",
                    "format_version": 1,
                    "generated_at": "2030-01-01T00:00:00+00:00",
                    "tables": {
                        "sales": [{
                            "id": 4,
                            "title": "Recovered yard sale",
                            "date": "2030-06-01",
                            "description": "Community sale",
                            "lat": 49.8,
                            "lng": -99.9,
                            "user_email": "seller@example.test",
                            "user_name": "Community member",
                            "user_picture": None,
                            "source_name": "Admin-entered",
                            "source_url": "https://example.test/sale",
                        }],
                        "scrape_jobs": [{
                            "id": 7,
                            "location": "Brandon, Manitoba",
                            "status": "running",
                            "result_count": 1,
                            "message": "In progress",
                            "started_at": "2030-01-01T00:00:00+00:00",
                            "finished_at": None,
                            "job_type": "north_america",
                            "progress": 1,
                            "total_steps": 70,
                        }],
                    },
                }),
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment.pop("DATABASE_URL", None)
            environment.pop("DATABASE_PATH", None)

            first_restore = subprocess.run(
                [
                    sys.executable,
                    str(RESTORE_SCRIPT),
                    str(backup_path),
                    "--database-path",
                    str(database_path),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(first_restore.returncode, 0, first_restore.stderr)

            conn = sqlite3.connect(database_path)
            conn.execute(
                """
                INSERT INTO sales (title, date, lat, lng)
                VALUES (?, ?, ?, ?)
                """,
                ("Existing target sale", "2030-06-02", 49.8, -99.9),
            )
            conn.execute(
                "INSERT INTO scrape_jobs (location, status) VALUES (?, ?)",
                ("Current target job", "running"),
            )
            conn.commit()
            conn.close()

            refused_restore = subprocess.run(
                [
                    sys.executable,
                    str(RESTORE_SCRIPT),
                    str(backup_path),
                    "--database-path",
                    str(database_path),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(refused_restore.returncode, 0)
            self.assertIn("target database is not empty", refused_restore.stderr)
            conn = sqlite3.connect(database_path)
            unchanged_job_status = conn.execute(
                "SELECT status FROM scrape_jobs WHERE location = ?",
                ("Current target job",),
            ).fetchone()[0]
            conn.close()
            self.assertEqual(unchanged_job_status, "running")

            replacing_restore = subprocess.run(
                [
                    sys.executable,
                    str(RESTORE_SCRIPT),
                    str(backup_path),
                    "--database-path",
                    str(database_path),
                    "--replace",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(replacing_restore.returncode, 0, replacing_restore.stderr)

            conn = sqlite3.connect(database_path)
            restored_sale = conn.execute(
                "SELECT id, title, source_url FROM sales"
            ).fetchone()
            restored_job = conn.execute(
                "SELECT id, status, message FROM scrape_jobs"
            ).fetchone()
            conn.close()

            self.assertEqual(
                restored_sale,
                (4, "Recovered yard sale", "https://example.test/sale"),
            )
            self.assertEqual(restored_job[0:2], (7, "interrupted"))
            self.assertIn("interrupted during backup restoration", restored_job[2])


if __name__ == "__main__":
    unittest.main()
