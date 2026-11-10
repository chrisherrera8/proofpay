# Cleaner Sign-up and Booking Plan

Step 5 of `plans/plan.md`. Branch: `feature/cleaner-signup`.

**Status (Nov 10):** backend done (steps 1-4 below, 4 commits, 397 tests pass, nothing pushed or merged). **Web, seed/README and the hosted check are left.** The booking page on this branch is broken against the new API until the web step lands, so do not merge to `main` before then. Start with "Pick up here" at the bottom.

Commits on `feature/cleaner-signup`: `f4ea70f` cleaners table and API, `1b7968c` booking with a cleaner, `631927e` pay the booked cleaner, `af5bb01` 24-hour purge.

**Timing:** the deadline is Nov 12, 12:00pm PST and the Nov 9 freeze has passed. This touches the booking flow and the payout payee, so it is not a small change. "Cut line" at the bottom says what to drop first.

## What it does

Today the cleaner is one fixed PayPal email (`PAYPAL_CLEANER_EMAIL`) and any job can be opened by anyone at `/cleaner`. This step makes cleaners real, short-lived demo users:

1. A cleaner signs up (name, PayPal email) and lands on their own job list.
2. A customer booking a job picks a date, then picks one of the cleaners free that day.
3. A cleaner is booked for the whole day: one job per cleaner per date, no time slots.
4. The payout goes to the booked cleaner's PayPal email, not the global one.
5. Cleaner data is deleted 24 hours after sign-up, because this is a demo.

## Decisions

- **No passwords.** Sign-up returns a cleaner id; the site keeps it in `localStorage` and `/cleaner` lists only that cleaner's jobs. This is a convenience filter, not security (same open-endpoint gap as today, still listed under "Out of scope").
- **Whole-day booking.** `jobs` gets `service_date` (a `Date`) and `cleaner_id`. A cleaner is unavailable on a date if they have any job that day except an abandoned one (see next point). `scheduled_at` stays as is for display.
- **Abandoned bookings free the cleaner.** A job still `BOOKED` (never authorized) after 30 minutes doesn't count as a claim, so someone who closes the PayPal popup doesn't lock a cleaner for the day. The check runs in code under a row lock on the cleaner (`SELECT ... FOR UPDATE`), so two simultaneous bookings can't both win; the loser gets a 409 "cleaner just got booked, pick another".
- **Payee per cleaner.** `settle()` pays `job.cleaner.paypal_email`; `PAYPAL_CLEANER_EMAIL` stays as the fallback for jobs with no cleaner (old rows, and jobs whose cleaner was purged).
- **Delete means scrub, not drop.** The audit log is append-only (a trigger blocks `DELETE`) and hash-chained, and it has a foreign key to `jobs`. So the purge deletes the cleaner row and their photos, and sets `jobs.cleaner_id` to NULL; it does not delete jobs or audit rows. For that to be honest, no cleaner name or email may go into audit payloads (today actor is the string `cleaner`, and payloads hold photo ids and byte counts only; add a test that keeps it that way).
- **Purge is lazy plus optional ping.** Render's free tier has no cron. Every cleaner query filters `created_at > now() - 24h`, so expired cleaners vanish immediately even if nothing has deleted them yet. The actual delete runs at the start of `GET /api/cleaners` (throttled to once a minute per process) and from `POST /api/maintenance/purge` (needs a `MAINTENANCE_TOKEN`) for an external pinger such as a GitHub Actions schedule.
- **One default cleaner, never expires.** It is built from the existing `PAYPAL_CLEANER_EMAIL` plus a new `DEFAULT_CLEANER_NAME` setting (default "Sparkle Crew"), stored as a `cleaners` row with `is_seed = true`. It is created idempotently at app startup (and by the seed script) so the booking page is never empty for judges. Real sign-ups expire after 24 hours. If `PAYPAL_CLEANER_EMAIL` is unset there is no default cleaner (fail closed, like the webhook id).

## How it's built

### 1. Cleaner model and migration (backend) — DONE

New `cleaners` table: `id` (uuid), `name`, `paypal_email` (NOT NULL), `is_seed` (default false), `created_at`. New columns on `jobs`: `cleaner_id` (nullable FK, `ON DELETE SET NULL`), `service_date` (nullable `Date`, backfilled from `scheduled_at` in UTC). One Alembic migration. Tests: migration up and down, FK null-out.

### 2. Cleaner API — DONE

- `POST /api/cleaners` (`name`, `paypal_email`, validated like `customer_email`) returns the cleaner.
- `GET /api/cleaners?date=YYYY-MM-DD` returns unexpired cleaners with `available: bool` for that date (or only the free ones with `?available=true`). Runs the lazy purge first.
- `GET /api/cleaners/{id}` for the cleaner's own page (404 once expired).
- `GET /api/jobs?cleaner_id=` filter, used by `/cleaner`.

### 3. Booking uses a cleaner — DONE

`JobCreate` gains `cleaner_id`. `create_job` locks the cleaner row, rejects (409) if the date is taken or the cleaner is expired, stores `cleaner_id` and `service_date`, and writes `cleaner_id` (an id, no name or email) into the `JOB_BOOKED` audit payload. Tests: double booking, abandoned hold released after 30 minutes, expired cleaner, same cleaner on two different dates, concurrent bookings (two threads, one wins).

### 4. Payout goes to the booked cleaner — DONE

`settle()` picks the payee from the job's cleaner, falling back to `PAYPAL_CLEANER_EMAIL`. If a cleaner was purged before payout, the fallback applies and an audit row notes it. Tests: payee choice, fallback, purge mid-flow.

### 5. Purge — DONE

`purge_expired(db)` deletes photos for jobs of expired non-seed cleaners, nulls `cleaner_id`, deletes the cleaners, and writes one `CLEANERS_PURGED` audit row (count only). `POST /api/maintenance/purge` behind a bearer token (503 if unset, like the webhook id). Tests: only expired non-seed rows go, jobs and audit rows survive, `verify_chain()` still passes, idempotent.

### 6. Web (on the new components) — NOT STARTED

- `/cleaner/signup`: name and PayPal email, with a note that the email should be a PayPal sandbox account and that data is deleted after 24 hours. On success store the id and go to `/cleaner`.
- `/cleaner`: shows the signed-in cleaner's name and jobs only; no id in storage sends them to sign-up; a 404 from an expired cleaner clears storage and sends them to sign-up.
- `/book`: date first, then a "Choose your cleaner" list (name, free or booked) loaded for that date, then the existing form. The date input becomes date-only; the time-of-day field goes away.
- `Booked` shows the cleaner's name and date.
- A "demo data resets after 24 hours" line in the footer.
- `npx tsc --noEmit` and the Playwright screenshots (390px and 1280px) per `web/design.md`.

### 7. README and hosted check — NOT STARTED

The default cleaner is already created at startup (and by the roster endpoint) from `PAYPAL_CLEANER_EMAIL` and `DEFAULT_CLEANER_NAME`, so **no seed script is needed**. README gets the setup steps (`DEFAULT_CLEANER_NAME`, `MAINTENANCE_TOKEN`, the optional pinger, the webhook registration).

## Order of work

1. ~~Model, migration, cleaner API and tests~~ (`f4ea70f`).
2. ~~Booking with a cleaner, availability and tests~~ (`1b7968c`).
3. ~~Payee change and tests~~ (`631927e`).
4. ~~Purge and tests~~ (`af5bb01`).
5. Web pages (section 6 above). **Next.**
6. README and hosted check: sign up, book that cleaner, upload photos, reach `PAID_OUT` with the payout on the cleaner's sandbox account, then confirm the purge removes them.

Each step is one commit, reviewed before the next.

## Cut line (Nov 12 noon)

If time slips, drop in this order: the external pinger and `MAINTENANCE_TOKEN` (the lazy purge alone is enough), the abandoned-booking release, the concurrency test, the `/cleaner/:jobId` access check. Do not drop: the date-taken check, the per-cleaner payee, and the audit-has-no-PII test, since those are what the demo shows.

## Decided (Nov 10)

- PayPal email is required at sign-up.
- Exactly one permanent default cleaner, from `PAYPAL_CLEANER_EMAIL` (plus a name setting). No other seeded cleaners.
- Delete means scrub: cleaner row and photos go, jobs and audit rows stay, so the hash chain is never broken.

## Open questions

None open.

## Out of scope

Time slots and cleaner working hours, cleaner login or passwords, auth on the cleaner and photo endpoints, the rejection agent, refunds and re-payouts, voiding holds on cancel, reauthorization.

Note: a `needs_approval` job still needs a raw `POST /approval` call. Demo with auto-release jobs (Basic at $10 is under the $25 ceiling).

## What was built, and where it differs from the plan above

- **Booking body:** `POST /api/jobs` takes `cleaner_id` and `service_date` (both required) and **no longer accepts `scheduled_at`**. The server stores `scheduled_at` as noon UTC on that date (display only). Past dates are rejected with one day of slack. A taken day is 409; an unknown or expired cleaner is 404.
- **Extra guard:** `POST .../paypal/order` and `.../paypal/authorize` return 409 if another job took the cleaner's day while this one sat unpaid (checked before any PayPal call).
- **Audit log holds no cleaner PII.** `JOB_BOOKED` stores `cleaner_id` and `service_date`. `PAYOUT_CREATED` **no longer stores `receiver`**; it stores `payee` (`cleaner` or `default`) and `cleaner_id`. Tests check no name or email reaches the log.
- **Payee:** `resolve_payee()` in `app/cleaners.py`. If the cleaner was purged between capture and payout, the default account is paid.
- **Purge:** `purge_expired()` (cleaner rows, then photos of their jobs; jobs and audit stay; one count-only `CLEANERS_PURGED` row). Runs from `GET /api/cleaners` at most once a minute per process, and from `POST /api/maintenance/purge` (bearer `MAINTENANCE_TOKEN`; 503 if unset, 401 if wrong).
- **Default cleaner:** one `is_seed` row (database-enforced unique), created from `PAYPAL_CLEANER_EMAIL` and `DEFAULT_CLEANER_NAME` (default "Sparkle Crew", constant in `app/config.py`) at startup and by the roster call. Your edit made the insert race-safe; it landed in commit `631927e`.
- **`.env.example`** now lists `DEFAULT_CLEANER_NAME` and `MAINTENANCE_TOKEN`. `render.yaml` was not changed (it never listed the dashboard-only variables).
- **Tests:** `tests/test_cleaners.py`, `test_booking_cleaner.py` (includes a two-thread race test that fails without the row lock), `test_payee.py`, `test_purge.py`; `test_booking_api.py` was updated to the new body. The `conftest.py` TABLES list includes `cleaners`, and `PAYPAL_CLEANER_EMAIL` is blanked for tests.

## API the web step uses

| Call | Notes |
|---|---|
| `POST /api/cleaners` `{name, paypal_email}` | 201 returns `{id, name, is_seed, created_at}`; the email is never returned. 422 on a bad email. |
| `GET /api/cleaners?date=YYYY-MM-DD[&available=true]` | `[{id, name, is_seed, created_at, available}]`, default cleaner first, then newest. `date` is required. |
| `GET /api/cleaners/{id}` | 404 once expired or purged. |
| `POST /api/jobs` | body: `customer_name, customer_email, address, service_type, cleaner_id, service_date, amount`. |
| `GET /api/jobs?cleaner_id=` | `JobOut` now has `cleaner_id` and `service_date`. **It has no cleaner name**; see the open decision below. |

## Pick up here (new session)

Setup: `docker compose up -d --wait`, then `uv run pytest -q` should show 397 passed (it passed 11 of 12 runs; one failure was seen once and never reproduced, test unknown). The web app is in `web/`; read `web/CLAUDE.md` and `web/design.md` first, and follow the Playwright screenshot rule (390px and 1280px, no console errors) from `plans/ui-revamp.md`. The `.mcp.json` servers may need approval on first start. Use `npx tsc --noEmit` and `npm run build`.

**Next: web step (section 6).** Concretely:

1. `web/src/api.ts`: add `Cleaner` types and `signUp`, `listCleaners(date, availableOnly)`, `getCleaner`; change `createJob` to send `cleaner_id` and `service_date` (drop `scheduled_at`); add `cleaner_id` and `service_date` to `Job`; `listJobs` gets a `cleaner_id` filter.
2. `/cleaner/signup` page: name and PayPal email (required), a note that the email should be a PayPal **sandbox** account and that data is deleted after 24 hours. On success store the cleaner id in `localStorage` (wrap in try/catch) and go to `/cleaner`.
3. `/cleaner`: no stored id sends to sign-up; a 404 from `getCleaner` clears storage and sends to sign-up; otherwise show the cleaner's name and only their jobs (`cleaner_id` filter). Decide whether the default cleaner needs a way in (it has no sign-up: probably a "Continue as Sparkle Crew" link, or list all jobs for it).
4. `/book`: date first, then "Choose your cleaner" from `listCleaners(date)` (booked ones disabled), then the existing form. Remove the time-of-day field. Show the 409 message ("already booked") and send the customer back to the picker.
5. `Booked`: show the cleaner and date. **Open decision:** `JobOut` carries no cleaner name. Either add `cleaner_name` to `JobOut` through `Job.cleaner` (eager-load it in `JOB_LOAD_OPTIONS`; it goes null after a purge) or fetch `getCleaner(cleaner_id)` and handle the 404. Adding it to `JobOut` is simpler.
6. Footer line: "Demo data resets after 24 hours." Route entries in `web/src/main.tsx`.

**Then (section 7):** README setup steps; set `DEFAULT_CLEANER_NAME` (optional) and `MAINTENANCE_TOKEN` (optional) on Render; the migration runs on start. Hosted check: sign up, book that cleaner, upload photos, reach `PAID_OUT` with the payout in the cleaner's sandbox account, then call the purge endpoint (or wait 24 hours) and confirm the cleaner and photos are gone while the job and `verify_chain()` stay intact. Also try booking the same cleaner and day twice (expect the 409 message) and the default cleaner path.

**Known gaps to accept for the demo:** `/cleaner` access is a `localStorage` filter, not security (the endpoints stay open); a `needs_approval` job still needs a raw `POST /approval` call, so demo with Basic jobs ($10, under the $25 auto-release ceiling); a cleaner who expires mid-job strands that job's photos upload and payout goes to the default account.
