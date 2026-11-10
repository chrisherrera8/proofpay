# Capture, Payouts and Webhooks Plan

Step 4 of `plans/plan.md`. Branch: `feature/capture-payouts`. Kept deliberately small for the demo.

**Decisions (Nov 9):** the cleaner gets **100%** of the job amount (no share, no constant, no rounding); capture runs **automatically** after `RELEASED`, with `/settle` as the retry; a failed payout leaves the job `CAPTURED` and is surfaced in the admin UI later. Nothing is left open, so a new session can start at step 1 of "Order of work".

## What it does

A `RELEASED` job means the work is proven and allowed to be paid, but no money has moved: PayPal only holds the customer's funds (the authorization from booking). This step moves the money:

| Step | PayPal call | Job moves to |
|---|---|---|
| Capture | `POST /v2/payments/authorizations/{id}/capture` | `RELEASED → CAPTURED` (the customer is charged) |
| Payout | `POST /v1/payments/payouts` to the cleaner's PayPal email | stays `CAPTURED` while PayPal processes it |
| Confirmation | webhook `PAYMENT.PAYOUTS-ITEM.SUCCEEDED` | `CAPTURED → PAID_OUT` |

Both request shapes are already proven in `spikes/capture_spike.py` and `spikes/paypal_spike.py`, and the webhook events and their signatures were confirmed in spike 2 (`spikes/webhook_events.jsonl`). The LLM never touches this step.

## Decisions to keep it simple

- **Automatic, with a retry button.** Whenever a job reaches `RELEASED` (auto-release in `/submit` or `/verify`, or an approval), the same request goes on to capture and then create the payout. If PayPal fails, the job stays where it is and `POST /api/jobs/{id}/settle` does whatever the next step is. This is the same pattern as `/verify`, and it avoids repeating the "stuck, no retry" gap from the policy engine.
- **One cleaner.** The payee is a single setting, `PAYPAL_CLEANER_EMAIL` (already in `.env.example`). Jobs have no subcontractor field yet.
- **Payout amount = the job amount** (100% to the cleaner, for now). No share setting, constant or rounding code; the payout is `job.amount`.
- **`PAID_OUT` comes from the webhook, with a polling fallback.** PayPal creates payouts asynchronously (the item succeeded about 9s after creation in the spike). `/settle` on a `CAPTURED` job fetches the batch from PayPal and marks it paid if the item succeeded, so the demo still works if the webhook isn't reachable.
- **Money calls are idempotent.** Capture and the payout both send a deterministic `PayPal-Request-Id` (the existing `request_id()` helper), and the payout's `sender_batch_id` is `proofpay-{job_id}`, which PayPal rejects if reused. A retry can't pay twice.
- **No lock held during PayPal calls**, as in `authorize`: call PayPal first, then `transition()` and commit.

## How it's built

### 1. PayPal client (`app/paypal/client.py`) (done Nov 9)

Three new methods, same style as `authorize_order`, with `PayPalError` on failure and parsed dataclasses back:

- `capture_authorization(authorization_id, amount, currency) -> Capture(id, status, debug_id)`. `final_capture: true`. Only `COMPLETED` counts as success; `PENDING` or `DECLINED` are returned, not raised, and the route decides.
- `create_payout(job_id, receiver_email, amount, currency) -> PayoutBatch(batch_id, item_id?, status)`.
- `get_payout_batch(batch_id) -> PayoutBatch` with the item's status, for the polling fallback.
- `verify_webhook(headers, body) -> bool` calls PayPal's `/v1/notifications/verify-webhook-signature` with `PAYPAL_WEBHOOK_ID`. Fails closed (returns False) on any error.

`FakePayPal` in the tests gets the same methods so no test touches the network.

### 2. `settle(db, job, paypal)` in `app/settlement.py` (done Nov 9, review fixes included)

One function that does the next missing step for a job and returns:

1. `RELEASED`: capture against `payments.authorization_id` for the job amount. On `COMPLETED`: save `capture_id`, set the payment status, `transition(RELEASED → CAPTURED)` with actor `paypal`, event `CAPTURE_COMPLETED` and the debug id. On any other status or a `PayPalError`: audit row `CAPTURE_ERROR`, job stays `RELEASED`.
2. `CAPTURED` with no payout row: create the payout and add a `Payout(status="PENDING", batch_id, item_id, amount)` row plus a `PAYOUT_CREATED` audit row. The job stays `CAPTURED`. A failed call writes `PAYOUT_ERROR` and leaves no row.
3. `CAPTURED` with a pending payout: fetch the batch; if the item succeeded, mark it paid (shared helper with the webhook).
4. Any other status: nothing to do.

`mark_paid(db, payout)` is the shared helper: `Payout.status = "SUCCESS"`, `transition(CAPTURED → PAID_OUT)` with actor `paypal`, event `PAYOUT_SUCCEEDED`.

### 3. Hook it in (done Nov 9)

- After the commit that leaves a job `RELEASED` in `/submit` and `/verify` (`app/api/cleaner.py`) and in `POST /approval` (approve only; `app/api/approvals.py`), call `settle()`. A settle failure must not turn a successful decision into an error response: the response still returns the job, in whatever status it reached. `settle` re-raises DB failures (after logging the PayPal ids), so each hook wraps the call in `try/except Exception` that does `log.exception(...)` and `db.rollback()`. The manual `/settle` endpoint does not swallow, so whoever clicked sees the failure.
- `POST /api/jobs/{id}/settle` runs the same function by hand: 404 for an unknown job, 409 if the job isn't `RELEASED`, `CAPTURED` or `PAID_OUT`. A `PAID_OUT` job is returned as is (200, no PayPal calls), so a double click or stale retry button isn't an error.
- `JobOut` gains `payout` (`amount`, `status`) from the job's one payout row (`payouts.job_id` is unique), eager-loaded like `verification`, so the list endpoint stays free of per-job queries.

### 4. Webhook endpoint (to do)

`POST /api/webhooks/paypal` (`app/api/webhooks.py`):

1. Read the raw body, verify the signature with the client. Invalid: 400. `PAYPAL_WEBHOOK_ID` not set: 503.
2. `PAYMENT.PAYOUTS-ITEM.SUCCEEDED`: find the payout by `payout_batch_id` (the batch id is on every payout event) and call `mark_paid()`. Already `PAID_OUT`: return 200 and do nothing (PayPal retries deliveries).
3. `PAYMENT.PAYOUTS-ITEM.FAILED`, `UNCLAIMED`, `RETURNED`, `BLOCKED`: set the payout row `FAILED` and write a `PAYOUT_FAILED` audit row. The job stays `CAPTURED` (the customer was charged and the cleaner was not paid, so a human has to look; the admin UI shows it later).
4. Everything else (capture, authorization and order events): 200, ignored. Always answer 200 for events we understand or ignore so PayPal doesn't keep retrying.

Registering the webhook is manual: add the Render API URL (`/api/webhooks/paypal`) in the PayPal developer dashboard, subscribe to the payout item events, and set `PAYPAL_WEBHOOK_ID` on Render. Add `paypal_webhook_id` and `paypal_cleaner_email` to `app/config.py`.

### 5. Web (small) (to do)

On `/cleaner/:jobId`, show payment progress under the decision panel when the job is `CAPTURED` or `PAID_OUT`: "Payment captured, payout on the way" and "Paid $10.00 to your PayPal". A "Retry payment" button when the job is `RELEASED`, or `CAPTURED` with a payout that is not `FAILED`, calls `/settle`. For a `FAILED` payout `settle` does nothing (it only logs), so hide the button there and show "Payout failed, needs attention" instead. This needs the job API response to expose the payout's status (`JobOut.payout` is done in step 3; add it to the web `Job` type here). `npx tsc --noEmit` must pass.

**Known gap from step 3:** auto-release now ends `CAPTURED` in the same request, but `DecisionPanel` in `web/src/pages/CleanerJob.tsx` only shows the `auto_release` decision while the job is `RELEASED`. Until this step lands, a cleaner whose job passes sees no result panel. Fix it here: show the decision panel for `auto_release` while the job is `RELEASED`, `CAPTURED` or `PAID_OUT`, and also after an admin approval (`needs_approval` decision, job now past `PENDING_APPROVAL`) show the payment progress instead of nothing.

## Tests

- `tests/test_paypal_client.py` additions: request shapes (path, body, `final_capture`, request id, `sender_batch_id`), parsing, and error handling for the new methods; `verify_webhook` true, false and error.
- `tests/test_settlement.py` (with `FakePayPal`): happy path `RELEASED → CAPTURED` with a payout row and `verify_chain(db) is None`; capture failure leaves `RELEASED` with a `CAPTURE_ERROR` row and a retry succeeds; capture returning `PENDING` or `DECLINED` doesn't advance; payout failure leaves `CAPTURED` with no payout row and a retry succeeds; settling twice never pays twice; the payout amount equals the job amount ($10, $20 and $30); the polling fallback marks the job paid.
- `tests/test_cleaner_api.py` additions: an auto-released job ends `CAPTURED`; a pending job approved through the endpoint ends `CAPTURED`; settle failure still returns 200 with the job in `RELEASED`; `/settle` retry; 404 and 409; `payout` in the detail and list responses.
- `tests/test_webhooks.py`: item succeeded marks the job `PAID_OUT`; a replayed delivery is a no-op 200; item failed marks the payout `FAILED` and leaves the job `CAPTURED`; a bad signature is 400; unknown event types are 200; no webhook id is 503.
- Existing tests that end at `RELEASED` after submit will now see `CAPTURED` (the fake PayPal captures). Same cost as the policy engine step.
- Prove the key tests can fail by breaking the code (for example, skip the idempotent `sender_batch_id` or the signature check), then restore it.
- Manual sandbox check at the end: Basic job through the hosted site to `PAID_OUT` ($10 to the cleaner), with a webhook delivery and the cleaner account balance.

## Order of work

1. ~~Client methods and `FakePayPal`, with client tests.~~ (done Nov 9)
2. ~~`settle()`, `mark_paid()` and config, with DB tests.~~ (done Nov 9, review fixes included)
3. ~~Hook into `/submit`, `/verify` and `/approval`, add `/settle` and `JobOut.payout`, fix the old `RELEASED` assertions.~~ (done Nov 9)
4. **Next:** webhook endpoint and tests.
5. Small web change, then the manual sandbox run.

Each step is one commit, reviewed before the next.

## Decisions made

1. **Payout amount:** 100% of the job amount to the cleaner. A share or fee can be added later in `settle()` if it's ever wanted.
2. **Capture:** automatic after `RELEASED`, with `POST /api/jobs/{id}/settle` as the retry.
3. **Failed payout:** the job stays `CAPTURED` and the payout row is `FAILED`; the admin UI step surfaces it. No refund.

## Out of scope here

Reauthorization of old authorizations (the Nov 5 test jobs are past the 3-day honor period and may fail to capture; use a fresh booking), voiding the hold when a job is denied or cancelled, refunds, partial captures, per-subcontractor payees, the monthly cap, auth, the admin UI (approvals list, audit log view) and the rejection agent.
