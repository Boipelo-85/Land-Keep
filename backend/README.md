# Land-Keep backend

FastAPI backend for the Land-Keep rental application demo. SQLite is used by
default; set `DATABASE_URL` to a SQLAlchemy PostgreSQL URL to use PostgreSQL.

## Run locally

Requires Python 3.10 or newer. From this directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py seed.py
py -m uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`; interactive API docs are at
`http://127.0.0.1:8000/docs`.

Demo accounts created by `seed.py`:

| Role | Email | Password |
| --- | --- | --- |
| Landlord | `landlord@example.com` | `LandKeep123!` |
| Tenant | `tenant@example.com` | `LandKeep123!` |

`seed.py` creates the tables, demo users and vacant units.

## Endpoint overview

| Method | Path | Access | Purpose |
| --- | --- | --- | --- |
| POST | `/auth/register` | Public | Create a tenant or landlord account |
| POST | `/auth/login` | Public | Obtain a bearer token |
| GET | `/auth/me` | Authenticated | Return the current account |
| GET | `/units` | Authenticated | List vacant units |
| POST | `/applications` | Tenant | Apply for a vacant unit and run a mock credit check |
| GET | `/applications/{application_id}` | Applicant / landlord | Track an application |
| POST | `/applications/{application_id}/decision` | Landlord | Record an approve, review, or decline decision |
| POST | `/leases/from-application/{application_id}` | Landlord | Create a lease for an approved application |
| GET | `/leases/{lease_id}/pdf` | Lease parties | Download the lease PDF |
| POST | `/leases/{lease_id}/accept` | Tenant | Accept a lease and create its first rent charge |
| GET | `/notifications/me` | Authenticated | List the current user's latest event-triggered alerts |

## Design notes

- Routers handle HTTP concerns; business decisions and lease side effects live
  in `app/services`.
- Passwords are stored as salted PBKDF2 hashes. Login tokens are signed,
  expiring bearer tokens; configure `LANDKEEP_SECRET_KEY` for deployments.
- Notifications are currently stored as in-app alerts; email and SMS delivery
  providers have not been connected. The credit check is a mock and must be
  replaced before production use.
- `models.py` defines the domain tables used by the current API. New schema changes should
  use migrations before deploying against an existing PostgreSQL database.
