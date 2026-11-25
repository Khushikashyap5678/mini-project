import calendar
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import hmac
from pathlib import Path
import os
import secrets
import sqlite3

from flask import (
    Flask, Response, abort, flash, redirect, render_template, request, session, url_for,
)


ROOT = Path(__file__).resolve().parent
INDIA = timezone(timedelta(hours=5, minutes=30), "IST")
DEPARTMENTS = {
    "academic": ("Academic Advising", "Course planning and faculty meetings", "book", "blue"),
    "student": ("Student Services", "Student records and campus support", "cap", "violet"),
    "career": ("Career & Placement", "Career guidance and placement queries", "briefcase", "amber"),
    "library": ("Library", "Research help and library services", "library", "green"),
    "other": ("Other", "General campus appointments", "calendar", "blue"),
}
REMINDER_OPTIONS = {0: "Off", 15: "15 minutes before", 60: "1 hour before", 1440: "24 hours before"}
FILTERS = {
    "upcoming": "Upcoming", "pending": "Pending approval", "approved": "Approved",
    "past": "Past", "cancelled": "Cancelled", "all": "All appointments",
}


def campus_now():
    return datetime.now(INDIA).replace(tzinfo=None)


def create_app(data_dir=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=Path(data_dir or os.getenv("CAMPUS_DATA_DIR") or ROOT / "instance") / "appointments.db",
        MAX_CONTENT_LENGTH=32 * 1024,
        SESSION_COOKIE_SAMESITE="Lax",
        TEACHER_PASSWORD=os.getenv("TEACHER_PASSWORD", ""),
    )

    @contextmanager
    def database():
        connection = sqlite3.connect(app.config["DATABASE"], timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    app.config["DATABASE"].parent.mkdir(parents=True, exist_ok=True)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                appointment_date TEXT NOT NULL,
                notes TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                department TEXT NOT NULL DEFAULT 'other',
                reminder_minutes INTEGER NOT NULL DEFAULT 1440,
                revision INTEGER NOT NULL DEFAULT 0
            )
        """)
        columns = {column["name"] for column in db.execute("PRAGMA table_info(appointments)")}
        if "department" not in columns:
            db.execute("ALTER TABLE appointments ADD COLUMN department TEXT NOT NULL DEFAULT 'other'")
        if "reminder_minutes" not in columns:
            db.execute("ALTER TABLE appointments ADD COLUMN reminder_minutes INTEGER NOT NULL DEFAULT 1440")
        if "revision" not in columns:
            db.execute("ALTER TABLE appointments ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
        db.execute("UPDATE appointments SET status='pending' WHERE status='booked'")
        db.execute("CREATE TABLE IF NOT EXISTS portal_settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute(
            "INSERT OR IGNORE INTO portal_settings VALUES ('session_key', ?)",
            (secrets.token_hex(32),),
        )
        app.secret_key = os.getenv("CAMPUS_SECRET_KEY") or db.execute(
            "SELECT value FROM portal_settings WHERE name = 'session_key'"
        ).fetchone()["value"]

    def csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    @app.before_request
    def protect_forms():
        if request.method == "POST":
            expected = session.get("csrf_token")
            supplied = request.form.get("csrf_token", "")
            if not expected or not secrets.compare_digest(expected.encode(), supplied.encode()):
                abort(400, "The form expired. Go back, reload the page and try again.")

    app.jinja_env.globals.update(
        departments=DEPARTMENTS, reminder_options=REMINDER_OPTIONS, csrf_token=csrf_token,
    )

    def get_appointment(appointment_id):
        with database() as db:
            return db.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()

    def as_appointment(row):
        item = dict(row)
        item["when"] = datetime.fromisoformat(item["appointment_date"])
        return item

    def month_link(target, selected_day=""):
        return url_for(
            "index", month=target.strftime("%Y-%m"), day=selected_day or None,
            status=request.args.get("status") or ("all" if selected_day else None),
            department=request.args.get("department") or None,
            q=request.args.get("q") or None,
        ) + "#schedule"

    @app.get("/")
    def index():
        now = campus_now()
        today = now.date()
        status_filter = request.args.get("status", "upcoming")
        if status_filter not in FILTERS:
            status_filter = "upcoming"
        department_filter = request.args.get("department", "")
        if department_filter not in DEPARTMENTS:
            department_filter = ""
        query = request.args.get("q", "").strip()[:100]
        try:
            selected_day = date.fromisoformat(request.args.get("day", ""))
        except ValueError:
            selected_day = None
        try:
            first = date.fromisoformat(request.args.get("month", "") + "-01")
            if not 1900 <= first.year <= 9998:
                raise ValueError
        except ValueError:
            preferred = selected_day if selected_day and 1900 <= selected_day.year <= 9998 else today
            first = preferred.replace(day=1)

        with database() as db:
            appointments = [as_appointment(row) for row in db.execute(
                "SELECT * FROM appointments ORDER BY appointment_date, id"
            )]

        upcoming = []
        due = []
        counts = {}
        filtered = []
        for item in appointments:
            when = item["when"]
            day = when.date()
            status = item["status"]
            active = status in ("pending", "approved")
            is_future = when >= now
            item["display_status"] = {
                "pending": "Pending approval", "approved": "Approved", "cancelled": "Cancelled",
            }[status]
            if active:
                counts[day] = counts.get(day, 0) + 1
            if status == "approved" and is_future:
                upcoming.append(item)
                lead = item["reminder_minutes"]
                if lead and when - now <= timedelta(minutes=lead):
                    due.append(item)

            categories = {status}
            if active:
                categories.add("upcoming" if is_future else "past")
            search_text = " ".join((item["title"], item["notes"] or "", DEPARTMENTS[item["department"]][0]))
            if (
                (status_filter == "all" or status_filter in categories)
                and (not department_filter or item["department"] == department_filter)
                and (not selected_day or selected_day == day)
                and query.casefold() in search_text.casefold()
            ):
                filtered.append(item)

        previous = (first - timedelta(days=1)).replace(day=1)
        following = (first + timedelta(days=32)).replace(day=1)
        weeks = calendar.Calendar().monthdatescalendar(first.year, first.month)
        while len(weeks) < 6:
            weeks.append([weeks[-1][-1] + timedelta(days=offset) for offset in range(1, 8)])
        if status_filter == "past":
            filtered.reverse()
        return render_template(
            "index.html", now=now, today=today, upcoming=upcoming, reminders=due, appointments=filtered,
            total=len(appointments), pending_count=sum(item["status"] == "pending" for item in appointments), week_count=sum(
                item["when"] < datetime.combine(today + timedelta(days=7), datetime.min.time())
                for item in upcoming
            ),
            month=first, previous_month=month_link(previous) if previous.year >= 1900 else None,
            next_month=month_link(following) if following.year <= 9998 else None,
            weeks=weeks, date_counts=counts, month_link=month_link, selected_day=selected_day,
            status_filter=status_filter, department_filter=department_filter, query=query, filters=FILTERS,
        )

    def appointment_form(appointment=None):
        initial_department = request.args.get("department", "academic")
        if initial_department not in DEPARTMENTS:
            initial_department = "academic"
        values = dict(appointment) if appointment else {
            "title": "", "appointment_date": "", "notes": "",
            "department": initial_department, "reminder_minutes": 1440,
        }
        errors = []
        now = campus_now()
        if request.method == "POST":
            if appointment and request.form.get("revision", type=int) != appointment["revision"]:
                flash("This request changed while you were editing it. Review the latest details.", "error")
                return redirect(url_for("edit_appointment", appointment_id=appointment["id"]))
            values.update(
                title=request.form.get("title", "").strip(),
                appointment_date=request.form.get("appointment_date", "").strip(),
                notes=request.form.get("notes", "").strip(),
                department=request.form.get("department", values["department"]),
            )
            try:
                values["reminder_minutes"] = int(request.form.get("reminder_minutes", values["reminder_minutes"]))
            except ValueError:
                values["reminder_minutes"] = -1
            if not 1 <= len(values["title"]) <= 100:
                errors.append("Enter an appointment title of 1 to 100 characters.")
            if len(values["notes"]) > 600:
                errors.append("Keep your notes within 600 characters.")
            if values["department"] not in DEPARTMENTS:
                errors.append("Choose a campus department.")
            if values["reminder_minutes"] not in REMINDER_OPTIONS:
                errors.append("Choose a reminder option.")
            try:
                when = datetime.strptime(values["appointment_date"], "%Y-%m-%dT%H:%M")
                unchanged_time = appointment and values["appointment_date"] == appointment["appointment_date"]
                if when <= now and not unchanged_time:
                    errors.append("Choose a date and time in the future (IST).")
                if when.year > 9998 and not unchanged_time:
                    errors.append("Choose a date before the year 9999.")
                values["appointment_date"] = when.isoformat(timespec="minutes")
            except ValueError:
                errors.append("Enter a valid date and time.")

            if not errors:
                data = (values["title"], values["appointment_date"], values["notes"],
                        values["department"], values["reminder_minutes"])
                with database() as db:
                    if appointment:
                        current = (appointment["title"], appointment["appointment_date"], appointment["notes"] or "",
                                   appointment["department"], appointment["reminder_minutes"])
                        if data == current:
                            flash("No changes to save.", "success")
                            return redirect(url_for("index", status="all" if when < now else None))
                        updated = db.execute("""
                            UPDATE appointments SET title=?, appointment_date=?, notes=?, department=?, reminder_minutes=?,
                                status='pending', revision=revision+1
                            WHERE id=? AND status IN ('pending', 'approved') AND revision=?
                        """, (*data, appointment["id"], appointment["revision"]))
                        if not updated.rowcount:
                            flash("This request changed while you were editing it. Reopen it to see the latest details.", "error")
                            return redirect(url_for("index"))
                    else:
                        db.execute("""
                            INSERT INTO appointments (title, appointment_date, notes, department, reminder_minutes, status)
                            VALUES (?, ?, ?, ?, ?, 'pending')
                        """, data)
                flash("Changes saved. Awaiting teacher approval." if appointment else "Request sent. Awaiting teacher approval.", "success")
                return redirect(url_for("index", status="all" if when < now else None))
        return render_template(
            "appointment_form.html", appointment=appointment, values=values, errors=errors,
            earliest=(now + timedelta(minutes=1)).isoformat(timespec="minutes"),
        ), 400 if errors else 200

    @app.route("/add", methods=["GET", "POST"])
    def add_appointment():
        return appointment_form()

    @app.route("/edit/<int:appointment_id>", methods=["GET", "POST"])
    def edit_appointment(appointment_id):
        appointment = get_appointment(appointment_id)
        if appointment is None or appointment["status"] not in ("pending", "approved"):
            flash("That active appointment could not be found.", "error")
            return redirect(url_for("index"))
        return appointment_form(appointment)

    @app.post("/cancel/<int:appointment_id>")
    def cancel_appointment(appointment_id):
        with database() as db:
            updated = db.execute(
                "UPDATE appointments SET status='cancelled' WHERE id=? AND status IN ('pending', 'approved')",
                (appointment_id,),
            )
        if updated.rowcount:
            flash("Appointment cancelled.", "success")
            return redirect(url_for("index", status="cancelled") + "#schedule")
        flash("That active appointment could not be found.", "error")
        return redirect(url_for("index"))

    def teacher_signature():
        password = app.config["TEACHER_PASSWORD"]
        return hmac.new(app.secret_key.encode(), password.encode(), "sha256").hexdigest() if password else ""

    def teacher_signed_in():
        signature = teacher_signature()
        return bool(signature and secrets.compare_digest(signature, session.get("teacher", "")))

    @app.route("/teacher", methods=["GET", "POST"])
    def teacher_dashboard():
        password = app.config["TEACHER_PASSWORD"]
        if request.method == "POST":
            submitted = request.form.get("password", "")
            if password and secrets.compare_digest(password.encode(), submitted.encode()):
                session.clear()
                session["teacher"] = teacher_signature()
                return redirect(url_for("teacher_dashboard"))
            flash("Teacher password is incorrect.", "error")
        signed_in = teacher_signed_in()
        appointments = []
        if signed_in:
            with database() as db:
                appointments = [as_appointment(row) for row in db.execute(
                    "SELECT * FROM appointments WHERE status='pending' ORDER BY appointment_date, id"
                )]
        return render_template(
            "teacher.html", configured=bool(password), signed_in=signed_in, appointments=appointments,
        )

    @app.post("/teacher/approve/<int:appointment_id>")
    def approve_appointment(appointment_id):
        if not teacher_signed_in():
            abort(403)
        revision = request.form.get("revision", type=int)
        if revision is None:
            abort(400, "Refresh the queue before reviewing this request.")
        with database() as db:
            result = db.execute("""
                UPDATE appointments SET status='approved'
                WHERE id=? AND status='pending' AND revision=?
            """, (appointment_id, revision))
        if result.rowcount:
            flash("Appointment approved.", "success")
        else:
            flash("This request changed or has already been handled. Check the current queue.", "error")
        return redirect(url_for("teacher_dashboard"))

    @app.post("/teacher/logout")
    def teacher_logout():
        session.pop("teacher", None)
        return redirect(url_for("teacher_dashboard"))

    @app.get("/calendar/<int:appointment_id>.ics")
    def export_appointment(appointment_id):
        row = get_appointment(appointment_id)
        if row is None or row["status"] != "approved":
            abort(404)
        item = as_appointment(row)
        start = item["when"].replace(tzinfo=INDIA)
        finish = start + timedelta(minutes=30)
        calendar_id = sha256(app.secret_key.encode()).hexdigest()[:24]
        lines = [
            "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Campus Appointments//EN",
            "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
            f"UID:{appointment_id}-{calendar_id}@campus-appointments.local",
            "DTSTAMP:" + utc_stamp(datetime.now(timezone.utc)),
            "DTSTART:" + utc_stamp(start), "DTEND:" + utc_stamp(finish),
            "SUMMARY:" + calendar_text(item["title"]),
            "DESCRIPTION:" + calendar_text(item["notes"] or ""),
            "LOCATION:" + calendar_text(DEPARTMENTS[item["department"]][0]),
        ]
        if item["reminder_minutes"]:
            lines.extend((
                "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + calendar_text(item["title"]),
                f"TRIGGER:-PT{item['reminder_minutes']}M", "END:VALARM",
            ))
        lines += ["END:VEVENT", "END:VCALENDAR"]
        return Response(
            "\r\n".join(calendar_line(line) for line in lines) + "\r\n",
            content_type="text/calendar; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="campus-appointment-{appointment_id}.ics"'},
        )

    return app


def utc_stamp(value):
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def calendar_text(value):
    return (value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n")
            .replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,"))


def calendar_line(line):
    pieces = []
    current = ""
    size = 0
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > 75:
            pieces.append(current)
            current, size = " ", 1
        current += char
        size += width
    pieces.append(current)
    return "\r\n".join(pieces)


app = create_app()

if __name__ == "__main__":
    app.run(port=int(os.getenv("CAMPUS_PORT", "5000")))
