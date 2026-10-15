import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


TABLE_COLUMNS = {
    "sales": (
        "id",
        "title",
        "date",
        "description",
        "lat",
        "lng",
        "user_email",
        "user_name",
        "user_picture",
        "source_name",
        "source_url",
    ),
    "scrape_jobs": (
        "id",
        "location",
        "status",
        "result_count",
        "message",
        "started_at",
        "finished_at",
        "job_type",
        "progress",
        "total_steps",
    ),
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Restore a YardScout JSON backup into an empty database."
    )
    parser.add_argument("backup", type=Path, help="Path to the downloaded JSON backup")
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument(
        "--database-path",
        help="SQLite file to restore (creates it if needed)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace existing sales and scrape history in the target database",
    )
    return parser.parse_args()


def validate_backup(backup):
    if not isinstance(backup, dict):
        raise ValueError("Backup must be a JSON object.")
    if backup.get("format") != "yardscout-json-backup" or backup.get("format_version") != 1:
        raise ValueError("Backup format is not supported.")
    tables = backup.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(TABLE_COLUMNS):
        raise ValueError("Backup must contain sales and scrape_jobs tables.")
    for table_name, columns in TABLE_COLUMNS.items():
        rows = tables[table_name]
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not set(columns).issubset(row)
            for row in rows
        ):
            raise ValueError(f"Backup table {table_name!r} has invalid rows.")
    return tables


def restore(tables, replace_existing):
    os.environ["YARDSCOUT_SKIP_DB_INIT"] = "1"
    from app import USE_SQLITE, get_db, init_db

    if os.environ.get("DATABASE_URL") and USE_SQLITE:
        raise RuntimeError(
            "DATABASE_URL is set but PostgreSQL is unavailable; refusing to restore "
            "into a local SQLite fallback."
        )
    init_db(mark_stale_scrapes=False)

    conn = get_db()
    cur = conn.cursor()
    try:
        counts = {}
        for table_name in TABLE_COLUMNS:
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            count_row = cur.fetchone()
            if count_row is None:
                raise RuntimeError(f"Could not inspect existing rows in {table_name}.")
            counts[table_name] = (
                count_row["count"] if isinstance(count_row, Mapping) else count_row[0]
            )
        if any(counts.values()) and not replace_existing:
            raise RuntimeError(
                "The target database is not empty. Re-run with --replace only if "
                "you intend to replace its sales and scrape history."
            )

        if replace_existing:
            cur.execute("DELETE FROM scrape_jobs")
            cur.execute("DELETE FROM sales")

        placeholder = "?" if USE_SQLITE else "%s"
        for table_name, columns in TABLE_COLUMNS.items():
            rows = tables[table_name]
            if not rows:
                continue
            column_sql = ", ".join(columns)
            placeholders = ", ".join(placeholder for _ in columns)
            if table_name == "scrape_jobs":
                normalized_rows = []
                for row in rows:
                    normalized = {column: row[column] for column in columns}
                    if normalized["status"] == "running":
                        normalized["status"] = "interrupted"
                        normalized["message"] = (
                            "Scan was marked interrupted during backup restoration."
                        )
                    normalized_rows.append(normalized)
                rows = normalized_rows
            values = [
                tuple(row[column] for column in columns)
                for row in rows
            ]
            cur.executemany(
                f"INSERT INTO {table_name} ({column_sql}) VALUES ({placeholders})",
                values,
            )

        if not USE_SQLITE:
            for table_name in TABLE_COLUMNS:
                cur.execute(
                    f"""
                    SELECT setval(
                        pg_get_serial_sequence('{table_name}', 'id'),
                        COALESCE(MAX(id), 1),
                        MAX(id) IS NOT NULL
                    )
                    FROM {table_name}
                    """
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

    return {name: len(rows) for name, rows in tables.items()}


def main():
    args = parse_args()
    if args.database_path:
        os.environ.pop("DATABASE_URL", None)
        os.environ["DATABASE_PATH"] = args.database_path
    elif not os.environ.get("DATABASE_URL") and not os.environ.get("DATABASE_PATH"):
        raise SystemExit(
            "Set DATABASE_URL or DATABASE_PATH, or pass an explicit database destination."
        )

    try:
        with args.backup.open("r", encoding="utf-8") as backup_file:
            tables = validate_backup(json.load(backup_file))
        restored = restore(tables, args.replace)
    except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Backup restore failed: {exc}") from exc

    print(
        "Restore complete: "
        f"{restored['sales']} sale(s), "
        f"{restored['scrape_jobs']} scrape job(s)."
    )


if __name__ == "__main__":
    main()
