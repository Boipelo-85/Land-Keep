# Paystack rent payments

Tenant: open Pay rent, review the charge, then Continue to Paystack. Hosted checkout collects payment details. Returning to LandKeep triggers server verification; Check status can verify again. A confirmed payment updates the rent ledger and landlord view once. An existing open checkout is resumed rather than creating another transaction.

Landlord: open Payments to enable online payments with your password, see tenant balances, and inspect recent attempts. Each landlord sees only their own properties. All payments go to ONE Land-Keep Paystack account. No landlord subaccounts, onward payouts, platform commissions, recurring card debits, or refund automation are included. Refunds and reversals require reconciliation in this version.

## Configure locally

Edit `C:\Users\Boipelo\Land-Keep\backend\.env` locally:

```dotenv
PAYMENT_PROVIDER=paystack
PAYSTACK_SECRET_KEY=YOUR_PAYSTACK_TEST_SECRET_KEY
PAYSTACK_WEBHOOK_SECRET=
PAYSTACK_CALLBACK_URL=http://localhost:5173/pay-rent?payment=return
```

Replace the test-key placeholder with the actual `sk_test_...` secret from your Paystack dashboard. Keep secrets out of frontend files and source control. This hosted redirect integration does not need a public key.

If you create a webhook signing secret in Paystack, put the full `whsec_...` value in PAYSTACK_WEBHOOK_SECRET. This activates modern timestamped signature checking and disables legacy signature fallback. Without it, legacy `x-paystack-signature` is verified using the API secret key. The API and webhook mode must match.

In the Paystack dashboard, configure the webhook URL:

`https://YOUR_PUBLIC_HOST/api/payments/paystack/webhook`

That `/api` path assumes the frontend/reverse proxy strips `/api` before forwarding to FastAPI. If your public host exposes FastAPI directly, use `/payments/paystack/webhook` instead. Paystack cannot deliver webhooks to localhost. Tenant callback verification works locally while the browser can reach your backend; public webhooks are necessary to handle a tenant closing their browser before returning.

Restart the backend, which applies migrations automatically:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Boipelo\Land-Keep\start-backend.ps1"
```

Frontend in a second terminal:

```powershell
cd C:\Users\Boipelo\Land-Keep\client-vite-scaffold
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open http://localhost:5173, sign in as landlord, open Payments, enable online payments, and save with your password. Sign in as tenant and pay an outstanding charge using Paystack test details. Confirm the balance and landlord history update. Never use real card details in test mode.

For live mode, use an approved South African Paystack account that supports ZAR, replace the key with the account's live secret, use an HTTPS callback and public HTTPS webhook, configure the matching signing secret, and restart. Do not mix test and live keys while transactions are pending. Changing credentials may prevent verification of old in-flight transactions.

## Operational behavior

Only verified successful payments with matching reference, integer amount, currency and test/live domain credit rent. Webhook signatures are checked against the original request bytes. Duplicate verification and callback/webhook races cannot insert the same payment twice. A database index prevents concurrent open Paystack checkouts for a charge. Uncertain initialization failures remain open so retries cannot accidentally create a second charge; use Check status and investigate unresolved attempts in Paystack before manually changing them. Confirmed collection does not prove bank settlement.

Sources: https://paystack.com/docs/payments/accept-payments/ ; https://paystack.com/docs/payments/verify-payments/ ; https://paystack.com/docs/payments/webhooks/
