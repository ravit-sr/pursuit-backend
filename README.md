# Pursuit — Backend

FastAPI backend for **Pursuit**, a job application tracker built to practice real full-stack development: hand-designed MySQL schema, JWT auth, OAuth, file uploads, and an AI-powered resume coach.

Frontend repo: [pursuit-frontend](../../pursuit-frontend) <!-- update this link once both repos exist -->

## Features

- **Auth**: email/password (bcrypt) + JWT sessions via HTTP-only cookies, plus Google Sign-In and GitHub OAuth (find-or-create user logic, shared `authProvider` column)
- **Applications**: full CRUD for tracked job applications, ownership-checked (IDOR-safe) per user
- **Resume Coach**: upload a resume (PDF/DOCX, parsed server-side), get AI analysis and chat with an AI coach about it, powered by Gemini
- **Dashboard insights**: AI-generated summary of application trends via Gemini
- **Integrations**: Google Calendar and GitHub account linking via OAuth
- **Profile**: photo upload, password change, settings (theme, goals)
- **Security**: parameterized SQL everywhere, bcrypt password hashing, rate limiting (`slowapi`), security headers middleware, IDOR checks on every resource lookup

## Tech stack

FastAPI · MySQL (`mysql-connector-python`) · Pydantic · PyJWT · bcrypt · Google GenAI SDK (Gemini) · pdfplumber / python-docx for resume parsing

## Local setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt

cp .env.example .env           # fill in real values
mysql -u root -p < data.sql    # create schema
# apply anything in migrations/ in order, if not already covered by data.sql

uvicorn main:app --reload
```

API docs available at `http://127.0.0.1:8000/docs` once running.

## Environment variables

See [`.env.example`](.env.example) for the full list. Locally you only need the top section (`SECRET_KEY`, Gmail, Google/GitHub OAuth, Gemini). The bottom section (`DB_*`, `FRONTEND_URL`, etc.) is only used in production.

## Deployment

Deployed on Render, against a free-tier MySQL instance on Aiven. See `.env.example` for the production-only environment variables Render needs.

## Known issues

See [`known_issues.md`](known_issues.md) for the current Gemini API key format issue (Google-side, not a bug in this codebase).
