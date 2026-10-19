# LandKeep

One place for a landlord to run the whole tenant journey: apply, credit check, approve, notify, lease, rent, maintenance, analytics.

```
Land-Keep/
├── backend/               FastAPI + SQLAlchemy + SQLite (Python, ML later)
└── client-vite-scaffold/  React + Redux Toolkit + Vite
```

## Run it (two terminals)

**1. Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python seed.py                                        # demo data
uvicorn app.main:app --reload                         # http://localhost:8000/docs
```

**2. Client**

```bash
cd client-vite-scaffold
npm install
npm run dev                                           # http://localhost:5173
```

The client calls the API through a Vite proxy (`/api` goes to `localhost:8000`), so there is nothing to configure.

## Demo logins (password `password123`)

| Role | Email |
|---|---|
| Landlord | `landlord@landkeep.test` |
| Applicant / tenant | `applicant@landkeep.test` |

## Demo story

1. Applicant: browse vacant units, apply (with consent), watch the tracker.
2. Landlord: open the application, run the credit check, approve.
3. Landlord: convert to tenant (generates the lease PDF).
4. Applicant: read the lease, accept it, become an active tenant.

See `backend/README.md` for the API and design notes.
