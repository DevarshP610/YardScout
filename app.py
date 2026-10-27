import os
import sys
import sqlite3
import threading
import json
import secrets
import smtplib
from collections.abc import Mapping
from datetime import date, datetime, timezone
from email.message import EmailMessage
from functools import wraps
from urllib.parse import urlsplit

import requests

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # pragma: no cover - fallback when Postgres driver is unavailable
    psycopg2 = None
    RealDictCursor = None

from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
APP_ENV = os.environ.get("APP_ENV", "production").strip().casefold()
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()
if not SECRET_KEY:
    if APP_ENV == "development":
        SECRET_KEY = secrets.token_urlsafe(32)
    else:
        raise RuntimeError(
            "SECRET_KEY must be configured with a strong random value outside development."
        )
if len(SECRET_KEY) < 32 and APP_ENV not in {"development", "test"}:
    raise RuntimeError("SECRET_KEY must be at least 32 characters outside development.")
app.secret_key = SECRET_KEY
PRODUCTION_MODE = APP_ENV not in {"development", "test"}
app.config.update(
    SESSION_COOKIE_SECURE=PRODUCTION_MODE,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)
if PRODUCTION_MODE:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and psycopg2 is None:
    raise RuntimeError(
        "DATABASE_URL is configured, but the PostgreSQL driver is unavailable. "
        "Install psycopg2-binary instead of silently falling back to SQLite."
    )
USE_SQLITE = not DATABASE_URL
SALE_RETENTION_DAYS = 7
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "devarshp610@gmail.com").strip().casefold()
DATABASE_PATH = os.environ.get("DATABASE_PATH", "garage_sale_finder.db")
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USERNAME).strip()
scrape_lock = threading.Lock()


@app.before_request
def enforce_https():
    if not PRODUCTION_MODE or request.is_secure:
        return None
    return redirect(request.url.replace("http://", "https://", 1), code=308)


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(self)")
    if PRODUCTION_MODE and request.is_secure:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response

oauth = OAuth(app)

google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

def get_db():
    if USE_SQLITE:
        conn = sqlite3.connect(DATABASE_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    if psycopg2 is None:
        raise RuntimeError(
            "PostgreSQL was selected, but the PostgreSQL driver is unavailable."
        )
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )

def init_db(mark_stale_scrapes=True):
    conn = get_db()
    cur = conn.cursor()
    if USE_SQLITE:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                user_email TEXT,
                user_name TEXT,
                user_picture TEXT,
                source_name TEXT,
                source_url TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scrape_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location TEXT NOT NULL,
                status TEXT NOT NULL,
                result_count INTEGER NOT NULL DEFAULT 0,
                message TEXT,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                job_type TEXT NOT NULL DEFAULT 'location',
                progress INTEGER NOT NULL DEFAULT 0,
                total_steps INTEGER NOT NULL DEFAULT 1
            )
        """)
        cur.execute("PRAGMA table_info(scrape_jobs)")
        job_columns = {row[1] for row in cur.fetchall()}
        for column, definition in (
            ("job_type", "TEXT NOT NULL DEFAULT 'location'"),
            ("progress", "INTEGER NOT NULL DEFAULT 0"),
            ("total_steps", "INTEGER NOT NULL DEFAULT 1"),
        ):
            if column not in job_columns:
                cur.execute(f"ALTER TABLE scrape_jobs ADD COLUMN {column} {definition}")
        cur.execute("PRAGMA table_info(sales)")
        columns = {row[1] for row in cur.fetchall()}
        if "source_name" not in columns:
            cur.execute("ALTER TABLE sales ADD COLUMN source_name TEXT")
        if "source_url" not in columns:
            cur.execute("ALTER TABLE sales ADD COLUMN source_url TEXT")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS creator_follows (
                follower_email TEXT NOT NULL,
                creator_email TEXT NOT NULL,
                creator_name TEXT,
                creator_picture TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (follower_email, creator_email)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_email TEXT NOT NULL,
                creator_email TEXT NOT NULL,
                sale_id INTEGER,
                message TEXT NOT NULL,
                read_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS saved_sales (
                user_email TEXT NOT NULL,
                sale_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_email, sale_id)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(date)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_sales_user_email ON sales(user_email)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_notifications_recipient_id "
            "ON notifications(recipient_email, id DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_saved_sales_user "
            "ON saved_sales(user_email, created_at DESC)"
        )
        if mark_stale_scrapes:
            cur.execute(
                "UPDATE scrape_jobs SET status = 'interrupted', message = 'App restarted before this scrape finished.' WHERE status = 'running'"
            )
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                user_email TEXT,
                user_name TEXT,
                user_picture TEXT,
                source_name TEXT,
                source_url TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scrape_jobs (
                id SERIAL PRIMARY KEY,
                location TEXT NOT NULL,
                status TEXT NOT NULL,
                result_count INTEGER NOT NULL DEFAULT 0,
                message TEXT,
                started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP,
                job_type TEXT NOT NULL DEFAULT 'location',
                progress INTEGER NOT NULL DEFAULT 0,
                total_steps INTEGER NOT NULL DEFAULT 1
            )
        """)
        cur.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS source_name TEXT")
        cur.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS source_url TEXT")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS creator_follows (
                follower_email TEXT NOT NULL,
                creator_email TEXT NOT NULL,
                creator_name TEXT,
                creator_picture TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (follower_email, creator_email)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                recipient_email TEXT NOT NULL,
                creator_email TEXT NOT NULL,
                sale_id INTEGER,
                message TEXT NOT NULL,
                read_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS saved_sales (
                user_email TEXT NOT NULL,
                sale_id INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_email, sale_id)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(date)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_sales_user_email ON sales(user_email)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_notifications_recipient_id "
            "ON notifications(recipient_email, id DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_saved_sales_user "
            "ON saved_sales(user_email, created_at DESC)"
        )
        cur.execute("ALTER TABLE scrape_jobs ADD COLUMN IF NOT EXISTS job_type TEXT NOT NULL DEFAULT 'location'")
        cur.execute("ALTER TABLE scrape_jobs ADD COLUMN IF NOT EXISTS progress INTEGER NOT NULL DEFAULT 0")
        cur.execute("ALTER TABLE scrape_jobs ADD COLUMN IF NOT EXISTS total_steps INTEGER NOT NULL DEFAULT 1")
        if mark_stale_scrapes:
            cur.execute(
                "UPDATE scrape_jobs SET status = 'interrupted', message = 'App restarted before this scrape finished.' WHERE status = 'running'"
            )
    conn.commit()
    cur.close()
    conn.close()


def is_admin(user):
    return bool(user and user.get("email", "").strip().casefold() == ADMIN_EMAIL)


def row_as_dict(row):
    if row is None:
        raise RuntimeError("The database did not return the expected row.")
    if isinstance(row, sqlite3.Row):
        return {key: row[key] for key in row.keys()}
    if isinstance(row, Mapping):
        return dict(row)
    raise TypeError(f"Unsupported database row type: {type(row).__name__}")


def normalized_email(value):
    return value.strip().casefold() if isinstance(value, str) else ""


def email_notifications_enabled():
    return bool(SMTP_HOST and SMTP_FROM)


def send_notification_email(recipient, subject, body):
    if not email_notifications_enabled():
        return
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = recipient
    message.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
        server.starttls()
        if SMTP_USERNAME:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(message)


def notify_creator_followers(sale):
    creator_email = normalized_email(sale.get("user_email"))
    if not creator_email:
        return
    conn = get_db()
    cur = conn.cursor()
    placeholder = "?" if USE_SQLITE else "%s"
    cur.execute(
        f"SELECT follower_email FROM creator_follows WHERE creator_email = {placeholder}",
        (creator_email,),
    )
    recipients = [row_as_dict(row)["follower_email"] for row in cur.fetchall()]
    message = f"{sale.get('user_name') or 'A creator you follow'} posted a new garage sale: {sale['title']}."
    for recipient in recipients:
        if USE_SQLITE:
            cur.execute(
                """
                INSERT INTO notifications
                    (recipient_email, creator_email, sale_id, message)
                VALUES (?, ?, ?, ?)
                """,
                (recipient, creator_email, sale["id"], message),
            )
        else:
            cur.execute(
                """
                INSERT INTO notifications
                    (recipient_email, creator_email, sale_id, message)
                VALUES (%s, %s, %s, %s)
                """,
                (recipient, creator_email, sale["id"], message),
            )
    conn.commit()
    cur.close()
    conn.close()
    for recipient in recipients:
        try:
            send_notification_email(
                recipient,
                "A creator you follow posted on YardScout",
                f"{message}\n\nView YardScout: https://yardscout.me",
            )
        except (OSError, smtplib.SMTPException) as exc:
            print(f"Notification email to {recipient} failed: {exc}", file=sys.stderr)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin(session.get("user")):
            return jsonify({"error": "Admin access required"}), 403
        return view(*args, **kwargs)
    return wrapped


def update_scrape_job(job_id, status, result_count=0, message=None, progress=None, total_steps=None):
    conn = get_db()
    cur = conn.cursor()
    if USE_SQLITE:
        cur.execute(
            """
            UPDATE scrape_jobs
            SET status = ?, result_count = ?, message = ?,
                progress = COALESCE(?, progress), total_steps = COALESCE(?, total_steps),
                finished_at = CASE WHEN ? = 'running' THEN NULL ELSE CURRENT_TIMESTAMP END
            WHERE id = ?
            """,
            (status, result_count, message, progress, total_steps, status, job_id)
        )
    else:
        cur.execute(
            """
            UPDATE scrape_jobs
            SET status = %s, result_count = %s, message = %s,
                progress = COALESCE(%s, progress), total_steps = COALESCE(%s, total_steps),
                finished_at = CASE WHEN %s = 'running' THEN NULL ELSE CURRENT_TIMESTAMP END
            WHERE id = %s
            """,
            (status, result_count, message, progress, total_steps, status, job_id)
        )
    conn.commit()
    cur.close()
    conn.close()


def execute_scrape_job(job_id, location, latitude, longitude, country_code):
    try:
        from scraper import run_location_scrape
        count, message = run_location_scrape(
            location,
            latitude=latitude,
            longitude=longitude,
            country_code=country_code,
        )
        update_scrape_job(job_id, "completed", count, message, progress=1, total_steps=1)
    except Exception as exc:
        print(f"Scrape job {job_id} failed: {exc}", file=sys.stderr)
        update_scrape_job(job_id, "failed", 0, str(exc)[:500], progress=1, total_steps=1)
    finally:
        scrape_lock.release()


def execute_north_america_scan(job_id, start_index=0, initial_count=0):
    result_count = initial_count
    last_saved_count = initial_count
    try:
        from scraper import NORTH_AMERICA_SCAN_TARGETS, run_north_america_scan

        def save_progress(progress, total_steps, result_count, current_location):
            nonlocal last_saved_count
            last_saved_count = result_count
            update_scrape_job(
                job_id,
                "running",
                result_count,
                f"Scanned {progress} of {total_steps} regional hubs; current: {current_location}.",
                progress=progress,
                total_steps=total_steps,
            )

        result_count = run_north_america_scan(
            save_progress,
            start_index=start_index,
            initial_count=initial_count,
        )
        update_scrape_job(
            job_id,
            "completed",
            result_count,
            "Scanned approved sources for regional hubs in all 50 U.S. states and the District of Columbia, plus all 10 provinces and 3 territories. This does not cover every town or third-party site.",
            progress=len(NORTH_AMERICA_SCAN_TARGETS),
            total_steps=len(NORTH_AMERICA_SCAN_TARGETS),
        )
    except Exception as exc:
        print(f"North America scrape job {job_id} failed: {exc}", file=sys.stderr)
        update_scrape_job(job_id, "failed", last_saved_count, str(exc)[:500])
    finally:
        scrape_lock.release()


@app.route("/")
def home():
    user = session.get("user")
    return render_template("index.html", user=user)


@app.route("/googlecca4542b2772bb8d.html")
def google_site_verification():
    return app.send_static_file("googlecca4542b2772bb8d.html")


@app.route("/login")
def login():
    if not os.environ.get("GOOGLE_CLIENT_ID") or not os.environ.get("GOOGLE_CLIENT_SECRET"):
        return "Google sign-in is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.", 503
    host = request.host.split(":", 1)[0].strip("[]").casefold()
    scheme = "http" if host in {"localhost", "127.0.0.1"} else "https"
    redirect_uri = url_for("auth_callback", _external=True, _scheme=scheme)
    return google.authorize_redirect(redirect_uri)

@app.route("/auth/callback")
def auth_callback():
    token = google.authorize_access_token()
    user = token.get("userinfo")
    if not user or not user.get("email"):
        return jsonify({"error": "Google user info unavailable"}), 400
    session["user"] = {
        "email": user.get("email"),
        "name": user.get("name"),
        "picture": user.get("picture")
    }
    return redirect("/")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")

@app.route("/api/me")
def me():
    user = session.get("user")
    if user:
        user = {**user, "is_admin": is_admin(user)}
    return jsonify(user)


@app.route("/api/follows", methods=["GET", "POST"])
def follows():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Login required"}), 401
    follower_email = normalized_email(user.get("email"))
    conn = get_db()
    cur = conn.cursor()
    placeholder = "?" if USE_SQLITE else "%s"
    if request.method == "POST":
        data = request.get_json(silent=True)
        creator_email = normalized_email(data.get("creator_email") if isinstance(data, dict) else None)
        if not creator_email or creator_email == follower_email:
            cur.close()
            conn.close()
            return jsonify({"error": "Choose a different signed-in creator to follow."}), 400
        creator_name = data.get("creator_name", "") if isinstance(data, dict) else ""
        creator_picture = data.get("creator_picture", "") if isinstance(data, dict) else ""
        if not isinstance(creator_name, str) or not isinstance(creator_picture, str):
            cur.close()
            conn.close()
            return jsonify({"error": "Creator details must be text."}), 400
        if USE_SQLITE:
            cur.execute(
                """
                INSERT OR REPLACE INTO creator_follows
                    (follower_email, creator_email, creator_name, creator_picture)
                VALUES (?, ?, ?, ?)
                """,
                (follower_email, creator_email, creator_name.strip(), creator_picture.strip()),
            )
        else:
            cur.execute(
                """
                INSERT INTO creator_follows
                    (follower_email, creator_email, creator_name, creator_picture)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (follower_email, creator_email) DO UPDATE SET
                    creator_name = EXCLUDED.creator_name,
                    creator_picture = EXCLUDED.creator_picture
                """,
                (follower_email, creator_email, creator_name.strip(), creator_picture.strip()),
            )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"following": True, "creator_email": creator_email}), 201
    cur.execute(
        f"""
        SELECT creator_email, creator_name, creator_picture
        FROM creator_follows
        WHERE follower_email = {placeholder}
        ORDER BY created_at DESC
        """,
        (follower_email,),
    )
    result = [row_as_dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(result)


@app.route("/api/follows/<path:creator_email>", methods=["DELETE"])
def unfollow_creator(creator_email):
    user = session.get("user")
    if not user:
        return jsonify({"error": "Login required"}), 401
    conn = get_db()
    cur = conn.cursor()
    if USE_SQLITE:
        cur.execute(
            "DELETE FROM creator_follows WHERE follower_email = ? AND creator_email = ?",
            (normalized_email(user.get("email")), normalized_email(creator_email)),
        )
    else:
        cur.execute(
            "DELETE FROM creator_follows WHERE follower_email = %s AND creator_email = %s",
            (normalized_email(user.get("email")), normalized_email(creator_email)),
        )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"following": False})


@app.route("/api/notifications")
def notifications():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Login required"}), 401
    conn = get_db()
    cur = conn.cursor()
    placeholder = "?" if USE_SQLITE else "%s"
    cur.execute(
        f"""
        SELECT id, creator_email, sale_id, message, read_at, created_at
        FROM notifications
        WHERE recipient_email = {placeholder}
        ORDER BY id DESC
        LIMIT 50
        """,
        (normalized_email(user.get("email")),),
    )
    result = [row_as_dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(result)


@app.route("/api/saved-sales", methods=["GET", "POST"])
def saved_sales():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Login required"}), 401
    user_email = normalized_email(user.get("email"))
    conn = get_db()
    cur = conn.cursor()
    placeholder = "?" if USE_SQLITE else "%s"

    if request.method == "POST":
        data = request.get_json(silent=True)
        raw_sale_id: object = data.get("sale_id") if isinstance(data, dict) else None
        if isinstance(raw_sale_id, bool) or not isinstance(raw_sale_id, (int, str)):
            cur.close()
            conn.close()
            return jsonify({"error": "A valid sale ID is required."}), 400
        try:
            sale_id = int(raw_sale_id)
        except (TypeError, ValueError):
            cur.close()
            conn.close()
            return jsonify({"error": "A valid sale ID is required."}), 400
        if sale_id < 1:
            cur.close()
            conn.close()
            return jsonify({"error": "A valid sale ID is required."}), 400
        cur.execute(
            f"SELECT id FROM sales WHERE id = {placeholder}",
            (sale_id,),
        )
        if cur.fetchone() is None:
            cur.close()
            conn.close()
            return jsonify({"error": "That listing is no longer available."}), 404
        if USE_SQLITE:
            cur.execute(
                """
                INSERT OR IGNORE INTO saved_sales (user_email, sale_id)
                VALUES (?, ?)
                """,
                (user_email, sale_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO saved_sales (user_email, sale_id)
                VALUES (%s, %s)
                ON CONFLICT (user_email, sale_id) DO NOTHING
                """,
                (user_email, sale_id),
            )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"saved": True, "sale_id": sale_id}), 201

    cur.execute(
        f"""
        SELECT sale_id
        FROM saved_sales
        WHERE user_email = {placeholder}
        ORDER BY created_at DESC
        """,
        (user_email,),
    )
    result = [int(row_as_dict(row)["sale_id"]) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(result)


@app.route("/api/saved-sales/<int:sale_id>", methods=["DELETE"])
def unsave_sale(sale_id):
    user = session.get("user")
    if not user:
        return jsonify({"error": "Login required"}), 401
    conn = get_db()
    cur = conn.cursor()
    if USE_SQLITE:
        cur.execute(
            "DELETE FROM saved_sales WHERE user_email = ? AND sale_id = ?",
            (normalized_email(user.get("email")), sale_id),
        )
    else:
        cur.execute(
            "DELETE FROM saved_sales WHERE user_email = %s AND sale_id = %s",
            (normalized_email(user.get("email")), sale_id),
        )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"saved": False, "sale_id": sale_id})


@app.route("/api/notifications/<int:notification_id>/read", methods=["POST"])
def mark_notification_read(notification_id):
    user = session.get("user")
    if not user:
        return jsonify({"error": "Login required"}), 401
    conn = get_db()
    cur = conn.cursor()
    if USE_SQLITE:
        cur.execute(
            """
            UPDATE notifications SET read_at = CURRENT_TIMESTAMP
            WHERE id = ? AND recipient_email = ?
            """,
            (notification_id, normalized_email(user.get("email"))),
        )
    else:
        cur.execute(
            """
            UPDATE notifications SET read_at = CURRENT_TIMESTAMP
            WHERE id = %s AND recipient_email = %s
            """,
            (notification_id, normalized_email(user.get("email"))),
        )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"read": True})


@app.route("/admin")
def admin():
    user = session.get("user")
    if not user:
        return redirect(url_for("login"))
    if not is_admin(user):
        return "Admin access required", 403
    database_backend = "PostgreSQL" if not USE_SQLITE else "SQLite"
    return render_template(
        "admin.html",
        user=user,
        database_backend=database_backend,
    )


@app.route("/api/admin/scrapes")
@admin_required
def admin_scrapes():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM scrape_jobs ORDER BY id DESC LIMIT 10")
    jobs = [dict(row) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify(jobs)


@app.route("/api/admin/backup")
@admin_required
def download_database_backup():
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM sales ORDER BY id")
        sales = [dict(row) for row in cur.fetchall()]
        cur.execute("SELECT * FROM scrape_jobs ORDER BY id")
        scrape_jobs = [dict(row) for row in cur.fetchall()]
        cur.execute("SELECT * FROM saved_sales ORDER BY user_email, sale_id")
        saved_sales = [dict(row) for row in cur.fetchall()]
    finally:
        cur.close()
        conn.close()

    generated_at = datetime.now(timezone.utc)
    backup = {
        "format": "yardscout-json-backup",
        "format_version": 1,
        "generated_at": generated_at.isoformat(),
        "tables": {
            "sales": sales,
            "scrape_jobs": scrape_jobs,
            "saved_sales": saved_sales,
        },
    }
    payload = json.dumps(
        backup,
        indent=2,
        default=lambda value: value.isoformat() if isinstance(value, (date, datetime)) else str(value),
    )
    response = app.response_class(payload, mimetype="application/json")
    response.headers["Content-Disposition"] = (
        f'attachment; filename="yardscout-backup-{generated_at:%Y%m%dT%H%M%SZ}.json"'
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/admin/location-suggestions")
@admin_required
def admin_location_suggestions():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify([])
    try:
        response = requests.get(
            "https://photon.komoot.io/api/",
            params={"q": query, "limit": 40, "lang": "en"},
            headers={"User-Agent": "YardScout/1.0 (location suggestions)"},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
            raise ValueError("Location service returned an invalid response.")
        features = payload["features"]
    except (requests.RequestException, ValueError) as exc:
        app.logger.warning("Location suggestions unavailable: %s", exc)
        return jsonify({"error": "Location suggestions are temporarily unavailable."}), 502

    suggestions = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            continue
        raw_country_code = properties.get("countrycode")
        country_code = raw_country_code.upper() if isinstance(raw_country_code, str) else ""
        place_type = properties.get("type")
        name = properties.get("name")
        coordinates = geometry.get("coordinates")
        if (
            country_code not in {"US", "CA"}
            or place_type not in {"city", "town", "village", "municipality", "locality"}
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(coordinates, list)
            or len(coordinates) != 2
        ):
            continue
        longitude, latitude = coordinates
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            continue
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue

        label_parts = [name]
        region = properties.get("state")
        country = properties.get("country")
        region = region if isinstance(region, str) else ""
        country = country if isinstance(country, str) else ""
        if region and region.casefold() != name.casefold():
            label_parts.append(region)
        if country:
            label_parts.append(country)
        label = ", ".join(label_parts)
        if any(item["label"] == label for item in suggestions):
            continue
        suggestions.append({
            "label": label,
            "city": name,
            "region": region or "",
            "country": country or "",
            "country_code": country_code,
            "latitude": latitude,
            "longitude": longitude,
        })
        if len(suggestions) == 6:
            break
    return jsonify(suggestions)


@app.route("/api/admin/manual-sales", methods=["POST"])
@admin_required
def create_manual_sale():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    title = data.get("title")
    sale_date = data.get("date")
    description = data.get("description", "")
    source_url = data.get("source_url", "")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 250:
        return jsonify({"error": "Enter a title up to 250 characters."}), 400
    if not isinstance(sale_date, str):
        return jsonify({"error": "Enter the sale date."}), 400
    try:
        sale_date = date.fromisoformat(sale_date).isoformat()
    except ValueError:
        return jsonify({"error": "Enter a valid sale date."}), 400
    if sale_date < date.today().isoformat():
        return jsonify({"error": "The sale date has passed; verify it before adding the listing."}), 400
    if not isinstance(description, str) or len(description.strip()) > 2000:
        return jsonify({"error": "Description must be 2,000 characters or fewer."}), 400
    if not isinstance(source_url, str) or len(source_url.strip()) > 1000:
        return jsonify({"error": "The source link must be 1,000 characters or fewer."}), 400
    source_url = source_url.strip() or None
    hostname = ""
    if source_url:
        try:
            parsed_url = urlsplit(source_url)
        except ValueError:
            return jsonify({"error": "Enter a valid http or https source link."}), 400
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            return jsonify({"error": "Enter a valid http or https source link."}), 400
        hostname = (parsed_url.hostname or "").casefold()

    raw_latitude = data.get("latitude")
    raw_longitude = data.get("longitude")
    if raw_latitude is None or raw_longitude is None:
        return jsonify({"error": "Choose the listing location from the suggestions."}), 400
    try:
        latitude = float(raw_latitude)
        longitude = float(raw_longitude)
    except (TypeError, ValueError):
        return jsonify({"error": "Choose the listing location from the suggestions."}), 400
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return jsonify({"error": "The selected location has invalid coordinates."}), 400

    user = session.get("user") or {}
    is_facebook_link = hostname == "facebook.com" or hostname.endswith(".facebook.com")
    source_name = "Facebook (manual)" if is_facebook_link else "Admin-entered"
    values = (
        title.strip(),
        sale_date,
        description.strip(),
        latitude,
        longitude,
        source_name,
        source_url,
        user.get("email"),
        user.get("name", "YardScout Admin"),
    )
    conn = get_db()
    cur = conn.cursor()
    try:
        if USE_SQLITE:
            cur.execute(
                """
                INSERT INTO sales
                    (title, date, description, lat, lng, source_name, source_url, user_email, user_name, user_picture)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                values,
            )
            sale_id = cur.lastrowid
            cur.execute("SELECT * FROM sales WHERE id = ?", (sale_id,))
        else:
            cur.execute(
                """
                INSERT INTO sales
                    (title, date, description, lat, lng, source_name, source_url, user_email, user_name, user_picture)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '')
                RETURNING *
                """,
                values,
            )
        sale = row_as_dict(cur.fetchone())
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
    return jsonify(sale), 201


@app.route("/api/admin/scrapes", methods=["POST"])
@admin_required
def start_scrape():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400
    scope = data.get("scope", "location")
    if scope == "north_america":
        from scraper import NORTH_AMERICA_SCAN_TARGETS

        if not scrape_lock.acquire(blocking=False):
            return jsonify({"error": "A scrape is already running. Check its status before starting another."}), 409
        conn = get_db()
        cur = conn.cursor()
        total_steps = len(NORTH_AMERICA_SCAN_TARGETS)
        try:
            if USE_SQLITE:
                cur.execute(
                    """
                    INSERT INTO scrape_jobs (location, status, job_type, progress, total_steps)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    ("North America regional sweep", "running", "north_america", 0, total_steps),
                )
                job_id = cur.lastrowid
            else:
                cur.execute(
                    """
                    INSERT INTO scrape_jobs (location, status, job_type, progress, total_steps)
                    VALUES (%s, %s, %s, %s, %s) RETURNING id
                    """,
                    ("North America regional sweep", "running", "north_america", 0, total_steps),
                )
                job_id = int(row_as_dict(cur.fetchone())["id"])
            conn.commit()
        except Exception:
            conn.rollback()
            scrape_lock.release()
            raise
        finally:
            cur.close()
            conn.close()

        worker = threading.Thread(
            target=execute_north_america_scan,
            args=(job_id,),
            daemon=True,
            name=f"north-america-scrape-{job_id}",
        )
        try:
            worker.start()
        except Exception as exc:
            try:
                update_scrape_job(job_id, "failed", 0, f"Could not start the background scan: {exc}"[:500])
            finally:
                scrape_lock.release()
            raise
        return jsonify({
            "id": job_id,
            "location": "North America regional sweep",
            "status": "running",
            "job_type": "north_america",
            "total_steps": total_steps,
        }), 202
    if scope != "location":
        return jsonify({"error": "Choose a supported scrape scope."}), 400
    location = data.get("location")
    if not isinstance(location, str):
        return jsonify({"error": "Location must be text."}), 400
    location = location.strip()
    if not location or len(location) > 160:
        return jsonify({"error": "Enter a location up to 160 characters."}), 400
    raw_latitude = data.get("latitude")
    raw_longitude = data.get("longitude")
    if raw_latitude is None or raw_longitude is None:
        return jsonify({"error": "Choose a location from the suggestions."}), 400
    try:
        latitude = float(raw_latitude)
        longitude = float(raw_longitude)
    except (TypeError, ValueError):
        return jsonify({"error": "Choose a location from the suggestions."}), 400
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return jsonify({"error": "The selected location has invalid coordinates."}), 400
    country_code = data.get("country_code")
    if not isinstance(country_code, str) or country_code not in {"US", "CA"}:
        return jsonify({"error": "Choose a location in the United States or Canada."}), 400
    if not scrape_lock.acquire(blocking=False):
        return jsonify({"error": "A scrape is already running. Check its status before starting another."}), 409

    conn = get_db()
    cur = conn.cursor()
    try:
        if USE_SQLITE:
            cur.execute(
                """
                INSERT INTO scrape_jobs (location, status, job_type, progress, total_steps)
                VALUES (?, ?, ?, ?, ?)
                """,
                (location, "running", "location", 0, 1)
            )
            job_id = cur.lastrowid
        else:
            cur.execute(
                """
                INSERT INTO scrape_jobs (location, status, job_type, progress, total_steps)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
                """,
                (location, "running", "location", 0, 1)
            )
            job_id = int(row_as_dict(cur.fetchone())["id"])
        conn.commit()
    except Exception:
        conn.rollback()
        scrape_lock.release()
        raise
    finally:
        cur.close()
        conn.close()

    worker = threading.Thread(
        target=execute_scrape_job,
        args=(job_id, location, latitude, longitude, country_code),
        daemon=True,
        name=f"scrape-job-{job_id}"
    )
    try:
        worker.start()
    except Exception as exc:
        try:
            update_scrape_job(job_id, "failed", 0, f"Could not start the background scan: {exc}"[:500])
        finally:
            scrape_lock.release()
        raise
    return jsonify({"id": job_id, "location": location, "status": "running"}), 202


@app.route("/api/admin/scrapes/<int:job_id>/resume", methods=["POST"])
@admin_required
def resume_north_america_scrape(job_id):
    from scraper import NORTH_AMERICA_SCAN_TARGETS

    conn = get_db()
    cur = conn.cursor()
    if USE_SQLITE:
        cur.execute(
            "SELECT * FROM scrape_jobs WHERE id = ?",
            (job_id,),
        )
    else:
        cur.execute(
            "SELECT * FROM scrape_jobs WHERE id = %s",
            (job_id,),
        )
    job = cur.fetchone()
    cur.close()
    conn.close()
    if not job:
        return jsonify({"error": "Scrape job not found."}), 404

    job = row_as_dict(job)
    if job["job_type"] != "north_america" or job["status"] not in {"interrupted", "failed"}:
        return jsonify({"error": "Only interrupted or failed North America sweeps can be resumed."}), 409
    if not scrape_lock.acquire(blocking=False):
        return jsonify({"error": "A scrape is already running. Check its status before resuming another."}), 409

    start_index = min(max(int(job["progress"]), 0), len(NORTH_AMERICA_SCAN_TARGETS))
    initial_count = int(job["result_count"])
    worker = threading.Thread(
        target=execute_north_america_scan,
        args=(job_id, start_index, initial_count),
        daemon=True,
        name=f"north-america-scrape-{job_id}",
    )
    try:
        update_scrape_job(
            job_id,
            "running",
            initial_count,
            f"Resuming at regional hub {start_index + 1} of {len(NORTH_AMERICA_SCAN_TARGETS)}.",
        )
        worker.start()
    except Exception as exc:
        try:
            update_scrape_job(
                job_id,
                "failed",
                initial_count,
                f"Could not resume the background scan: {exc}"[:500],
            )
        finally:
            scrape_lock.release()
        raise
    return jsonify({"id": job_id, "status": "running", "progress": start_index}), 202


@app.route("/api/sales", methods=["GET"])
def get_sales():
    conn = get_db()
    cur = conn.cursor()
    if USE_SQLITE:
        cur.execute(
            "DELETE FROM sales WHERE date <= date('now', ?)",
            (f"-{SALE_RETENTION_DAYS} days",),
        )
    else:
        cur.execute(
            "DELETE FROM sales WHERE date <= (CURRENT_DATE - %s)::text",
            (SALE_RETENTION_DAYS,),
        )
    cur.execute("SELECT * FROM sales ORDER BY id DESC")
    sales = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify([dict(s) for s in sales])

@app.route("/api/sales", methods=["POST"])
def add_sale():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400
    if not isinstance(data.get("title"), str) or not isinstance(data.get("date"), str):
        return jsonify({"error": "Title and date must be text."}), 400
    title = data["title"].strip()
    sale_date = data["date"].strip()
    lat = data.get("lat")
    lng = data.get("lng")

    if not title or not sale_date or lat is None or lng is None:
        return jsonify({"error": "Missing required sale fields"}), 400
    try:
        sale_date = date.fromisoformat(sale_date).isoformat()
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return jsonify({"error": "Date and coordinates must be valid."}), 400
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return jsonify({"error": "Coordinates are outside valid latitude/longitude bounds."}), 400
    description = data.get("description", "")
    if not isinstance(description, str):
        return jsonify({"error": "Description must be text."}), 400

    conn = get_db()
    cur = conn.cursor()
    if USE_SQLITE:
        cur.execute(
            """
            INSERT INTO sales (title, date, description, lat, lng, user_email, user_name, user_picture, source_name, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            (
                title,
                sale_date,
                description.strip(),
                lat,
                lng,
                user.get("email"),
                user.get("name"),
                user.get("picture")
            )
        )
        sale_id = cur.lastrowid
        cur.execute("SELECT * FROM sales WHERE id = ?", (sale_id,))
        new_sale = row_as_dict(cur.fetchone())
    else:
        cur.execute(
            """
            INSERT INTO sales (title, date, description, lat, lng, user_email, user_name, user_picture, source_name, source_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL)
            RETURNING *
            """,
            (
                title,
                sale_date,
                description.strip(),
                lat,
                lng,
                user.get("email"),
                user.get("name"),
                user.get("picture")
            )
        )
        new_sale = row_as_dict(cur.fetchone())
    conn.commit()
    cur.close()
    conn.close()
    notify_creator_followers(new_sale)
    return jsonify(new_sale), 201

@app.route("/api/scrape", methods=["POST"])
def trigger_scrape():
    if not is_admin(session.get("user")):
        return jsonify({"error": "Admin access required"}), 403
    return jsonify({"error": "Use the admin location scraper at /api/admin/scrapes."}), 410

@app.route("/api/sales/<int:sale_id>", methods=["DELETE"])
def delete_sale(sale_id):
    user = session.get("user")
    if not user:
        return jsonify({"error": "Login required"}), 401
    conn = get_db()
    cur = conn.cursor()
    if is_admin(user):
        if USE_SQLITE:
            cur.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
        else:
            cur.execute("DELETE FROM sales WHERE id = %s", (sale_id,))
    elif USE_SQLITE:
        cur.execute("DELETE FROM sales WHERE id = ? AND user_email = ?", (sale_id, user.get("email")))
    else:
        cur.execute("DELETE FROM sales WHERE id = %s AND user_email = %s", (sale_id, user.get("email")))
    if USE_SQLITE:
        cur.execute("DELETE FROM saved_sales WHERE sale_id = ?", (sale_id,))
    else:
        cur.execute("DELETE FROM saved_sales WHERE sale_id = %s", (sale_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Deleted!"})

if os.environ.get("YARDSCOUT_SKIP_DB_INIT") != "1":
    with app.app_context():
        init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)