# Admin UI Plan

Step 5 of `plans/plan.md`. Branch: `feature/admin-ui`. Kept deliberately small for the demo (the Nov 9 freeze has passed, so this is the smallest version that closes the gaps from steps 3 and 4).

**Status:** draft written Nov 9. The decisions below are proposals; confirm them before step 1.

## What it does

Every job can now reach `PAID_OUT`, but the people running the business have no screen. Approving a `PENDING_APPROVAL` job takes a raw API call, the audit log can't be seen, a failed payout is invisible, and every endpoint is open. This step adds an admin area that fixes those four things.

| Piece | Why |
|---|---|
| Approvals list | `POST /approval` exists, but nothing lists pending jobs or lets an admin approve or deny. |
| Audit log view | The hash chain exists (`verify_chain()`), but nobody can see it. It is the proof the whole product rests on. |
| Failed payouts | A `FAILED` payout leaves the job `CAPTURED` and the payment panel says "needs attention", but only the cleaner sees that. |
| Auth | The approval and settle endpoints, and the audit log, must not be public. |

## Decisions to keep it simple (proposed)

- **One shared admin token.** An `ADMIN_TOKEN` setting on Render, sent as `Authorization: Bearer ...`. The web app asks for it once on `/admin`, keeps it in `sessionStorage` and sends it with admin calls. No users, sessions or roles. `decided_by` on approvals stays free text but is pre-filled.
- **Protect only what is admin-only:** `POST /approval`, the new admin read endpoints, and `POST /settle` stays open for the cleaner's retry button. The cleaner routes and photo endpoints stay open for now (still a known gap, listed under "Out of scope").
- **Read-only audit view.** A table of the latest rows with a "Verify chain" button that calls `verify_chain()` and reports OK or the first bad row. No filtering beyond a job id.
- **Failed payouts are a filter, not a new flow.** The admin list shows jobs `CAPTURED` with a `FAILED` payout in an "Needs attention" section. No refund or re-payout button (out of scope).
- **Rejection agent is the first cut.** If time is short, drop it and keep the other four pieces.

## How it's built

### 1. Auth gate (backend)

`ADMIN_TOKEN` in `app/config.py` and `.env.example`. A `require_admin` dependency compares the bearer token with `secrets.compare_digest`; 401 if wrong or missing, 503 if `ADMIN_TOKEN` is unset (fail closed, like the webhook id). Apply it to `POST /approval`. Tests: no token, wrong token, right token, unset setting.

### 2. Admin read endpoints (backend)

All behind `require_admin`:

- `GET /api/admin/jobs?bucket=approvals|attention|all` returns `JobOut` rows: `approvals` = `PENDING_APPROVAL`, `attention` = `CAPTURED` with a `FAILED` payout (or `RELEASED` that never captured), `all` = everything recent. Eager-load as the existing list endpoint does.
- `GET /api/admin/audit?job_id=&limit=` returns rows newest first (id, job id, event, actor, payload, hash).
- `GET /api/admin/audit/verify` returns `{ok: true}` or `{ok: false, first_bad_id}`.

### 3. Admin pages (web)

- `/admin`: token prompt, then tabs for **Approvals**, **Needs attention** and **Audit log**.
- Approvals: each pending job shows address, amount, the engine's reasons (`decision`) and the vision results, with Approve and Deny buttons (deny asks for a reason). On success the row disappears.
- Needs attention: jobs with a failed payout or an uncaptured release, with the status and a Retry button that calls `/settle`.
- Audit log: table plus "Verify chain".
- `JobOut.decision` still shows the original outcome after an admin acts, so the admin pages read `status`, not `decision`, for the truth.
- `npx tsc --noEmit` must pass.

### 4. Cleaner-side gaps (small)

- `/cleaner` also lists jobs waiting in `PENDING_APPROVAL`, with the "Waiting for approval" label, so a cleaner can see why a job vanished from the list.
- Decide the re-clean photos question: clear the earlier attempt's photos on `REJECTED → SUBMITTED`, or keep them and show "previous attempt". Proposal: keep them, since clearing needs an audit story.

### 5. Seed data and README

A script (`scripts/seed.py` or a CLI in `app`) that inserts one mandate row and three demo jobs (one auto-release, one needs approval, one rejected) so the demo starts populated. README gets the setup steps, including `ADMIN_TOKEN` and the webhook registration.

### 6. Rejection agent (optional, last)

On a `reject` outcome, a second Gemini call drafts a re-clean request from the failed items, stored on the verification or as an audit payload and shown on the cleaner page. Skipped automatically if the call fails. The LLM only writes text; it never changes a job's status.

## Tests

- Auth: each protected endpoint with no, wrong and right token; unset setting is 503.
- Admin endpoints: buckets return the right jobs; audit order and `limit`; verify reports a tampered row (use the existing tamper helper if one exists).
- Approval from the admin UI path still produces `CAPTURED` (settle runs after approve).
- Seed script is idempotent (running twice doesn't double the jobs).
- Prove the auth test can fail by removing the dependency, then restore it.
- Manual hosted check: approve a `needs_approval` job and see it reach `PAID_OUT`; deny one; view and verify the audit chain; confirm a request without the token gets 401. This also covers the reject and needs-approval paths, which are untested on the hosted site.

## Order of work

1. Auth gate and tests.
2. Admin read endpoints and tests.
3. Admin pages (approvals, needs attention, audit log).
4. Cleaner list and re-clean photo decision.
5. Seed data, README, hosted check.
6. Rejection agent, only if time allows.

Each step is one commit, reviewed before the next.

## Out of scope here

Real users or roles, auth on the cleaner and photo endpoints, mandate editing, refunds and re-payouts, voiding holds on deny or cancel, reauthorization, the monthly cap, per-subcontractor payees, and dispute drafting.
