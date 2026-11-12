# ProofPay

Proof-of-work payment release for home-service jobs, with agent spend mandates.
A customer's PayPal payment is authorized at booking and only captured once a
vision model verifies the cleaner's before/after photos against the job
checklist and a deterministic policy engine approves the release.

Built for the PayPal AI Hackathon (Devpost).

## Layout

- `app/` FastAPI service (API, state machine, policy engine, webhooks)
- `web/` Vite app: `/` (cleaning site with 3 tiers), `/book`, `/cleaner`
- `spikes/` throwaway PayPal/MCP experiments

## Setup

Copy `.env.example` to `.env` and fill in PayPal sandbox credentials.
(Full setup instructions to follow.)

Run the API: `uv run uvicorn app.main:app --reload`.
Run the site: `cd web && cp .env.example .env`, set `VITE_PAYPAL_CLIENT_ID`, then `npm install && npm run dev` (http://localhost:5173).
For a hosted site, add its URL to `CORS_ORIGINS` on the API.

## Tests

Tests run against a throwaway local Postgres (RAM-backed, about 3 seconds for the whole suite):

```
docker compose up -d --wait
uv run pytest
docker compose down
```

`tests/conftest.py` ignores `DATABASE_URL` from `.env`; set `TEST_DATABASE_URL` to use a different database.

## Deploy (free tier)

**API on Render.** New > Blueprint, pick this repo; it reads `render.yaml`. Set the
secrets when prompted: `DATABASE_URL` (Neon string ending in `?sslmode=require`),
`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, and `CORS_ORIGINS` set to the site's URL, for
example `https://proofpay.example.workers.dev` (a JSON list or a comma-separated list also work). The start command runs
`alembic upgrade head` before the server. The service sleeps when idle, so the first
request after a pause takes 30-60 seconds.

**Site on Cloudflare.** Connect the repo, then set root directory `web`, build
command `npm run build` and deploy command `npx wrangler deploy`. `web/wrangler.jsonc`
serves `dist` as a single-page app, so wrangler needs no auto-detection. Add the build
variables `VITE_API_URL` (the Render URL, no trailing slash), `VITE_PAYPAL_CLIENT_ID`
(sandbox client ID) and `NODE_VERSION` (22). Variables are baked in at build time, so redeploy after changing them.

**Cleaners.** Cleaners sign up at `/cleaner/signup` with a name and a PayPal *sandbox* email; customers pick a free cleaner for a whole day when booking, and the payout goes to that cleaner. Signing up again with the same PayPal email returns the existing cleaner rather than a second one; from a browser that doesn't hold that cleaner the API answers 409 and the site asks the person to confirm it's theirs (there are no passwords, so this is an honest-user check). A cleaner stays available for 24 hours after it was last used (`cleaners.last_used_at`, bumped on sign-up, lookups, booking, photo uploads, submit, approvals and payouts); after that the cleaner and all of its jobs (with their photos, checks, payments and payouts) are deleted. The audit log stays: it is append-only and holds ids and counts only, no names or emails. Extra Render variables for this:

| Variable | Needed | Purpose |
|---|---|---|
| `PAYPAL_CLEANER_EMAIL` | yes | Sandbox account that receives payouts for the permanent default cleaner and any job whose cleaner was already deleted. Unset = no default cleaner, so the booking page is empty until someone signs up. |
| `PAYPAL_WEBHOOK_ID` | yes | ID from registering the webhook in the PayPal developer dashboard (unset = webhooks refused). |
| `DEFAULT_CLEANER_NAME` | no | Display name of the default cleaner (default `Sparkle Crew`). |
| `MAINTENANCE_TOKEN` | no | Enables `POST /api/maintenance/purge` (`Authorization: Bearer <token>`). Without it expired data is still deleted lazily whenever the cleaner list is loaded; the token only lets an external pinger (e.g. a scheduled GitHub Action) do it on a timer. |

The default cleaner is created at startup, so no seed script is needed.

If you change `CORS_ORIGINS` or `VITE_API_URL`, redeploy the matching service.

## Warning: PayPal authorization honor period

A PayPal authorization is valid for 29 days, but only the first 3 are the
"honor period". Capturing after that can be declined by the card issuer. The
clock starts when a job reaches `AUTHORIZED` and stops at `CAPTURED`, so a job
stuck in `PENDING_APPROVAL` or in a re-clean loop past day 3 may fail to
capture. Reauthorizing (day 4 onward) returns a new authorization ID and
restarts the window, so always capture against the latest ID. Automatic
reauthorization is not implemented yet. The demo finishes in minutes, so it is
unaffected.

## License

MIT, see `LICENSE`.
