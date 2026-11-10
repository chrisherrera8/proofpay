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
