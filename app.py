import os
import sys
import sqlite3
import threading
from collections.abc import Mapping
from datetime import date
from functools import wraps

import requests

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # pragma: no cover - fallback when Postgres driver is unavailable
    psycopg2 = None
    RealDictCursor = None

from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from authlib.integrations.flask_client import OAuth

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

DATABASE_URL = os.environ.get("DATABASE_URL")
USE_SQLITE = not DATABASE_URL or psycopg2 is None
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "devarshp610@gmail.com").strip().casefold()
DATABASE_PATH = os.environ.get("DATABASE_PATH", "garage_sale_finder.db")
scrape_lock = threading.Lock()

oauth = OAuth(app)

google = oauth.register(
    name='google',
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

def get_db():
    if USE_SQLITE or psycopg2 is None:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )

def init_db():
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
                finished_at TEXT
            )
        """)
        cur.execute("PRAGMA table_info(sales)")
        columns = {row[1] for row in cur.fetchall()}
        if "source_name" not in columns:
            cur.execute("ALTER TABLE sales ADD COLUMN source_name TEXT")
        if "source_url" not in columns:
            cur.execute("ALTER TABLE sales ADD COLUMN source_url TEXT")
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
                finished_at TIMESTAMP
            )
        """)
        cur.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS source_name TEXT")
        cur.execute("ALTER TABLE sales ADD COLUMN IF NOT EXISTS source_url TEXT")
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


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin(session.get("user")):
            return jsonify({"error": "Admin access required"}), 403
        return view(*args, **kwargs)
    return wrapped


def update_scrape_job(job_id, status, result_count=0, message=None):
    conn = get_db()
    cur = conn.cursor()
    if USE_SQLITE:
        cur.execute(
            """
            UPDATE scrape_jobs
            SET status = ?, result_count = ?, message = ?,
                finished_at = CASE WHEN ? = 'running' THEN NULL ELSE CURRENT_TIMESTAMP END
            WHERE id = ?
            """,
            (status, result_count, message, status, job_id)
        )
    else:
        cur.execute(
            """
            UPDATE scrape_jobs
            SET status = %s, result_count = %s, message = %s,
                finished_at = CASE WHEN %s = 'running' THEN NULL ELSE CURRENT_TIMESTAMP END
            WHERE id = %s
            """,
            (status, result_count, message, status, job_id)
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
        update_scrape_job(job_id, "completed", count, message)
    except Exception as exc:
        print(f"Scrape job {job_id} failed: {exc}", file=sys.stderr)
        update_scrape_job(job_id, "failed", 0, str(exc)[:500])
    finally:
        scrape_lock.release()

@app.route("/")
def home():
    user = session.get("user")
    return render_template("index.html", user=user)

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


@app.route("/admin")
def admin():
    user = session.get("user")
    if not user:
        return redirect(url_for("login"))
    if not is_admin(user):
        return "Admin access required", 403
    return render_template("admin.html", user=user)


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


@app.route("/api/admin/scrapes", methods=["POST"])
@admin_required
def start_scrape():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400
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
                "INSERT INTO scrape_jobs (location, status) VALUES (?, ?)",
                (location, "running")
            )
            job_id = cur.lastrowid
        else:
            cur.execute(
                "INSERT INTO scrape_jobs (location, status) VALUES (%s, %s) RETURNING id",
                (location, "running")
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

    threading.Thread(
        target=execute_scrape_job,
        args=(job_id, location, latitude, longitude, country_code),
        daemon=True,
        name=f"scrape-job-{job_id}"
    ).start()
    return jsonify({"id": job_id, "location": location, "status": "running"}), 202

@app.route("/api/sales", methods=["GET"])
def get_sales():
    conn = get_db()
    cur = conn.cursor()
    # Database hosts use UTC, which can already be tomorrow for local users.
    if USE_SQLITE:
        cur.execute("DELETE FROM sales WHERE date < date('now', '-1 day')")
    else:
        cur.execute("DELETE FROM sales WHERE date < (CURRENT_DATE - 1)::text")
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
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "Deleted!"})

with app.app_context():
    init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)