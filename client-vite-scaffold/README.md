# Land-Keep Alerts

The Land-Keep alert inbox frontend, built with React and Vite.

## Run locally

Requires Node.js 20.19+ or 22.12+.

1. Start the backend by following [the backend setup guide](../backend/README.md).
2. From this directory, install frontend dependencies and start Vite:

   ```powershell
   npm install
   Copy-Item .env.example .env.local
   npm run dev
   ```

3. Open the URL printed by Vite and sign in with a Land-Keep account.

Set `VITE_API_URL` in `.env.local` if the backend is not running at
`http://127.0.0.1:8000`. The inbox currently displays in-app alerts generated
by application and lease events. Email, SMS, scheduled rent reminders, and
predictive alerts are not implemented yet.

Run `npm run build` to create a production build and `npm run lint` to lint the
frontend.
