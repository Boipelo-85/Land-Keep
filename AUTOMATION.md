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

- Set `WHATSAPP_MODE=real` with `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TOKEN`, and a supported `WHATSAPP_GRAPH_VERSION` for your Meta account. Configure the `messages` webhook subscription to reach `/automation/whatsapp/webhook` on FastAPI over HTTPS. Set `WEBHOOK_VERIFY_TOKEN` and `WHATSAPP_APP_SECRET` on the backend.
- Set `SMS_MODE=real` with the Twilio account credentials and sender number. Set `EMAIL_MODE=real` with the SMTP settings. Enable only the channels you intend to use in the landlord's reminder settings.
- Set `LANDKEEP_LEASE_REMINDERS=true` to use the lease due-date offsets. Existing installations retain the month-end schedule by default.
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
