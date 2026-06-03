import os, shutil, io, csv, uuid
from datetime import datetime, timedelta
from email.mime.text import MIMEText

from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Form
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func
from passlib.context import CryptContext
from jose import JWTError, jwt
from apscheduler.schedulers.background import BackgroundScheduler

from models import Base, User, Report, ReportType, UserRole, AuditLog
from database import get_db, engine, SessionLocal

os.makedirs("uploads", exist_ok=True)
SECRET_KEY = "your-super-secret-key-change-this-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

app = FastAPI(title="SamPhase API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"],
                   allow_headers=["*"])
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


def log_audit(db: Session, action: str, user_id: int = None):
    db.add(AuditLog(user_id=user_id, action=action))
    db.commit()


def send_escalation_email(report, tier, recipient):
    print(f"\n[ESCALATION TIER {tier}] To: {recipient} | Report #{report.id}: {report.title} is OVERDUE.")


def check_deadlines():
    db = SessionLocal()
    now = datetime.utcnow()
    overdue_reports = db.query(Report).filter(Report.due_date < now, Report.status != "Closed").all()
    for r in overdue_reports:
        days_overdue = (now - r.due_date).days
        if days_overdue >= 0 and r.escalation_level == 0:
            send_escalation_email(r, 1, "staff@domain.com")
            r.escalation_level = 1
        elif days_overdue >= 3 and r.escalation_level == 1:
            send_escalation_email(r, 2, "manager@domain.com")
            r.escalation_level = 2
        elif days_overdue >= 5 and r.escalation_level == 2:
            send_escalation_email(r, 3, "slt@domain.com")
            r.escalation_level = 3
    db.commit()
    db.close()


@app.on_event("startup")
def startup_tasks():
    db = SessionLocal()
    if not db.query(User).filter(User.username == "admin").first():
        db.add(User(username="admin", hashed_password=pwd_context.hash("password123"), role=UserRole.ADMIN,
                    site_location="Global"))
        db.commit()
    db.close()
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_deadlines, 'interval', minutes=1)
    scheduler.start()


def create_access_token(data: dict):
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": data["sub"], "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401)
    user = db.query(User).filter(User.username == username).first()
    if not user: raise HTTPException(status_code=401)
    return user


@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    with open("index.html", "r") as f: return f.read()


@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not pwd_context.verify(form_data.password, user.hashed_password): raise HTTPException(
        status_code=400)
    log_audit(db, "User Logged In", user.id)
    return {"access_token": create_access_token(data={"sub": user.username}), "token_type": "bearer",
            "role": user.role.value, "site": user.site_location}


@app.post("/users/")
def create_user(username: str = Form(...), password: str = Form(...), role: UserRole = Form(...), site: str = Form(...),
                db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.ADMIN: raise HTTPException(status_code=403)
    db.add(User(username=username, hashed_password=pwd_context.hash(password), role=role, site_location=site))
    log_audit(db, f"Created new user account: {username}", current_user.id)
    return {"message": "User created"}


@app.get("/reports/summary")
def get_report_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role == UserRole.STAFF: raise HTTPException(status_code=403)
    base_query = db.query(Report)
    if user.role != UserRole.ADMIN: base_query = base_query.filter(
        Report.site_location == user.site_location)  # Multi-site filter

    open_c = base_query.filter(Report.status == "Open").count()
    closed_c = base_query.filter(Report.status == "Closed").count()
    overdue_c = base_query.filter(Report.due_date < datetime.utcnow(), Report.status != "Closed").count()

    cqc_domains = ["Safe", "Effective", "Caring", "Responsive", "Well-led"]
    heatmap = {}
    for domain in cqc_domains:
        heatmap[domain] = {
            "Open": base_query.filter(Report.cqc_tag == domain, Report.status == "Open").count(),
            "Closed": base_query.filter(Report.cqc_tag == domain, Report.status == "Closed").count()
        }
    return {"open": open_c, "closed": closed_c, "overdue": overdue_c, "heatmap": heatmap}


@app.get("/reports/")
def list_reports(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    all_reports = db.query(Report).order_by(Report.created_at.desc()).all()
    filtered = []
    for r in all_reports:
        # Multi-site barrier
        if user.role != UserRole.ADMIN and r.site_location != user.site_location: continue
        if r.report_type == ReportType.SAFEGUARDING and user.role not in [UserRole.DSL,
                                                                          UserRole.ADMIN] and r.reporter_id != user.id: continue
        if user.role == UserRole.STAFF and r.reporter_id != user.id: continue
        filtered.append(r)
    return filtered


@app.post("/reports/")
def create_report(
        type: ReportType = Form(...), category: str = Form("General"), cqc_tag: str = Form("None"),
        title: str = Form(...), description: str = Form(...), days_to_resolve: int = Form(7),
        is_pilot: bool = Form(False), file: UploadFile = File(None), db: Session = Depends(get_db),
        user: User = Depends(get_current_user)
):
    deadline = datetime.utcnow() + timedelta(days=days_to_resolve)
    file_path = None
    if file and file.filename:
        file_path = f"uploads/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename.replace(' ', '_')}"
        with open(file_path, "wb") as buffer: shutil.copyfileobj(file.file, buffer)

    db.add(Report(report_type=type, category=category, cqc_tag=cqc_tag, title=title, description=description,
                  due_date=deadline, is_pilot=is_pilot, site_location=user.site_location, reporter_id=user.id,
                  attachment_path=file_path))
    log_audit(db, f"Submitted new {type.value} report: {title}", user.id)
    return {"message": "Report submitted"}


@app.put("/reports/{report_id}/close")
def close_report(
        report_id: int, action_plan: str = Form(...), review_days: int = Form(30),
        rca_1: str = Form(""), rca_2: str = Form(""), rca_3: str = Form(""), rca_4: str = Form(""),
        rca_5: str = Form(""),
        db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    report = db.query(Report).filter(Report.id == report_id).first()
    report.status = "Closed"
    report.action_plan = action_plan
    report.rca_1 = rca_1;
    report.rca_2 = rca_2;
    report.rca_3 = rca_3;
    report.rca_4 = rca_4;
    report.rca_5 = rca_5
    report.review_date = datetime.utcnow() + timedelta(days=review_days)
    log_audit(db, f"Closed report #{report.id} and completed RCA", user.id)
    return {"message": "Closed"}


@app.post("/reports/{report_id}/share")
def share_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    report = db.query(Report).filter(Report.id == report_id).first()
    report.secure_link_id = str(uuid.uuid4())
    report.secure_link_expires = datetime.utcnow() + timedelta(hours=48)
    log_audit(db, f"Generated secure external link for report #{report.id}", user.id)
    return {"secure_link": report.secure_link_id}


@app.get("/shared/{link_id}", response_class=HTMLResponse)
def get_shared_report(link_id: str, db: Session = Depends(get_db)):
    report = db.query(Report).filter(Report.secure_link_id == link_id).first()
    if not report or report.secure_link_expires < datetime.utcnow(): return "<h1>Link Expired</h1>"
    log_audit(db, f"External User accessed secure link for report #{report.id}")
    return f"<html><body style='font-family: Arial; padding: 40px;'><h2>SamPhase Secure Portal</h2><p><strong>Type:</strong> {report.report_type.value.upper()}</p><p><strong>Title:</strong> {report.title}</p><div style='background: #f3f4f6; padding: 15px;'>{report.description}</div></body></html>"


@app.get("/reports/export")
def export_reports(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role == UserRole.STAFF: raise HTTPException(status_code=403)
    all_reports = db.query(Report).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["ID", "Site", "Type", "Category", "CQC Domain", "Title", "Status", "Action Plan", "RCA Final Cause"])
    for r in all_reports:
        if user.role != UserRole.ADMIN and r.site_location != user.site_location: continue
        if r.report_type == ReportType.SAFEGUARDING and user.role not in [UserRole.DSL, UserRole.ADMIN]: continue
        writer.writerow([r.id, r.site_location, r.report_type.value.upper(), r.category, r.cqc_tag, r.title, r.status,
                         r.action_plan, r.rca_5])
    output.seek(0)
    log_audit(db, "Exported CSV Data", user.id)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=samphase_export.csv"})


# --- NEW: AI COPILOT AND BLACK BOX ---
@app.get("/audit_logs/")
def get_audit_logs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != UserRole.ADMIN: raise HTTPException(status_code=403, detail="Admins only.")
    logs = db.query(AuditLog, User.username).outerjoin(User, AuditLog.user_id == User.id).order_by(
        AuditLog.timestamp.desc()).limit(100).all()
    return [{"timestamp": l[0].timestamp, "username": l[1] if l[1] else "System/External", "action": l[0].action} for l
            in logs]


@app.post("/ai_analysis/")
def ai_analyze_themes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role not in [UserRole.ADMIN, UserRole.MANAGER]: raise HTTPException(status_code=403)
    log_audit(db, "Executed AI Theme Extraction", user.id)

    # In production, this is where you pass report texts to the OpenAI API.
    # For now, we simulate the output so your local server doesn't crash without an API key.
    mock_ai_response = """
    **AI Copilot Intelligence Report**

    1. **Primary Theme:** 42% of recent complaints at Bournemouth HQ relate to weekend staffing handovers.
    2. **RCA Insight:** '5 Whys' data indicates recurring maintenance delays are negatively impacting the CQC 'Safe' domain.
    3. **Actionable Recommendation:** Implement a mandatory Friday afternoon maintenance checklist and review weekend handover documentation procedures.
    """
    return {"analysis": mock_ai_response}