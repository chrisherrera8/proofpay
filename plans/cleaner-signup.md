# Cleaner Sign-up and Booking Plan

Step 5 of `plans/plan.md`. Branch: `feature/cleaner-signup`.

**Status:** draft written Nov 10; the three open questions were answered the same day (see "Decided"). Ready for step 1.

**Timing:** the deadline is Nov 12, 12:00pm PST and the Nov 9 freeze has passed. This touches the booking flow and the payout payee, so it is not a small change. "Cut line" at the bottom says what to drop first.

## What it does

Today the cleaner is one fixed PayPal email (`PAYPAL_CLEANER_EMAIL`) and any job can be opened by anyone at `/cleaner`. This step makes cleaners real, short-lived demo users:

1. A cleaner signs up (name, PayPal email) and lands on their own job list.
2. A customer booking a job picks a date, then picks one of the cleaners free that day.
3. A cleaner is booked for the whole day: one job per cleaner per date, no time slots.
4. The payout goes to the booked cleaner's PayPal email, not the global one.
5. Cleaner data is deleted 24 hours after sign-up, because this is a demo.

## Decisions (proposed)

- **No passwords.** Sign-up returns a cleaner id; the site keeps it in `localStorage` and `/cleaner` lists only that cleaner's jobs. This is a convenience filter, not security (same open-endpoint gap as today, still listed under "Out of scope").
- **Whole-day booking.** `jobs` gets `service_date` (a `Date`) and `cleaner_id`. A cleaner is unavailable on a date if they have any job that day except an abandoned one (see next point). `scheduled_at` stays as is for display.
- **Abandoned bookings free the cleaner.** A job still `BOOKED` (never authorized) after 30 minutes doesn't count as a claim, so someone who closes the PayPal popup doesn't lock a cleaner for the day. The check runs in code under a row lock on the cleaner (`SELECT ... FOR UPDATE`), so two simultaneous bookings can't both win; the loser gets a 409 "cleaner just got booked, pick another".
- **Payee per cleaner.** `settle()` pays `job.cleaner.paypal_email`; `PAYPAL_CLEANER_EMAIL` stays as the fallback for jobs with no cleaner (old rows, and jobs whose cleaner was purged).
- **Delete means scrub, not drop.** The audit log is append-only (a trigger blocks `DELETE`) and hash-chained, and it has a foreign key to `jobs`. So the purge deletes the cleaner row and their photos, and sets `jobs.cleaner_id` to NULL; it does not delete jobs or audit rows. For that to be honest, no cleaner name or email may go into audit payloads (today actor is the string `cleaner`, and payloads hold photo ids and byte counts only; add a test that keeps it that way).
- **Purge is lazy plus optional ping.** Render's free tier has no cron. Every cleaner query filters `created_at > now() - 24h`, so expired cleaners vanish immediately even if nothing has deleted them yet. The actual delete runs at the start of `GET /api/cleaners` (throttled to once a minute per process) and from `POST /api/maintenance/purge` (needs a `MAINTENANCE_TOKEN`) for an external pinger such as a GitHub Actions schedule.
- **One default cleaner, never expires.** It is built from the existing `PAYPAL_CLEANER_EMAIL` plus a new `DEFAULT_CLEANER_NAME` setting (default "Sparkle Crew"), stored as a `cleaners` row with `is_seed = true`. It is created idempotently at app startup (and by the seed script) so the booking page is never empty for judges. Real sign-ups expire after 24 hours. If `PAYPAL_CLEANER_EMAIL` is unset there is no default cleaner (fail closed, like the webhook id).

## How it's built

### 1. Cleaner model and migration (backend)

New `cleaners` table: `id` (uuid), `name`, `paypal_email` (NOT NULL), `is_seed` (default false), `created_at`. New columns on `jobs`: `cleaner_id` (nullable FK, `ON DELETE SET NULL`), `service_date` (nullable `Date`, backfilled from `scheduled_at` in UTC). One Alembic migration. Tests: migration up and down, FK null-out.

### 2. Cleaner API

- `POST /api/cleaners` (`name`, `paypal_email`, validated like `customer_email`) returns the cleaner.
- `GET /api/cleaners?date=YYYY-MM-DD` returns unexpired cleaners with `available: bool` for that date (or only the free ones with `?available=true`). Runs the lazy purge first.
- `GET /api/cleaners/{id}` for the cleaner's own page (404 once expired).
- `GET /api/jobs?cleaner_id=` filter, used by `/cleaner`.

### 3. Booking uses a cleaner

`JobCreate` gains `cleaner_id`. `create_job` locks the cleaner row, rejects (409) if the date is taken or the cleaner is expired, stores `cleaner_id` and `service_date`, and writes `cleaner_id` (an id, no name or email) into the `JOB_BOOKED` audit payload. Tests: double booking, abandoned hold released after 30 minutes, expired cleaner, same cleaner on two different dates, concurrent bookings (two threads, one wins).

### 4. Payout goes to the booked cleaner

`settle()` picks the payee from the job's cleaner, falling back to `PAYPAL_CLEANER_EMAIL`. If a cleaner was purged before payout, the fallback applies and an audit row notes it. Tests: payee choice, fallback, purge mid-flow.

### 5. Purge

`purge_expired(db)` deletes photos for jobs of expired non-seed cleaners, nulls `cleaner_id`, deletes the cleaners, and writes one `CLEANERS_PURGED` audit row (count only). `POST /api/maintenance/purge` behind a bearer token (503 if unset, like the webhook id). Tests: only expired non-seed rows go, jobs and audit rows survive, `verify_chain()` still passes, idempotent.

### 6. Web (on the new components)

- `/cleaner/signup`: name and PayPal email, with a note that the email should be a PayPal sandbox account and that data is deleted after 24 hours. On success store the id and go to `/cleaner`.
- `/cleaner`: shows the signed-in cleaner's name and jobs only; no id in storage sends them to sign-up; a 404 from an expired cleaner clears storage and sends them to sign-up.
- `/book`: date first, then a "Choose your cleaner" list (name, free or booked) loaded for that date, then the existing form. The date input becomes date-only; the time-of-day field goes away.
- `Booked` shows the cleaner's name and date.
- A "demo data resets after 24 hours" line in the footer.
- `npx tsc --noEmit` and the Playwright screenshots (390px and 1280px) per `web/design.md`.

### 7. Seed script and README

The default cleaner is created at startup from `PAYPAL_CLEANER_EMAIL` and `DEFAULT_CLEANER_NAME` (idempotent; a test runs it twice); `scripts/seed.py` just calls the same function. README gets the setup steps (`DEFAULT_CLEANER_NAME`, `MAINTENANCE_TOKEN`, the optional pinger, the webhook registration).

## Order of work

1. Model, migration, cleaner API and tests (steps 1-2).
2. Booking with a cleaner, availability and tests (step 3).
3. Payee change and tests (step 4).
4. Purge and tests (step 5).
5. Web pages (step 6).
6. Seed, README, hosted check: sign up, book that cleaner, upload photos, reach `PAID_OUT` with the payout on the cleaner's sandbox account, then confirm the purge removes them.

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
