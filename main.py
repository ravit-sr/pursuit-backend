from fastapi import FastAPI, Request
from pydantic import BaseModel, field_validator, Field
from fastapi import HTTPException
import mysql.connector as C
import bcrypt
import jwt
from datetime import datetime, timedelta
from fastapi import Depends, Header, Response, Cookie
from fastapi import UploadFile, File
from fastapi.responses import FileResponse
import uuid
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import requests
from fastapi.responses import RedirectResponse
import pdfplumber
import json
import re
from typing import Optional
import docx
from html import escape
import smtplib
from email.mime.text import MIMEText
import os
import io
from PIL import Image
from pathlib import Path
from dotenv import load_dotenv
from google import genai

import httpx

if os.environ.get("DEBUG_HTTPX_REQUESTS", "").lower() == "true":
    old_send = httpx.Client.send

    def debug_send(self, request, *args, **kwargs):
        print("\n========== GEMINI REQUEST ==========")
        print("URL:", request.url)
        print("Authorization:", request.headers.get("Authorization"))
        print("x-goog-api-key:", request.headers.get("x-goog-api-key"))
        print("====================================\n")
        return old_send(self, request, *args, **kwargs)

    httpx.Client.send = debug_send

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pursuit")


BASE_DIR = Path(__file__).resolve().parent
dotenv_path = BASE_DIR / ".env"

logger.info("Loading env from: %s (exists=%s)", dotenv_path, dotenv_path.exists())

load_dotenv(dotenv_path)
logger.info("GEMINI_API_KEY set: %s", bool(os.getenv("GEMINI_API_KEY")))
logger.info("GMAIL_ADDRESS set: %s", bool(os.getenv("GMAIL_ADDRESS")))
logger.info("GMAIL_APP_PASSWORD set: %s", bool(os.getenv("GMAIL_APP_PASSWORD")))

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is not set in .env")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

# In production (Render), set GOOGLE_REDIRECT_URI and FRONTEND_URL as env vars
# to your real deployed URLs. Locally, these defaults keep working as before.
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/integrations/google/callback")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://127.0.0.1:5500")
IS_PRODUCTION = FRONTEND_URL.startswith("https://")

COOKIE_NAME = "session_token"
COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days, matches JWT exp

def get_db_connection():
    """
    Local dev (no env vars set): connects to localhost/root/no-password/pursuit,
    exactly like before.
    Production (Render): set DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME,
    and DB_SSL_CA (path to Aiven's ca.pem) as env vars.
    """
    ssl_args = {}
    if os.environ.get("DB_SSL_CA"):
        ssl_args = {"ssl_ca": os.environ["DB_SSL_CA"], "ssl_verify_cert": True}
    return C.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "pursuit"),
        **ssl_args,
    )

def set_session_cookie(response: Response, token: str):
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=IS_PRODUCTION,   # True once served over https (Render), False locally
        max_age=COOKIE_MAX_AGE,
        path="/",
    )
UPLOAD_DIR = "uploads/resumes"
os.makedirs(UPLOAD_DIR, exist_ok=True)
AVATAR_UPLOAD_DIR = "uploads/avatars"
os.makedirs(AVATAR_UPLOAD_DIR, exist_ok=True)


app = FastAPI()

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get(
        "ALLOWED_ORIGINS", "http://127.0.0.1:5500"
    ).split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response

def send_email(to_email: str, subject: str, html_body: str):
    logger.info("Connecting to Gmail...")

    msg = MIMEText(html_body, "html")
    msg["Subject"] = subject
    msg["From"] = f"Pursuit <{GMAIL_ADDRESS}>"
    msg["Reply-To"] = GMAIL_ADDRESS
    msg["To"] = to_email

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        logger.info("Starting TLS...")
        server.starttls()

        logger.info("Logging in...")
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)

        logger.info("Sending email...")
        server.sendmail(GMAIL_ADDRESS, [to_email], msg.as_string())

        logger.info("Email sent successfully.")


class ApplicationInput(BaseModel):
    company: str = Field(..., max_length=200)
    role: str = Field(..., max_length=200)
    location: str = Field(..., max_length=200)
    source: str = Field(..., max_length=50)
    status: str = Field(..., max_length=50)
    jobType: str = Field(..., max_length=50)
    salary: str = Field(..., max_length=100)
    dateApplied: str
    contact: Optional[str] = Field(None, max_length=200)
    contactEmail: Optional[str] = Field(None, max_length=254)
    interviewDate: Optional[str] = None
    followUp: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=5000)
    coverLetter: Optional[str] = Field(None, max_length=10000)
    tags: Optional[str] = Field(None, max_length=500)
    resumeFileName: Optional[str] = Field(None, max_length=255)
    rejectionReason: Optional[str] = Field(None, max_length=500)

class SignupInput(BaseModel):
    firstName: str
    lastName: str
    email: str
    password: str

    @field_validator("firstName", "lastName")
    @classmethod
    def name_not_blank(cls, v):
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("Name must be between 1 and 100 characters.")
        return v

    @field_validator("email")
    @classmethod
    def email_looks_valid(cls, v):
        v = v.strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v) or len(v) > 254:
            raise ValueError("Please enter a valid email address.")
        return v

    @field_validator("password")
    @classmethod
    def password_strong_enough(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if len(v) > 72:
            raise ValueError("Password must be under 72 characters.")
        return v

class SigninInput(BaseModel):
    email: str
    password: str

class ForgotPasswordInput(BaseModel):
    email: str

class ResetPasswordInput(BaseModel):
    token: str
    newPassword: str

class SettingsInput(BaseModel):
    theme: str = "system"
    accentColor: str = "#4f8ef7"
    fontSize: str = "14px"
    compactTable: bool = False
    statusEmojis: bool = True

    notifWeekly: bool = True
    notifInterview: bool = True
    notifFollowup: bool = True
    notifTips: bool = False
    notifUpdates: bool = False
    notifFrequency: str = "Weekly"

    goalRole: Optional[str] = None
    goalIndustry: Optional[str] = None
    goalSalary: Optional[str] = None
    goalLocations: Optional[str] = None
    goalWeeklyTarget: int = 8
    goalDeadline: Optional[str] = None
    goalFulltime: bool = True
    goalRemote: bool = True
    goalContract: bool = False
    goalPartTime: bool = False

    privacyProfileVisibility: bool = True
    privacyAnonymousAnalytics: bool = True
    privacyAiTrainingOptIn: bool = False

class ProfileInput(BaseModel):
    firstName: str
    lastName: str
    location: Optional[str] = None
    experienceLevel: Optional[str] = None
    bio: Optional[str] = None
    linkedinUrl: Optional[str] = None
    githubUrl: Optional[str] = None
    website: Optional[str] = None

class PasswordUpdateInput(BaseModel):
    currentPassword: str
    newPassword: str

class IntegrationInput(BaseModel):
    connected: bool

class GoogleAuthInput(BaseModel):
    credential: str

class ChatMessageInput(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def message_not_too_long(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Message cannot be empty.")
        if len(v) > 4000:
            raise ValueError("Message is too long (max 4000 characters).")
        return v

def get_current_user(session_token: str = Cookie(None, alias=COOKIE_NAME)):
    if session_token is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    try:
        payload = jwt.decode(session_token, SECRET_KEY, algorithms=["HS256"])
        return payload["userId"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired, please sign in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")

def make_integration_state(user_id, purpose):
    return jwt.encode(
        {"userId": user_id, "purpose": purpose, "exp": datetime.utcnow() + timedelta(minutes=10)},
        SECRET_KEY, algorithm="HS256"
    )

def decode_integration_state(state):
    payload = jwt.decode(state, SECRET_KEY, algorithms=["HS256"])
    return payload["userId"], payload["purpose"]

def get_valid_google_access_token(user_id):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute(
        "SELECT accessToken, refreshToken, tokenExpiry FROM user_integrations WHERE userId = %s AND serviceName = 'google_calendar' AND connected = 1",
        (user_id,)
    )
    row = mc.fetchone()
    if not row or not row.get("refreshToken"):
        db.close()
        return None

    if row["tokenExpiry"] and row["tokenExpiry"] > datetime.utcnow() + timedelta(minutes=2):
        db.close()
        return row["accessToken"]

    refresh_res = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "refresh_token": row["refreshToken"],
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token"
        }
    )
    refresh_data = refresh_res.json()
    new_access_token = refresh_data.get("access_token")
    if not new_access_token:
        db.close()
        return None

    new_expiry = datetime.utcnow() + timedelta(seconds=refresh_data.get("expires_in", 3600))
    mc2 = db.cursor()
    mc2.execute(
        "UPDATE user_integrations SET accessToken = %s, tokenExpiry = %s WHERE userId = %s AND serviceName = 'google_calendar'",
        (new_access_token, new_expiry, user_id)
    )
    db.commit()
    db.close()
    return new_access_token

def sync_interview_to_calendar(user_id, company, role, interview_date, existing_event_id):
    if not interview_date:
        return existing_event_id
    access_token = get_valid_google_access_token(user_id)
    if not access_token:
        return existing_event_id

    start_date = interview_date[:10] if isinstance(interview_date, str) else interview_date.isoformat()
    end_date = (datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    body = {
        "summary": "Interview: " + company + " — " + role,
        "start": {"date": start_date},
        "end": {"date": end_date}
    }
    headers = {"Authorization": "Bearer " + access_token}

    if existing_event_id:
        res = requests.patch(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events/" + existing_event_id,
            json=body, headers=headers
        )
    else:
        res = requests.post(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            json=body, headers=headers
        )
    if res.status_code in (200, 201):
        return res.json().get("id")
    return existing_event_id

@app.get("/applications")
def get_applications(current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc=db.cursor(dictionary=True)
    mc.execute("SELECT * FROM applications WHERE userId = %s", (current_user_id,))
    result = mc.fetchall()
    db.close()
    return result

@app.delete("/applications/{app_id}")
def delete_application(app_id: int, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc=db.cursor(dictionary=True)
    mc.execute("DELETE FROM applications WHERE id = %s AND userId = %s", (app_id, current_user_id))
    db.commit()
    db.close()
    return {"deleted": app_id}

@app.post("/applications")
def add_application(app_data: ApplicationInput, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor()
    def none_if_empty(value):
        return value if value else None

    interview_date = none_if_empty(app_data.interviewDate)
    follow_up_date = none_if_empty(app_data.followUp)
    rejection_reason = none_if_empty(app_data.rejectionReason)
    mc.execute("""
        INSERT INTO applications
        (userId, company, role, location, source, status, jobType, salary,
         dateApplied, contact, contactEmail, interviewDate, followUpDate,
         notes, coverLetter, tags, resumeFileName, rejectionReason)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        current_user_id, app_data.company, app_data.role, app_data.location,
        app_data.source, app_data.status, app_data.jobType, app_data.salary,
        app_data.dateApplied, app_data.contact, app_data.contactEmail,
        interview_date, follow_up_date, app_data.notes,
        app_data.coverLetter, app_data.tags, app_data.resumeFileName, rejection_reason
    ))
    db.commit()
    new_id = mc.lastrowid

    if interview_date:
        event_id = sync_interview_to_calendar(current_user_id, app_data.company, app_data.role, interview_date, None)
        if event_id:
            mc.execute("UPDATE applications SET calendarEventId = %s WHERE id = %s", (event_id, new_id))
            db.commit()

    db.close()
    return {"id": new_id}

@app.put("/applications/{app_id}")
def update_applications(app_id: int, app_data: ApplicationInput, current_user_id: int = Depends(get_current_user)):
    def none_if_empty(value):
        return value if value else None

    interview_date = none_if_empty(app_data.interviewDate)
    follow_up_date = none_if_empty(app_data.followUp)
    rejection_reason = none_if_empty(app_data.rejectionReason)

    db = get_db_connection()
    mc = db.cursor()
    mc_lookup = db.cursor(dictionary=True)
    mc_lookup.execute("SELECT calendarEventId FROM applications WHERE id = %s AND userId = %s", (app_id, current_user_id))
    existing_row = mc_lookup.fetchone()
    existing_event_id = existing_row["calendarEventId"] if existing_row else None
    mc.execute("""
        UPDATE applications
        SET company = %s, role = %s, location = %s, source = %s, status = %s,
            jobType = %s, salary = %s, dateApplied = %s, contact = %s,
            contactEmail = %s, interviewDate = %s, followUpDate = %s,
            notes = %s, coverLetter = %s, tags = %s, resumeFileName = %s,
            rejectionReason = %s
        WHERE id = %s AND userId = %s
    """, (
        app_data.company, app_data.role, app_data.location, app_data.source,
        app_data.status, app_data.jobType, app_data.salary, app_data.dateApplied,
        app_data.contact, app_data.contactEmail, interview_date, follow_up_date,
        app_data.notes, app_data.coverLetter, app_data.tags, app_data.resumeFileName,
        rejection_reason, app_id, current_user_id
    ))
    db.commit()

    if interview_date:
        event_id = sync_interview_to_calendar(current_user_id, app_data.company, app_data.role, interview_date, existing_event_id)
        if event_id != existing_event_id:
            mc.execute("UPDATE applications SET calendarEventId = %s WHERE id = %s", (event_id, app_id))
            db.commit()

    db.close()
    return {"updated": app_id}

@app.post("/signup")
@limiter.limit("5/minute")
def signup(request: Request, data: SignupInput):
    hashed_password = bcrypt.hashpw(data.password.encode("utf-8"), bcrypt.gensalt())

    db = get_db_connection()
    mc = db.cursor()
    try:
        mc.execute(
            "INSERT INTO users (firstName, lastName, email, password) VALUES (%s, %s, %s, %s)",
            (data.firstName, data.lastName, data.email, hashed_password.decode("utf-8"))
        )
        db.commit()
        new_id = mc.lastrowid
    except C.IntegrityError:
        db.close()
        raise HTTPException(status_code=409, detail="An Account with this email already exists.")
    db.close()
    return {"id": new_id, "email": data.email}

@app.post("/logout")
def logout(response: Response):
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"message": "Logged out."}

@app.post("/signin")
@limiter.limit("10/minute")
def signin(request: Request, data: SigninInput, response: Response):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT * FROM users WHERE email = %s", (data.email,))
    user = mc.fetchone()
    db.close()

    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    password_matches = bcrypt.checkpw(data.password.encode("utf-8"), user["password"].encode("utf-8"))
    if not password_matches:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token_payload = {
        "userId": user["id"],
        "exp": datetime.utcnow() + timedelta(days=7)
    }
    token = jwt.encode(token_payload, SECRET_KEY, algorithm="HS256")
    set_session_cookie(response, token)

    return {
        "id": user["id"],
        "firstName": user["firstName"],
        "lastName": user["lastName"],
        "email": user["email"]
    }

@app.post("/auth/forgot-password")
@limiter.limit("3/minute")
def forgot_password(request: Request, data: ForgotPasswordInput):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT id, firstName, password, authProvider FROM users WHERE email = %s", (data.email,))
    user = mc.fetchone()
    db.close()
    generic_response = {"message": "If an account exists for that email, a reset link has been sent."}

    if user is None:
        return generic_response

    if not user.get("password"):
        try:
            send_email(
                data.email,
                "Pursuit — Password reset requested",
                "<p>Hi " + escape(user["firstName"] or "") + ",</p>"
                "<p>This account uses "
                + escape((user.get("authProvider") or "social login").capitalize())
                + " to sign in.</p>"
                "<p>There is no local password to reset. Please sign in using your "
                + escape((user.get("authProvider") or "social login").capitalize())
                + " account.</p>"
                "<p>If you didn't request this, you can safely ignore this email.</p>"
            )
        except Exception as e:
            logger.error("SMTP error (forgot-password, no-local-password branch): %r", e)

        return generic_response

    reset_token = jwt.encode(
        {
            "userId": user["id"],
            "purpose": "password_reset",
            "exp": datetime.utcnow() + timedelta(minutes=30),
        },
        SECRET_KEY,
        algorithm="HS256",
    )

    reset_link = FRONTEND_URL + "/reset-password.html?token=" + reset_token

    try:
        send_email(
            data.email,
            "Reset your Pursuit password",
            "<p>Hi " + escape(user["firstName"] or "") + ",</p>"
            "<p>We got a request to reset your Pursuit password. This link expires in 30 minutes:</p>"
            "<p><a href=\"" + reset_link + "\">" + reset_link + "</a></p>"
            "<p>If you didn't request this, you can safely ignore this email.</p>"
        )
    except Exception as e:
        logger.error("Failed to send password reset email: %r", e)
        raise HTTPException(status_code=502, detail="Couldn't send the reset email. Please try again shortly.")

    return generic_response

@app.post("/auth/reset-password")
@limiter.limit("10/minute")
def reset_password(request: Request, data: ResetPasswordInput):
    try:
        payload = jwt.decode(data.token, SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="This reset link has expired. Please request a new one.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="This reset link is invalid.")

    if payload.get("purpose") != "password_reset":
        raise HTTPException(status_code=400, detail="This reset link is invalid.")

    if len(data.newPassword) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    hashed = bcrypt.hashpw(data.newPassword.encode("utf-8"), bcrypt.gensalt())

    db = get_db_connection()
    mc = db.cursor()
    mc.execute("UPDATE users SET password = %s WHERE id = %s", (hashed.decode("utf-8"), payload["userId"]))
    db.commit()
    db.close()

    return {"reset": True}

@app.get("/settings")
def get_settings(current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT * FROM user_settings WHERE userId = %s", (current_user_id,))
    settings = mc.fetchone()
    db.close()

    if settings is None:
        return SettingsInput().dict()
    return settings

@app.put("/settings")
def update_settings(data: SettingsInput, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor()
    mc.execute("""
        INSERT INTO user_settings
        (userId, theme, accentColor, fontSize, compactTable, statusEmojis,
         notifWeekly, notifInterview, notifFollowup, notifTips, notifUpdates, notifFrequency,
         goalRole, goalIndustry, goalSalary, goalLocations, goalWeeklyTarget, goalDeadline,
         goalFulltime, goalRemote, goalContract, goalParttime,
         privacyProfileVisibility, privacyAnonymousAnalytics, privacyAiTrainingOptIn)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            theme = VALUES(theme), accentColor = VALUES(accentColor), fontSize = VALUES(fontSize),
            compactTable = VALUES(compactTable), statusEmojis = VALUES(statusEmojis),
            notifWeekly = VALUES(notifWeekly), notifInterview = VALUES(notifInterview),
            notifFollowup = VALUES(notifFollowup), notifTips = VALUES(notifTips),
            notifUpdates = VALUES(notifUpdates), notifFrequency = VALUES(notifFrequency),
            goalRole = VALUES(goalRole), goalIndustry = VALUES(goalIndustry),
            goalSalary = VALUES(goalSalary), goalLocations = VALUES(goalLocations),
            goalWeeklyTarget = VALUES(goalWeeklyTarget), goalDeadline = VALUES(goalDeadline),
            goalFulltime = VALUES(goalFulltime), goalRemote = VALUES(goalRemote),
            goalContract = VALUES(goalContract), goalPartTime = VALUES(goalPartTime),
            privacyProfileVisibility = VALUES(privacyProfileVisibility),
            privacyAnonymousAnalytics = VALUES(privacyAnonymousAnalytics),
            privacyAiTrainingOptIn = VALUES(privacyAiTrainingOptIn)
    """, (
        current_user_id, data.theme, data.accentColor, data.fontSize,
        data.compactTable, data.statusEmojis,
        data.notifWeekly, data.notifInterview, data.notifFollowup, data.notifTips,
        data.notifUpdates, data.notifFrequency,
        data.goalRole, data.goalIndustry, data.goalSalary, data.goalLocations,
        data.goalWeeklyTarget, data.goalDeadline, data.goalFulltime, data.goalRemote,
        data.goalContract, data.goalPartTime,
        data.privacyProfileVisibility, data.privacyAnonymousAnalytics, data.privacyAiTrainingOptIn
    ))
    db.commit()
    db.close()
    return {"saved": True}

@app.get("/profile")
def get_profile(current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute(
        "SELECT firstName, lastName, email, location, experienceLevel, bio, linkedinUrl, githubUrl, website, avatarFileName FROM users WHERE id = %s",
        (current_user_id,)
    )
    profile = mc.fetchone()
    db.close()
    return profile

@app.post("/profile/photo")
async def upload_profile_photo(file: UploadFile = File(...), current_user_id: int = Depends(get_current_user)):
    allowed_ext = {".jpg", ".jpeg", ".png", ".webp"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail="Please upload a JPG, PNG, or WEBP image.")

    contents = await file.read()
    if len(contents) > 3 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image must be under 3MB.")

    # Don't trust the extension alone — verify the bytes actually decode as an
    # image before writing anything to disk. This blocks someone uploading an
    # HTML/SVG/script payload renamed to look like a .png.
    try:
        img_check = Image.open(io.BytesIO(contents))
        img_check.verify()
    except Exception:
        raise HTTPException(status_code=400, detail="That file isn't a valid image.")

    stored_filename = str(uuid.uuid4()) + ext
    file_path = os.path.join(AVATAR_UPLOAD_DIR, stored_filename)
    with open(file_path, "wb") as f:
        f.write(contents)

    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT avatarFileName FROM users WHERE id = %s", (current_user_id,))
    old = mc.fetchone()

    mc2 = db.cursor()
    mc2.execute("UPDATE users SET avatarFileName = %s WHERE id = %s", (stored_filename, current_user_id))
    db.commit()
    db.close()

    if old and old.get("avatarFileName"):
        old_path = os.path.join(AVATAR_UPLOAD_DIR, old["avatarFileName"])
        if os.path.exists(old_path):
            os.remove(old_path)

    return {"avatarFileName": stored_filename}

@app.get("/profile/photo")
def get_profile_photo(current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT avatarFileName FROM users WHERE id = %s", (current_user_id,))
    row = mc.fetchone()
    db.close()

    if not row or not row.get("avatarFileName"):
        raise HTTPException(status_code=404, detail="No profile photo set.")

    file_path = os.path.join(AVATAR_UPLOAD_DIR, row["avatarFileName"])
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Photo file missing on disk.")

    return FileResponse(file_path, headers={"Cache-Control": "no-store"})

@app.delete("/profile/photo")
def delete_profile_photo(current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT avatarFileName FROM users WHERE id = %s", (current_user_id,))
    row = mc.fetchone()

    mc2 = db.cursor()
    mc2.execute("UPDATE users SET avatarFileName = NULL WHERE id = %s", (current_user_id,))
    db.commit()
    db.close()

    if row and row.get("avatarFileName"):
        old_path = os.path.join(AVATAR_UPLOAD_DIR, row["avatarFileName"])
        if os.path.exists(old_path):
            os.remove(old_path)

    return {"removed": True}

@app.put("/profile")
def update_profile(data: ProfileInput, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor()
    mc.execute("""
        UPDATE users
        SET firstName = %s, lastName = %s, location = %s, experienceLevel = %s,
            bio = %s, linkedinUrl = %s, githubUrl = %s, website = %s
        WHERE id = %s
    """, (
        data.firstName, data.lastName, data.location, data.experienceLevel,
        data.bio, data.linkedinUrl, data.githubUrl, data.website,
        current_user_id
    ))
    db.commit()
    db.close()
    return {"updated": current_user_id}

@app.delete("/users/{user_id}")
def delete_user(user_id: int, current_user_id: int = Depends(get_current_user)):
    if user_id != current_user_id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this account.")

    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT avatarFileName FROM users WHERE id = %s", (user_id,))
    user_row = mc.fetchone()

    mc.execute("SELECT storedFileName FROM resumes WHERE userId = %s", (user_id,))
    resume_rows = mc.fetchall()

    mc2 = db.cursor()
    # resume_chat_messages has no userId column, so delete via the user's chat threads first
    mc2.execute("""
        DELETE rcm FROM resume_chat_messages rcm
        JOIN resume_chats rc ON rcm.chatId = rc.id
        WHERE rc.userId = %s
    """, (user_id,))
    mc2.execute("DELETE FROM resume_chats WHERE userId = %s", (user_id,))
    mc2.execute("DELETE FROM user_ai_insights WHERE userId = %s", (user_id,))
    mc2.execute("DELETE FROM resumes WHERE userId = %s", (user_id,))
    mc2.execute("DELETE FROM applications WHERE userId = %s", (user_id,))
    mc2.execute("DELETE FROM user_settings WHERE userId = %s", (user_id,))
    mc2.execute("DELETE FROM user_integrations WHERE userId = %s", (user_id,))
    mc2.execute("DELETE FROM users WHERE id = %s", (user_id,))
    db.commit()
    db.close()

    if user_row and user_row.get("avatarFileName"):
        avatar_path = os.path.join(AVATAR_UPLOAD_DIR, user_row["avatarFileName"])
        if os.path.exists(avatar_path):
            os.remove(avatar_path)

    for r in resume_rows:
        stored_name = r.get("storedFileName")
        if stored_name:
            resume_path = os.path.join(UPLOAD_DIR, stored_name)
            if os.path.exists(resume_path):
                os.remove(resume_path)

    return {"deleted": user_id}

@app.put("/profile/password")
def update_password(data: PasswordUpdateInput, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT password FROM users WHERE id = %s", (current_user_id,))
    user = mc.fetchone()

    if user is None:
        db.close()
        raise HTTPException(status_code=404, detail="User not found.")

    password_matches = bcrypt.checkpw(data.currentPassword.encode("utf-8"), user["password"].encode("utf-8"))
    if not password_matches:
        db.close()
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    new_hashed = bcrypt.hashpw(data.newPassword.encode("utf-8"), bcrypt.gensalt())
    mc2 = db.cursor()
    mc2.execute("UPDATE users SET password = %s WHERE id = %s", (new_hashed.decode("utf-8"), current_user_id))
    db.commit()
    db.close()
    return {"updated": current_user_id}

@app.get("/resumes")
def get_resumes(current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT * FROM resumes WHERE userId = %s ORDER BY uploadedAt DESC", (current_user_id,))
    resumes = mc.fetchall()
    db.close()
    return resumes

@app.post("/resumes")
async def upload_resume(file: UploadFile = File(...), current_user_id: int = Depends(get_current_user)):
    ext = os.path.splitext(file.filename)[1]

    allowed_ext = {".pdf", ".docx", ".txt"}
    if ext.lower() not in allowed_ext:
        raise HTTPException(status_code=400, detail="Please upload a PDF, DOCX, or TXT file.")

    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File must be under 5MB.")

    # Don't trust the extension alone — check the actual file signature.
    # .docx files are zip archives (PK\x03\x04), PDFs start with %PDF.
    ext_lower = ext.lower()
    if ext_lower == ".pdf" and not contents.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="That file doesn't look like a valid PDF.")
    if ext_lower == ".docx" and not contents.startswith(b"PK\x03\x04"):
        raise HTTPException(status_code=400, detail="That file doesn't look like a valid DOCX.")
    if ext_lower == ".txt":
        try:
            contents.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="That .txt file isn't valid UTF-8 text.")

    stored_name = str(uuid.uuid4()) + ext
    file_path = os.path.join(UPLOAD_DIR, stored_name)

    with open(file_path, "wb") as f:
        f.write(contents)

    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT COUNT(*) as cnt FROM resumes WHERE userId = %s AND active = TRUE", (current_user_id,))
    has_active = mc.fetchone()["cnt"] > 0

    mc2 = db.cursor()
    mc2.execute(
        "INSERT INTO resumes (userId, fileName, storedFileName, fileSize, active) VALUES (%s, %s, %s, %s, %s)",
        (current_user_id, file.filename, stored_name, len(contents), not has_active)
    )
    db.commit()
    new_id = mc2.lastrowid
    db.close()
    return {"id": new_id, "fileName": file.filename, "fileSize": len(contents), "active": not has_active}

@app.put("/resumes/{resume_id}/activate")
def activate_resume(resume_id: int, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor()
    mc.execute("UPDATE resumes SET active = FALSE WHERE userId = %s", (current_user_id,))
    mc.execute("UPDATE resumes SET active = TRUE WHERE id = %s AND userId = %s", (resume_id, current_user_id))
    db.commit()
    db.close()
    return {"activated": resume_id}

@app.delete("/resumes/{resume_id}")
def delete_resume(resume_id: int, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT * FROM resumes WHERE id = %s AND userId = %s", (resume_id, current_user_id))
    resume = mc.fetchone()
    if resume is None:
        db.close()
        raise HTTPException(status_code=404, detail="Resume not found.")

    file_path = os.path.join(UPLOAD_DIR, resume["storedFileName"])
    if os.path.exists(file_path):
        os.remove(file_path)

    mc2 = db.cursor()
    mc2.execute("DELETE FROM resumes WHERE id = %s", (resume_id,))

    if resume["active"]:
        mc2.execute("SELECT id FROM resumes WHERE userId = %s ORDER BY uploadedAt DESC LIMIT 1", (current_user_id,))
        next_one = mc2.fetchone()
        if next_one:
            mc2.execute("UPDATE resumes SET active = TRUE WHERE id = %s", (next_one[0],))

    db.commit()
    db.close()
    return {"deleted": resume_id}

def extract_resume_text(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        text = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text.strip()
    elif ext == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    elif ext == ".docx":
        doc = docx.Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs).strip()
    else:
        return None


def call_gemini_resume_analysis(resume_text, target_roles):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not set on the server.")

    roles_line = ", ".join(target_roles) if target_roles else "general software/tech roles"

    prompt = """You are an expert resume reviewer and ATS (Applicant Tracking System) analyst.

        Analyze the resume text below for someone applying to roles like: """ + roles_line + """

        Resume text:
        \"\"\"
        """ + resume_text[:12000] + """
        \"\"\"

        Respond with ONLY valid JSON (no markdown fences, no commentary) matching exactly this shape:
        {
        "score": <int 0-100, overall resume quality>,
        "ats": <int 0-100, ATS compatibility>,
        "keyword": <int 0-100, keyword match for the target roles>,
        "formatting": <int 0-100, formatting/structure quality>,
        "impact": <int 0-100, how well achievements are quantified>,
        "completeness": <int 0-100, completeness of sections>,
        "missingKeywords": [5 to 10 relevant keywords/skills missing from the resume for these roles],
        "presentKeywords": [5 to 10 relevant keywords/skills already present in the resume],
        "suggestions": [
            {"priority": "high or medium or low", "title": "short title", "text": "1-2 sentence actionable suggestion"}
        ] (3 to 5 suggestions, ordered by priority, highest first)
    }"""

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        raw_text = response.text
    except Exception as e:
        logger.error("Gemini resume analysis call failed: %r", e)
        raise HTTPException(status_code=502, detail="AI analysis is temporarily unavailable. Please try again shortly.")
    if not raw_text:
        raise HTTPException(status_code=502, detail="AI returned an unexpected response.")

    cleaned = re.sub(r"^```(json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="AI response was not valid JSON.")

    return parsed

def call_gemini_chat(resume_text, history, new_message):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not set on the server.")

    system_context = (
        "You are a friendly, expert resume coach helping a job seeker improve their resume "
        "through conversation. Be concise and specific — give concrete rewrites, not vague "
        "advice. Reference actual content from their resume when relevant.\n\n"
        "Their resume:\n\"\"\"\n" + resume_text[:12000] + "\n\"\"\""
    )

    contents = [
        {"role": "user", "parts": [{"text": system_context}]},
        {"role": "model", "parts": [{"text": "Got it — I've read through your resume. What would you like help with?"}]}
    ]
    for h in history:
        gemini_role = "model" if h["role"] == "assistant" else "user"
        contents.append({"role": gemini_role, "parts": [{"text": h["message"]}]})
    contents.append({"role": "user", "parts": [{"text": new_message}]})

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(model="gemini-2.5-flash", contents=contents)
        return response.text.strip()
    except Exception as e:
        logger.error("Gemini resume chat call failed: %r", e)
        raise HTTPException(status_code=502, detail="Resume Coach is temporarily unavailable. Please try again shortly.")

@app.post("/resumes/{resume_id}/analyze")
@limiter.limit("10/minute")
def analyze_resume(request: Request, resume_id: int, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT * FROM resumes WHERE id = %s AND userId = %s", (resume_id, current_user_id))
    resume = mc.fetchone()
    if resume is None:
        db.close()
        raise HTTPException(status_code=404, detail="Resume not found.")

    file_path = os.path.join(UPLOAD_DIR, resume["storedFileName"])
    if not os.path.exists(file_path):
        db.close()
        raise HTTPException(status_code=404, detail="Resume file missing on disk.")

    resume_text = extract_resume_text(file_path)
    if not resume_text:
        db.close()
        raise HTTPException(status_code=400, detail="Could not extract text — please upload a PDF, DOCX, or TXT resume.")

    mc.execute(
        "SELECT role FROM applications WHERE userId = %s GROUP BY role ORDER BY MAX(dateApplied) DESC LIMIT 5",
        (current_user_id,)
    )
    roles = [r["role"] for r in mc.fetchall() if r["role"]]

    analysis = call_gemini_resume_analysis(resume_text, roles)
    analysis["targetRoles"] = roles

    mc2 = db.cursor()
    mc2.execute(
        "UPDATE resumes SET analysisJson = %s, analyzedAt = NOW() WHERE id = %s",
        (json.dumps(analysis), resume_id)
    )
    db.commit()
    db.close()
    return analysis

@app.get("/resumes/{resume_id}/preview")
def preview_resume(resume_id: int, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT * FROM resumes WHERE id = %s AND userId = %s", (resume_id, current_user_id))
    resume = mc.fetchone()
    db.close()
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found.")

    file_path = os.path.join(UPLOAD_DIR, resume["storedFileName"])
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Resume file missing on disk.")

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return FileResponse(file_path, media_type="application/pdf")
    elif ext == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return {"type": "txt", "text": f.read()}
    elif ext == ".docx":
        doc = docx.Document(file_path)
        html_parts = []
        for p in doc.paragraphs:
            if p.text.strip():
                html_parts.append("<p>" + escape(p.text) + "</p>")
        html = "".join(html_parts) if html_parts else "<p><em>No readable text found in this document.</em></p>"
        return {"type": "docx", "html": html}
    else:
        raise HTTPException(status_code=400, detail="Preview not supported for this file type.")

def call_gemini_insights(applications):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not set on the server.")

    total = len(applications)
    status_counts = {}
    source_counts = {}
    for a in applications:
        status_counts[a["status"]] = status_counts.get(a["status"], 0) + 1
        source_counts[a["source"]] = source_counts.get(a["source"], 0) + 1

    app_lines = []
    for a in applications[:60]:
        app_lines.append(
            str(a["company"]) + " | " + str(a["role"]) + " | status=" + str(a["status"]) +
            " | source=" + str(a["source"]) + " | applied=" + str(a["dateApplied"]) +
            " | tags=" + str(a["tags"] or "")
        )
    apps_block = "\n".join(app_lines)

    prompt = """You are a career coach analyzing a job seeker's application history.

Total applications: """ + str(total) + """
Status breakdown: """ + json.dumps(status_counts) + """
Source breakdown: """ + json.dumps(source_counts) + """

Individual applications (company | role | status | source | date applied | tags):
""" + apps_block + """

Respond with ONLY valid JSON (no markdown fences, no commentary) matching exactly this shape:
{
  "insights": [
    {"type": "danger or warning or success", "text": "one short punchy sentence, under 20 words, with key numbers/terms wrapped in **double asterisks**"}
  ] (2 to 4 items, most important pattern first),
  "strengths": ["short sentence highlighting something going well, key numbers/terms wrapped in **double asterisks**"] (2 to 4 items),
  "gaps": ["short sentence identifying a weakness or missed opportunity, key numbers/terms wrapped in **double asterisks**"] (2 to 4 items),
  "actions": ["short, concrete, actionable recommendation"] (2 to 4 items)
}

Base every claim strictly on the data given above — do not invent numbers or facts not present in the data. If there is too little data (fewer than 5 applications) to find real patterns, say so honestly in the insights instead of making things up."""

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        raw_text = response.text
    except Exception as e:
        logger.error("Gemini insights call failed: %r", e)
        raise HTTPException(status_code=502, detail="AI insights are temporarily unavailable. Please try again shortly.")
    if not raw_text:
        raise HTTPException(status_code=502, detail="AI returned an unexpected response.")

    cleaned = re.sub(r"^```(json)?|```$", "", raw_text.strip(), flags=re.MULTILINE).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="AI response was not valid JSON.")

    return parsed

@app.get("/applications/insights")
def get_insights(current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT insightsJson, generatedAt FROM user_ai_insights WHERE userId = %s", (current_user_id,))
    row = mc.fetchone()
    db.close()
    if not row or not row["insightsJson"]:
        return {"insights": None, "generatedAt": None}
    return {
        "insights": json.loads(row["insightsJson"]),
        "generatedAt": row["generatedAt"].isoformat() if row["generatedAt"] else None
    }

@app.post("/applications/insights/generate")
@limiter.limit("10/minute")
def generate_insights(request: Request, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT * FROM applications WHERE userId = %s ORDER BY dateApplied DESC", (current_user_id,))
    applications = mc.fetchall()

    if len(applications) == 0:
        db.close()
        raise HTTPException(status_code=400, detail="Add at least one application before generating insights.")

    insights = call_gemini_insights(applications)

    mc2 = db.cursor()
    mc2.execute(
        """INSERT INTO user_ai_insights (userId, insightsJson, generatedAt)
           VALUES (%s, %s, NOW())
           ON DUPLICATE KEY UPDATE insightsJson = VALUES(insightsJson), generatedAt = VALUES(generatedAt)""",
        (current_user_id, json.dumps(insights))
    )
    db.commit()
    db.close()
    return insights

@app.get("/integrations")
def get_integrations(current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT serviceName, connected FROM user_integrations WHERE userId = %s", (current_user_id,))
    rows = mc.fetchall()
    db.close()
    return rows

@app.put("/integrations/{service_name}")
def update_integration(service_name: str, data: IntegrationInput, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute(
        "SELECT id FROM user_integrations WHERE userId = %s AND serviceName = %s",
        (current_user_id, service_name)
    )
    existing = mc.fetchone()

    mc2 = db.cursor()
    if existing:
        mc2.execute(
            "UPDATE user_integrations SET connected = %s WHERE id = %s",
            (data.connected, existing["id"])
        )
    else:
        mc2.execute(
            "INSERT INTO user_integrations (userId, serviceName, connected) VALUES (%s, %s, %s)",
            (current_user_id, service_name, data.connected)
        )
    db.commit()
    db.close()
    return {"serviceName": service_name, "connected": data.connected}

@app.get("/integrations/github/connect")
def github_integration_connect(session_token: str = Cookie(None, alias=COOKIE_NAME)):
    try:
        payload = jwt.decode(session_token, SECRET_KEY, algorithms=["HS256"])
        user_id = payload["userId"]
    except (jwt.PyJWTError, TypeError):
        return RedirectResponse(FRONTEND_URL + "/settings.html?error=session_expired")

    state = make_integration_state(user_id, "github_integration")
    github_authorize_url = (
        "https://github.com/login/oauth/authorize"
        "?client_id=" + GITHUB_CLIENT_ID +
        "&scope=read:user" +
        "&state=" + state
    )
    return RedirectResponse(github_authorize_url)

@app.get("/integrations/google_calendar/connect")
def google_calendar_connect(session_token: str = Cookie(None, alias=COOKIE_NAME)):
    try:
        payload = jwt.decode(session_token, SECRET_KEY, algorithms=["HS256"])
        user_id = payload["userId"]
    except (jwt.PyJWTError, TypeError):
        return RedirectResponse(FRONTEND_URL + "/settings.html?error=session_expired")

    state = make_integration_state(user_id, "google_calendar")
    google_authorize_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        "?client_id=" + GOOGLE_CLIENT_ID +
        "&redirect_uri=" + GOOGLE_REDIRECT_URI +
        "&response_type=code" +
        "&access_type=offline" +
        "&prompt=consent" +
        "&scope=https://www.googleapis.com/auth/calendar.events" +
        "&state=" + state
    )
    return RedirectResponse(google_authorize_url)

@app.get("/integrations/google/callback")
def google_calendar_callback(code: str, state: str):
    try:
        user_id, purpose = decode_integration_state(state)
    except jwt.PyJWTError:
        return RedirectResponse(FRONTEND_URL + "/settings.html?error=session_expired")

    token_res = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code"
        }
    )
    token_data = token_res.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)

    if not access_token:
        return RedirectResponse(FRONTEND_URL + "/settings.html?error=google_calendar_failed")

    token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)

    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT id, refreshToken FROM user_integrations WHERE userId = %s AND serviceName = 'google_calendar'", (user_id,))
    existing = mc.fetchone()

    final_refresh_token = refresh_token if refresh_token else (existing["refreshToken"] if existing else None)

    mc2 = db.cursor()
    if existing:
        mc2.execute(
            "UPDATE user_integrations SET connected = 1, accessToken = %s, refreshToken = %s, tokenExpiry = %s WHERE id = %s",
            (access_token, final_refresh_token, token_expiry, existing["id"])
        )
    else:
        mc2.execute(
            "INSERT INTO user_integrations (userId, serviceName, connected, accessToken, refreshToken, tokenExpiry) VALUES (%s, 'google_calendar', 1, %s, %s, %s)",
            (user_id, access_token, final_refresh_token, token_expiry)
        )
    db.commit()
    db.close()

    return RedirectResponse(FRONTEND_URL + "/settings.html?connected=google_calendar")

@app.post("/auth/google")
@limiter.limit("10/minute")
def google_auth(request: Request, data: GoogleAuthInput, response: Response):
    try:
        idinfo = id_token.verify_oauth2_token(
            data.credential, google_requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError as e:
        logger.warning("Google token verify failed: %s", e)
        raise HTTPException(status_code=401, detail="Google sign-in failed. Please try again.")

    email = idinfo["email"]
    first_name = idinfo.get("given_name", "")
    last_name = idinfo.get("family_name", "")

    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = mc.fetchone()

    mc2 = db.cursor()
    if user is None:
        mc2.execute(
            "INSERT INTO users (firstName, lastName, email, password, authProvider) VALUES (%s, %s, %s, NULL, %s)",
            (first_name, last_name, email, "google")
        )
        db.commit()
        user_id = mc2.lastrowid
    else:
        user_id = user["id"]
        first_name = user["firstName"]
        last_name = user["lastName"]

    token = jwt.encode(
        {"userId": user_id, "exp": datetime.utcnow() + timedelta(days=7)},
        SECRET_KEY, algorithm="HS256"
    )
    db.close()
    set_session_cookie(response, token)
    return {"id": user_id, "firstName": first_name, "lastName": last_name, "email": email}

def handle_github_integration_callback(code, user_id):
    token_res = requests.post(
        "https://github.com/login/oauth/access_token",
        data={"client_id": GITHUB_CLIENT_ID, "client_secret": GITHUB_CLIENT_SECRET, "code": code},
        headers={"Accept": "application/json"}
    )
    access_token = token_res.json().get("access_token")
    if not access_token:
        return RedirectResponse(FRONTEND_URL + "/settings.html?error=github_failed")

    profile_res = requests.get("https://api.github.com/user", headers={"Authorization": "Bearer " + access_token})
    profile = profile_res.json()
    github_url = profile.get("html_url", "")
    github_username = profile.get("login", "")

    db = get_db_connection()
    mc = db.cursor()
    mc.execute("UPDATE users SET githubUrl = %s WHERE id = %s", (github_url, user_id))

    mc2 = db.cursor(dictionary=True)
    mc2.execute("SELECT id FROM user_integrations WHERE userId = %s AND serviceName = 'github'", (user_id,))
    existing = mc2.fetchone()

    mc3 = db.cursor()
    if existing:
        mc3.execute(
            "UPDATE user_integrations SET connected = 1, accountLabel = %s WHERE id = %s",
            (github_username, existing["id"])
        )
    else:
        mc3.execute(
            "INSERT INTO user_integrations (userId, serviceName, connected, accountLabel) VALUES (%s, 'github', 1, %s)",
            (user_id, github_username)
        )
    db.commit()
    db.close()

    return RedirectResponse(FRONTEND_URL + "/settings.html?connected=github")

@app.get("/auth/github/callback")
def github_callback(code: str, state: str = None):
    if state:
        try:
            integration_user_id, purpose = decode_integration_state(state)
            if purpose == "github_integration":
                return handle_github_integration_callback(code, integration_user_id)
        except jwt.PyJWTError:
            pass
    token_res = requests.post(
        "https://github.com/login/oauth/access_token",
        data={
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": code
        },
        headers={"Accept": "application/json"}
    )
    access_token = token_res.json().get("access_token")
    if not access_token:
        return RedirectResponse(FRONTEND_URL + "/signin.html?error=github_failed")

    profile_res = requests.get(
        "https://api.github.com/user",
        headers={"Authorization": "Bearer " + access_token}
    )
    profile = profile_res.json()

    emails_res = requests.get(
        "https://api.github.com/user/emails",
        headers={"Authorization": "Bearer " + access_token}
    )
    emails = emails_res.json()
    primary_email = None
    for e in emails:
        if e.get("primary") and e.get("verified"):
            primary_email = e["email"]
            break
    if not primary_email and emails:
        primary_email = emails[0]["email"]
    if not primary_email:
        return RedirectResponse(FRONTEND_URL + "/signin.html?error=no_email")

    full_name = profile.get("name") or profile.get("login") or "GitHub User"
    name_parts = full_name.split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    github_url = profile.get("html_url", "")

    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT * FROM users WHERE email = %s", (primary_email,))
    user = mc.fetchone()

    mc2 = db.cursor()
    if user is None:
        mc2.execute(
            "INSERT INTO users (firstName, lastName, email, password, authProvider, githubUrl) VALUES (%s, %s, %s, NULL, %s, %s)",
            (first_name, last_name, primary_email, "github", github_url)
        )
        db.commit()
        user_id = mc2.lastrowid
    else:
        user_id = user["id"]
        first_name = user["firstName"]
        last_name = user["lastName"]

    jwt_token = jwt.encode(
        {"userId": user_id, "exp": datetime.utcnow() + timedelta(days=7)},
        SECRET_KEY, algorithm="HS256"
    )
    db.close()

    redirect_url = (
        FRONTEND_URL + "/signin.html#id=" + str(user_id) +
        "&firstName=" + first_name +
        "&lastName=" + last_name +
        "&email=" + primary_email
    )
    redirect_response = RedirectResponse(redirect_url)
    set_session_cookie(redirect_response, jwt_token)
    return redirect_response

DAILY_CHAT_LIMIT = 40

@app.get("/resumes/{resume_id}/chats")
def list_resume_chats(resume_id: int, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT id FROM resumes WHERE id = %s AND userId = %s", (resume_id, current_user_id))
    if mc.fetchone() is None:
        db.close()
        raise HTTPException(status_code=404, detail="Resume not found.")
    mc.execute(
        "SELECT id, title, createdAt FROM resume_chats WHERE resumeId = %s AND userId = %s ORDER BY createdAt DESC",
        (resume_id, current_user_id)
    )
    chats = mc.fetchall()
    db.close()
    return chats


@app.post("/resumes/{resume_id}/chats")
def create_resume_chat(resume_id: int, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT id FROM resumes WHERE id = %s AND userId = %s", (resume_id, current_user_id))
    if mc.fetchone() is None:
        db.close()
        raise HTTPException(status_code=404, detail="Resume not found.")

    mc2 = db.cursor()
    mc2.execute(
        "INSERT INTO resume_chats (userId, resumeId, title) VALUES (%s, %s, %s)",
        (current_user_id, resume_id, "New Chat")
    )
    db.commit()
    new_id = mc2.lastrowid
    db.close()
    return {"id": new_id, "title": "New Chat"}


@app.delete("/resume-chats/{chat_id}")
def delete_resume_chat(chat_id: int, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT id FROM resume_chats WHERE id = %s AND userId = %s", (chat_id, current_user_id))
    if mc.fetchone() is None:
        db.close()
        raise HTTPException(status_code=404, detail="Chat not found.")

    mc2 = db.cursor()
    mc2.execute("DELETE FROM resume_chat_messages WHERE chatId = %s", (chat_id,))
    mc2.execute("DELETE FROM resume_chats WHERE id = %s", (chat_id,))
    db.commit()
    db.close()
    return {"deleted": chat_id}


@app.get("/resume-chats/{chat_id}/messages")
def get_chat_messages(chat_id: int, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT id FROM resume_chats WHERE id = %s AND userId = %s", (chat_id, current_user_id))
    if mc.fetchone() is None:
        db.close()
        raise HTTPException(status_code=404, detail="Chat not found.")
    mc.execute(
        "SELECT role, message, createdAt FROM resume_chat_messages WHERE chatId = %s ORDER BY createdAt ASC",
        (chat_id,)
    )
    messages = mc.fetchall()
    db.close()
    return messages


@app.post("/resume-chats/{chat_id}/messages")
@limiter.limit("15/minute")
def post_chat_message(request: Request, chat_id: int, data: ChatMessageInput, current_user_id: int = Depends(get_current_user)):
    db = get_db_connection()
    mc = db.cursor(dictionary=True)
    mc.execute("SELECT * FROM resume_chats WHERE id = %s AND userId = %s", (chat_id, current_user_id))
    chat = mc.fetchone()
    if chat is None:
        db.close()
        raise HTTPException(status_code=404, detail="Chat not found.")

    mc.execute("SELECT * FROM resumes WHERE id = %s AND userId = %s", (chat["resumeId"], current_user_id))
    resume = mc.fetchone()
    if resume is None:
        db.close()
        raise HTTPException(status_code=404, detail="Resume not found.")

    mc.execute(
        "SELECT COUNT(*) as cnt FROM resume_chat_messages rcm "
        "JOIN resume_chats rc ON rcm.chatId = rc.id "
        "WHERE rc.userId = %s AND rcm.role = 'user' AND DATE(rcm.createdAt) = CURDATE()",
        (current_user_id,)
    )
    today_count = mc.fetchone()["cnt"]
    if today_count >= DAILY_CHAT_LIMIT:
        db.close()
        raise HTTPException(status_code=429, detail="You've reached today's limit of " + str(DAILY_CHAT_LIMIT) + " AI messages. Try again tomorrow.")

    file_path = os.path.join(UPLOAD_DIR, resume["storedFileName"])
    resume_text = extract_resume_text(file_path) if os.path.exists(file_path) else None
    if not resume_text:
        db.close()
        raise HTTPException(status_code=400, detail="Could not read this resume's text — try a PDF, TXT, or DOCX file.")

    user_message = data.message.strip()
    if not user_message:
        db.close()
        raise HTTPException(status_code=400, detail="Message can't be empty.")

    mc.execute(
        "SELECT COUNT(*) as cnt FROM resume_chat_messages WHERE chatId = %s AND role = 'user'",
        (chat_id,)
    )
    is_first_message = mc.fetchone()["cnt"] == 0

    mc.execute(
        "SELECT role, message FROM resume_chat_messages WHERE chatId = %s ORDER BY createdAt DESC LIMIT 12",
        (chat_id,)
    )
    recent = list(reversed(mc.fetchall()))

    mc2 = db.cursor()
    mc2.execute(
        "INSERT INTO resume_chat_messages (chatId, role, message) VALUES (%s, %s, %s)",
        (chat_id, "user", user_message)
    )
    db.commit()

    new_title = chat["title"]
    if is_first_message:
        new_title = user_message[:40] + ("…" if len(user_message) > 40 else "")
        mc2.execute("UPDATE resume_chats SET title = %s WHERE id = %s", (new_title, chat_id))
        db.commit()

    reply = call_gemini_chat(resume_text, recent, user_message)

    mc2.execute(
        "INSERT INTO resume_chat_messages (chatId, role, message) VALUES (%s, %s, %s)",
        (chat_id, "assistant", reply)
    )
    db.commit()
    db.close()
    return {"reply": reply, "title": new_title}