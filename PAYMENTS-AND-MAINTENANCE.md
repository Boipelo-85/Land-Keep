# Payment and maintenance update

## Payment provider choice

For this South African ZAR rent project, retain PayFast: the existing application already has hosted checkout, recipient routing and server-confirmed payment handling. Switching providers would require a new adapter, merchant onboarding and verification work. This is a fit recommendation, not a claim of measured superiority or uptime.

Stripe's official availability page lists South Africa in its extended network: https://stripe.com/global . Check eligibility and the applicable local onboarding route before choosing a direct Stripe integration. Current PayFast merchant options must be checked in your own provider account; wallets and bank-payment options vary by account and device.

The screenshot supplied is a card form (card number, expiry and security code), not a bank-account-number form. LandKeep now opens a rent-review dialog when Pay is clicked. When configured, Continue to PayFast submits the signed amount/reference to the provider's HTTPS checkout, where payment details are entered. LandKeep never collects raw card numbers, security codes, bank passwords or PINs. The hosted provider determines the screen layout and available methods; this does not copy another company's checkout.

## Configure checkout

In backend/.env configure your actual platform sandbox account:

```dotenv
PAYMENT_PROVIDER=payfast
PAYFAST_MODE=sandbox
PAYFAST_MERCHANT_ID=your_platform_sandbox_merchant_id
PAYFAST_MERCHANT_KEY=your_platform_sandbox_merchant_key
PAYFAST_PASSPHRASE=your_sandbox_passphrase
PAYFAST_SPLIT_PAYMENTS_ENABLED=false
LANDKEEP_PUBLIC_BASE_URL=https://your-public-app-domain
PAYFAST_NOTIFY_URL=https://your-public-app-domain/api/payments/payfast/notify
PAYFAST_RETURN_URL=https://your-public-app-domain/pay-rent?payment=return
PAYFAST_CANCEL_URL=https://your-public-app-domain/pay-rent?payment=cancelled
```

Enable split payments with PayFast first, then set PAYFAST_SPLIT_PAYMENTS_ENABLED=true. Do not enter invented credentials. Your public app must forward /api requests to the running FastAPI backend. A localhost-only URL cannot receive provider notifications.

Sign in as the landlord, open Payment setup, save the recipient merchant ID, complete the existing R5 hosted verification flow, then enable tenant payments. Restart the backend after configuration changes. Tenants then open Pay rent, review the amount, and Continue to PayFast. If setup is incomplete the dialog says what is missing and cannot submit a checkout.

Use only test payment details in sandbox. Move to live mode only with your own live account configuration. Rent is not marked paid by a browser redirect or clicking Pay: the existing verified provider notification remains required.

No live transaction or real sandbox account was tested here because merchant credentials were not supplied. The review/redirect path was tested with synthetic local configuration. Configuration cannot be bypassed by adding a local card form.

## Maintenance

The exact screenshot wording "I cant find mu unit keys hey." and "The keys" is now recognized, including after escalation. The bot asks about lockout and safe access rather than repeating an unrelated generic message. Follow-up urgency is raised when appropriate and an existing emergency cannot be downgraded. Local mode is limited; a configured Claude account is still used for open-ended generative conversation.

The actual trained category classifier and newly trained advisory priority classifier are retained. TRAINED-MODEL.md records evaluations on synthetic data. Emergency guidance and qualified-tradesperson referrals take precedence. Advice continues after reporting to the landlord.

## Contractor workflow

Landlords now have a Contractors sidebar screen. Save a contractor's name, trade and contact details; choose a maintenance report; assign a contractor and optional visit date; then track assigned, scheduled, in-progress, completed or cancelled work. Reassignment retains the old cancelled work-order record. Assignment/status updates appear in the tenant's saved maintenance chat. Completing a work order resolves the maintenance request. Contact contractors separately to confirm availability; this version does not send invitations or provide contractor login accounts.

All contractor records and assignments are agency scoped and protected by backend landlord permissions. This update does not include late-rent prediction or reliable future recurrence forecasting: those still need suitable historical data and independent validation.
