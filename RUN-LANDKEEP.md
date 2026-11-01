# Start the complete project

Double-click **START-LANDKEEP.cmd** from the extracted Land-Keep folder. See **START-HERE.txt** for prerequisites, demo logins, preserving existing data, and AI configuration. This launcher prepares an isolated Python environment, installs dependencies, applies migrations, starts both services, checks the frontend proxy against the backend, and opens the website. Keep its window open.

The commands below are an alternative manual workflow.

# Run LandKeep on Windows

This update preserves the existing React/Vite frontend and FastAPI backend. The frontend now proxies `/api` to `http://127.0.0.1:8000` instead of port 8001.

## First setup

Extract the ZIP, open the extracted `Land-Keep` folder in VS Code, and open a PowerShell terminal there. Use Python 3.12 and a recent Node.js LTS (22.12+ or 24).

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\client-vite-scaffold
npm ci
cd ..
```

If you use another installed Python version, substitute its launcher command. No environment activation is needed. Keep your existing database and `.env` if updating an existing installation; back up the database before applying updates. Never run `seed.py` against a database you want to retain: it resets demo data. The new startup script uses `initialize_demo.py`, which skips seeding when users already exist.

Optional: copy `backend/.env.example` to `backend/.env` and enter your own `ANTHROPIC_API_KEY` for live AI. Without a key, text chat uses local maintenance guidance; photo uploads remain available for landlord review, but AI image assessment requires the key. Provider credentials are not included.

## Start both services

From the `Land-Keep` root in the first terminal:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-backend.ps1
```

This applies existing database migrations, initializes synthetic demo data only when no users exist, then starts FastAPI on port 8000.

In a second terminal at the same root:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-frontend.ps1
```

Open the URL Vite prints (normally http://127.0.0.1:5173). Keep both terminals open. If 5173 is occupied, Vite may choose 5174; the API proxy works there too. Stop an older backend before starting another on port 8000.

API health: http://127.0.0.1:8000/health
API documentation: http://127.0.0.1:8000/docs

If you prefer to start services manually, run these in their respective folders after migrations and initialization:

```powershell
# backend folder
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
# client-vite-scaffold folder, separate terminal
npm run dev
```

If intentionally using a different backend port, set `LANDKEEP_API_TARGET` in `client-vite-scaffold/.env` and restart Vite.

## Demo logins (new demo database only)

Password for both: `password123`

- Tenant with active lease: `tenant@landkeep.test`
- Landlord: `landlord@landkeep.test`

Sign in as the tenant and open Maintenance help. Start a chat and describe a leak. Continue the conversation, choose Report to landlord, and then sign in as the landlord to view the report. Tenant access requires an active lease after approval and acceptance, matching the existing workflow.

## Fixes

- Corrected the frontend API port and added a configurable target and clearer connection errors.
- Ensured migrations and API load backend `.env` database settings consistently.
- Prevented repeated Enter presses while a chat message is sending.
- Excluded bot messages from local issue classification.
- Escalated urgent or confident assessments requiring human assistance.
- Prevented negative phrases such as "not fixed" from resolving an escalated report.
- Kept saved report status aligned with explicit tenant resolution; rejected actions on closed chats.
- Added a new-chat action after resolution and refreshed the tenant's report list.
- Resumed chats for the current active lease and displayed lease-loading errors.
- Moved external AI calls off the API event loop.

## Validation performed

- Backend: 59 tests passed, including authentication, application/lease flows, maintenance/chat, uploads/storage, payments and reminders.
- Frontend: production build and TypeScript check passed. Lint completed with four pre-existing state-in-effect warnings in other screens.
- Started FastAPI and Vite together against a throwaway synthetic database. Verified real HTTP requests through Vite: health, both logins, landlord applications, tenant lease, chat start/reply/resume, escalation, unresolved follow-up, landlord report visibility, and resolution.
- Verified repeated demo initialization preserves existing users.

Live Claude calls and provider delivery were not verified without credentials. Notification console mode previews delivery locally. Windows launch scripts are provided but were not executed in this Linux environment. No hosted deployment or browser click-through test was performed; this ZIP is a locally runnable project.


## Conversational chat update

Local fallback now follows short messages and earlier tenant context, including lost keys and plumbing follow-ups. It continues after escalation without repeating the report acknowledgement or closing from inferred resolution. Explicit resolution buttons remain available. The chat displays a pending message immediately, scrolls to the latest reply, and keeps Send message above the optional photo controls in the reading flow (photos are collapsed by default).

The interface identifies local guidance when a provider call fails or no key is configured. Local guidance is a limited rules-based assistant, not an unrestricted language model. For natural open-ended AI conversation, set a valid `ANTHROPIC_API_KEY` in `backend/.env`, configure an available model with `MAINTENANCE_AI_MODEL`, and restart the backend. No credentials are included; live provider access was not verified.

The earlier chat revision passed 61 backend tests and frontend build/type checking. Regression tests cover incomplete messages, continued context after escalation, and advancing plumbing follow-ups.

To update an existing Windows installation without replacing its database or settings, copy `backend/app` and `client-vite-scaffold/src` from this archive over the same folders in your existing Land-Keep folder. Keep `backend/landkeep.db`, `.env`, storage, and your virtual environment. Restart the backend and frontend, then refresh the browser.


## Trained model update

A trained local classifier is now included and connected to new reports. Read **TRAINED-MODEL.md** for current metrics, dependencies, correction controls, and retraining. The launcher applies the additive 0007 migration for stored model provenance.
