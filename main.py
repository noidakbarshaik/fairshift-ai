from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, create_engine, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = Path("/tmp/fairshift.db") if os.getenv("VERCEL") else ROOT / "fairshift.db"
DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")
if DB_URL.startswith("postgresql://"):
    DB_URL = "postgresql+psycopg://" + DB_URL[len("postgresql://"): ]
engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {}, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
SECRET_KEY = os.getenv("FAIRSHIFT_SECRET", "local-demo-only-change-before-deploy")
if os.getenv("ENVIRONMENT") == "production" and SECRET_KEY == "local-demo-only-change-before-deploy":
    raise RuntimeError("Set FAIRSHIFT_SECRET to a strong secret in production.")
SESSION_TTL = 60 * 60 * 12


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    industry: Mapped[str] = mapped_column(String(60), nullable=False)
    locations_json: Mapped[str] = mapped_column(Text, default="[]")
    categories_json: Mapped[str] = mapped_column(Text, default="[]")
    standard_hours: Mapped[float] = mapped_column(Float, default=8)
    overtime_multiplier: Mapped[float] = mapped_column(Float, default=1.5)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    org_id: Mapped[Optional[str]] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    hourly_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="en")


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (
        Index("uq_attendance_one_open_session", "worker_id", unique=True,
              sqlite_where=text("check_out IS NULL"), postgresql_where=text("check_out IS NULL")),
    )
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    check_in: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    check_out: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0)
    worker: Mapped[User] = relationship()


class SafetyReport(Base):
    __tablename__ = "safety_reports"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    reference: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    worker_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    access_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(String(120), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="Reported")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ReportEvent(Base):
    __tablename__ = "report_events"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("safety_reports.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str] = mapped_column(String(300), default="")
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    actor_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)


class LoginIn(BaseModel):
    email: str
    password: str


class AttendanceIn(BaseModel):
    break_minutes: int = Field(default=0, ge=0, le=600)


class ReportIn(BaseModel):
    category: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=8, max_length=3000)
    location: str = Field(min_length=2, max_length=120)
    severity: str = Field(pattern="^(Low|Medium|High|Urgent)$")
    anonymous: bool = False


class StatusIn(BaseModel):
    status: str = Field(pattern="^(Under Review|In Progress|Resolved)$")
    note: str = Field(default="", max_length=300)


app = FastAPI(title="FairShift AI", version="0.1.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def password_digest(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    result = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240000).hex()
    return f"{salt}${result}"


def password_ok(password: str, encoded: str) -> bool:
    try:
        salt, expected = encoded.split("$", 1)
        actual = password_digest(password, salt).split("$", 1)[1]
        return hmac.compare_digest(actual, expected)
    except ValueError:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def make_session(user_id: str) -> str:
    expires = int(now_utc().timestamp()) + SESSION_TTL
    payload = f"{user_id}.{expires}"
    signature = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def session_user_id(request: Request) -> Optional[str]:
    raw = request.cookies.get("fairshift_session", "")
    try:
        user_id, expires, signature = raw.rsplit(".", 2)
        payload = f"{user_id}.{expires}"
        expected = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if int(expires) < int(now_utc().timestamp()) or not hmac.compare_digest(signature, expected):
            return None
        return user_id
    except (ValueError, TypeError):
        return None


def require_user(request: Request, db: Session) -> User:
    uid = session_user_id(request)
    user = db.get(User, uid) if uid else None
    if not user:
        raise HTTPException(401, "Please sign in to continue.")
    return user


def require_admin(request: Request, db: Session) -> User:
    user = require_user(request, db)
    if user.role != "admin":
        raise HTTPException(403, "Administrator access is required.")
    return user


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def dt_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return as_utc(value).isoformat()


def duration_hours(start: datetime, end: datetime, break_minutes: int = 0) -> float:
    start, end = as_utc(start), as_utc(end)
    if end < start:
        raise ValueError("Check-out time cannot be earlier than check-in.")
    return max(0.0, (end - start).total_seconds() / 3600 - break_minutes / 60)


def pay_breakdown(hours: float, rate: Optional[float], standard_hours: float, multiplier: float) -> dict:
    if rate is None:
        return {"available": False, "reason": "Your hourly rate has not been configured."}
    regular = min(hours, standard_hours)
    overtime = max(0.0, hours - standard_hours)
    regular_pay = regular * rate
    overtime_pay = overtime * rate * multiplier
    return {"available": True, "eligible_hours": round(hours, 2), "regular_hours": round(regular, 2),
            "overtime_hours": round(overtime, 2), "hourly_rate": round(rate, 2),
            "regular_pay": round(regular_pay, 2), "overtime_multiplier": multiplier,
            "overtime_pay": round(overtime_pay, 2), "estimated_gross_pay": round(regular_pay + overtime_pay, 2),
            "standard_hours": standard_hours, "currency": "INR"}


def org_info(org: Organization) -> dict:
    return {"id": org.id, "name": org.name, "industry": org.industry,
            "locations": json.loads(org.locations_json), "categories": json.loads(org.categories_json),
            "standard_hours": org.standard_hours, "overtime_multiplier": org.overtime_multiplier}


def seed_database() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(Organization.id).limit(1)):
            return
        orgs = [
            Organization(id="construction", name="FairShift Construction Services", industry="Construction",
                         locations_json=json.dumps(["North Site", "Warehouse", "Site Office"]),
                         categories_json=json.dumps(["Electrical hazard", "Damaged equipment", "Unsafe scaffolding", "Missing protective equipment", "Harassment or unfair treatment", "Other"])),
            Organization(id="campus", name="FairShift Campus Services", industry="College & University Facilities",
                         locations_json=json.dumps(["Main Campus", "Library", "Science Block", "Student Residence"]),
                         categories_json=json.dumps(["Electrical fault", "Wet floor", "Damaged equipment", "Unsafe working conditions", "Harassment or unfair treatment", "Other"])),
        ]
        db.add_all(orgs)
        users = [
            User(id="admin-demo", email="admin@fairshift.demo", name="Demo Administrator", role="admin", password_hash=password_digest("FairShiftDemo26!")),
            User(id="worker-construction", org_id="construction", email="worker@fairshift.demo", name="Sample Worker A", role="worker", password_hash=password_digest("FairShiftDemo26!"), hourly_rate=180),
            User(id="worker-campus", org_id="campus", email="campus@fairshift.demo", name="Sample Worker B", role="worker", password_hash=password_digest("FairShiftDemo26!"), hourly_rate=165),
            User(id="worker-construction-2", org_id="construction", email="siteworker@fairshift.demo", name="Sample Worker C", role="worker", password_hash=password_digest("FairShiftDemo26!"), hourly_rate=200),
            User(id="worker-campus-2", org_id="campus", email="campusworker@fairshift.demo", name="Sample Worker D", role="worker", password_hash=password_digest("FairShiftDemo26!"), hourly_rate=175),
        ]
        db.add_all(users)
        db.flush()
        now = now_utc()
        yesterday = now - timedelta(days=1)
        db.add_all([
            Attendance(id="att-sample-1", worker_id="worker-construction", check_in=yesterday.replace(hour=3, minute=30), check_out=yesterday.replace(hour=13, minute=45), break_minutes=30),
            Attendance(id="att-sample-2", worker_id="worker-campus", check_in=yesterday.replace(hour=4, minute=0), check_out=yesterday.replace(hour=12, minute=30), break_minutes=30),
        ])
        samples = [
            ("construction", "Electrical hazard", "A damaged cable cover was noticed near the materials area.", "North Site", "High", "Under Review", False, "worker-construction"),
            ("construction", "Missing protective equipment", "Spare eye protection is low at the cutting station.", "Warehouse", "Medium", "Reported", True, None),
            ("campus", "Wet floor", "Water is collecting near the library entrance after cleaning.", "Library", "Urgent", "In Progress", True, None),
            ("campus", "Damaged equipment", "A trolley wheel is loose and needs repair.", "Student Residence", "Low", "Resolved", False, "worker-campus"),
        ]
        for index, (org_id, category, description, location, severity, status, anonymous, worker_id) in enumerate(samples):
            report = SafetyReport(id=f"report-sample-{index+1}", reference=f"FS-SAMPLE-{index+1:03d}", org_id=org_id,
                                  worker_id=worker_id, category=category, description=description, location=location,
                                  severity=severity, anonymous=anonymous, status=status, created_at=now, updated_at=now)
            db.add(report)
            db.flush()
            db.add(ReportEvent(id=f"event-sample-{index+1}", report_id=report.id, status="Reported", note="Report received", changed_at=now))
            if status != "Reported":
                db.add(ReportEvent(id=f"event-sample-{index+1}-status", report_id=report.id, status=status, note="Sample status update", changed_at=now))
        db.commit()


@app.on_event("startup")
def startup() -> None:
    seed_database()


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/login")
def login(data: LoginIn, response: Response):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
        if not user or not password_ok(data.password, user.password_hash):
            raise HTTPException(401, "Email or password is incorrect.")
        response.set_cookie("fairshift_session", make_session(user.id), httponly=True, secure=os.getenv("COOKIE_SECURE", "0") == "1", samesite="lax", max_age=SESSION_TTL, path="/")
        org = db.get(Organization, user.org_id) if user.org_id else None
        return {"user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role,
                         "organization": org.name if org else None, "industry": org.industry if org else None}}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("fairshift_session", path="/")
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    with SessionLocal() as db:
        user = require_user(request, db)
        org = db.get(Organization, user.org_id) if user.org_id else None
        return {"id": user.id, "name": user.name, "email": user.email, "role": user.role,
                "organization": org.name if org else None, "industry": org.industry if org else None,
                "hourly_rate": user.hourly_rate}


@app.get("/api/organizations")
def organizations(request: Request):
    with SessionLocal() as db:
        user = require_user(request, db)
        if user.role != "admin":
            raise HTTPException(403, "Administrator access is required.")
        return [org_info(org) for org in db.scalars(select(Organization).order_by(Organization.name)).all()]


def worker_attendance(db: Session, user: User) -> list[dict]:
    rows = db.scalars(select(Attendance).where(Attendance.worker_id == user.id).order_by(Attendance.check_in.desc()).limit(100)).all()
    org = db.get(Organization, user.org_id)
    out = []
    for row in rows:
        hours = duration_hours(row.check_in, row.check_out, row.break_minutes) if row.check_out else None
        out.append({"id": row.id, "check_in": dt_iso(row.check_in), "check_out": dt_iso(row.check_out),
                    "break_minutes": row.break_minutes, "hours": round(hours, 2) if hours is not None else None,
                    "pay": pay_breakdown(hours, user.hourly_rate, org.standard_hours, org.overtime_multiplier) if hours is not None else None})
    return out


@app.get("/api/worker/summary")
def worker_summary(request: Request):
    with SessionLocal() as db:
        user = require_user(request, db)
        if user.role != "worker":
            raise HTTPException(403, "Worker access is required.")
        org = db.get(Organization, user.org_id)
        latest = db.scalar(select(Attendance).where(Attendance.worker_id == user.id, Attendance.check_out.is_(None)).order_by(Attendance.check_in.desc()))
        records = worker_attendance(db, user)
        total_hours = sum(row["hours"] or 0 for row in records)
        open_pay = pay_breakdown(0, user.hourly_rate, org.standard_hours, org.overtime_multiplier)
        completed_pay = [row["pay"] for row in records if row["pay"] and row["pay"]["available"]]
        return {"organization": org_info(org), "checked_in": latest is not None,
                "current_session": {"check_in": dt_iso(latest.check_in)} if latest else None,
                "attendance": records, "total_recorded_hours": round(total_hours, 2),
                "estimated_gross_pay": round(sum(item["estimated_gross_pay"] for item in completed_pay), 2),
                "pay_assumptions": open_pay}


@app.post("/api/worker/check-in")
def check_in(request: Request):
    with SessionLocal() as db:
        user = require_user(request, db)
        if user.role != "worker":
            raise HTTPException(403, "Worker access is required.")
        active = db.scalar(select(Attendance.id).where(Attendance.worker_id == user.id, Attendance.check_out.is_(None)))
        if active:
            raise HTTPException(409, "You are already checked in.")
        record = Attendance(id=secrets.token_hex(12), worker_id=user.id, check_in=now_utc())
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "You are already checked in.")
        return {"ok": True, "check_in": dt_iso(record.check_in)}


@app.post("/api/worker/check-out")
def check_out(data: AttendanceIn, request: Request):
    with SessionLocal() as db:
        user = require_user(request, db)
        if user.role != "worker":
            raise HTTPException(403, "Worker access is required.")
        record = db.scalar(select(Attendance).where(Attendance.worker_id == user.id, Attendance.check_out.is_(None)).order_by(Attendance.check_in.desc()))
        if not record:
            raise HTTPException(409, "There is no open check-in to check out.")
        finish = now_utc()
        check_in_utc = as_utc(record.check_in)
        if finish <= check_in_utc:
            raise HTTPException(422, "Invalid check-out time.")
        if data.break_minutes >= (finish - check_in_utc).total_seconds() / 60:
            raise HTTPException(422, "Break time must be shorter than the recorded shift.")
        changed = db.execute(update(Attendance).where(Attendance.id == record.id, Attendance.check_out.is_(None))
                             .values(check_out=finish, break_minutes=data.break_minutes))
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, "This shift has already been checked out.")
        db.commit()
        org = db.get(Organization, user.org_id)
        hours = duration_hours(record.check_in, finish, record.break_minutes)
        return {"ok": True, "hours": round(hours, 2), "pay": pay_breakdown(hours, user.hourly_rate, org.standard_hours, org.overtime_multiplier)}


@app.post("/api/worker/reports")
def submit_report(data: ReportIn, request: Request):
    with SessionLocal() as db:
        user = require_user(request, db)
        if user.role != "worker":
            raise HTTPException(403, "Worker access is required.")
        org = db.get(Organization, user.org_id)
        if data.category not in json.loads(org.categories_json):
            raise HTTPException(422, "Choose a category for your organization.")
        if data.location not in json.loads(org.locations_json):
            raise HTTPException(422, "Choose a location for your organization.")
        access = secrets.token_urlsafe(24) if data.anonymous else None
        report = SafetyReport(id=secrets.token_hex(12), reference=f"FS-{secrets.token_hex(4).upper()}",
                              org_id=org.id, worker_id=None if data.anonymous else user.id,
                              access_hash=token_hash(access) if access else None, category=data.category,
                              description=data.description.strip(), location=data.location, severity=data.severity,
                              anonymous=data.anonymous, status="Reported", created_at=now_utc(), updated_at=now_utc())
        db.add(report)
        db.flush()
        db.add(ReportEvent(id=secrets.token_hex(12), report_id=report.id, status="Reported", note="Report received", changed_at=now_utc()))
        db.commit()
        return {"reference": report.reference, "anonymous_access_token": access,
                "message": "Save your reference number" + (" and private access code" if access else "") + " to check progress."}


@app.get("/api/worker/reports")
def my_reports(request: Request):
    with SessionLocal() as db:
        user = require_user(request, db)
        if user.role != "worker":
            raise HTTPException(403, "Worker access is required.")
        rows = db.scalars(select(SafetyReport).where(SafetyReport.worker_id == user.id).order_by(SafetyReport.created_at.desc())).all()
        return [{"reference": row.reference, "category": row.category, "description": row.description,
                 "location": row.location, "severity": row.severity, "status": row.status,
                 "created_at": dt_iso(row.created_at)} for row in rows]


@app.get("/api/reports/track/{reference}")
def track_report(reference: str, access_code: str = ""):
    with SessionLocal() as db:
        row = db.scalar(select(SafetyReport).where(SafetyReport.reference == reference))
        if not row:
            raise HTTPException(404, "Report reference was not found.")
        if row.anonymous:
            if not access_code or not row.access_hash or not hmac.compare_digest(token_hash(access_code), row.access_hash):
                raise HTTPException(403, "The private access code is required for this report.")
        elif row.worker_id is None:
            raise HTTPException(404, "Report reference was not found.")
        events = db.scalars(select(ReportEvent).where(ReportEvent.report_id == row.id).order_by(ReportEvent.changed_at)).all()
        return {"reference": row.reference, "status": row.status,
                "history": [{"status": e.status, "note": e.note, "changed_at": dt_iso(e.changed_at)} for e in events]}


def selected_org(request: Request, db: Session, org_id: Optional[str]) -> Organization:
    admin = require_admin(request, db)
    if not org_id:
        org_id = "construction"
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found.")
    return org


def dashboard_data(db: Session, org: Organization) -> dict:
    worker_list = db.scalars(select(User).where(User.org_id == org.id, User.role == "worker").order_by(User.name)).all()
    all_sessions = db.scalars(select(Attendance).join(User, Attendance.worker_id == User.id).where(User.org_id == org.id).order_by(Attendance.check_in.desc())).all()
    reports = db.scalars(select(SafetyReport).where(SafetyReport.org_id == org.id).order_by(SafetyReport.updated_at.desc())).all()
    active_workers = {a.worker_id for a in all_sessions if a.check_out is None}
    hours_total = overtime_total = 0.0
    attendance_rows = []
    for record in all_sessions:
        worker = db.get(User, record.worker_id)
        hrs = duration_hours(record.check_in, record.check_out, record.break_minutes) if record.check_out else None
        if hrs is not None:
            hours_total += hrs
            overtime_total += max(0, hrs - org.standard_hours)
        attendance_rows.append({"worker": worker.name, "check_in": dt_iso(record.check_in), "check_out": dt_iso(record.check_out),
                                "hours": round(hrs, 2) if hrs is not None else None,
                                "overtime_hours": round(max(0, hrs-org.standard_hours), 2) if hrs is not None else None,
                                "status": "Checked in" if record.check_out is None else "Complete"})
    report_rows = []
    for report in reports:
        # Anonymous reporter identity is not returned and is not linked to a user row.
        report_rows.append({"reference": report.reference, "category": report.category,
                            "description": report.description, "location": report.location,
                            "severity": report.severity, "anonymous": report.anonymous,
                            "reporter": "Anonymous" if report.anonymous else (db.get(User, report.worker_id).name if report.worker_id else "Worker"),
                            "status": report.status, "created_at": dt_iso(report.created_at),
                            "updated_at": dt_iso(report.updated_at)})
    open_reports = [r for r in report_rows if r["status"] != "Resolved"]
    return {"organization": org_info(org), "metrics": {"workers": len(worker_list), "currently_checked_in": len(active_workers),
             "attendance_sessions": len(all_sessions), "recorded_hours": round(hours_total, 2),
             "overtime_hours": round(overtime_total, 2), "open_reports": len(open_reports),
             "urgent_open_reports": sum(r["severity"] == "Urgent" for r in open_reports)},
            "attendance": attendance_rows[:100], "reports": report_rows[:100],
            "workers": [{"name": w.name, "email": w.email, "hourly_rate": w.hourly_rate} for w in worker_list]}


@app.get("/api/admin/dashboard")
def admin_dashboard(request: Request, org_id: Optional[str] = None):
    with SessionLocal() as db:
        org = selected_org(request, db, org_id)
        return dashboard_data(db, org)


@app.patch("/api/admin/reports/{reference}")
def update_report(reference: str, data: StatusIn, request: Request):
    with SessionLocal() as db:
        admin = require_admin(request, db)
        report = db.scalar(select(SafetyReport).where(SafetyReport.reference == reference))
        if not report:
            raise HTTPException(404, "Report not found.")
        report.status = data.status
        report.updated_at = now_utc()
        db.add(ReportEvent(id=secrets.token_hex(12), report_id=report.id, status=data.status,
                           note=data.note.strip() or f"Status updated to {data.status}", changed_at=now_utc(), actor_id=admin.id))
        db.commit()
        return {"ok": True, "reference": reference, "status": report.status}


def grounded_insight(data: dict) -> str:
    metrics = data["metrics"]
    findings = []
    if metrics["urgent_open_reports"]:
        findings.append(f"{metrics['urgent_open_reports']} urgent safety report(s) remain unresolved; review and assign an owner promptly.")
    if metrics["open_reports"]:
        findings.append(f"{metrics['open_reports']} safety report(s) are still open.")
    if metrics["overtime_hours"] > 0:
        findings.append(f"Recorded sessions include {metrics['overtime_hours']:.2f} overtime hours under the configured {data['organization']['standard_hours']}-hour threshold.")
    if not findings:
        findings.append("No open safety reports or overtime hours are recorded in this sample. Continue checking records as shifts are completed.")
    return " ".join(findings)


@app.post("/api/admin/insights")
def admin_insights(request: Request, org_id: Optional[str] = None):
    with SessionLocal() as db:
        org = selected_org(request, db, org_id)
        data = dashboard_data(db, org)
        summary = grounded_insight(data)
        # Optional server-side Gemini enhancement receives only aggregates and status/category counts.
        api_key = os.getenv("GEMINI_API_KEY")
        ai_used = False
        if api_key:
            from urllib.request import Request as URLRequest, urlopen
            counts: dict[str, int] = {}
            for row in data["reports"]:
                key = f"{row['category']} | {row['status']}"
                counts[key] = counts.get(key, 0) + 1
            payload = {"metrics": data["metrics"], "report_counts_by_category_and_status": counts,
                       "industry": data["organization"]["industry"]}
            prompt = ("Write a concise, cautious workforce operations summary using only these JSON facts. "
                      "Do not invent numbers, infer individual intent, identify workers, or provide legal advice. "
                      "Offer one practical follow-up. JSON: " + json.dumps(payload))
            body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
            model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            req = URLRequest(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                             data=body, headers={"Content-Type": "application/json", "x-goog-api-key": api_key}, method="POST")
            try:
                with urlopen(req, timeout=12) as result:
                    generated = json.loads(result.read().decode())
                candidate = generated["candidates"][0]["content"]["parts"][0]["text"][:2000]
                summary = candidate + "\n\nCounts shown above are calculated from application records."
                ai_used = True
            except Exception:
                pass  # Keep deterministic database-backed summary when AI is unavailable.
        return {"summary": summary, "metrics": data["metrics"], "ai_enabled": bool(api_key), "ai_used": ai_used}


@app.get("/api/admin/rules")
def get_rules(request: Request, org_id: Optional[str] = None):
    with SessionLocal() as db:
        return org_info(selected_org(request, db, org_id))


class RulesIn(BaseModel):
    standard_hours: float = Field(gt=0, le=24)
    overtime_multiplier: float = Field(ge=1, le=5)


@app.put("/api/admin/rules")
def update_rules(data: RulesIn, request: Request, org_id: Optional[str] = None):
    with SessionLocal() as db:
        org = selected_org(request, db, org_id)
        org.standard_hours = data.standard_hours
        org.overtime_multiplier = data.overtime_multiplier
        db.commit()
        return org_info(org)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
