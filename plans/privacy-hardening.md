# Privacy Hardening Plan

Follow-up to PR #8 (`feature/cleaner-last-used-signup-dedupe`: same-email sign-up reuses the cleaner, and cleaners expire 24 hours after `last_used_at`). Start a **new branch from `main` after PR #8 is merged**, for example `feature/privacy-hardening`. If #8 is not merged yet, branch from it instead, because items 2 and 3 depend on its sign-up code.

**Goal:** a visitor using the live demo must not see other visitors' cleaners, customer details or jobs, and must not be able to act as another visitor's cleaner.

**Who it's for:** the demo is public and has no accounts. The only identity today is a cleaner id kept in `localStorage` (`proofpay.cleanerId`), and the API endpoints have no auth. This plan adds just enough to close the real data leaks without building a login system.

## Findings (what leaks today)

| # | Problem | Where | Severity |
|---|---|---|---|
| 1 | `GET /api/jobs` with no `cleaner_id` returns **every** job (limit up to 200) to anyone. `JobOut` includes `customer_name`, `customer_email`, `address`, and the job ids that unlock the photo and detail endpoints. | `app/api/jobs.py` `list_jobs`, `app/schemas.py` `JobOut` | High |
| 2 | Since PR #8, anyone who types a cleaner's PayPal email signs in as that cleaner and sees their jobs, customer details and photos. No proof of ownership. | `app/api/cleaners.py` `sign_up`, `app/cleaners.py` `sign_up_or_resume` | High once the app is public |
| 3 | The roster (`GET /api/cleaners`) lists every active visitor's cleaner name and sign-up time to every customer. | `app/api/cleaners.py` `roster` | Medium |
| 4 | Approve, deny, settle, photo upload and submit need no auth: knowing a job UUID is enough. | `app/api/approvals.py`, `app/api/cleaner.py` | Accepted for the demo (stated in code); item 1 stops the ids being listed |

The PayPal email is never returned by any endpoint (`CleanerOut`); keep it that way.

## Recommended order

1. **Item 1** (small, closes the real leak). Ship on its own PR.
2. **Items 2 and 3** together (both need the per-cleaner token), on a second PR. Skip them if the demo stays private or low-stakes, and document the risk in the README instead.
3. **Item 4** is out of scope. Re-check it after items 1-3.

## Item 1: `GET /api/jobs` must be scoped

**Decision:** require `cleaner_id` on `GET /api/jobs`. The only web caller is `CleanerJobs.tsx`, which always sends it (`listJobs(status, cleanerId)` in `web/src/api.ts`).

Backend:
- In `list_jobs`, make `cleaner_id: uuid.UUID` required (a missing value then returns 422). Keep the `status`, `limit` and `offset` parameters.
- Keep the `touch_cleaner(db, cleaner_id)` call and its commit.
- Check whether anything else lists jobs without a cleaner (`grep -rn "listJobs\|/api/jobs" web/src tests spikes`). If a customer page lists jobs, give it a different safe path (for example look up by job id only) rather than reopening the list.

Tests:
- `GET /api/jobs` without `cleaner_id` returns 422.
- With a `cleaner_id`, it returns only that cleaner's jobs and none from another cleaner.
- Update `tests/test_cleaners.py::test_jobs_list_filters_by_cleaner_and_exposes_service_date` and any web MSW handler in `web/src/test/handlers.ts` that assumed an unscoped list.

Acceptance: opening `/api/jobs?limit=200` on the live API returns 422, not data.

## Item 2: per-cleaner token (proof of ownership)

**Decision:** a secret token returned at sign-up and sent on every cleaner-side request. Do not use a PIN: a token needs no extra typing and cannot be guessed.

Design:
- `cleaners` gets `token_hash` (text, nullable for the default cleaner and old rows). New migration after `d7b2e5a8c1f4`.
- Sign-up creates the token with `secrets.token_urlsafe(32)`, stores only its SHA-256 hash, and returns the plain token **once**, in a new response field (for example `CleanerSession` = `CleanerOut` + `token`). Never log it, and never put it in the audit log.
- **Same-email sign-in is the awkward case.** Resuming by email can no longer hand out the account for free. Pick one and write the choice down before coding:
  - A. Resuming by email rotates the token and issues a new one. This still lets anyone with the email take over, so it only helps once something else proves ownership. **Not enough on its own.**
  - B. Resuming works only from a browser that already holds the token (`localStorage`). A second device or a cleared browser must create a new cleaner, which brings back the duplicate-email case. Allow duplicates by email again only in that case, and show the old one as expired in the UI.
  - C. Keep email-only sign-in and document it as a known demo limitation (the PayPal email is a sandbox address and no real money moves).
  - **Recommendation: C for a sandbox demo, B if the demo will be shown to strangers.** Do not ship A.
- Cleaner-side endpoints (`app/api/cleaner.py`, `GET /api/jobs?cleaner_id=`, `GET /api/cleaners/{id}`, `POST /api/jobs/{id}/approval` if it should stay admin-only) read `Authorization: Bearer <token>`, hash it and compare with `secrets.compare_digest`. Return 404 (not 403) on a mismatch so job ids can't be probed. The default cleaner has no token, so the "Continue as <default cleaner>" path must stay open or get a fixed demo token.
- A job's cleaner-side routes (`/api/jobs/{job_id}/photos`, `submit`, `verify`, `settle`) check that the token belongs to `job.cleaner_id`.
- Web: `web/src/lib/cleaner-session.ts` stores `{id, token}` (migrate the old id-only value by treating it as logged out). `web/src/api.ts` adds the header when a token exists. "Switch cleaner" clears both.

Tests: wrong or missing token returns 404 on each cleaner route; right token works; another cleaner's token on this job returns 404; the token hash, not the token, is stored; the response never contains `paypal_email`.

## Item 3: roster visibility

**Decision:** the booking picker shows the default cleaner plus the viewer's own cleaner, not other visitors' cleaners.

- `GET /api/cleaners` accepts the token optionally. With no token it returns only the default cleaner. With a valid token it returns the default cleaner plus that cleaner.
- `list_cleaners` stays the same; filter in the endpoint so availability logic is untouched.
- Cost to accept: a cleaner created on another device or browser isn't selectable from this one. Say so in the sign-up copy.
- The customer is a different person from the cleaner, so a customer booking from a fresh browser sees only the default cleaner. If the demo needs customers to book sign-up cleaners, keep the roster open and rely on item 1 plus name-only exposure (names are the only data it shows). **Decide this with the owner before coding item 3.**

Tests: no token returns only the default cleaner; a valid token adds that cleaner; another visitor's cleaner never appears.

## Out of scope

- Real authentication, passwords or OAuth.
- Locking down approve, deny and settle (item 4). They stay open in the demo.
- Rate limiting sign-up or sign-in. Worth a separate issue if the app goes public.

## Pick up here

1. Confirm PR #8 is merged and update `main`.
2. Create the branch and implement **item 1** first, with tests. Run `.venv/bin/python -m pytest` (needs `docker compose up -d --wait` for the test Postgres on port 5433) and `cd web && npx vitest run`.
3. Ask the owner the two open questions before items 2 and 3: option A, B or C for same-email sign-in, and whether customers should see other visitors' cleaners in the booking picker.
4. Update the README "Cleaners" paragraph and add a one-line known-limitations note for anything left open.
