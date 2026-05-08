import os
import sqlite3
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

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
