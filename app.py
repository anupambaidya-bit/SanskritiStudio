"""Sanskriti Studio – class registration, demos, schedules, payments and promotions.

Run:  flask --app app run --debug        (see README.md)
"""
import calendar as pycal
import csv
import functools
import io
import json
import os
import re
import secrets
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

import db
import storage
import whatsapp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv():
    """Tiny .env reader so no extra package is needed."""
    path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
    DATABASE=os.environ.get("DATABASE", os.path.join(BASE_DIR, "instance", "sanskriti.db")),
    MAX_CONTENT_LENGTH=int(os.environ.get("MAX_UPLOAD_MB", "50")) * 1024 * 1024,
    PERMANENT_SESSION_LIFETIME=timedelta(days=90),  # log in once, stay logged in
    SEED_SAMPLE_DATA=os.environ.get("SEED_SAMPLE_DATA", "1") == "1",
)
db.init_app(app)
app.jinja_env.globals["media_url"] = storage.url

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:5000").rstrip("/")
if PUBLIC_BASE_URL.startswith("https"):
    # Behind Cloudflare (tunnel or proxy): trust its X-Forwarded-* headers and use secure cookies.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config.update(SESSION_COOKIE_SECURE=True, PREFERRED_URL_SCHEME="https")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
IMAGE_EXT = {"jpg", "jpeg", "png", "gif", "webp"}
VIDEO_EXT = {"mp4", "webm", "mov", "m4v"}
AUDIO_EXT = {"mp3", "m4a", "aac", "ogg", "oga", "wav"}
MINOR_AGE = 14
STATUS_LABELS = {
    "interested": "Interested",
    "demo": "Demo booked",
    "demo_done": "Feedback pending",
    "subscribed": "Subscribed",
    "dropped": "Not continuing",
}
DEFAULT_SETTINGS = {
    "studio_name": "Sanskriti Studio",
    "address": "Sanskriti Studio, Ragam Gardens",
    "maps_query": "Sanskriti Studio, Ragam Gardens",
    "upi_id": "sanskriti@upi",
    "payee_name": "Sanskriti Studio",
    "admin_phones": "",
    "payment_due_day": "5",
    # website look (Admin → Website)
    "logo": "",
    "music": "seed-music.mp3",
    "music_on": "1",
    "bg_color": "#f6e7d2",
    "about_title": "What does Sanskriti mean?",
    "about_text": (
        "Sanskriti (संस्कृति) is the Sanskrit word for culture. It comes from sam, \"together, completely\", "
        "and kṛ, \"to make\": something shaped with care until it is refined. That is how we see classical "
        "dance. Every adavu, mudra and abhinaya is practised patiently, passed from guru to student, until "
        "it becomes part of who you are.\n"
        "At Sanskriti Studio in Ragam Gardens, children and adults learn Odissi and Bharatanatyam the "
        "traditional way, in a warm space where rhythm, music and story come together."),
}
SITE_KEYS = ("bg_color", "about_title", "about_text", "music_on")
BG_PRESETS = [("#f6e7d2", "Sandalwood"), ("#fbf6ee", "Ivory"), ("#fdecd9", "Saffron cream"),
              ("#f3e6f5", "Lotus"), ("#e8f1ea", "Tulsi"), ("#efe7dc", "Temple stone")]


# ---------------------------------------------------------------- helpers

def setting(key):
    row = db.query("SELECT value FROM settings WHERE key = ?", (key,), one=True)
    if row is not None and row["value"] is not None:
        return row["value"]
    return DEFAULT_SETTINGS.get(key, "")


def normalize_phone(raw):
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    return digits if 11 <= len(digits) <= 15 else None


def parse_phone_list(raw):
    """Numbers separated by commas, semicolons, slashes or new lines, or just spaces
    (e.g. "98450 12345, +91 99000 11111" or "9845012345 9900011111")."""
    phones = set()
    for chunk in re.split(r"[,;/|\n]+", raw or ""):
        p = normalize_phone(chunk)
        if p:
            phones.add(p)
        else:
            phones.update(q for q in (normalize_phone(x) for x in chunk.split()) if q)
    return phones


def admin_phones():
    return parse_phone_list(os.environ.get("ADMIN_PHONES", "").strip().strip('"').strip("'")) | \
        parse_phone_list(setting("admin_phones"))


def current_period(d=None):
    d = d or date.today()
    return f"{d.year:04d}-{d.month:02d}"


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def link(path):
    return PUBLIC_BASE_URL + path


def save_upload(file_storage, kinds=("image", "video")):
    """Store an uploaded file (Supabase Storage, or static/uploads locally). Returns (filename, media_type) or (None, None)."""
    if not file_storage or not file_storage.filename:
        return None, None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    media_type = ("image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT
                  else "audio" if ext in AUDIO_EXT else None)
    if media_type not in kinds:
        names = {"image": "JPG/PNG/WEBP images", "video": "MP4/WEBM videos", "audio": "MP3/M4A/OGG music"}
        flash("That file type isn't supported here. Use " + " or ".join(names[k] for k in kinds) + ".", "error")
        return None, None
    name = f"{int(time.time())}-{secrets.token_hex(3)}-{secure_filename(file_storage.filename)}"
    storage.save(file_storage, name)
    return name, media_type


# ---------------------------------------------------------------- WhatsApp

def send_wa(to, body, kind="general", media=None, media_type=None, otp=None):
    provider = whatsapp.get_provider()
    media_url = None
    if media:
        media_url = url_for_static(media)
        if media_url.startswith("/"):
            media_url = link(media_url) if PUBLIC_BASE_URL.startswith("https") else None
    if otp and hasattr(provider, "send_otp"):
        ok, err = provider.send_otp(to, otp)
    else:
        ok, err = provider.send(to, body, media_url=media_url, media_type=media_type)
    db.execute(
        "INSERT INTO messages (to_phone, body, kind, provider, status, error) VALUES (?,?,?,?,?,?)",
        (to, body, kind, provider.name, "sent" if ok else "failed", err),
    )
    return ok


def url_for_static(filename):
    return storage.url(filename)


def notify_admins(body, kind="admin_alert"):
    for phone in admin_phones():
        send_wa(phone, body, kind)


def who(user):
    """Short description of a student for admin messages."""
    bits = [user["name"] or "New student", f"+{user['phone']}"]
    if user["age"]:
        bits.append(f"age {user['age']}")
    if user["parent_name"]:
        bits.append(f"parent {user['parent_name']}")
    if user["community"]:
        bits.append(user["community"])
    return ", ".join(bits)


# ---------------------------------------------------------------- formatting

@app.template_filter("t12")
def t12(hhmm):
    if not hhmm:
        return ""
    h, m = map(int, hhmm.split(":"))
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


@app.template_filter("days")
def days_label(days):
    if not days:
        return ""
    return ", ".join(DAYS[int(d)] for d in days.split(",") if d.strip().isdigit())


@app.template_filter("nicedate")
def nicedate(iso):
    if not iso:
        return ""
    d = date.fromisoformat(iso[:10])
    return d.strftime("%a, %d %b")


@app.template_filter("period")
def period_label(p):
    y, m = p.split("-")
    return f"{pycal.month_abbr[int(m)]} {y}"


@app.template_filter("phone")
def phone_fmt(p):
    if p and p.startswith("91") and len(p) == 12:
        return f"+91 {p[2:7]} {p[7:]}"
    return f"+{p}"


@app.template_filter("money")
def money(n):
    return f"₹{int(n or 0):,}"


@app.context_processor
def inject():
    return {
        "csrf_token": csrf_token,
        "setting": setting,
        "STATUS_LABELS": STATUS_LABELS,
        "DAYS": DAYS,
        "maps_embed": "https://www.google.com/maps?" + urlencode({"q": setting("maps_query"), "output": "embed"}),
        "maps_link": "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": setting("maps_query")}),
        "today": date.today().isoformat(),
        "provider_name": whatsapp.get_provider().name,
        "wa_link": lambda p: f"https://wa.me/{p}",
    }


# ---------------------------------------------------------------- auth & csrf

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def before():
    if request.method == "POST":
        token = session.get("_csrf")
        if not token or token != request.form.get("_csrf"):
            abort(400, "Your session expired. Please go back and try again.")
    g.user = None
    if session.get("uid"):
        g.user = db.query("SELECT * FROM users WHERE id = ?", (session["uid"],), one=True)
        if g.user is None:
            session.clear()


def login_required(role=None):
    def deco(view):
        @functools.wraps(view)
        def wrapped(*a, **kw):
            if g.user is None:
                return redirect(url_for("login", next=request.path, **({"as": "admin"} if role == "admin" else {})))
            if role == "admin" and g.user["role"] != "admin":
                abort(403)
            return view(*a, **kw)
        return wrapped
    return deco


admin_required = login_required("admin")


@app.route("/login", methods=["GET", "POST"])
def login():
    mode = request.values.get("as", "student")
    nxt = request.values.get("next", "")
    phone = ""
    step = "phone"
    if request.method == "POST":
        phone = normalize_phone(request.form.get("phone"))
        if not phone:
            flash("Please enter a valid WhatsApp number.", "error")
        elif mode == "admin" and phone not in admin_phones():
            if admin_phones():
                flash(f"{phone_fmt(phone)} is not on the admin list. Check the ADMIN_PHONES variable in Railway "
                      "(numbers separated by commas) or ask another admin to add you in Settings.", "error")
            else:
                flash("No admin numbers are set up yet. Add ADMIN_PHONES in Railway, e.g. 98450 12345, 99000 11111.", "error")
        elif "code" in request.form:
            row = db.query("SELECT * FROM otps WHERE phone = ?", (phone,), one=True)
            code = re.sub(r"\D", "", request.form.get("code", ""))
            if not row or row["expires_at"] < time.time() or row["attempts"] >= 5:
                flash("That code has expired. We've sent you a new one.", "error")
                _send_otp(phone)
                step = "code"
            elif not secrets.compare_digest(row["code"], code):
                db.execute("UPDATE otps SET attempts = attempts + 1 WHERE phone = ?", (phone,))
                flash("That code doesn't match. Please check WhatsApp and try again.", "error")
                step = "code"
            else:
                db.execute("DELETE FROM otps WHERE phone = ?", (phone,))
                return _finish_login(phone, nxt)
        else:
            _send_otp(phone)
            step = "code"
    return render_template("login.html", mode=mode, step=step, phone=phone, next=nxt)


def _send_otp(phone):
    row = db.query("SELECT * FROM otps WHERE phone = ?", (phone,), one=True)
    if row and time.time() - row["sent_at"] < 30 and row["expires_at"] > time.time():
        code = row["code"]  # don't spam; reuse the code sent moments ago
    else:
        code = f"{secrets.randbelow(1_000_000):06d}"
        db.execute(
            """INSERT INTO otps (phone, code, expires_at, sent_at, attempts) VALUES (?,?,?,?,0)
               ON CONFLICT (phone) DO UPDATE SET code = excluded.code, expires_at = excluded.expires_at,
               sent_at = excluded.sent_at, attempts = 0""",
            (phone, code, time.time() + 600, time.time()),
        )
        if not send_wa(phone, f"Your {setting('studio_name')} login code is {code}. It is valid for 10 minutes.",
                       "otp", otp=code):
            flash("We couldn't send the WhatsApp code just now. Please try again in a minute.", "error")
    if whatsapp.get_provider().name == "console":
        flash(f"Demo mode (WhatsApp not connected yet): your code is {code}", "info")


def _finish_login(phone, nxt):
    role = "admin" if phone in admin_phones() else "customer"
    user = db.query("SELECT * FROM users WHERE phone = ?", (phone,), one=True)
    if user is None:
        uid = db.execute("INSERT INTO users (phone, role) VALUES (?, ?)", (phone, role))
    else:
        uid = user["id"]
        db.execute("UPDATE users SET role = ? WHERE id = ?", (role, uid))
    session.clear()
    session.permanent = True
    session["uid"] = uid
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect(url_for("admin_home" if role == "admin" else "home"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------------------------------------------------------------- shared queries

def active_classes():
    classes = db.query("SELECT * FROM classes WHERE active = 1 ORDER BY name")
    batches = defaultdict(list)
    for b in db.query("SELECT * FROM batches WHERE active = 1 ORDER BY start_time"):
        batches[b["class_id"]].append(b)
    return classes, batches


def upcoming_demos(class_id=None):
    sql = """SELECT d.*, c.name AS cname, c.color, c.image,
                    (SELECT COUNT(*) FROM enrollments e WHERE e.demo_id = d.id
                       AND e.status IN ('demo','demo_done','subscribed')) AS booked
             FROM demos d JOIN classes c ON c.id = d.class_id
             WHERE d.date >= ? AND c.active = 1"""
    args = [date.today().isoformat()]
    if class_id:
        sql += " AND d.class_id = ?"
        args.append(class_id)
    return db.query(sql + " ORDER BY d.date, d.start_time", args)


def active_promotions():
    return db.query("""SELECT p.*, c.name AS cname FROM promotions p LEFT JOIN classes c ON c.id = p.class_id
                       WHERE p.active = 1 ORDER BY p.created_at DESC, p.id DESC""")


ENROLL_SQL = """
SELECT e.*, u.name AS uname, u.phone, u.age, u.parent_name, u.community,
       c.name AS cname, c.fee, c.color,
       d.date AS demo_date, d.start_time AS demo_time,
       b.days AS bdays, b.start_time AS bstart, b.end_time AS bend
FROM enrollments e
JOIN users u ON u.id = e.user_id
JOIN classes c ON c.id = e.class_id
LEFT JOIN demos d ON d.id = e.demo_id
LEFT JOIN batches b ON b.id = e.batch_id
"""


def ensure_dues(period=None):
    """Create this month's fee row for every subscribed student (idempotent)."""
    period = period or current_period()
    db.execute(
        """INSERT INTO payments (user_id, class_id, period, amount)
           SELECT e.user_id, e.class_id, ?, c.fee FROM enrollments e JOIN classes c ON c.id = e.class_id
           WHERE e.status = 'subscribed' AND c.fee > 0
           ON CONFLICT (user_id, class_id, period) DO NOTHING""",
        (period,),
    )


def book_demo(user, demo):
    """Book a demo for a user; returns True if booked."""
    enr = db.query("SELECT * FROM enrollments WHERE user_id = ? AND class_id = ?",
                   (user["id"], demo["class_id"]), one=True)
    if enr and enr["status"] == "subscribed":
        return False
    if enr:
        db.execute("UPDATE enrollments SET status = 'demo', demo_id = ?, updated_at = ? WHERE id = ?",
                   (demo["id"], now_iso(), enr["id"]))
    else:
        db.execute("INSERT INTO enrollments (user_id, class_id, status, demo_id) VALUES (?,?, 'demo', ?)",
                   (user["id"], demo["class_id"], demo["id"]))
    return True


# ---------------------------------------------------------------- public

@app.route("/")
def index():
    if g.user and not request.args.get("preview"):
        return redirect(url_for("admin_home" if g.user["role"] == "admin" else "home"))
    classes, batches = active_classes()
    return render_template("landing.html", classes=classes, batches=batches, slides=carousel_slides(classes),
                           demos=upcoming_demos()[:4], promos=active_promotions())


def carousel_slides(classes):
    """Homepage carousel: the admin's slides, plus a slide for any active class that has none."""
    rows = db.query("""SELECT s.*, c.name AS class_name, c.description AS class_desc, c.active AS class_active
                       FROM slides s LEFT JOIN classes c ON c.id = s.class_id
                       WHERE s.active = 1 ORDER BY s.sort, s.id""")
    slides = [dict(r) for r in rows if r["class_id"] is None or r["class_active"]]
    covered = {s["class_id"] for s in slides}
    for c in classes:
        if c["id"] not in covered and c["image"]:
            slides.append({"media": c["image"], "media_type": "image", "caption": c["name"],
                           "class_id": c["id"], "class_name": c["name"], "class_desc": c["description"]})
    return slides


# ---------------------------------------------------------------- customer

@app.route("/profile", methods=["GET", "POST"])
@login_required()
def profile():
    user = g.user
    classes, batches = active_classes()
    demos = upcoming_demos()
    mine = {e["class_id"]: e for e in db.query("SELECT * FROM enrollments WHERE user_id = ?", (user["id"],))}
    first_time = not user["name"]
    form = request.form if request.method == "POST" else None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        community = request.form.get("community", "").strip()
        parent = request.form.get("parent_name", "").strip()
        try:
            age = int(request.form.get("age", ""))
        except ValueError:
            age = 0
        class_ids = {int(x) for x in request.form.getlist("classes") if x.isdigit()}
        demo_ids = {int(x) for x in request.form.getlist("demos") if x.isdigit()}
        valid_classes = {c["id"] for c in classes}
        demo_map = {d["id"]: d for d in demos}
        # booking a demo implies interest in that class
        class_ids |= {demo_map[d]["class_id"] for d in demo_ids if d in demo_map}

        errors = []
        if not name:
            errors.append("Please enter your name.")
        if not 2 <= age <= 100:
            errors.append("Please enter a valid age.")
        if age and age < MINOR_AGE and not parent:
            errors.append(f"Students under {MINOR_AGE} need a parent or guardian's name.")
        if user["role"] != "admin" and not (class_ids & valid_classes) and not any(
                e["status"] != "interested" for e in mine.values()):
            errors.append("Pick at least one class you're interested in.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("profile.html", classes=classes, batches=batches, demos=demos,
                                   mine=mine, first_time=first_time, form=form,
                                   communities=_communities())

        db.execute("UPDATE users SET name = ?, age = ?, community = ?, parent_name = ? WHERE id = ?",
                   (name, age, community, parent if age < MINOR_AGE or parent else None, user["id"]))
        user = db.query("SELECT * FROM users WHERE id = ?", (user["id"],), one=True)

        added = []
        for cid in class_ids & valid_classes:
            if cid not in mine:
                db.execute("INSERT INTO enrollments (user_id, class_id) VALUES (?, ?)", (user["id"], cid))
                added.append(cid)
        for cid, e in mine.items():  # unticking only removes plain interest, never a booking
            if cid not in class_ids and e["status"] == "interested":
                db.execute("DELETE FROM enrollments WHERE id = ?", (e["id"],))
        booked = []
        for did in demo_ids:
            d = demo_map.get(did)
            if d and (mine.get(d["class_id"]) is None or mine[d["class_id"]]["demo_id"] != did):
                if book_demo(user, d):
                    booked.append(d)

        names = {c["id"]: c["name"] for c in classes}
        if first_time or added or booked:
            lines = [("New registration" if first_time else "Profile update") + f": {who(user)}"]
            interested = [names[c] for c in (class_ids & valid_classes)]
            if interested:
                lines.append("Interested in: " + ", ".join(interested))
            for d in booked:
                lines.append(f"Demo booked: {d['cname']} on {nicedate(d['date'])} at {t12(d['start_time'])}")
            notify_admins("\n".join(lines), "registration")
        if booked:
            for d in booked:
                send_wa(user["phone"],
                        f"Hi {user['name']}, your free {d['cname']} demo is booked for {nicedate(d['date'])} at "
                        f"{t12(d['start_time'])}, {d['location'] or setting('address')}.\nMap: "
                        f"https://www.google.com/maps/search/?api=1&query={quote(setting('maps_query'))}",
                        "demo_booked")
        flash("Welcome to Sanskriti! You're all set." if first_time else "Profile saved.", "success")
        return redirect(url_for("home"))

    return render_template("profile.html", classes=classes, batches=batches, demos=demos, mine=mine,
                           first_time=first_time, form=form, communities=_communities())


def _communities():
    return [r["community"] for r in db.query(
        "SELECT DISTINCT community FROM users WHERE community IS NOT NULL AND community != '' ORDER BY community")]


@app.route("/home")
@login_required()
def home():
    user = g.user
    if not user["name"]:
        return redirect(url_for("profile"))
    ensure_dues()
    enrollments = db.query(ENROLL_SQL + " WHERE e.user_id = ? ORDER BY c.name", (user["id"],))
    payments = db.query("""SELECT p.*, c.name AS cname FROM payments p JOIN classes c ON c.id = p.class_id
                           WHERE p.user_id = ? AND p.status IN ('pending','submitted')
                           ORDER BY p.period""", (user["id"],))
    feedback_due = [e for e in enrollments if e["status"] == "demo_done"]
    subscribed = [e for e in enrollments if e["status"] == "subscribed"]
    month_start = date.today().replace(day=1).isoformat()
    regular_due = []
    for e in subscribed:
        fb = db.query("""SELECT 1 FROM feedback WHERE user_id = ? AND class_id = ? AND created_at >= ?""",
                      (user["id"], e["class_id"], month_start), one=True)
        if not fb:
            regular_due.append(e)
    my_classes = {e["class_id"] for e in enrollments}
    demos = upcoming_demos()
    booked_demo_ids = {e["demo_id"] for e in enrollments if e["status"] == "demo"}
    return render_template("home.html", enrollments=enrollments, payments=payments,
                           feedback_due=feedback_due, regular_due=regular_due, subscribed=subscribed,
                           demos=demos, booked_demo_ids=booked_demo_ids, my_classes=my_classes,
                           promos=active_promotions(), next_classes=_next_sessions(subscribed))


def _next_sessions(subscribed, days=7):
    out = []
    today = date.today()
    for i in range(days):
        d = today + timedelta(days=i)
        for e in subscribed:
            if e["bdays"] and str(d.weekday()) in e["bdays"].split(","):
                out.append({"date": d.isoformat(), "time": e["bstart"], "end": e["bend"], "cname": e["cname"],
                            "color": e["color"]})
    return sorted(out, key=lambda x: (x["date"], x["time"]))[:4]


@app.route("/demo/<int:demo_id>/book", methods=["POST"])
@login_required()
def demo_book(demo_id):
    if not g.user["name"]:
        return redirect(url_for("profile"))
    d = db.query("SELECT d.*, c.name AS cname FROM demos d JOIN classes c ON c.id = d.class_id WHERE d.id = ?",
                 (demo_id,), one=True) or abort(404)
    if book_demo(g.user, d):
        flash(f"Booked! See you at the {d['cname']} demo on {nicedate(d['date'])} at {t12(d['start_time'])}.", "success")
        send_wa(g.user["phone"],
                f"Hi {g.user['name']}, your free {d['cname']} demo is booked for {nicedate(d['date'])} at "
                f"{t12(d['start_time'])}, {d['location'] or setting('address')}.", "demo_booked")
        notify_admins(f"Demo booked: {d['cname']} on {nicedate(d['date'])} {t12(d['start_time'])}\n{who(g.user)}",
                      "demo_booked")
    else:
        flash(f"You're already enrolled in {d['cname']}.", "info")
    return redirect(request.form.get("back") or url_for("home"))


@app.route("/demo-feedback/<int:enrollment_id>", methods=["GET", "POST"])
@login_required()
def demo_feedback(enrollment_id):
    e = db.query(ENROLL_SQL + " WHERE e.id = ? AND e.user_id = ?", (enrollment_id, g.user["id"]), one=True) or abort(404)
    batches = db.query("SELECT * FROM batches WHERE class_id = ? AND active = 1 ORDER BY start_time", (e["class_id"],))
    if request.method == "POST":
        rating = int(request.form.get("rating") or 0) or None
        comment = request.form.get("comment", "").strip()
        choice = request.form.get("batch", "")
        db.execute("INSERT INTO feedback (user_id, class_id, kind, rating, comment) VALUES (?,?, 'demo', ?, ?)",
                   (g.user["id"], e["class_id"], rating, comment))
        stars = f"{rating}★" if rating else "no rating"
        if choice.isdigit() and any(b["id"] == int(choice) for b in batches):
            b = next(b for b in batches if b["id"] == int(choice))
            db.execute("UPDATE enrollments SET status = 'subscribed', batch_id = ?, updated_at = ? WHERE id = ?",
                       (b["id"], now_iso(), e["id"]))
            ensure_dues()
            when = f"{days_label(b['days'])} {t12(b['start_time'])}-{t12(b['end_time'])}"
            notify_admins(f"🎉 New subscription: {e['cname']} ({when})\n{who(g.user)}\nDemo feedback: {stars}"
                          + (f" \"{comment}\"" if comment else ""), "subscribed")
            send_wa(g.user["phone"],
                    f"Welcome to {e['cname']} at {setting('studio_name')}! Your batch: {when}.\n"
                    f"Monthly fee {money(e['fee'])}. Pay here: {link('/home')}", "subscribed")
            flash(f"You're in! {e['cname']}, {when}.", "success")
        else:
            db.execute("UPDATE enrollments SET status = 'dropped', updated_at = ? WHERE id = ?", (now_iso(), e["id"]))
            notify_admins(f"Demo feedback (not continuing yet): {e['cname']}\n{who(g.user)}\nFeedback: {stars}"
                          + (f" \"{comment}\"" if comment else ""), "feedback")
            flash("Thank you for the feedback! You can join any time from your home page.", "success")
        return redirect(url_for("home"))
    return render_template("demo_feedback.html", e=e, batches=batches)


@app.route("/feedback", methods=["POST"])
@login_required()
def regular_feedback():
    class_id = request.form.get("class_id", type=int)
    rating = request.form.get("rating", type=int)
    comment = request.form.get("comment", "").strip()
    c = db.query("SELECT name FROM classes WHERE id = ?", (class_id,), one=True) or abort(404)
    db.execute("INSERT INTO feedback (user_id, class_id, kind, rating, comment) VALUES (?,?, 'regular', ?, ?)",
               (g.user["id"], class_id, rating, comment))
    notify_admins(f"Feedback for {c['name']}: {rating or '-'}★ {comment}\n{who(g.user)}", "feedback")
    flash("Thanks for your feedback!", "success")
    return redirect(url_for("home"))


@app.route("/join/<int:class_id>", methods=["POST"])
@login_required()
def join_class(class_id):
    """One-tap 'I'm interested' from a class card or promotion."""
    c = db.query("SELECT * FROM classes WHERE id = ? AND active = 1", (class_id,), one=True) or abort(404)
    if not g.user["name"]:
        return redirect(url_for("profile"))
    exists = db.query("SELECT 1 FROM enrollments WHERE user_id = ? AND class_id = ?", (g.user["id"], class_id), one=True)
    if not exists:
        db.execute("INSERT INTO enrollments (user_id, class_id) VALUES (?, ?)", (g.user["id"], class_id))
        notify_admins(f"New interest: {c['name']}\n{who(g.user)}", "registration")
    flash(f"Added {c['name']} to your classes. Book a demo below.", "success")
    return redirect(url_for("home") + "#demos")


@app.route("/pay/<int:payment_id>", methods=["GET", "POST"])
@login_required()
def pay(payment_id):
    p = db.query("""SELECT p.*, c.name AS cname FROM payments p JOIN classes c ON c.id = p.class_id
                    WHERE p.id = ? AND p.user_id = ?""", (payment_id, g.user["id"]), one=True) or abort(404)
    if request.method == "POST":
        method = request.form.get("method", "UPI")[:20]
        ref = request.form.get("reference", "").strip()[:60]
        db.execute("UPDATE payments SET status = 'submitted', method = ?, reference = ? WHERE id = ? AND status = 'pending'",
                   (method, ref, p["id"]))
        notify_admins(f"Payment to confirm: {money(p['amount'])} for {p['cname']} ({period_label(p['period'])}) via "
                      f"{method}{' ref ' + ref if ref else ''}\n{who(g.user)}\nConfirm: {link('/admin#payments')}",
                      "payment_submitted")
        flash("Thanks! We'll confirm your payment shortly.", "success")
        return redirect(url_for("home"))
    params = urlencode({"pa": setting("upi_id"), "pn": setting("payee_name"), "am": p["amount"], "cu": "INR",
                        "tn": f"{p['cname']} {period_label(p['period'])} {g.user['name']}"[:50]})
    upi = {"generic": "upi://pay?" + params, "phonepe": "phonepe://pay?" + params, "gpay": "tez://upi/pay?" + params}
    return render_template("pay.html", p=p, upi=upi)


# ---------------------------------------------------------------- calendar (customers + admins)

@app.route("/calendar")
@login_required()
def calendar_view():
    try:
        y, m = map(int, request.args.get("m", current_period()).split("-"))
        first = date(y, m, 1)
    except ValueError:
        first = date.today().replace(day=1)
    class_filter = request.args.get("class", type=int)
    weeks = pycal.Calendar(0).monthdatescalendar(first.year, first.month)
    start, end = weeks[0][0], weeks[-1][-1]

    batches = db.query("""SELECT b.*, c.name AS cname, c.color FROM batches b JOIN classes c ON c.id = b.class_id
                          WHERE b.active = 1 AND c.active = 1""")
    demos = db.query("""SELECT d.*, c.name AS cname, c.color FROM demos d JOIN classes c ON c.id = d.class_id
                        WHERE c.active = 1 AND d.date BETWEEN ? AND ?""", (start.isoformat(), end.isoformat()))
    mine = {e["class_id"]: e for e in db.query("SELECT * FROM enrollments WHERE user_id = ?", (g.user["id"],))}
    is_admin = g.user["role"] == "admin"

    events = defaultdict(list)
    day = start
    while day <= end:
        for b in batches:
            if class_filter and b["class_id"] != class_filter:
                continue
            if str(day.weekday()) in b["days"].split(","):
                e = mine.get(b["class_id"])
                is_mine = bool(e and e["batch_id"] == b["id"] and e["status"] == "subscribed")
                events[day].append({
                    "kind": "class", "id": b["id"], "title": b["cname"], "start": b["start_time"],
                    "end": b["end_time"], "color": b["color"], "mine": is_mine,
                    "info": f"Every {days_label(b['days'])}" + (f" · {b['teacher']}" if b["teacher"] else ""),
                    "action": None if (is_admin or is_mine) else url_for("calendar_pick", batch_id=b["id"]),
                    "action_label": "Choose this batch",
                })
        day += timedelta(days=1)
    for d in demos:
        if class_filter and d["class_id"] != class_filter:
            continue
        e = mine.get(d["class_id"])
        is_mine = bool(e and e["demo_id"] == d["id"] and e["status"] == "demo")
        past = d["date"] < date.today().isoformat()
        events[date.fromisoformat(d["date"])].append({
            "kind": "demo", "id": d["id"], "title": "Demo: " + d["cname"], "start": d["start_time"],
            "end": d["end_time"] or "", "color": d["color"], "mine": is_mine,
            "info": (d["location"] or setting("address")) + (f" · {d['notes']}" if d["notes"] else ""),
            "action": None if (is_admin or is_mine or past or (e and e["status"] == "subscribed"))
            else url_for("demo_book", demo_id=d["id"]),
            "action_label": "Book this free demo",
        })
    for evs in events.values():
        evs.sort(key=lambda x: x["start"])
        for ev in evs:
            ev["when"] = t12(ev["start"]) + (f" – {t12(ev['end'])}" if ev["end"] else "")
            ev["json"] = json.dumps({k: ev[k] for k in ("title", "when", "info", "action", "action_label", "kind")})

    prev_m = (first - timedelta(days=1)).replace(day=1)
    next_m = (first + timedelta(days=32)).replace(day=1)
    classes = db.query("SELECT id, name, color FROM classes WHERE active = 1 ORDER BY name")
    return render_template("calendar.html", weeks=weeks, events=events, first=first, prev_m=prev_m, next_m=next_m,
                           classes=classes, class_filter=class_filter, today_d=date.today())


@app.route("/calendar/pick/<int:batch_id>", methods=["POST"])
@login_required()
def calendar_pick(batch_id):
    b = db.query("""SELECT b.*, c.name AS cname FROM batches b JOIN classes c ON c.id = b.class_id
                    WHERE b.id = ?""", (batch_id,), one=True) or abort(404)
    if not g.user["name"]:
        return redirect(url_for("profile"))
    e = db.query("SELECT * FROM enrollments WHERE user_id = ? AND class_id = ?", (g.user["id"], b["class_id"]), one=True)
    when = f"{days_label(b['days'])} {t12(b['start_time'])}"
    if e and e["status"] == "demo_done":
        return redirect(url_for("demo_feedback", enrollment_id=e["id"], batch=b["id"]))
    if e and e["status"] == "subscribed":
        db.execute("UPDATE enrollments SET batch_id = ?, updated_at = ? WHERE id = ?", (b["id"], now_iso(), e["id"]))
        notify_admins(f"Batch change: {b['cname']} → {when}\n{who(g.user)}", "batch_change")
        flash(f"Your {b['cname']} batch is now {when}.", "success")
    else:
        if e:
            db.execute("UPDATE enrollments SET batch_id = ?, updated_at = ? WHERE id = ?", (b["id"], now_iso(), e["id"]))
        else:
            db.execute("INSERT INTO enrollments (user_id, class_id, batch_id) VALUES (?,?,?)",
                       (g.user["id"], b["class_id"], b["id"]))
        notify_admins(f"Preferred batch: {b['cname']} {when}\n{who(g.user)}", "registration")
        flash(f"Noted {when} as your preferred {b['cname']} batch. Book a free demo to get started.", "success")
    return redirect(url_for("home"))


# ---------------------------------------------------------------- admin: funnel dashboard

@app.route("/admin")
@admin_required
def admin_home():
    ensure_dues()
    class_filter = request.args.get("class", type=int)
    where, args = "", []
    if class_filter:
        where, args = " WHERE e.class_id = ?", [class_filter]
    rows = db.query(ENROLL_SQL + where + " ORDER BY e.updated_at DESC", args)
    cols = {k: [] for k in STATUS_LABELS}
    for r in rows:
        cols[r["status"]].append(r)

    psql = """SELECT p.*, u.name AS uname, u.phone, c.name AS cname FROM payments p
              JOIN users u ON u.id = p.user_id JOIN classes c ON c.id = p.class_id"""
    pw = " AND p.class_id = ?" if class_filter else ""
    due = db.query(psql + " WHERE p.status IN ('pending','submitted')" + pw +
                   " ORDER BY p.status = 'submitted' DESC, p.period, u.name", args)
    paid = db.query(psql + " WHERE p.status = 'paid' AND p.period = ?" + pw + " ORDER BY p.paid_at DESC",
                    [current_period()] + args)
    stats = {
        "interested": len(cols["interested"]),
        "demo": len(cols["demo"]),
        "demo_done": len(cols["demo_done"]),
        "subscribed": len(cols["subscribed"]),
        "due_amount": sum(p["amount"] for p in due),
        "due_count": len(due),
        "paid_amount": sum(p["amount"] for p in paid),
    }
    classes = db.query("SELECT id, name, color FROM classes ORDER BY name")
    return render_template("admin/dashboard.html", cols=cols, due=due, paid=paid, stats=stats,
                           demos=upcoming_demos(class_filter), recent_demos=_recent_demos(),
                           classes=classes, class_filter=class_filter,
                           feedback=db.query("""SELECT f.*, u.name AS uname, c.name AS cname FROM feedback f
                                                JOIN users u ON u.id = f.user_id LEFT JOIN classes c ON c.id = f.class_id
                                                ORDER BY f.created_at DESC LIMIT 8"""))


def _recent_demos():
    """Demos from the last two weeks that still have students marked 'booked' (to mark attended)."""
    return db.query("""SELECT d.*, c.name AS cname, COUNT(e.id) AS booked FROM demos d
                       JOIN classes c ON c.id = d.class_id
                       JOIN enrollments e ON e.demo_id = d.id AND e.status = 'demo'
                       WHERE d.date <= ? AND d.date >= ? GROUP BY d.id, c.name ORDER BY d.date DESC""",
                    (date.today().isoformat(), (date.today() - timedelta(days=14)).isoformat()))


def _feedback_request(e):
    send_wa(e["phone"],
            f"Hi {e['uname']}, thank you for attending the {e['cname']} demo at {setting('studio_name')}! "
            f"Please share quick feedback and pick your batch here: {link('/demo-feedback/' + str(e['id']))}",
            "feedback_request")
    db.execute("UPDATE enrollments SET last_reminded_at = ? WHERE id = ?", (now_iso(), e["id"]))


def _payment_reminder(p):
    send_wa(p["phone"],
            f"Hi {p['uname']}, a gentle reminder that the {p['cname']} fee of {money(p['amount'])} for "
            f"{period_label(p['period'])} is pending. Pay by PhonePe / Google Pay here: {link('/pay/' + str(p['id']))}",
            "payment_reminder")
    db.execute("UPDATE payments SET last_reminded_at = ? WHERE id = ?", (now_iso(), p["id"]))


@app.route("/admin/enrollment/<int:eid>", methods=["POST"])
@admin_required
def admin_enrollment(eid):
    e = db.query(ENROLL_SQL + " WHERE e.id = ?", (eid,), one=True) or abort(404)
    action = request.form.get("action")
    if action == "attended":
        db.execute("UPDATE enrollments SET status = 'demo_done', updated_at = ? WHERE id = ?", (now_iso(), eid))
        _feedback_request(e)
        flash(f"Marked {e['uname']} as attended and sent the feedback request on WhatsApp.", "success")
    elif action == "remind_feedback":
        _feedback_request(e)
        flash(f"Feedback reminder sent to {e['uname']}.", "success")
    elif action == "invite":
        demos = upcoming_demos(e["class_id"])
        if demos:
            d = demos[0]
            send_wa(e["phone"], f"Hi {e['uname']}, join our free {e['cname']} demo on {nicedate(d['date'])} at "
                                f"{t12(d['start_time'])}, {d['location'] or setting('address')}. Book in one tap: "
                                f"{link('/home#demos')}", "demo_invite")
            db.execute("UPDATE enrollments SET last_reminded_at = ? WHERE id = ?", (now_iso(), eid))
            flash(f"Demo invite sent to {e['uname']}.", "success")
        else:
            flash(f"There's no upcoming {e['cname']} demo yet. Add one under Classes.", "error")
    elif action == "subscribe":
        batch_id = request.form.get("batch_id", type=int) or e["batch_id"]
        db.execute("UPDATE enrollments SET status = 'subscribed', batch_id = ?, updated_at = ? WHERE id = ?",
                   (batch_id, now_iso(), eid))
        ensure_dues()
        flash(f"{e['uname']} is now subscribed to {e['cname']}.", "success")
    elif action == "drop":
        db.execute("UPDATE enrollments SET status = 'dropped', updated_at = ? WHERE id = ?", (now_iso(), eid))
        flash(f"Moved {e['uname']} to 'Not continuing'.", "success")
    elif action == "reopen":
        db.execute("UPDATE enrollments SET status = 'interested', updated_at = ? WHERE id = ?", (now_iso(), eid))
        flash(f"Moved {e['uname']} back to Interested.", "success")
    return redirect(request.form.get("back") or url_for("admin_home"))


@app.route("/admin/demo/<int:demo_id>/attended", methods=["POST"])
@admin_required
def admin_demo_attended(demo_id):
    rows = db.query(ENROLL_SQL + " WHERE e.demo_id = ? AND e.status = 'demo'", (demo_id,))
    for e in rows:
        db.execute("UPDATE enrollments SET status = 'demo_done', updated_at = ? WHERE id = ?", (now_iso(), e["id"]))
        _feedback_request(e)
    flash(f"Marked {len(rows)} student(s) as attended and asked each for feedback on WhatsApp.", "success")
    return redirect(url_for("admin_home"))


@app.route("/admin/payment/<int:pid>", methods=["POST"])
@admin_required
def admin_payment(pid):
    p = db.query("""SELECT p.*, u.name AS uname, u.phone, c.name AS cname FROM payments p
                    JOIN users u ON u.id = p.user_id JOIN classes c ON c.id = p.class_id WHERE p.id = ?""",
                 (pid,), one=True) or abort(404)
    action = request.form.get("action")
    if action == "paid":
        db.execute("UPDATE payments SET status = 'paid', method = COALESCE(method, ?), paid_at = ? WHERE id = ?",
                   (request.form.get("method", "Cash"), now_iso(), pid))
        send_wa(p["phone"], f"Received {money(p['amount'])} for {p['cname']} ({period_label(p['period'])}). "
                            f"Thank you, {p['uname']}!", "payment_receipt")
        flash(f"Marked {p['uname']}'s {p['cname']} fee as paid.", "success")
    elif action == "remind":
        _payment_reminder(p)
        flash(f"Payment reminder sent to {p['uname']}.", "success")
    elif action == "waive":
        db.execute("UPDATE payments SET status = 'waived' WHERE id = ?", (pid,))
        flash("Fee waived.", "success")
    elif action == "undo":
        db.execute("UPDATE payments SET status = 'pending', paid_at = NULL WHERE id = ?", (pid,))
        flash("Payment moved back to pending.", "success")
    return redirect(url_for("admin_home") + "#payments")


@app.route("/admin/remind/<kind>", methods=["POST"])
@admin_required
def admin_remind(kind):
    n = run_reminders(kinds={kind}, force=True)
    flash(f"Sent {n} WhatsApp reminder(s)." if n else "Nobody needed a reminder right now.", "success")
    return redirect(request.form.get("back") or url_for("admin_home"))


def run_reminders(kinds=None, force=False):
    """Send reminders. Used by the admin buttons and by `flask send-reminders` (daily cron).
    Without force, people reminded in the last few days are skipped so nobody gets spammed."""
    kinds = kinds or {"payments", "feedback", "classes", "demos"}
    if "all" in kinds:
        kinds = {"payments", "feedback", "classes", "demos"}
    ensure_dues()
    sent = 0
    cutoff = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
    tomorrow = date.today() + timedelta(days=1)

    if "payments" in kinds and (force or date.today().day >= int(setting("payment_due_day") or 1)):
        for p in db.query("""SELECT p.*, u.name AS uname, u.phone, c.name AS cname FROM payments p
                             JOIN users u ON u.id = p.user_id JOIN classes c ON c.id = p.class_id
                             WHERE p.status = 'pending'"""):
            if force or not p["last_reminded_at"] or p["last_reminded_at"] < cutoff:
                _payment_reminder(p)
                sent += 1
    if "feedback" in kinds:
        for e in db.query(ENROLL_SQL + " WHERE e.status = 'demo_done'"):
            if force or not e["last_reminded_at"] or e["last_reminded_at"] < cutoff:
                _feedback_request(e)
                sent += 1
    if "classes" in kinds:
        wd = str(tomorrow.weekday())
        for e in db.query(ENROLL_SQL + " WHERE e.status = 'subscribed' AND e.batch_id IS NOT NULL"):
            if wd in (e["bdays"] or "").split(","):
                send_wa(e["phone"], f"Reminder: {e['cname']} class tomorrow ({nicedate(tomorrow.isoformat())}) at "
                                    f"{t12(e['bstart'])}, {setting('address')}. See you there!", "class_reminder")
                sent += 1
    if "demos" in kinds:
        for e in db.query(ENROLL_SQL + " WHERE e.status = 'demo' AND d.date = ?", (tomorrow.isoformat(),)):
            send_wa(e["phone"], f"Reminder: your free {e['cname']} demo is tomorrow at {t12(e['demo_time'])}, "
                                f"{setting('address')}. Map: {link('/#visit')}", "demo_reminder")
            sent += 1
    if "invites" in kinds:
        for e in db.query(ENROLL_SQL + " WHERE e.status = 'interested'"):
            demos = upcoming_demos(e["class_id"])
            if demos and (force or not e["last_reminded_at"] or e["last_reminded_at"] < cutoff):
                d = demos[0]
                send_wa(e["phone"], f"Hi {e['uname']}, join our free {e['cname']} demo on {nicedate(d['date'])} at "
                                    f"{t12(d['start_time'])}. Book in one tap: {link('/home#demos')}", "demo_invite")
                db.execute("UPDATE enrollments SET last_reminded_at = ? WHERE id = ?", (now_iso(), e["id"]))
                sent += 1
    return sent


# ---------------------------------------------------------------- admin: classes, schedules, demos

@app.route("/admin/classes", methods=["GET", "POST"])
@admin_required
def admin_classes():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Class name is required.", "error")
        else:
            image, _ = save_upload(request.files.get("image"), kinds=("image",))
            cid = db.execute("INSERT INTO classes (name, description, fee, image, color) VALUES (?,?,?,?,?)",
                             (name, request.form.get("description", ""), request.form.get("fee", type=int) or 0,
                              image, request.form.get("color") or "#6b3fa0"))
            _add_batch_from_form(cid)
            flash(f"Added {name}. It's now visible to students.", "success")
            return redirect(url_for("admin_classes") + f"#class-{cid}")
    classes = db.query("""SELECT c.*, (SELECT COUNT(*) FROM enrollments e WHERE e.class_id = c.id
                          AND e.status = 'subscribed') AS students FROM classes c ORDER BY c.active DESC, c.name""")
    batches = defaultdict(list)
    for b in db.query("SELECT * FROM batches ORDER BY start_time"):
        batches[b["class_id"]].append(b)
    demos = defaultdict(list)
    for d in upcoming_demos():
        demos[d["class_id"]].append(d)
    return render_template("admin/classes.html", classes=classes, batches=batches, demos=demos)


def _add_batch_from_form(class_id):
    days = [d for d in request.form.getlist("days") if d.isdigit() and 0 <= int(d) <= 6]
    start, end = request.form.get("start_time"), request.form.get("end_time")
    if days and start and end:
        db.execute("INSERT INTO batches (class_id, days, start_time, end_time, teacher) VALUES (?,?,?,?,?)",
                   (class_id, ",".join(sorted(set(days))), start, end, request.form.get("teacher", "").strip()))
        return True
    return False


@app.route("/admin/classes/<int:cid>/update", methods=["POST"])
@admin_required
def admin_class_update(cid):
    c = db.query("SELECT * FROM classes WHERE id = ?", (cid,), one=True) or abort(404)
    image, _ = save_upload(request.files.get("image"), kinds=("image",))
    db.execute("UPDATE classes SET name = ?, description = ?, fee = ?, color = ?, image = ? WHERE id = ?",
               (request.form.get("name", c["name"]).strip() or c["name"], request.form.get("description", ""),
                request.form.get("fee", type=int) or 0, request.form.get("color") or c["color"],
                image or c["image"], cid))
    flash("Class updated.", "success")
    return redirect(url_for("admin_classes") + f"#class-{cid}")


@app.route("/admin/classes/<int:cid>/toggle", methods=["POST"])
@admin_required
def admin_class_toggle(cid):
    db.execute("UPDATE classes SET active = 1 - active WHERE id = ?", (cid,))
    flash("Class visibility updated.", "success")
    return redirect(url_for("admin_classes") + f"#class-{cid}")


@app.route("/admin/classes/<int:cid>/batches", methods=["POST"])
@admin_required
def admin_batch_add(cid):
    if _add_batch_from_form(cid):
        flash("Schedule added.", "success")
    else:
        flash("Pick at least one day plus start and end times.", "error")
    return redirect(url_for("admin_classes") + f"#class-{cid}")


@app.route("/admin/batches/<int:bid>/update", methods=["POST"])
@admin_required
def admin_batch_update(bid):
    b = db.query("SELECT * FROM batches WHERE id = ?", (bid,), one=True) or abort(404)
    days = [d for d in request.form.getlist("days") if d.isdigit()]
    if request.form.get("delete"):
        db.execute("DELETE FROM batches WHERE id = ?", (bid,))
        flash("Schedule removed.", "success")
    elif days:
        db.execute("UPDATE batches SET days = ?, start_time = ?, end_time = ?, teacher = ? WHERE id = ?",
                   (",".join(sorted(set(days))), request.form.get("start_time") or b["start_time"],
                    request.form.get("end_time") or b["end_time"], request.form.get("teacher", "").strip(), bid))
        flash("Schedule updated.", "success")
    return redirect(url_for("admin_classes") + f"#class-{b['class_id']}")


@app.route("/admin/classes/<int:cid>/demos", methods=["POST"])
@admin_required
def admin_demo_add(cid):
    c = db.query("SELECT * FROM classes WHERE id = ?", (cid,), one=True) or abort(404)
    d, start = request.form.get("date"), request.form.get("start_time")
    if not (d and start):
        flash("Demo needs a date and a start time.", "error")
    else:
        did = db.execute("INSERT INTO demos (class_id, date, start_time, end_time, location, notes) VALUES (?,?,?,?,?,?)",
                         (cid, d, start, request.form.get("end_time") or None,
                          request.form.get("location") or setting("address"), request.form.get("notes", "")))
        flash(f"Demo added for {c['name']} on {nicedate(d)}.", "success")
        if request.form.get("notify"):
            n = 0
            for e in db.query(ENROLL_SQL + " WHERE e.class_id = ? AND e.status IN ('interested','dropped')", (cid,)):
                send_wa(e["phone"], f"Hi {e['uname']}, a free {c['name']} demo is on {nicedate(d)} at {t12(start)}, "
                                    f"{setting('address')}. Book in one tap: {link('/home#demos')}", "demo_invite")
                n += 1
            flash(f"Invited {n} interested student(s) on WhatsApp.", "success")
    return redirect(url_for("admin_classes") + f"#class-{cid}")


@app.route("/admin/demos/<int:did>/delete", methods=["POST"])
@admin_required
def admin_demo_delete(did):
    d = db.query("SELECT * FROM demos WHERE id = ?", (did,), one=True) or abort(404)
    db.execute("UPDATE enrollments SET status = 'interested' WHERE demo_id = ? AND status = 'demo'", (did,))
    db.execute("DELETE FROM demos WHERE id = ?", (did,))
    flash("Demo removed. Anyone booked on it is back to Interested.", "success")
    return redirect(url_for("admin_classes") + f"#class-{d['class_id']}")


# ---------------------------------------------------------------- admin: promotions

AUDIENCES = {
    "all": ("Everyone", "SELECT DISTINCT u.phone, u.name FROM users u WHERE u.role = 'customer' AND u.name IS NOT NULL"),
    "not_subscribed": ("Not yet subscribed", """SELECT DISTINCT u.phone, u.name FROM users u WHERE u.role = 'customer'
        AND u.name IS NOT NULL AND u.id NOT IN (SELECT user_id FROM enrollments WHERE status = 'subscribed')"""),
    "subscribed": ("Current students", """SELECT DISTINCT u.phone, u.name FROM users u
        JOIN enrollments e ON e.user_id = u.id WHERE e.status = 'subscribed'"""),
    "class": ("Interested in this class", """SELECT DISTINCT u.phone, u.name FROM users u
        JOIN enrollments e ON e.user_id = u.id WHERE e.class_id = ?"""),
}


def _send_promo(promo, audience):
    label, sql = AUDIENCES.get(audience, AUDIENCES["all"])
    if audience == "class":
        if not promo["class_id"]:
            return 0
        people = db.query(sql, (promo["class_id"],))
    else:
        people = db.query(sql)
    body = f"✨ {promo['title']}\n{promo['body'] or ''}\n{link('/home')}".strip()
    for person in people:
        send_wa(person["phone"], body, "promotion", media=promo["media"], media_type=promo["media_type"])
    return len(people)


@app.route("/admin/promotions", methods=["GET", "POST"])
@admin_required
def admin_promotions():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Give the promotion a title.", "error")
        else:
            media, media_type = save_upload(request.files.get("media"))
            pid = db.execute("INSERT INTO promotions (title, body, media, media_type, class_id) VALUES (?,?,?,?,?)",
                             (title, request.form.get("body", ""), media, media_type,
                              request.form.get("class_id", type=int)))
            msg = "Promotion is live on the student home page."
            if request.form.get("send"):
                promo = db.query("SELECT * FROM promotions WHERE id = ?", (pid,), one=True)
                n = _send_promo(promo, request.form.get("audience", "all"))
                msg += f" Sent on WhatsApp to {n} people."
            flash(msg, "success")
            return redirect(url_for("admin_promotions"))
    promos = db.query("""SELECT p.*, c.name AS cname FROM promotions p LEFT JOIN classes c ON c.id = p.class_id
                         ORDER BY p.active DESC, p.created_at DESC, p.id DESC""")
    classes = db.query("SELECT id, name FROM classes WHERE active = 1 ORDER BY name")
    return render_template("admin/promotions.html", promos=promos, classes=classes, audiences=AUDIENCES)


@app.route("/admin/promotions/<int:pid>", methods=["POST"])
@admin_required
def admin_promotion_action(pid):
    promo = db.query("SELECT * FROM promotions WHERE id = ?", (pid,), one=True) or abort(404)
    action = request.form.get("action")
    if action == "send":
        n = _send_promo(promo, request.form.get("audience", "all"))
        flash(f"Sent on WhatsApp to {n} people.", "success")
    elif action == "toggle":
        db.execute("UPDATE promotions SET active = 1 - active WHERE id = ?", (pid,))
        flash("Promotion updated.", "success")
    elif action == "delete":
        db.execute("DELETE FROM promotions WHERE id = ?", (pid,))
        flash("Promotion deleted.", "success")
    return redirect(url_for("admin_promotions"))


# ---------------------------------------------------------------- admin: people, messages, settings

@app.route("/admin/people")
@admin_required
def admin_people():
    q = request.args.get("q", "").strip()
    sql = "SELECT * FROM users WHERE role = 'customer'"
    args = []
    if q:
        sql += (" AND (LOWER(name) LIKE ? OR phone LIKE ? OR LOWER(community) LIKE ?"
                " OR LOWER(parent_name) LIKE ?)")
        args = [f"%{q.lower()}%"] * 4
    users = db.query(sql + " ORDER BY created_at DESC", args)
    enr = defaultdict(list)
    for e in db.query(ENROLL_SQL):
        enr[e["user_id"]].append(e)
    dues = {r["user_id"]: r["amt"] for r in db.query(
        "SELECT user_id, SUM(amount) AS amt FROM payments WHERE status IN ('pending','submitted') GROUP BY user_id")}
    if request.args.get("format") == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Name", "WhatsApp", "Age", "Parent", "Community", "Classes", "Pending fees", "Joined"])
        for u in users:
            w.writerow([u["name"], "+" + u["phone"], u["age"], u["parent_name"], u["community"],
                        "; ".join(f"{e['cname']} ({STATUS_LABELS[e['status']]})" for e in enr[u["id"]]),
                        dues.get(u["id"], 0), u["created_at"][:10]])
        return Response(out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=sanskriti-students.csv"})
    return render_template("admin/people.html", users=users, enr=enr, dues=dues, q=q)


@app.route("/admin/messages")
@admin_required
def admin_messages():
    msgs = db.query("SELECT * FROM messages ORDER BY id DESC LIMIT 300")
    return render_template("admin/messages.html", msgs=msgs)


@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        for key in DEFAULT_SETTINGS:
            if key in request.form:
                db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                           "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                           (key, request.form.get(key, "").strip()))
        if g.user["phone"] not in admin_phones():
            # never lock yourself out
            phones = setting("admin_phones")
            db.execute("INSERT INTO settings (key, value) VALUES ('admin_phones', ?) "
                       "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                       ((phones + "," if phones else "") + g.user["phone"],))
        flash("Settings saved.", "success")
        return redirect(url_for("admin_settings"))
    return render_template("admin/settings.html", env_admins=os.environ.get("ADMIN_PHONES", ""))


def set_setting(key, value):
    db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
               "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))


@app.route("/admin/website", methods=["GET", "POST"])
@admin_required
def admin_site():
    """Logo, background colour, music, the 'What Sanskriti means' text and the homepage carousel."""
    if request.method == "POST":
        action = request.form.get("action", "")
        sid = request.form.get("slide_id", type=int)
        if action == "look":
            color = request.form.get("bg_color", "").strip()
            if re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                set_setting("bg_color", color.lower())
            set_setting("about_title", request.form.get("about_title", "").strip())
            set_setting("about_text", request.form.get("about_text", "").strip().replace("\r\n", "\n"))
            flash("Saved. Open the homepage to see it.", "success")
        elif action == "logo":
            name, _ = save_upload(request.files.get("file"), kinds=("image",))
            if name:
                set_setting("logo", name)
                flash("Logo updated.", "success")
        elif action == "logo_remove":
            set_setting("logo", "")
            flash("Logo removed.", "success")
        elif action == "music":
            name, _ = save_upload(request.files.get("file"), kinds=("audio",))
            if name:
                set_setting("music", name)
                set_setting("music_on", "1")
                flash("Music updated.", "success")
        elif action == "music_default":
            set_setting("music", DEFAULT_SETTINGS["music"])
            set_setting("music_on", "1")
            flash("Back to the default music.", "success")
        elif action == "music_toggle":
            set_setting("music_on", "0" if setting("music_on") == "1" else "1")
            flash("Music turned " + ("on." if setting("music_on") == "1" else "off."), "success")
        elif action == "slide_add":
            name, kind = save_upload(request.files.get("file"))
            if name:
                top = db.query("SELECT COALESCE(MAX(sort), 0) AS m FROM slides", one=True)["m"]
                db.execute("INSERT INTO slides (media, media_type, caption, class_id, sort) VALUES (?,?,?,?,?)",
                           (name, kind, request.form.get("caption", "").strip(),
                            request.form.get("class_id", type=int) or None, top + 1))
                flash("Added to the carousel.", "success")
        elif sid and action == "slide_save":
            db.execute("UPDATE slides SET caption = ?, class_id = ? WHERE id = ?",
                       (request.form.get("caption", "").strip(), request.form.get("class_id", type=int) or None, sid))
            flash("Slide saved.", "success")
        elif sid and action == "slide_replace":
            name, kind = save_upload(request.files.get("file"))
            if name:
                db.execute("UPDATE slides SET media = ?, media_type = ? WHERE id = ?", (name, kind, sid))
                flash("Photo/video replaced.", "success")
        elif sid and action == "slide_toggle":
            db.execute("UPDATE slides SET active = 1 - active WHERE id = ?", (sid,))
        elif sid and action == "slide_delete":
            db.execute("DELETE FROM slides WHERE id = ?", (sid,))
            flash("Slide removed.", "success")
        elif sid and action in ("slide_up", "slide_down"):
            order = [r["id"] for r in db.query("SELECT id FROM slides ORDER BY sort, id")]
            i = order.index(sid) if sid in order else -1
            j = i - 1 if action == "slide_up" else i + 1
            if i >= 0 and 0 <= j < len(order):
                order[i], order[j] = order[j], order[i]
                for n, x in enumerate(order):
                    db.execute("UPDATE slides SET sort = ? WHERE id = ?", (n, x))
        return redirect(url_for("admin_site") + request.form.get("anchor", ""))
    slides = db.query("""SELECT s.*, c.name AS class_name FROM slides s LEFT JOIN classes c ON c.id = s.class_id
                         ORDER BY s.sort, s.id""")
    classes = db.query("SELECT id, name FROM classes ORDER BY name")
    return render_template("admin/website.html", slides=slides, classes=classes, presets=BG_PRESETS)


# ---------------------------------------------------------------- errors & CLI

@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", title="Admins only", message="This page is for Sanskriti admins."), 403


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", title="Not found", message="We couldn't find that page."), 404


@app.errorhandler(413)
def too_large(_e):
    return render_template("error.html", title="File too large",
                           message=f"Uploads can be up to {os.environ.get('MAX_UPLOAD_MB', '50')} MB."), 413


@app.cli.command("send-reminders")
def send_reminders_cmd():
    """Daily job: class + demo reminders for tomorrow, payment and feedback nudges."""
    n = run_reminders()
    print(f"Sent {n} reminder(s).")


@app.cli.command("reset-db")
def reset_db_cmd():
    """Delete all data and recreate the tables with sample data."""
    if db.is_postgres():
        conn = db.connect(app)
        conn.execute("DROP TABLE IF EXISTS " + ", ".join(sorted(db.ID_TABLES | {"otps", "settings"})) + " CASCADE")
        conn.commit()
        conn.close()
    elif os.path.exists(app.config["DATABASE"]):
        os.remove(app.config["DATABASE"])
    db.init_db(app, seed=True)
    print("Database reset.")


if __name__ == "__main__":
    app.run(debug=True)
