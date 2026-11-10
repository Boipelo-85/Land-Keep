# Live LandKeep automation

Landlords can review delivery status and replies under **Notifications**. Migration `0012_automation_messages` adds the message log and preserves existing records.

Configure the intended database and a unique `LANDKEEP_SECRET` in `backend/.env` before provisioning the first landlord. Run these commands from `backend` with the project's Python environment active.

```powershell
python -m alembic upgrade head
python create_landlord.py --email you@your-company.co.za --name "Your Name"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use a clean live database or explicitly migrate verified records from a development database. Previous fixture data stays in its database. The Windows launchers run migrations and health checks without seeding records.

## Configure delivery

### Lease notifications

Migration `0014_lease_notifications` adds `lease_notification_preferences`,
`notification_contact_verifications`, and `channel_costs`, plus fields on the existing lease, agency
settings, and automation log tables. Migration `0015_actual_message_currency` records the currency
of actual charges separately from the estimate. Apply both with `python -m alembic upgrade head`.

Landlords manage channels, property overrides, schedules, templates, and a monthly paid-message
count cap in **Notifications**. Tenants manage verified channels per lease in **My lease**.
The default steps are 3 and 1 days before rent is due, the due date, and 1, 3, and 7 days overdue.
SMS and WhatsApp default to the 3-day-before, due-date, and 3-day-overdue steps. Each step also
creates an inbox reminder while the charge has an outstanding balance. **Payments** can pause a
lease or record cash and bank transfers.

Populate `channel_costs` as the platform operator with the provider's per-message price, currency,
and effective date. A zero count cap blocks live paid reminder sends. Missing effective prices
block the corresponding paid channel. Cost previews use the schedule and current balances as a
projection. Set `LANDKEEP_NOTIFICATION_PUBLIC_API_URL` to the public HTTPS API base to include
unsubscribe links in rent emails.

Use `LANDKEEP_DEMO_MODE=true` only with an isolated local demo database. It simulates rent reminder
delivery and contact verification. The date preview does not send or reserve messages. Use
**Run demo simulation** from the preview with a seeded landlord to write simulated messages.

The hourly reminder evaluation uses database reservations to deduplicate sends. A separate durable
retry worker and overnight queue for non-rent notices are still open. A provider request with an
unknown outcome requires reconciliation before any replay. Actual Twilio cost is recorded when the
send response includes it. Twilio may populate the price later. The log shows the estimate in that
case, and fetching the later price remains open. [Twilio Message resource](https://www.twilio.com/docs/messaging/api/message-resource)

#### Test checklist

1. Open **My lease** as a new tenant. Confirm Email is selected by default and SMS and WhatsApp are hidden.
2. Enable WhatsApp as landlord, verify the tenant's contact, select WhatsApp, and preview 3 and 1 days before the due date.
3. Turn WhatsApp off and confirm it disappears from the tenant's choices and an inbox notice appears.
4. Record part of a charge in **Payments** and preview the outstanding balance. Record the remainder and check that no reminder is due.
5. For a live staging test, supply effective channel prices and a small cap. Check the cap alerts, the skipped paid log entries, and continued inbox and email delivery.

- Set `WHATSAPP_MODE=real` with `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TOKEN`, and a supported `WHATSAPP_GRAPH_VERSION` for your Meta account. Configure the `messages` webhook subscription to reach `/automation/whatsapp/webhook` on FastAPI over HTTPS. Set `WEBHOOK_VERIFY_TOKEN` and `WHATSAPP_APP_SECRET` on the backend.
- Set `SMS_MODE=real` with the Twilio account credentials and sender number. Set `EMAIL_MODE=real` with the SMTP settings. Enable only the channels you intend to use in the landlord's reminder settings.
- Reminders use lease due-date offsets by default. Set `LANDKEEP_LEASE_REMINDERS=false` to use the month-end schedule.
- Set `LANDKEEP_REPAIR_FOLLOWUPS=true` after approving the WhatsApp follow-up template. With live WhatsApp enabled, the hourly job evaluates repairs resolved at least 48 hours ago, including existing eligible requests. It sends only where the tenant has consented.
- In `backend/.env`, replace any old channel modes with `real` for configured providers. A blank mode follows the legacy sender settings. Explicit `log` mode records locally.

Submit templates in the Utility category. The live adapter uses the following names in `en_US` with one positional body parameter containing the rendered notification.

| Name | Proposed body |
| --- | --- |
| `landkeep_rent_reminder` | LandKeep rent update. {{1}} Please check your rent account in LandKeep. |
| `landkeep_maintenance_received` | LandKeep maintenance acknowledgement. {{1}} View your report in LandKeep. |
| `landkeep_maintenance_status` | LandKeep maintenance status update. {{1}} View your report in LandKeep. |
| `landkeep_maintenance_followup` | LandKeep repair follow-up. {{1}} You can also check your report in LandKeep. |

A live rollout requires a public HTTPS webhook and routing frontend `/api` requests to FastAPI. The existing scheduler and database reservations handle reminder deduplication. The durable retry queue, quiet hours and delivery-timeout fallback remain open.
