# ProofPay Implementation Plan

Combines idea #1 (proof-of-work payment release for home-service jobs) with idea #3 (agent spend mandates: policy engine, human approvals, audit log) for the PayPal AI Hackathon on Devpost.

Status: spikes 0-5 done (spike 4 vision test and spike 5 docs checks finished Nov 4), repo scaffolded (MIT). Customer site built, deployed and merged to `main` on Nov 5 (PR #2; see `plans/finished/customer-site.md`). Backend foundation merged to `main` on Nov 4 (PR #1): models, Alembic, state machine, hash-chained audit log, booking API, PayPal order and authorize endpoints, 131 tests, one sandbox run. Cleaner upload and vision verification merged Nov 9 (PR #3) and the policy engine with approvals merged Nov 9 (PR #4; see `plans/finished/policy-engine.md`). Capture, payouts and webhooks merged Nov 9 (PR #5, 338 tests; see `plans/capture-payouts.md`), with a sandbox run on the hosted site that took a $10 job to `PAID_OUT`. The admin UI and rejection agent are next. Schedule re-based Nov 2.
Deadline: Nov 12, 2026, 12:00pm PST. Feature freeze: Nov 9.

## 1. PayPal findings

| Question | Finding | Design consequence |
|---|---|---|
| Authorization window | The honor period is 3 days and the authorization is valid for 29 days; capturing inside the honor period is the most likely to succeed, and a later capture can be declined if the card issuer refuses to re-authorize. Spike 5 (Nov 4): the old docs URL still returns 404, so this comes from search summaries of the current pages ([standard](https://developer.paypal.com/docs/checkout/standard/customize/authorization-honor/), [payment-methods](https://developer.paypal.com/payment-methods/auth-honor)), not fetched pages. A legacy archive page says an order authorization expires after 3 days; it contradicts the current docs and is probably outdated. | Demo and test jobs must complete (capture) within 3 days of authorization. Store the authorization ID (`purchase_units[0].payments.authorizations[0].id`) as soon as the order is approved. |
| Reauthorization | Search results say you can reauthorize from day 4 through day 29. Each reauthorization returns a new authorization ID and a new 3-day honor period; reauthorizing late shortens it (day 27 leaves 2 days). | Store `authorization_id` as mutable, and always capture against the latest ID. A daily job reauthorizes jobs still pending after day 3. Stretch goal; the demo doesn't need it. |
| Payouts enablement | [Live accounts](https://developer.paypal.com/payouts/use-payouts/set-up.md) need a verified business account, and you must contact PayPal support to enable Payouts. The docs don't say whether the sandbox has it on by default. | Day-1 spike: send a $1 sandbox payout. If it fails, that tells us what's blocking it. Payouts will be sandbox-only, which is allowed. |
| Webhooks | The [Payouts webhook docs](https://docs.paypal.ai/send/webhook-reference) say batch events carry no item detail, so you have to call the batch-details endpoint. | Spike 2 (Nov 2) confirmed these events arrive with valid signatures: `CHECKOUT.ORDER.APPROVED`, `PAYMENT.AUTHORIZATION.CREATED`, `PAYMENT.AUTHORIZATION.VOIDED`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.PAYOUTSBATCH.PROCESSING`, `PAYMENT.PAYOUTSBATCH.SUCCESS` and `PAYMENT.PAYOUTS-ITEM.SUCCEEDED`. Not yet triggered, so unconfirmed: `PAYMENT.CAPTURE.DENIED/PENDING`, `PAYMENT.PAYOUTSBATCH.DENIED` and `PAYMENT.PAYOUTS-ITEM.FAILED/UNCLAIMED`; subscribe to them anyway. Order matters: `PAYMENT.PAYOUTS-ITEM.SUCCEEDED` arrived about 9s before `PAYMENT.PAYOUTSBATCH.SUCCESS`, so mark a job `PAID_OUT` on the item event and don't assume the batch event comes first. All payout events carry the batch id, which is how to match them to a job. |
| Agent Toolkit / MCP | The [official catalog](https://paypal.gitbook.com/agent-toolkit-and-mcp-server/available-tools.md) lists `create_order`, `get_order`, `pay_order`, the invoice tools, three dispute tools (`list_disputes`, `get_dispute`, `accept_dispute_claim`), `list_transaction`, subscriptions and shipment tracking. It has no authorize tool, no capture-authorization tool and no Payouts tool. | Spike 3 (Nov 2) confirmed this against the sandbox: the token exposes 28 tools, none for authorize, capture-authorization, void or Payouts. `create_order` has no `intent` parameter and always creates `CAPTURE` orders, so create `AUTHORIZE` orders over REST. `pay_order` fails on an `AUTHORIZE` order (HTTP 422, "use v2/checkout/orders/order_id/authorize") and leaves it untouched. So the agent uses MCP only for reads (`get_order`, `get_dispute`, invoices). Call REST directly for create order, authorize, capture, reauthorize, void and Payouts. MCP calls can fail transiently (one `create_order` returned a 503 and succeeded on retry), so retry them. |

Nov 4 sandbox run through our own API (`POST /api/jobs/{id}/paypal/order`, then `/authorize`) worked: an `AUTHORIZE` order opened at `https://www.sandbox.paypal.com/checkoutnow?token=<order_id>` was approved by the sandbox customer, and the authorization came back `CREATED` with the payer's email in the response. The JS SDK button path from our own React site is still untested against these routes.

Orders v2 also needs the buyer to approve in the PayPal JS SDK button with `intent=AUTHORIZE`. Spike 1 (Nov 2) confirmed the button and popup work from a hosted page; the booking site (section 3) now loads it as a normal top-level page.

## 2. Architecture

- **Two free hosts.** The FastAPI API runs on Render (free web service). The React site runs on Cloudflare Pages (static, unlimited bandwidth, no cold start). The API allows the site's origin through CORS, and the site reads the API URL from a `VITE_API_URL` env var so local and hosted runs differ by config only.
- **One Vite app with routes.** `/` is the customer-facing cleaning site (see section 3). `/book` is the booking and payment flow. `/cleaner` is mobile photo upload. `/admin` covers approvals, the audit log and job detail.
- **Postgres on Neon (free).** Render's free Postgres expires after a short window, which could break the demo while judging is still happening. The exact window is unverified; check it. Photos are resized client-side to about 1024px and stored in the database, which avoids another storage service. Spike 5 (Nov 4) checked Neon's free plan: 1 GB storage per project (writes blocked when exceeded), 100 CU-hours per project per month, scale-to-zero after 5 minutes idle (can't be turned off), 5 GB transfer per month, 6-hour history window, pooling included. No expiry is listed, so the Render concern stands. Plan for a cold start on the first request: warm the service before any live demo.
- **Core tables:** `jobs`, `checklist_items`, `photos`, `verifications`, `payments` (order, authorization and capture IDs), `payouts`, `mandates`, `approvals` and `audit_log`. The audit log is append-only (a database trigger blocks `UPDATE` and `DELETE`) and hash-chained: each row stores `prev_hash` and `hash` (SHA-256 of the previous hash plus the row's fields), and `verify_chain()` finds the first tampered row. Built in the Nov 4 backend work, so it is no longer a scope cut.
- **State machine:** `BOOKED → AUTHORIZED → SUBMITTED → VERIFIED → (RELEASED | PENDING_APPROVAL | REJECTED) → CAPTURED → PAID_OUT`. Each transition writes an audit row.
- **Policy engine** is plain deterministic Python; the LLM never moves money. It takes the vision score, the per-item results and the mandate, and returns `auto_release`, `needs_approval` or `reject`, plus reasons. The mandate (idea #3) holds:
  - a monthly payout cap
  - an approved-subcontractor list
  - an auto-release ceiling
  - a minimum score
  - required checklist items that must pass

  **Built Nov 9 (`app/policy.py`), simplified for the demo:** the engine uses only the minimum score, the auto-release ceiling and the required items. The monthly cap and the approved-subcontractor list are cut (the columns stay unused in `mandates`), and one global mandate row applies, with built-in defaults when the table is empty.
- **AI agent:** the vision call returns structured JSON (per-item pass/fail, confidence, notes). On rejection, a second call drafts the re-clean request or the dispute summary. The agent's tool calls go through the PayPal MCP server where it fits.
- **Payout:** built Nov 9. The cleaner gets 100% of the job amount (no share setting). Capture runs automatically after `RELEASED`, then a Payouts batch goes to `PAYPAL_CLEANER_EMAIL` in the sandbox. `PAID_OUT` is set by the `PAYMENT.PAYOUTS-ITEM.SUCCEEDED` webhook, with `POST /api/jobs/{id}/settle` as the retry and polling fallback. A failed payout leaves the job `CAPTURED`.

## 3. Customer site (own hosting)

The cleaning-company mock-up is a React site we host ourselves, in the same Vite app as the cleaner and admin screens.

- **Home / pricing (`/`):** a hero, three service tiers as cards (names and prices are mock content, Basic Clean $10, Deep Clean $20 and Deluxe Clean $30) and a "Book" button on each.
- **Booking (`/book?tier=...`):** a form for the tier, date, address and contact details. It calls the existing booking API to create the job, then `POST /api/jobs/{id}/paypal/order`, shows the PayPal JS SDK button with `intent=AUTHORIZE`, and on approval calls `/authorize`. The last step is a "Booked!" confirmation page showing the job status.
- **Tiers drive the checklist:** each tier maps to its own checklist template and price. `app/checklists.py` now has `basic`, `deep` and `deluxe` templates. `app/pricing.py` holds the tier prices and the API rejects a mismatched `amount`.
- **PayPal runs top-level.** The button sits on a normal top-level page. If the popup misbehaves on mobile, switch to the redirect flow with real `return_url` and `cancel_url`.
- **Free hosting:** Cloudflare Pages deploys from GitHub on every push and serves HTTPS on a `*.pages.dev` subdomain. A custom domain isn't needed.
- **Spike to run first:** load the PayPal button on the local booking page and complete a sandbox authorization through our own routes. Do this against the hosted URLs too (Cloudflare Pages and Render) to catch CORS and env-var mistakes early.

## 4. Vision model comparison

Official prices were not confirmed: search results conflicted and listed no image-token costs. Estimates assume about 6-8k input tokens and 500 output tokens per job (4 photos plus a checklist):

| Option | Listed price (per 1M tokens in/out) | Est. cost per verification |
|---|---|---|
| Gemini Flash (2.5 or 3 class) | about $0.30-0.50 / $2.50-3.00, plus a free tier | about $0.004-0.007, or $0 on the free tier |
| GPT-5-mini class | about $0.25 / $1.00 (sources disagree) | about $0.003 |
| Claude Haiku | $0.80 / $4.00 (unverified; another source says $1 / $5) | about $0.008-0.01 |

All three cost under a cent per job, so cost won't decide this.

**Recommendation:** Gemini Flash on the free tier for development and the demo, behind a small provider interface so swapping models is one config change. On day 1, test 10 before/after photos on two models and pick on accuracy. The free tier may use prompts for training, which is fine for demo photos.

**Decision (Nov 4, spike 4):** the default vision model is `gemini-3.6-flash`. On the 9 labeled cases (after the softened "not visible" prompt and the oven checklist item) it scored 9/9 at about 6.6s per job and about 2,406 in / 322 out tokens. `gemini-3.5-flash` also scored 9/9. `claude-haiku-5-5` scored 7/9, missing two bedrooms on "surfaces are dusted and clear".

| Model | Price per 1M in/out | Est. per job |
|---|---|---|
| `gemini-3.6-flash` | $0.75 / $3.75 through Dec 31, 2026; $1.50 / $7.50 from Jan 1, 2027 | about $0.0030, then $0.0060 |
| `gemini-3.5-flash` | $1.50 / $9.00 (third-party figures, not confirmed on Google's page) | about $0.0062 |
| `claude-haiku-5-5` | $0.10 / $0.50 (prompts up to 100k) | about $0.0006 |

- Prompt: items not visible in the after photo are marked `visible=false, pass=true` and ignored; the case fails only on visible items, or if none are visible.
- `gemini-2.5-flash-lite` and `gemini-2.5-flash` return 404 for new users. Cheaper untested options: `gemini-3.1-flash-lite` (about $0.0010) and `gemini-3.5-flash-lite` (about $0.0014).
- Caveats: only 9 cases, some with generated photos; output token counts may exclude thinking tokens, so real cost may run higher.

## 5. Cost flags

- **Free:** Cloudflare Pages, Render web service, Neon, PayPal sandbox, GitHub, the Gemini free tier.
- **Render free web service:** sleeps after idle, cold start about 30-60 seconds. Add a keep-warm ping before the demo and before judging.
- **Possibly paid:** a custom domain (about $10/year; not needed, the `*.pages.dev` subdomain is enough).
- **Not needed:** live PayPal, S3, Redis.

## 6. Schedule (re-based Nov 2; feature freeze Nov 9)

Spikes 0-5 and the repo scaffold (MIT license) are done (spikes 4 and 5 finished Nov 4). The Oct 28 plan assumed about 11 build days; there are now 6 (Nov 3-8), so the work is compressed and the scope cuts below are more likely to be used.

| Dates | Work |
|---|---|
| Nov 2 (done) | Spikes 0-3, scaffold with MIT license. |
| Nov 3 | ~~Spikes 4 and 5~~ (done Nov 4). ~~Models, Alembic, state machine, audit log, booking API, PayPal authorize endpoint~~ (done Nov 4, merged as PR #1; see `plans/finished/nov4-backend-foundation.md`). |
| Nov 4-5 | ~~Customer site (home with 3 tiers, booking form with validation, PayPal button, confirmation page), CORS, server-side price check, three checklist templates~~ (done Nov 5, PR #2). ~~Deploy: Cloudflare + Render + Neon, live booking verified~~ (done Nov 5, ahead of the Nov 7 row). ~~Cleaner upload and vision verification (provider interface)~~ (done Nov 9, PR #3). |
| Nov 5 | ~~Policy engine and mandates~~ (done Nov 9, PR #4), ~~capture and Payouts, webhooks with signature verification~~ (done Nov 9, PR #5), pytest on the policy engine and state machine. |
| Nov 6 | Admin UI (approvals, audit log), rejection agent (re-clean draft), seed data. |
| Nov 7 | ~~Deploy~~ (done Nov 5). Re-run the full flow on the hosted URLs after the new steps land. |
| Nov 8 | README setup instructions, bug fixes, demo rehearsal. |
| Nov 9 | **Freeze.** |
| Nov 10 | Record the demo video (under 3 minutes) and write the Devpost text. |
| Nov 11 | Buffer, repo and URL check. |
| Nov 12, before noon | Submit. |

**Scope cuts if time slips, in order:** reauthorization job, dispute drafting (keep the re-clean draft), mandate monthly caps. (The audit-log hash chain was removed from this list on Nov 4; it was built with the audit log.)

### Pick up here (next session)

Where things stand (Nov 9): booking, PayPal authorization, cleaner photo upload, vision verification and the policy engine are built. A job now runs `BOOKED → AUTHORIZED → SUBMITTED → VERIFIED` and then the engine moves it to `RELEASED`, `PENDING_APPROVAL` or `REJECTED` in the same request; a released job is then captured and paid out in the same request, and the webhook confirms `PAID_OUT`. Nothing exists yet for the admin UI or the rejection agent. Do these in order:

1. ~~**Housekeeping:** repoint Render and Cloudflare to `main`, confirm a deploy, delete `feature/customer-site`.~~ Done Nov 6: both platforms deploy from `main`, and the local `feature/customer-site` branch is deleted (the remote branch is still to delete). Warm the API before testing (cold start 30-60s).
2. ~~**Cleaner upload and vision verification**~~ Built Nov 6-9 on `feature/cleaner-and-vision` (merged as PR #3 on Nov 9; 227 tests pass, 97% line coverage, one live Gemini call matched its label). The `photos` and `verifications` tables already existed in the initial migration, so no new migration. Pieces:
   - `app/vision/`: `VisionProvider` interface, `GeminiProvider` (REST, retries 429/503 with the told delay capped at 20s), prompt, and `score_answer()`, which decides pass/fail in code (at least one visible item and every visible item passing) and ignores the model's own `overall_pass`/`score`. Model booleans are parsed, not truthy-tested (`"false"` is false), and non-finite confidence becomes 0.
   - `app/api/cleaner.py`: `POST/GET/DELETE /api/jobs/{id}/photos` (raw image body, `?kind=before|after`, magic-byte check for JPEG/PNG/WebP, 3 MB and 4-per-kind caps), `POST /submit` (`AUTHORIZED|REJECTED → SUBMITTED → VERIFIED`) and `POST /verify` to retry when the vision call fails (the job stays `SUBMITTED`). `JobOut` includes the latest `verification`, also in the list endpoint.
   - Web: `/cleaner` (job list) and `/cleaner/:jobId` (client-side resize to 1024px, thumbnails, submit, per-item result).
   - Tests now run against a local Postgres (`docker compose up -d --wait`, then `uv run pytest`; override with `TEST_DATABASE_URL`). Coverage: `uv run pytest --cov=app --cov-report=term-missing`.
   - Hosted check done Nov 9: `GEMINI_API_KEY` is set on Render and a Basic job went from photos to `RELEASED` on the deployed site (`gemini-3.6-flash`, score 1.0).
3. ~~**Policy engine and mandates**~~ Built Nov 9 on `feature/policy-engine` (plan: `plans/finished/policy-engine.md`; 273 tests pass). Pieces:
   - `app/policy.py`: pure `evaluate()` (seven ordered rules; the first match sets the outcome and every matching rule adds a reason), `DEFAULT_RULES` (min score 0.80, auto-release ceiling $25.00, no required items), `get_mandate(db)` (newest `mandates` row, a NULL column falls back to its default) and `decide(db, job)`, which moves `VERIFIED` to `RELEASED`, `PENDING_APPROVAL` or `REJECTED` with a `POLICY_DECIDED` audit row (outcome, reasons, rules in force, verification id) and a PENDING `Approval` for `needs_approval`. No migration.
   - `/submit` and `/verify` call `decide()` after `VERIFIED` is committed. `JobOut.decision` (outcome and reasons) comes from the latest `POLICY_DECIDED` audit row, eager-loaded, also in the list endpoint.
   - `POST /api/jobs/{id}/approval` (`approve` or `deny`, with `decided_by` and an optional `reason`): `PENDING_APPROVAL` to `RELEASED` or `REJECTED`; 409 if not pending, 404 for an unknown job. Audit actor is `admin`, the name is in the payload.
   - Web: `/cleaner/:jobId` shows the decision and its reasons, and the per-item result on a rejected job.
4. ~~**Capture and Payouts, then webhooks**~~ Built Nov 9 on `feature/capture-payouts` (merged as PR #5; plan: `plans/capture-payouts.md`; 338 tests pass). Pieces:
   - `app/paypal/client.py`: `capture_authorization`, `create_payout`, `get_payout_batch` and `verify_webhook` (fails closed). Capture and payout use deterministic `PayPal-Request-Id`s, and the payout's `sender_batch_id` is `proofpay-{job_id}`, so a retry can't pay twice.
   - `app/settlement.py`: `settle()` does the next missing step (capture, create the payout, or poll the batch) and `mark_paid()` is shared with the webhook. It is hooked into `/submit`, `/verify` and `POST /approval` (approve), and a settle failure never turns a successful decision into an error. `POST /api/jobs/{id}/settle` is the manual retry (404 unknown, 409 wrong status, a `PAID_OUT` job returns as is). `JobOut.payout` carries the payout amount and status.
   - `POST /api/webhooks/paypal` (`app/api/webhooks.py`): bad signature 400, no `PAYPAL_WEBHOOK_ID` 503, item succeeded marks the job `PAID_OUT`, item failed/unclaimed/returned/blocked marks the payout `FAILED` (job stays `CAPTURED`), a payout event with an unknown batch id returns 404 so PayPal redelivers.
   - Web: `/cleaner/:jobId` shows the auto-release decision through `RELEASED`, `CAPTURED` and `PAID_OUT`, plus a payment panel ("Payment captured, payout on the way", "Paid $10.00 to your PayPal", "Payout failed, needs attention") and a Retry payment button.
   - Hosted check done Nov 9: a Basic job went through the hosted site to `PAID_OUT`, a $10 payout showed on both PayPal sandbox accounts, and `GET /api/jobs/{id}` reported `PAID_OUT` with a `SUCCESS` payout. `PAYPAL_WEBHOOK_ID` and `PAYPAL_CLEANER_EMAIL` are set on Render. The reject and needs-approval paths are still untested on the hosted site.
5. **Admin UI** (approvals, audit log) and the rejection agent, then seed data and README setup.

Known gaps in the shipped cleaner work (decide when the matching step is built):
- `/cleaner` and the photo GET endpoints have no auth, and `/cleaner` lists every waiting job. Add this with the admin UI.
- Photos from an earlier attempt are not cleared on a re-clean. Decide this when the reject path is built.
- Two concurrent submits can both call the vision model (the second fails safely with a 409, at the cost of an extra Gemini call). A row lock or a `VERIFYING` state would fix it.
- Timeouts and connection errors from Gemini are not retried (only 429 and 503 are); the job stays `SUBMITTED` and the cleaner presses retry.

Known gaps in the policy engine work:
- If `decide()` raises, the job stays `VERIFIED` and `POST /verify` answers 409 (it only accepts `SUBMITTED`), so there is no retry path. Add one (let `/verify` re-run the engine on a `VERIFIED` job) if this shows up.
- `JobOut.decision` is the latest `POLICY_DECIDED` row, so after an admin approves or denies it still shows the engine's original outcome. Read `status` for the truth; the cleaner page hides the panel when they disagree.
- The approval endpoint has no auth, and `decided_by` is free text. Add a gate with the admin UI.
- The mandate is one global row with no way to edit it yet (seed data or the admin UI); `monthly_cap` and `approved_subcontractors` are unused columns.
- A rejection can list several reasons, including "required item not visible" ones, because every matching rule reports.
- Photos from a rejected attempt are still attached on a re-clean (see above), and the cleaner job list does not show jobs waiting in `PENDING_APPROVAL`.

Known gaps in the capture and payout work:
- A `FAILED` payout needs a human: the job stays `CAPTURED`, `settle` does nothing for it, and there is no refund or re-payout. The admin UI should surface these.
- Nothing voids the authorization when a job is denied or cancelled, and there is no reauthorization, so jobs older than the 3-day honor period may fail to capture; use a fresh booking.
- One payee (`PAYPAL_CLEANER_EMAIL`), no partial captures, no refunds. `/settle` has no auth, like the other endpoints.
- I did not confirm whether the webhook or the Retry button moved the hosted test job to `PAID_OUT`; check the PayPal dashboard for a 200 on `PAYMENT.PAYOUTS-ITEM.SUCCEEDED`.

Test follow-ups (optional, in priority order):
- Cover the `app/api/paypal.py` misses (lines 71-78 and 149-161, 84% covered), since that code handles money; also `app/paypal/client.py` lines 94, 151-152 and 159-160.
- Frontend tests for `CleanerJob`, `CleanerJobs` and `resize.ts`. The web app has no test runner yet (none for the earlier pages either); Vitest with Testing Library would be the choice.
- Make the `FakeVision` test double subclass the `VisionProvider` protocol, like `FakePayPal` does.

Leftovers that are cheap to do alongside: a void method in the PayPal client (two open sandbox authorizations from testing), a payer-identity check on the authorize route, and the manual Deep/Deluxe/cancel tests. Feature freeze is today (Nov 9), so cut from the scope-cuts list above if the admin UI runs long (the policy engine, capture and payouts are done).

## 7. Open questions

1. ~~Is Gemini Flash OK as the default vision model?~~ Yes: `gemini-3.6-flash` (Nov 4, spike 4).
2. ~~Should the subcontractor's share default to 70%?~~ Dropped Nov 4: no share percentage in the config or the schema. Decide how the payout amount is set on Nov 5.
3. ~~Tier names and prices?~~ Basic Clean $10, Deep Clean $20, Deluxe Clean $30 (service types `basic`, `deep`, `deluxe`).
4. ~~Is MIT fine for the license?~~ Assumed yes; the repo is scaffolded with MIT (Nov 2). Say so if you want a different license.

## Sources

- [PayPal authorization and honor period](https://developer.paypal.com/docs/checkout/advanced/authorization-honor/)
- [PayPal MCP available tools](https://paypal.gitbook.com/agent-toolkit-and-mcp-server/available-tools.md)
- [Payouts setup](https://developer.paypal.com/payouts/use-payouts/set-up.md)
- [Payouts webhook reference](https://docs.paypal.ai/send/webhook-reference)
