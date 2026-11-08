# Running the fixes

Open two PowerShell terminals.

Backend:
```powershell
cd C:\Users\Boipelo\Land-Keep
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-backend.ps1
```

Frontend:
```powershell
cd C:\Users\Boipelo\Land-Keep\client-vite-scaffold
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open http://localhost:5173. API documentation: http://127.0.0.1:8000/docs.

The backend script selects a working project environment, with the bundled Codex Python as a local fallback. It creates a random signing secret in backend/.env only when none is set, applies database migrations, preserves demo data through initialize_demo.py, then starts the API. An existing weak signing secret must be replaced; valid existing secrets are preserved.

For a standalone installation after installing Python 3.12:
```powershell
cd C:\Users\Boipelo\Land-Keep
py -3.12 -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-backend.ps1
```

Recurring charges catch up on startup and hourly, and before scheduled rent reminders. A unique lease/month key prevents duplicates. Migration stops for review if legacy duplicate charges exist; it does not delete billing records. Existing lease dates and existing rent amounts are preserved; date corrections apply to newly created leases.

For live application/lease email and SMS, configure SMTP/Twilio in backend/.env and set LANDKEEP_REMINDER_CONSOLE=false. Console mode records these notifications as simulated. Provider acceptance is recorded as sent; this is not confirmation of receipt. Provider exceptions are recorded as failed without discarding the application or lease action. Maintenance fallback tries the next enabled channel when a send fails.
