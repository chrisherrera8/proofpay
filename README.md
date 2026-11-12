# ProofPay

**Pay for the result, not the promise.** ProofPay holds a customer's PayPal payment as an
authorization when they book a home-cleaning job, and releases it only after the cleaner's
before/after photos pass an AI vision check *and* a deterministic policy engine approves the
release. If the photos don't check out, the money is never captured.

It is also a small model of an **agent spend mandate**: the AI reports what it sees, but the
rules that move money (minimum score, auto-release ceiling, required items) live in plain,
tested code that a person configures.

- **Live demo:** https://proofpay.chris88herrera.workers.dev (PayPal *sandbox* only, no real money).
  The API sleeps when idle, so the first request can take 30-60 seconds.
- Built for the PayPal AI Hackathon (Devpost).

## How a job flows

```
BOOKED -> AUTHORIZED -> SUBMITTED -> VERIFIED -+-> RELEASED -> CAPTURED -> PAID_OUT
                                               +-> REJECTED
```

1. **Book.** The customer picks a tier and a free cleaner for a whole day, optionally turns on a
   *strict check*, and approves a PayPal `AUTHORIZE` order. No money moves yet (`AUTHORIZED`).
2. **Submit.** The cleaner uploads before and after photos (resized in the browser) and submits.
3. **Verify.** A vision model checks each checklist item in the photos (`VERIFIED`).
4. **Decide.** The policy engine reads the result and picks `RELEASED` or `REJECTED`.
5. **Settle.** A released job is captured, then the cleaner is paid through PayPal Payouts. The
   PayPal webhook marks the job `PAID_OUT`.

```
 Customer ──> React site (Cloudflare) ──> FastAPI API (Render) ──> Postgres (Neon)
 Cleaner  ──>   /book  /cleaner              |        |
                                             |        +──> Gemini vision (provider interface)
                                             +──> PayPal sandbox: Orders, Capture, Payouts
                                             <── PayPal webhooks (signature verified)
```

## How PayPal is used

- **Orders v2 with `intent=AUTHORIZE`.** Payment is authorized at booking and held, not charged.
- **Capture** happens only after the job reaches `RELEASED`.
- **Payouts** sends the cleaner's share to their PayPal sandbox email.
- **Webhooks.** `POST /api/webhooks/paypal` verifies each event with PayPal's
  `verify-webhook-signature` endpoint (a bad signature gets 400) and marks the job `PAID_OUT` on the
  payout item event.
- The PayPal MCP server has no authorize, capture or Payouts tools, so the app calls the REST API
  for those (see `app/paypal/`).

## How AI is used

- **Gemini vision** (`app/vision/`) looks at the before/after photos and reports, per checklist
  item, whether it is visible and whether it passes, plus an overall score. It sits behind a small
  provider interface, so changing the model is one config change (`GEMINI_MODEL`).
- **The model never decides.** Pass/fail and what happens to the money are decided in code
  (`app/policy.py`), a pure function with its own tests.
- **Strict check** (optional, chosen at booking): a checklist item that isn't visible in the after
  photos fails instead of being skipped.

## Policy engine

`evaluate()` (`app/policy.py`) applies a set of rules in order and returns `auto_release` or
`reject`, with every matching reason attached. The mandate (minimum score, auto-release ceiling,
required items) is read from the database, with built-in defaults (0.80 and $25.00) when empty.

## Known gaps

This is a hackathon demo, not a product.

- **No authentication.** There are no passwords; a cleaner is identified by their PayPal email, and
  the "is this you?" prompt is an honest-user check.
- **Sandbox only.** No live PayPal, and the data is disposable.
- **Cleaner data is scrubbed 24 hours after last use** (see Cleaners below).
- **No automatic reauthorization** of PayPal authorizations (see the honor period warning).
- The policy engine uses one global mandate; per-customer mandates, monthly caps and
  subcontractor lists are not built.

## Layout

- `app/` FastAPI service (API, state machine, policy engine, webhooks)
- `web/` Vite app: `/` (cleaning site with 3 tiers), `/book`, `/cleaner`
- `spikes/` throwaway PayPal/MCP experiments

## Setup

Prerequisites: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22, and Docker (for the test database).

You also need:

- A **PayPal sandbox** app ([developer.paypal.com](https://developer.paypal.com)): client ID and secret,
  a sandbox **customer** (buyer) account to approve payments, and a sandbox **business** account whose
  email receives the payouts (`PAYPAL_CLEANER_EMAIL`). Register a webhook pointing at
  `/api/webhooks/paypal` and copy its ID into `PAYPAL_WEBHOOK_ID` (webhooks are refused without it).
- A **Gemini API key** from [Google AI Studio](https://aistudio.google.com) (`GEMINI_API_KEY`); the free tier is enough.
- A **Postgres** database. Use [Neon](https://neon.tech) free tier, or any Postgres; set `DATABASE_URL`
  and `DB_SCHEMA` if you don't use `public`.

Copy `.env.example` to `.env` and fill it in. Then:

```
uv sync
uv run alembic upgrade head     # create the tables
uv run uvicorn app.main:app --reload
```

The API runs at http://localhost:8000.

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

**Cleaners.** Cleaners sign up at `/cleaner/signup` with a name and a PayPal *sandbox* email; customers pick a free cleaner for a whole day when booking, and the payout goes to that cleaner. Signing up again with the same PayPal email returns the existing cleaner rather than a second one; from a browser that doesn't hold that cleaner the API answers 409 and the site asks the person to confirm it's theirs (there are no passwords, so this is an honest-user check). A cleaner stays available for 24 hours after it was last used (`cleaners.last_used_at`, bumped on sign-up, lookups, booking, photo uploads, submit, approvals and payouts); after that the cleaner and all of its jobs (with their photos, checks, payments and payouts) are deleted. Extra Render variables for this:

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
that waits past day 3 before capture may fail. Reauthorizing (day 4 onward) returns a new authorization ID and
restarts the window, so always capture against the latest ID. Automatic
reauthorization is not implemented yet. The demo finishes in minutes, so it is
unaffected.

## License

MIT, see `LICENSE`.
