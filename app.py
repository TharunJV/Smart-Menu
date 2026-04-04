from flask import (Flask, render_template, request, redirect,
                   url_for, flash, jsonify, session)
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, functools
from datetime import date

app = Flask(__name__)
app.secret_key = "smartmenu_secret_2024"

DB = os.path.join(os.path.dirname(__file__), "menu.db")
SESSIONS = ["breakfast", "lunch", "snacks", "dinner"]
SESSION_ICONS = {
    "breakfast": "🌅",
    "lunch":     "☀️",
    "snacks":    "🍎",
    "dinner":    "🌙"
}

# ── DB ────────────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS user (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                roll_no    TEXT NOT NULL UNIQUE,
                password   TEXT NOT NULL,
                role       TEXT NOT NULL DEFAULT 'student',
                created_at TEXT DEFAULT (date('now'))
            );
            CREATE TABLE IF NOT EXISTS menu (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                date    TEXT NOT NULL,
                session TEXT NOT NULL,
                UNIQUE(date, session)
            );
            CREATE TABLE IF NOT EXISTS dish (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                menu_id   INTEGER NOT NULL REFERENCES menu(id) ON DELETE CASCADE,
                dish_name TEXT NOT NULL,
                UNIQUE(menu_id, dish_name)
            );
            CREATE TABLE IF NOT EXISTS vote (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                dish_id INTEGER NOT NULL REFERENCES dish(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
                UNIQUE(dish_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS comment (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                dish_id    INTEGER NOT NULL REFERENCES dish(id) ON DELETE CASCADE,
                user_id    INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
                body       TEXT NOT NULL,
                rating     INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS vote_lock (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
                date      TEXT NOT NULL,
                locked_at TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(user_id, date)
            );
        """)
        # Migrate old vote table ip→user_id
        cols = [r[1] for r in conn.execute("PRAGMA table_info(vote)").fetchall()]
        if "ip" in cols:
            conn.executescript("""
                DROP TABLE vote;
                CREATE TABLE vote (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    dish_id INTEGER NOT NULL REFERENCES dish(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
                    UNIQUE(dish_id, user_id)
                );
            """)

    with get_db() as conn:
        if not conn.execute("SELECT id FROM user WHERE role='admin'").fetchone():
            conn.execute(
                "INSERT INTO user (name, roll_no, password, role) VALUES (?,?,?,?)",
                ("Admin", "admin", generate_password_hash("admin123"), "admin")
            )

init_db()

# ── DECORATORS ────────────────────────────────────────────────────────────────

def login_required(f):
    @functools.wraps(f)
    def d(*a, **kw):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return d

def admin_required(f):
    @functools.wraps(f)
    def d(*a, **kw):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        if session.get("role") != "admin":
            flash("⛔ Admin access only.", "error")
            return redirect(url_for("home"))
        return f(*a, **kw)
    return d

# ── HELPERS ───────────────────────────────────────────────────────────────────

def get_menu_for_date(target_date):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT m.session, d.id AS dish_id, d.dish_name,
                   COUNT(v.id) AS votes
            FROM   menu m
            JOIN   dish d  ON d.menu_id = m.id
            LEFT JOIN vote v ON v.dish_id = d.id
            WHERE  m.date = ?
            GROUP  BY d.id
            ORDER  BY m.session, votes DESC, d.dish_name
        """, (target_date,)).fetchall()
    result = {s: [] for s in SESSIONS}
    for r in rows:
        result[r["session"]].append({
            "id": r["dish_id"], "dish_name": r["dish_name"], "votes": r["votes"]
        })
    return result

def get_user_votes(target_date, user_id):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT v.dish_id FROM vote v
            JOIN dish d ON d.id = v.dish_id
            JOIN menu m ON m.id = d.menu_id
            WHERE m.date = ? AND v.user_id = ?
        """, (target_date, user_id)).fetchall()
    return {r["dish_id"] for r in rows}

def get_vote_count(dish_id):
    with get_db() as conn:
        return conn.execute(
            "SELECT COUNT(*) c FROM vote WHERE dish_id=?", (dish_id,)
        ).fetchone()["c"]

# ── AUTH ──────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET","POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("home"))
    if request.method == "POST":
        roll_no  = request.form.get("roll_no","").strip()
        password = request.form.get("password","").strip()
        if not roll_no or not password:
            flash("Please fill in all fields.", "error")
            return redirect(url_for("login"))
        with get_db() as conn:
            user = conn.execute("SELECT * FROM user WHERE roll_no=?", (roll_no,)).fetchone()
        if user and check_password_hash(user["password"], password):
            session.update(user_id=user["id"], user_name=user["name"],
                           roll_no=user["roll_no"], role=user["role"])
            flash(f"👋 Welcome back, {user['name']}!", "success")
            return redirect(request.form.get("next") or url_for("home"))
        flash("❌ Invalid Roll No or Password.", "error")
        return redirect(url_for("login"))
    return render_template("login.html", next=request.args.get("next",""))

@app.route("/register", methods=["GET","POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("home"))
    if request.method == "POST":
        name     = request.form.get("name","").strip()
        roll_no  = request.form.get("roll_no","").strip()
        password = request.form.get("password","").strip()
        confirm  = request.form.get("confirm","").strip()
        if not all([name, roll_no, password, confirm]):
            flash("Please fill in all fields.", "error"); return redirect(url_for("register"))
        if password != confirm:
            flash("Passwords do not match.", "error"); return redirect(url_for("register"))
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error"); return redirect(url_for("register"))
        try:
            with get_db() as conn:
                conn.execute("INSERT INTO user (name,roll_no,password,role) VALUES (?,?,?,?)",
                             (name, roll_no, generate_password_hash(password), "student"))
            flash("✅ Account created! Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("⚠️ Roll No already registered.", "error")
            return redirect(url_for("register"))
    return render_template("register.html")

@app.route("/logout")
def logout():
    name = session.get("user_name","")
    session.clear()
    flash(f"👋 See you later, {name}!", "success")
    return redirect(url_for("login"))

# ── PROFILE ───────────────────────────────────────────────────────────────────

@app.route("/profile", methods=["GET","POST"])
@login_required
def profile():
    user_id = session["user_id"]
    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_name":
            name = request.form.get("name","").strip()
            if not name:
                flash("Name cannot be empty.", "error")
            else:
                with get_db() as conn:
                    conn.execute("UPDATE user SET name=? WHERE id=?", (name, user_id))
                session["user_name"] = name
                flash("✅ Name updated!", "success")

        elif action == "change_password":
            current  = request.form.get("current_password","")
            new_pwd  = request.form.get("new_password","")
            confirm  = request.form.get("confirm_password","")
            with get_db() as conn:
                user = conn.execute("SELECT password FROM user WHERE id=?", (user_id,)).fetchone()
            if not check_password_hash(user["password"], current):
                flash("❌ Current password is incorrect.", "error")
            elif new_pwd != confirm:
                flash("New passwords do not match.", "error")
            elif len(new_pwd) < 6:
                flash("Password must be at least 6 characters.", "error")
            else:
                with get_db() as conn:
                    conn.execute("UPDATE user SET password=? WHERE id=?",
                                 (generate_password_hash(new_pwd), user_id))
                flash("✅ Password changed successfully!", "success")

        return redirect(url_for("profile"))

    with get_db() as conn:
        user = conn.execute("SELECT * FROM user WHERE id=?", (user_id,)).fetchone()
        vote_count = conn.execute("""
            SELECT COUNT(*) c FROM vote WHERE user_id=?
        """, (user_id,)).fetchone()["c"]
        comment_count = conn.execute(
            "SELECT COUNT(*) c FROM comment WHERE user_id=?", (user_id,)
        ).fetchone()["c"]
        # Recent votes with dish names
        recent_votes = conn.execute("""
            SELECT d.dish_name, m.date, m.session
            FROM vote v
            JOIN dish d ON d.id = v.dish_id
            JOIN menu m ON m.id = d.menu_id
            WHERE v.user_id = ?
            ORDER BY m.date DESC LIMIT 5
        """, (user_id,)).fetchall()

    return render_template("profile.html", user=user,
                           vote_count=vote_count, comment_count=comment_count,
                           recent_votes=recent_votes)

# ── HOME ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("home"))

@app.route("/home")
@login_required
def home():
    today    = date.today().isoformat()
    menu     = get_menu_for_date(today)
    has_menu = any(menu[s] for s in SESSIONS)
    return render_template("home.html", menu=menu, sessions=SESSIONS,
                           icons=SESSION_ICONS, today=today, has_menu=has_menu)

# ── VOTE ──────────────────────────────────────────────────────────────────────

@app.route("/vote")
@login_required
def vote_page():
    selected_date = request.args.get("date", date.today().isoformat())
    menu     = get_menu_for_date(selected_date)
    user_id  = session["user_id"]
    voted    = get_user_votes(selected_date, user_id)
    has_menu = any(menu[s] for s in SESSIONS)
    with get_db() as conn:
        dates = [r["date"] for r in conn.execute(
            "SELECT DISTINCT date FROM menu ORDER BY date DESC").fetchall()]
        leaderboard = conn.execute("""
            SELECT d.dish_name, COUNT(v.id) AS total_votes, m.session
            FROM dish d
            JOIN vote v ON v.dish_id = d.id
            JOIN menu m ON m.id = d.menu_id
            GROUP BY d.id ORDER BY total_votes DESC LIMIT 5
        """).fetchall()
        lock_row = conn.execute(
            "SELECT locked_at FROM vote_lock WHERE user_id=? AND date=?",
            (user_id, selected_date)
        ).fetchone()
    is_locked  = lock_row is not None
    locked_at  = lock_row["locked_at"] if lock_row else None
    return render_template("vote.html", menu=menu, sessions=SESSIONS,
                           icons=SESSION_ICONS, voted=voted,
                           selected_date=selected_date, dates=dates,
                           has_menu=has_menu, leaderboard=leaderboard,
                           is_locked=is_locked, locked_at=locked_at)

@app.route("/vote/save", methods=["POST"])
@login_required
def save_votes():
    target_date = request.form.get("date", "").strip()
    user_id     = session["user_id"]
    if not target_date:
        return jsonify(success=False, error="No date provided"), 400
    # Check user actually voted for something
    voted = get_user_votes(target_date, user_id)
    if not voted:
        return jsonify(success=False, error="You haven't voted for any dish yet!"), 400
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO vote_lock (user_id, date) VALUES (?,?)",
                (user_id, target_date)
            )
        return jsonify(success=True)
    except sqlite3.IntegrityError:
        return jsonify(success=False, error="Already saved."), 400

@app.route("/vote/cast", methods=["POST"])
@login_required
def cast_vote():
    dish_id     = request.form.get("dish_id", type=int)
    target_date = request.form.get("date", "").strip()
    user_id     = session["user_id"]
    if not dish_id:
        return jsonify(success=False, error="Invalid dish"), 400
    # Block if votes are locked for this date
    with get_db() as conn:
        locked = conn.execute(
            "SELECT id FROM vote_lock WHERE user_id=? AND date=?",
            (user_id, target_date)
        ).fetchone()
    if locked:
        return jsonify(success=False, error="Your votes are locked for this date."), 403
    try:
        with get_db() as conn:
            conn.execute("INSERT INTO vote (dish_id, user_id) VALUES (?,?)", (dish_id, user_id))
        return jsonify(success=True, votes=get_vote_count(dish_id))
    except sqlite3.IntegrityError:
        with get_db() as conn:
            conn.execute("DELETE FROM vote WHERE dish_id=? AND user_id=?", (dish_id, user_id))
        return jsonify(success=True, votes=get_vote_count(dish_id), removed=True)

# ── COMMENTS ──────────────────────────────────────────────────────────────────

@app.route("/dish/<int:dish_id>/comments")
@login_required
def get_comments(dish_id):
    with get_db() as conn:
        rows = conn.execute("""
            SELECT c.id, c.body, c.rating, c.created_at, u.name, u.role,
                   (c.user_id = ?) AS is_mine
            FROM comment c JOIN user u ON u.id = c.user_id
            WHERE c.dish_id = ?
            ORDER BY c.created_at DESC
        """, (session["user_id"], dish_id)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/dish/<int:dish_id>/comment", methods=["POST"])
@login_required
def add_comment(dish_id):
    body   = request.form.get("body","").strip()
    rating = request.form.get("rating", 0, type=int)
    if not body:
        return jsonify(success=False, error="Comment cannot be empty"), 400
    rating = max(0, min(5, rating))
    with get_db() as conn:
        conn.execute(
            "INSERT INTO comment (dish_id, user_id, body, rating) VALUES (?,?,?,?)",
            (dish_id, session["user_id"], body, rating)
        )
    return jsonify(success=True)

@app.route("/comment/<int:cid>/delete", methods=["POST"])
@login_required
def delete_comment(cid):
    user_id = session["user_id"]
    with get_db() as conn:
        c = conn.execute("SELECT user_id FROM comment WHERE id=?", (cid,)).fetchone()
        if c and (c["user_id"] == user_id or session["role"] == "admin"):
            conn.execute("DELETE FROM comment WHERE id=?", (cid,))
            return jsonify(success=True)
    return jsonify(success=False, error="Not allowed"), 403

# ── ADMIN ─────────────────────────────────────────────────────────────────────

@app.route("/admin", methods=["GET","POST"])
@admin_required
def admin():
    if request.method == "POST":
        menu_date = request.form.get("date","").strip()
        if not menu_date:
            flash("Please select a date.", "error"); return redirect(url_for("admin"))
        saved_any = False
        with get_db() as conn:
            for s in SESSIONS:
                dishes = [d.strip() for d in request.form.getlist(f"{s}[]") if d.strip()]
                if not dishes: continue
                conn.execute("INSERT OR IGNORE INTO menu (date,session) VALUES (?,?)", (menu_date, s))
                mid = conn.execute("SELECT id FROM menu WHERE date=? AND session=?",
                                   (menu_date, s)).fetchone()["id"]
                for dish in dishes:
                    conn.execute("INSERT OR IGNORE INTO dish (menu_id,dish_name) VALUES (?,?)", (mid, dish))
                    saved_any = True
        flash(f"✅ Menu saved for {menu_date}!" if saved_any else "⚠️ No new dishes added.",
              "success" if saved_any else "warning")
        return redirect(url_for("admin"))

    with get_db() as conn:
        recent        = [r["date"] for r in conn.execute(
            "SELECT DISTINCT date FROM menu ORDER BY date DESC LIMIT 10").fetchall()]
        student_count = conn.execute("SELECT COUNT(*) c FROM user WHERE role='student'").fetchone()["c"]
    return render_template("admin.html", sessions=SESSIONS, icons=SESSION_ICONS,
                           recent=recent, today=date.today().isoformat(),
                           student_count=student_count)

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    with get_db() as conn:
        student_count = conn.execute(
            "SELECT COUNT(*) c FROM user WHERE role='student'").fetchone()["c"]
        total_votes   = conn.execute("SELECT COUNT(*) c FROM vote").fetchone()["c"]
        total_dishes  = conn.execute("SELECT COUNT(*) c FROM dish").fetchone()["c"]
        total_menus   = conn.execute("SELECT COUNT(DISTINCT date) c FROM menu").fetchone()["c"]

        # Top 10 voted dishes ever
        top_dishes = conn.execute("""
            SELECT d.dish_name, m.session, COUNT(v.id) AS votes
            FROM dish d
            JOIN menu m ON m.id = d.menu_id
            LEFT JOIN vote v ON v.dish_id = d.id
            GROUP BY d.id ORDER BY votes DESC LIMIT 10
        """).fetchall()

        # Votes per session (all time)
        session_votes = conn.execute("""
            SELECT m.session, COUNT(v.id) AS votes
            FROM menu m
            JOIN dish d ON d.menu_id = m.id
            LEFT JOIN vote v ON v.dish_id = d.id
            GROUP BY m.session
        """).fetchall()

        # Daily vote trend (last 14 days)
        vote_trend = conn.execute("""
            SELECT m.date, COUNT(v.id) AS votes
            FROM vote v
            JOIN dish d ON d.id = v.dish_id
            JOIN menu m ON m.id = d.menu_id
            GROUP BY m.date ORDER BY m.date DESC LIMIT 14
        """).fetchall()

        # New registrations per day (last 14 days)
        reg_trend = conn.execute("""
            SELECT created_at AS day, COUNT(*) AS count
            FROM user WHERE role='student'
            GROUP BY created_at ORDER BY created_at DESC LIMIT 14
        """).fetchall()

        # Recent comments
        recent_comments = conn.execute("""
            SELECT c.body, c.rating, c.created_at, u.name, d.dish_name
            FROM comment c
            JOIN user u ON u.id = c.user_id
            JOIN dish d ON d.id = c.dish_id
            ORDER BY c.created_at DESC LIMIT 8
        """).fetchall()

    return render_template("dashboard.html",
        student_count=student_count, total_votes=total_votes,
        total_dishes=total_dishes, total_menus=total_menus,
        top_dishes=top_dishes, session_votes=session_votes,
        vote_trend=list(reversed(vote_trend)),
        reg_trend=list(reversed(reg_trend)),
        recent_comments=recent_comments)

@app.route("/admin/menu/<target_date>")
@admin_required
def get_menu_json(target_date):
    return jsonify(get_menu_for_date(target_date))

@app.route("/admin/delete_dish/<int:dish_id>", methods=["POST"])
@admin_required
def delete_dish(dish_id):
    with get_db() as conn:
        conn.execute("DELETE FROM dish WHERE id=?", (dish_id,))
    return jsonify(success=True)

@app.route("/admin/students")
@admin_required
def admin_students():
    with get_db() as conn:
        students = conn.execute("""
            SELECT u.id, u.name, u.roll_no, u.created_at,
                   COUNT(DISTINCT v.id) AS vote_count
            FROM user u
            LEFT JOIN vote v ON v.user_id = u.id
            WHERE u.role='student'
            GROUP BY u.id ORDER BY u.name
        """).fetchall()
    return render_template("students.html", students=students)

@app.route("/admin/students/delete/<int:uid>", methods=["POST"])
@admin_required
def delete_student(uid):
    with get_db() as conn:
        conn.execute("DELETE FROM user WHERE id=? AND role='student'", (uid,))
    flash("Student removed.", "success")
    return redirect(url_for("admin_students"))

if __name__ == "__main__":
    app.run(debug=True, port=5001)