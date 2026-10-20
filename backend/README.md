# LandKeep backend (part 1: data foundation)

One system for the whole tenant journey: apply, credit check, approve, notify, lease, rent, maintenance.

## Run

```bash
cd landkeep/backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head                               # apply versioned schema migrations
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

### Agency-scoped rent reminders

For reminders, an existing landlord account is the agency boundary: its
properties, leases, and reminder logs are scoped through `Property.landlord_id`.
New agencies default to day 3 before month end, Africa/Johannesburg, and the
channel strategy `fallback` in WhatsApp → SMS → email order. It sends through
the first opted-in channel that succeeds, avoiding duplicate cross-channel
messages. An agency can select `all` to send on every opted-in channel.

Copy `.env.example` to `.env`. The API loads it with python-dotenv. Local
development defaults to console mode, which previews each selected channel but
does not call providers. To send externally set `LANDKEEP_REMINDER_CONSOLE=false`
and configure provider values in `.env`.

Landlords configure their own policy with `PUT /reminders/settings`, for example:

```json
{
  "reminder_days_before_month_end": 3,
  "reminder_windows": [3, 1],
  "channel_order": ["whatsapp", "sms", "email"],
  "channel_strategy": "fallback",
  "agency_name": "Example Rentals",
  "contact_email": "rent@example.test",
  "contact_phone": "+27115550100"
}
```

Tenants manage their own consent at `PUT /reminders/preferences` with
`whatsapp_opt_in`, `sms_opt_in`, and `email_opt_in` booleans. All start false.
Authenticated landlords can preview only their agency with
`POST /reminders/run?dry_run=true`; add `&window_days=3` to preview the configured
copy for that window without sending or writing logs. A real manual run only
operates on today's configured window: `POST /reminders/run?dry_run=false`.
`GET /reminders/log` returns only the caller's agency records.

#### Provider setup

- **Twilio SMS:** set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and
  `TWILIO_SMS_FROM` to the account credentials and SMS-capable sender.
- **Twilio WhatsApp:** enable a WhatsApp sender, create and get approval for a
  Content Template, then set `TWILIO_WHATSAPP_FROM` and
  `TWILIO_WHATSAPP_CONTENT_SID` to its sender and `HX...` SID. The template
  body should use `{{6}}: {{1}}, {{3}} outstanding for {{2}}. Due {{4}};
  {{5}} days left. Contact {{7}}. {{8}}`. These variables are tenant,
  property/unit, amount, due date, days remaining, agency, agency contact, and
  opt-out text respectively.
  Set the Twilio inbound webhook to `/reminders/twilio/inbound` and configure
  `LANDKEEP_PUBLIC_BASE_URL` so signature verification works behind a proxy;
  STOP and related keywords clear the matching SMS or WhatsApp consent.
- **Email:** configure `SMTP_HOST`, `SMTP_PORT` (587 by default),
  `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM`; delivery uses STARTTLS.
- `LANDKEEP_PROVIDER_MAX_ATTEMPTS`,
  `LANDKEEP_PROVIDER_RETRY_BASE_SECONDS`, and
  `LANDKEEP_PROVIDER_MIN_INTERVAL_SECONDS` configure bounded exponential
  retries for Twilio 429 / SMTP temporary 4xx errors and a per-process send
  interval.

`RentCharge` and `Payment` remain the source of the current balance. A lease
without a charge for the current month is treated as owing its existing
`monthly_rent`. Partial-month leases are selected by date overlap; because the
current rent model does not represent proration, their charge follows the
existing full-month amount. Attempt records are unique by lease, month, window,
and channel, and live in a new table so prior SQLite data is left intact.

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
