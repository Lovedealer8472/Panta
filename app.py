import mimetypes
import os
import sqlite3
import uuid
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-me")

DATABASE = os.path.join(app.root_path, "pantanakerfi.db")

ADMIN_PASSWORD_HASH = os.environ.get(
    "ADMIN_PASSWORD_HASH",
    generate_password_hash("pantanakerfi"),  # default for first run
)

# ── Workflow constants ──────────────────────────────────────────────

STATUSES = [
    "Undirbúningur",
    "Á bið",
    "Pantað",
    "Staðfest",
    "Komið",
    "Lokið",
]

PAYMENT_OPTIONS = ["Ógreitt", "Innborgun", "Greitt"]
CONTACT_OPTIONS = [
    "Ekki haft samband",
    "Haft samband",
    "Minnt á",
    "Næst ekki í viðskiptavin",
]
PRIORITY_OPTIONS = ["Venjulegt", "Mikilvægt", "Brýnt"]

# ── Attachments config ──────────────────────────────────────────────

UPLOAD_ROOT = os.path.join(app.root_path, "uploads")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB per file
ALLOWED_EXT = {
    "pdf",
    "jpg", "jpeg", "png", "heic", "webp", "gif",
    "docx", "xlsx", "pptx", "doc", "xls", "ppt",
    "txt", "csv",
}
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
os.makedirs(UPLOAD_ROOT, exist_ok=True)

# ── Database helpers ────────────────────────────────────────────────


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name       TEXT NOT NULL,
            phone               TEXT DEFAULT '',
            email               TEXT DEFAULT '',
            product_name        TEXT NOT NULL,
            product_model       TEXT DEFAULT '',
            supplier            TEXT DEFAULT '',
            status              TEXT NOT NULL DEFAULT 'Undirbúningur',
            date_requested      TEXT DEFAULT '',
            date_ordered        TEXT DEFAULT '',
            estimated_arrival   TEXT DEFAULT '',
            date_arrived        TEXT DEFAULT '',
            date_completed      TEXT DEFAULT '',
            payment_status      TEXT DEFAULT 'Ógreitt',
            contact_status      TEXT DEFAULT 'Ekki haft samband',
            priority            TEXT DEFAULT 'Venjulegt',
            notes               TEXT DEFAULT '',
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS attachments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id      INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            filename      TEXT NOT NULL,
            stored_name   TEXT NOT NULL,
            mime_type     TEXT NOT NULL,
            size_bytes    INTEGER NOT NULL,
            uploaded_by   TEXT NOT NULL DEFAULT 'admin',
            uploaded_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attachments_order ON attachments(order_id);
        """
    )
    db.commit()


@app.cli.command("init-db")
def init_db_command():
    """Create the database tables."""
    with app.app_context():
        init_db()
    print("Database initialized.")


# Auto-init on first request
with app.app_context():
    _conn = sqlite3.connect(DATABASE)
    _conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name       TEXT NOT NULL,
            phone               TEXT DEFAULT '',
            email               TEXT DEFAULT '',
            product_name        TEXT NOT NULL,
            product_model       TEXT DEFAULT '',
            supplier            TEXT DEFAULT '',
            status              TEXT NOT NULL DEFAULT 'Undirbúningur',
            date_requested      TEXT DEFAULT '',
            date_ordered        TEXT DEFAULT '',
            estimated_arrival   TEXT DEFAULT '',
            date_arrived        TEXT DEFAULT '',
            date_completed      TEXT DEFAULT '',
            payment_status      TEXT DEFAULT 'Ógreitt',
            contact_status      TEXT DEFAULT 'Ekki haft samband',
            priority            TEXT DEFAULT 'Venjulegt',
            notes               TEXT DEFAULT '',
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS attachments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id      INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            filename      TEXT NOT NULL,
            stored_name   TEXT NOT NULL,
            mime_type     TEXT NOT NULL,
            size_bytes    INTEGER NOT NULL,
            uploaded_by   TEXT NOT NULL DEFAULT 'admin',
            uploaded_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_attachments_order ON attachments(order_id);
        """
    )
    _conn.commit()
    _conn.close()

# ── Auth helpers ────────────────────────────────────────────────────


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated


# ── Routes: Auth ────────────────────────────────────────────────────


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["logged_in"] = True
            return redirect(url_for("board"))
        flash("Rangt lykilorð.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── Routes: Board ───────────────────────────────────────────────────


@app.route("/")
@login_required
def board():
    db = get_db()
    query = request.args.get("q", "").strip()

    if query:
        like = f"%{query}%"
        rows = db.execute(
            """
            SELECT * FROM orders
            WHERE customer_name LIKE ?
               OR phone LIKE ?
               OR email LIKE ?
               OR product_name LIKE ?
               OR product_model LIKE ?
               OR supplier LIKE ?
               OR notes LIKE ?
            ORDER BY
                CASE priority
                    WHEN 'Brýnt' THEN 0
                    WHEN 'Mikilvægt' THEN 1
                    ELSE 2
                END,
                created_at DESC
            """,
            (like, like, like, like, like, like, like),
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT * FROM orders
            ORDER BY
                CASE priority
                    WHEN 'Brýnt' THEN 0
                    WHEN 'Mikilvægt' THEN 1
                    ELSE 2
                END,
                created_at DESC
            """
        ).fetchall()

    columns = {s: [] for s in STATUSES}
    for row in rows:
        status = row["status"]
        if status in columns:
            columns[status].append(row)

    today = datetime.now().strftime("%Y-%m-%d")
    return render_template(
        "board.html",
        columns=columns,
        statuses=STATUSES,
        query=query,
        today=today,
    )


# ── Routes: Create order ───────────────────────────────────────────


@app.route("/order/new", methods=["GET", "POST"])
@login_required
def order_new():
    if request.method == "POST":
        now = datetime.now().isoformat(timespec="seconds")
        db = get_db()
        db.execute(
            """
            INSERT INTO orders
                (customer_name, phone, email, product_name, product_model,
                 supplier, status, date_requested, date_ordered,
                 estimated_arrival, date_arrived, date_completed,
                 payment_status, contact_status, priority, notes,
                 created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                request.form["customer_name"].strip(),
                request.form.get("phone", "").strip(),
                request.form.get("email", "").strip(),
                request.form["product_name"].strip(),
                request.form.get("product_model", "").strip(),
                request.form.get("supplier", "").strip(),
                "Undirbúningur",
                request.form.get("date_requested", ""),
                "",
                "",
                "",
                "",
                request.form.get("payment_status", "Ógreitt"),
                "Ekki haft samband",
                request.form.get("priority", "Venjulegt"),
                request.form.get("notes", "").strip(),
                now,
                now,
            ),
        )
        db.commit()
        flash("Pöntun búin til.", "success")
        return redirect(url_for("board"))

    today = datetime.now().strftime("%Y-%m-%d")
    return render_template(
        "order_form.html",
        order=None,
        statuses=STATUSES,
        payment_options=PAYMENT_OPTIONS,
        contact_options=CONTACT_OPTIONS,
        priority_options=PRIORITY_OPTIONS,
        today=today,
    )


# ── Routes: View order detail ──────────────────────────────────────


@app.route("/order/<int:order_id>")
@login_required
def order_detail(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        abort(404)

    today = datetime.now().strftime("%Y-%m-%d")
    status_idx = STATUSES.index(order["status"]) if order["status"] in STATUSES else 0
    return render_template(
        "order_detail.html",
        order=order,
        statuses=STATUSES,
        status_idx=status_idx,
        payment_options=PAYMENT_OPTIONS,
        contact_options=CONTACT_OPTIONS,
        priority_options=PRIORITY_OPTIONS,
        today=today,
    )


# ── Routes: Edit order ─────────────────────────────────────────────


@app.route("/order/<int:order_id>/edit", methods=["GET", "POST"])
@login_required
def order_edit(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        abort(404)

    if request.method == "POST":
        now = datetime.now().isoformat(timespec="seconds")
        db.execute(
            """
            UPDATE orders SET
                customer_name=?, phone=?, email=?, product_name=?,
                product_model=?, supplier=?, status=?,
                date_requested=?, date_ordered=?, estimated_arrival=?,
                date_arrived=?, date_completed=?,
                payment_status=?, contact_status=?, priority=?, notes=?,
                updated_at=?
            WHERE id=?
            """,
            (
                request.form["customer_name"].strip(),
                request.form.get("phone", "").strip(),
                request.form.get("email", "").strip(),
                request.form["product_name"].strip(),
                request.form.get("product_model", "").strip(),
                request.form.get("supplier", "").strip(),
                request.form.get("status", order["status"]),
                request.form.get("date_requested", ""),
                request.form.get("date_ordered", ""),
                request.form.get("estimated_arrival", ""),
                request.form.get("date_arrived", ""),
                request.form.get("date_completed", ""),
                request.form.get("payment_status", "Ógreitt"),
                request.form.get("contact_status", "Ekki haft samband"),
                request.form.get("priority", "Venjulegt"),
                request.form.get("notes", "").strip(),
                now,
                order_id,
            ),
        )
        db.commit()
        flash("Pöntun uppfærð.", "success")
        return redirect(url_for("board"))

    today = datetime.now().strftime("%Y-%m-%d")
    return render_template(
        "order_form.html",
        order=order,
        statuses=STATUSES,
        payment_options=PAYMENT_OPTIONS,
        contact_options=CONTACT_OPTIONS,
        priority_options=PRIORITY_OPTIONS,
        today=today,
    )


# ── Routes: Delete order ───────────────────────────────────────────


@app.route("/order/<int:order_id>/delete", methods=["POST"])
@login_required
def order_delete(order_id):
    db = get_db()
    db.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    db.commit()
    flash("Pöntun eytt.", "success")
    return redirect(url_for("board"))


# ── Routes: Quick status change ────────────────────────────────────


@app.route("/order/<int:order_id>/status", methods=["POST"])
@login_required
def order_status(order_id):
    new_status = request.form.get("status", "")
    if new_status not in STATUSES:
        abort(400)

    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        abort(404)

    now = datetime.now().isoformat(timespec="seconds")
    extra_updates = ""
    params = [new_status, now]

    if new_status == "Lokið" and not order["date_completed"]:
        extra_updates = ", date_completed=?"
        params.append(datetime.now().strftime("%Y-%m-%d"))

    params.append(order_id)
    db.execute(
        f"UPDATE orders SET status=?, updated_at=?{extra_updates} WHERE id=?",
        params,
    )
    db.commit()
    return redirect(url_for("board"))


# ── Routes: Quick contact-status change ────────────────────────────


@app.route("/order/<int:order_id>/contact_status", methods=["POST"])
@login_required
def order_contact_status(order_id):
    new_value = request.form.get("contact_status", "")
    if new_value not in CONTACT_OPTIONS:
        abort(400)

    db = get_db()
    order = db.execute("SELECT id FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        abort(404)

    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "UPDATE orders SET contact_status=?, updated_at=? WHERE id=?",
        (new_value, now, order_id),
    )
    db.commit()
    return redirect(url_for("order_detail", order_id=order_id))


# ── Routes: Attachments ────────────────────────────────────────────


def _allowed(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def _order_upload_dir(order_id: int) -> str:
    path = os.path.join(UPLOAD_ROOT, str(order_id))
    os.makedirs(path, exist_ok=True)
    return path


def _attachment_payload(row, order_id):
    return {
        "id": row["id"],
        "filename": row["filename"],
        "size_bytes": row["size_bytes"],
        "mime_type": row["mime_type"],
        "uploaded_at": row["uploaded_at"],
        "url": url_for("attachment_download", order_id=order_id, att_id=row["id"]),
        "delete_url": url_for(
            "attachment_delete", order_id=order_id, att_id=row["id"]
        ),
    }


@app.route("/order/<int:order_id>/attachments", methods=["GET"])
@login_required
def attachment_list(order_id):
    db = get_db()
    order = db.execute("SELECT id FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        abort(404)
    rows = db.execute(
        "SELECT * FROM attachments WHERE order_id = ? ORDER BY uploaded_at DESC, id DESC",
        (order_id,),
    ).fetchall()
    return jsonify([_attachment_payload(r, order_id) for r in rows])


@app.route("/order/<int:order_id>/attachments", methods=["POST"])
@login_required
def attachment_upload(order_id):
    db = get_db()
    order = db.execute("SELECT id FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        abort(404)

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "Engar skrár sendar."}), 400

    target_dir = _order_upload_dir(order_id)
    now = datetime.now().isoformat(timespec="seconds")
    saved, rejected = [], []

    for fs in files:
        original = fs.filename or ""
        if not _allowed(original):
            rejected.append(
                {"filename": original, "reason": "Tegund ekki leyfð."}
            )
            continue

        safe_name = secure_filename(original) or "file"
        ext = safe_name.rsplit(".", 1)[1].lower() if "." in safe_name else "bin"
        stored_name = f"{uuid.uuid4().hex}.{ext}"
        dest = os.path.join(target_dir, stored_name)
        fs.save(dest)
        try:
            os.chmod(dest, 0o640)
        except OSError:
            pass

        size_bytes = os.path.getsize(dest)
        mime_type = (
            fs.mimetype
            or mimetypes.guess_type(safe_name)[0]
            or "application/octet-stream"
        )

        cur = db.execute(
            """
            INSERT INTO attachments
                (order_id, filename, stored_name, mime_type,
                 size_bytes, uploaded_by, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (order_id, safe_name, stored_name, mime_type, size_bytes, "admin", now),
        )
        att_id = cur.lastrowid
        row = db.execute(
            "SELECT * FROM attachments WHERE id = ?", (att_id,)
        ).fetchone()
        saved.append(_attachment_payload(row, order_id))

    db.commit()
    return jsonify({"saved": saved, "rejected": rejected})


@app.route("/order/<int:order_id>/attachments/<int:att_id>")
@login_required
def attachment_download(order_id, att_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM attachments WHERE id = ? AND order_id = ?",
        (att_id, order_id),
    ).fetchone()
    if row is None:
        abort(404)
    download = request.args.get("download") == "1"
    return send_from_directory(
        _order_upload_dir(order_id),
        row["stored_name"],
        as_attachment=download,
        download_name=row["filename"],
        mimetype=row["mime_type"],
    )


@app.route("/order/<int:order_id>/attachments/<int:att_id>/delete", methods=["POST"])
@login_required
def attachment_delete(order_id, att_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM attachments WHERE id = ? AND order_id = ?",
        (att_id, order_id),
    ).fetchone()
    if row is None:
        abort(404)

    file_path = os.path.join(_order_upload_dir(order_id), row["stored_name"])
    try:
        os.remove(file_path)
    except FileNotFoundError:
        pass

    db.execute("DELETE FROM attachments WHERE id = ?", (att_id,))
    db.commit()

    wants_json = (
        request.headers.get("Accept", "").startswith("application/json")
        or request.headers.get("X-Requested-With") == "fetch"
    )
    if wants_json:
        return jsonify({"ok": True})

    flash("Viðhengi eytt.", "success")
    return redirect(url_for("order_detail", order_id=order_id))


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "Skrá er of stór, hámark 25 MB."}), 413


# ── Run ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    if debug:
        app.run(host=host, port=port, debug=True)
    else:
        from waitress import serve

        print(f"Pantanakerfi running on http://{host}:{port}")
        serve(app, host=host, port=port, threads=4)
