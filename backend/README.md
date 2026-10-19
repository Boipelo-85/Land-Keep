# LandKeep backend (part 1: data foundation)

One system for the whole tenant journey: apply, credit check, approve, notify, lease, rent, maintenance.

## Run

```bash
cd landkeep/backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python seed.py
```

This creates `landkeep.db` (SQLite) and `data/maintenance_requests.csv` (labelled data for the ML model).
Set `LANDKEEP_DATABASE_URL` to use PostgreSQL instead.

Demo login: `landlord@landkeep.test` / `password123`

## Run the API (part 2)

```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs. Click **Authorize**, paste a token from `POST /auth/login`, and try the endpoints.
Emails and SMS are printed to the terminal and saved in the `notifications` table.

Run the tests: `python -m pytest tests -q`

### The applicant-to-tenant flow

| Step | Who | Endpoint |
|---|---|---|
| See vacant units | anyone | `GET /units/vacant` |
| Sign up | applicant | `POST /auth/register` |
| Apply (consent required) | applicant | `POST /applications` |
| Run credit check | landlord | `POST /applications/{id}/credit-check` |
| Approve or reject (email + SMS sent) | landlord | `POST /applications/{id}/decision` |
| Convert to tenant, generate lease PDF | landlord | `POST /applications/{id}/convert` |
| View or download lease | tenant / landlord | `GET /leases/{id}/pdf` |
| Accept lease, tenant goes live | tenant | `POST /leases/{id}/accept` |
| Track status timeline | applicant / landlord | `GET /applications/{id}` |

## What is here

| Path | Purpose |
|---|---|
| `app/models.py` | All tables. Every event is timestamped. Applicant and tenant are the same user at different stages. |
| `app/services/credit.py` | `CreditCheckService` interface, mock bureau, and the approve/review/decline recommendation. |
| `app/security.py` | Password hashing (PBKDF2). |
| `seed.py` | 50 units, 12 months of rent, ~400 labelled maintenance requests, 12 applications with history. |

## Design decisions to mention in the report

- The system recommends, the landlord decides. Credit checks need recorded consent (POPIA), stored as `consent_given` and `consent_at`.
- The credit bureau is mocked behind an interface. A real bureau plugs in without changing the rest.
- `MaintenanceRequest` keeps `predicted_*` and `confirmed_*` columns so model accuracy can be measured on real corrections.
- All data is synthetic. Maintenance text is template-based, so classifier accuracy will be optimistic. Hand-write a separate test set.

## Next

1. Maintenance requests API (with photo upload) and rent status endpoints
2. Rent reminder job (reuses the notification service)
3. ML classifier trained from `data/maintenance_requests.csv`
4. Analytics endpoints and the React screens
