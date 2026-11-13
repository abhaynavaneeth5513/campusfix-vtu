"""CampusFix: a campus complaint tracker for a VTU CSE DevOps project."""

import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Flask,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

CATEGORIES = ("Wi-Fi", "Classroom", "Laboratory", "Infrastructure", "Other")
STATUSES = ("Pending", "In Progress", "Resolved")
CATEGORY_SET = frozenset(CATEGORIES)
STATUS_SET = frozenset(STATUSES)
ADMIN_USERNAME = "admin"

# Used only when the environment variables are missing. Local testing only.
DEV_ADMIN_PASSWORD = "campusfix-dev"
DEV_SECRET_KEY = "campusfix-local-dev-secret-change-me"

EMPTY_STATS = {"total": 0, "Pending": 0, "In Progress": 0, "Resolved": 0}


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    env_secret = os.environ.get("CAMPUSFIX_SECRET_KEY") or None
    env_password = os.environ.get("CAMPUSFIX_ADMIN_PASSWORD") or None
    secret = env_secret or DEV_SECRET_KEY
    password = env_password or DEV_ADMIN_PASSWORD
    using_dev_secret = env_secret is None
    using_dev_password = env_password is None
    database = os.environ.get("CAMPUSFIX_DATABASE") or os.path.join(
        app.instance_path, "campusfix.db"
    )

    app.config.from_mapping(
        SECRET_KEY=secret,
        DATABASE=database,
        USING_DEV_SECRET=using_dev_secret,
        USING_DEV_PASSWORD=using_dev_password,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("CAMPUSFIX_COOKIE_SECURE") == "1",
        MAX_CONTENT_LENGTH=64 * 1024,
    )

    if test_config:
        password_override = test_config.get("ADMIN_PASSWORD")
        safe_config = {
            key: value for key, value in test_config.items() if key != "ADMIN_PASSWORD"
        }
        app.config.update(safe_config)
        if "ADMIN_PASSWORD" in test_config:
            if not isinstance(password_override, str) or len(password_override) < 8:
                raise ValueError("Test ADMIN_PASSWORD must be a string of at least 8 characters.")
            password = password_override
            app.config["USING_DEV_PASSWORD"] = False
        if "SECRET_KEY" in test_config:
            app.config["USING_DEV_SECRET"] = False

    app.config["ADMIN_PASSWORD_HASH"] = generate_password_hash(password)

    database_dir = os.path.dirname(app.config["DATABASE"])
    if database_dir:
        os.makedirs(database_dir, exist_ok=True)

    @app.teardown_appcontext
    def close_db(_error):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    with app.app_context():
        init_db()

    if app.config["USING_DEV_SECRET"] or app.config["USING_DEV_PASSWORD"]:
        app.logger.warning(
            "CampusFix is using local development defaults. "
            "Set CAMPUSFIX_SECRET_KEY and CAMPUSFIX_ADMIN_PASSWORD "
            "before any shared or production use."
        )

    register_routes(app)
    return app


def get_db():
    if "db" not in g:
        connection = sqlite3.connect(current_app.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        g.db = connection
    return g.db


def init_db():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL CHECK (length(trim(title)) > 0),
            description TEXT NOT NULL CHECK (length(trim(description)) > 0),
            category TEXT NOT NULL CHECK (
                category IN ('Wi-Fi', 'Classroom', 'Laboratory', 'Infrastructure', 'Other')
            ),
            status TEXT NOT NULL CHECK (
                status IN ('Pending', 'In Progress', 'Resolved')
            ),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    db.commit()


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def allow(value, choices):
    return value if value in choices else ""


def safe_compare(left, right):
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    if not left or not right or len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def csrf_valid():
    expected = session.get("csrf_token")
    provided = request.form.get("csrf_token", "")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    return safe_compare(expected, provided)


def validate_complaint(title, description, category):
    clean_title = " ".join((title or "").replace("\x00", "").split())
    clean_description = (description or "").replace("\x00", "").strip()
    clean_category = (category or "").strip()
    errors = []

    if not clean_title:
        errors.append("Title is required.")
    elif len(clean_title) < 3:
        errors.append("Title must be at least 3 characters.")
    elif len(clean_title) > 120:
        errors.append("Title must be 120 characters or fewer.")

    if not clean_description:
        errors.append("Description is required.")
    elif len(clean_description) < 10:
        errors.append("Description must be at least 10 characters.")
    elif len(clean_description) > 2000:
        errors.append("Description must be 2000 characters or fewer.")

    if clean_category not in CATEGORY_SET:
        errors.append("Select a valid category.")
        clean_category = ""

    return errors, clean_title, clean_description, clean_category


def list_complaints(category="", status=""):
    clauses = []
    params = []
    if category in CATEGORY_SET:
        clauses.append("category = ?")
        params.append(category)
    if status in STATUS_SET:
        clauses.append("status = ?")
        params.append(status)

    sql = (
        "SELECT id, title, description, category, status, created_at, updated_at "
        "FROM complaints"
    )
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC"

    return get_db().execute(sql, params).fetchall()


def complaint_stats():
    counts = dict(EMPTY_STATS)
    rows = get_db().execute(
        "SELECT status, COUNT(*) AS count FROM complaints GROUP BY status"
    ).fetchall()
    for row in rows:
        if row["status"] in STATUS_SET:
            counts[row["status"]] = row["count"]
    counts["total"] = counts["Pending"] + counts["In Progress"] + counts["Resolved"]
    return counts


def insert_complaint(title, description, category):
    now = utc_now()
    cursor = get_db().execute(
        """
        INSERT INTO complaints (title, description, category, status, created_at, updated_at)
        VALUES (?, ?, ?, 'Pending', ?, ?)
        """,
        (title, description, category, now, now),
    )
    get_db().commit()
    return cursor.lastrowid


def update_complaint_status(complaint_id, status):
    cursor = get_db().execute(
        "UPDATE complaints SET status = ?, updated_at = ? WHERE id = ?",
        (status, utc_now(), complaint_id),
    )
    get_db().commit()
    return cursor.rowcount == 1


def register_routes(app):
    def reject_csrf():
        flash("The form expired. Refresh the page and try again.", "danger")
        if request.path.startswith("/admin"):
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("index"))

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("is_admin"):
                flash("Sign in as admin to update complaints.", "warning")
                return redirect(url_for("admin_dashboard"))
            return view(*args, **kwargs)

        return wrapped

    def index_context(form=None):
        selected_category = allow(request.args.get("category", ""), CATEGORY_SET)
        selected_status = allow(request.args.get("status", ""), STATUS_SET)
        return {
            "complaints": list_complaints(selected_category, selected_status),
            "stats": complaint_stats(),
            "form": form or {"title": "", "description": "", "category": ""},
            "selected_category": selected_category,
            "selected_status": selected_status,
        }

    def admin_context():
        is_admin = bool(session.get("is_admin"))
        selected_category = allow(request.args.get("category", ""), CATEGORY_SET)
        selected_status = allow(request.args.get("status", ""), STATUS_SET)
        if is_admin:
            complaints = list_complaints(selected_category, selected_status)
            stats = complaint_stats()
        else:
            complaints = []
            stats = dict(EMPTY_STATS)
        return {
            "is_admin": is_admin,
            "complaints": complaints,
            "stats": stats,
            "selected_category": selected_category,
            "selected_status": selected_status,
        }

    @app.context_processor
    def inject_template_globals():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(32)
        return {
            "csrf_token": session["csrf_token"],
            "categories": CATEGORIES,
            "statuses": STATUSES,
            "using_dev_defaults": (
                current_app.config["USING_DEV_SECRET"]
                or current_app.config["USING_DEV_PASSWORD"]
            ),
        }

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "object-src 'none'"
        )
        return response

    @app.get("/health")
    def health():
        return jsonify({"status": "healthy"})

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    @app.get("/")
    def index():
        return render_template("index.html", **index_context())

    @app.post("/complaints")
    def submit_complaint():
        if not csrf_valid():
            return reject_csrf()

        errors, title, description, category = validate_complaint(
            request.form.get("title", ""),
            request.form.get("description", ""),
            request.form.get("category", ""),
        )
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template(
                "index.html",
                **index_context(
                    {"title": title, "description": description, "category": category}
                ),
            ), 400

        complaint_id = insert_complaint(title, description, category)
        flash(f"Complaint CF-{complaint_id:03d} submitted.", "success")
        return redirect(url_for("index"))

    @app.get("/admin")
    def admin_dashboard():
        response = app.make_response(render_template("admin.html", **admin_context()))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/admin/login")
    def admin_login():
        if not csrf_valid():
            return reject_csrf()

        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        username_ok = safe_compare(username, ADMIN_USERNAME)
        password_ok = check_password_hash(
            current_app.config["ADMIN_PASSWORD_HASH"], password
        )
        if not (username_ok and password_ok):
            flash("Invalid username or password.", "danger")
            return render_template("admin.html", **admin_context()), 401

        session.clear()
        session["is_admin"] = True
        session["csrf_token"] = secrets.token_hex(32)
        flash("Signed in to the admin dashboard.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.post("/admin/logout")
    def admin_logout():
        if not csrf_valid():
            return reject_csrf()
        session.clear()
        flash("Signed out.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.post("/admin/complaints/<int:complaint_id>/status")
    @admin_required
    def update_status(complaint_id):
        if not csrf_valid():
            return reject_csrf()

        status = (request.form.get("status") or "").strip()
        if status not in STATUS_SET:
            flash("Choose a valid status: Pending, In Progress, or Resolved.", "danger")
            return redirect(url_for("admin_dashboard"))

        if not update_complaint_status(complaint_id, status):
            flash("That complaint could not be found.", "danger")
            return redirect(url_for("admin_dashboard"))

        flash(f"Complaint CF-{complaint_id:03d} marked {status}.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.errorhandler(413)
    def request_too_large(_error):
        flash("That submission is too large.", "danger")
        return redirect(url_for("index"))


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
