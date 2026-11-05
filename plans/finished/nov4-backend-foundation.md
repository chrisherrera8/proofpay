# Nov 4 Plan: Backend Foundation

Scope from `plans/plan.md` section 6 (the row slipped from Nov 3 to Nov 4): models, Alembic, state machine, audit log, booking API, PayPal authorize endpoint. No UI, vision, policy engine, capture, payouts or webhooks today.

Starting point (before today's work): `app/` is empty (`.gitkeep`), there is no `pyproject.toml` or requirements file, and the only PayPal code is in `spikes/paypal_spike.py` (raw `requests` against `https://api-m.sandbox.paypal.com`). `.env.example` has the PayPal credentials but no `DATABASE_URL`.

## Status

Branch `feature/backend-foundation` (pushed). Steps 1-7 are done and the sandbox run passed. Step 8 is complete (131 tests pass, about 202s).

| Step | State | Notes |
|---|---|---|
| 1. Project setup | Done | `pyproject.toml` (uv), `app/config.py`, `app/db.py`. `DB_SCHEMA` env var sets `search_path` on every connection. Share percentage was removed. |
| 2. Models | Done | All nine tables plus `alembic_version`. Status is a string with a check constraint. |
| 3. Alembic | Done | One migration, `11ad39a14edc`, applied to the **`test` schema only**. Round trip (`upgrade`, `downgrade`, `upgrade`) works. It has no hard-coded schema, so the same file builds `public`. `audit_log` has a trigger that blocks `UPDATE` and `DELETE`. |
| 4. State machine | Done | `app/state_machine.py`: `transition()` locks the job row, rejects illegal moves with `InvalidTransition`, writes the audit row in the same transaction. `REJECTED → SUBMITTED` is allowed for the re-clean loop. |
| 5. Audit log | Done | `app/audit.py`: hash chain, `append_audit()`, `verify_chain()`, advisory lock keeps the chain linear. Tampering is detected (tested). |
| 6. Booking API | Done | `app/api/jobs.py`, `app/schemas.py`, `app/checklists.py`, `app/main.py` (`/healthz`, 409 handler for `InvalidTransition`). `GET /api/jobs` has `status`/`limit`/`offset`. 16 tests in `tests/test_booking_api.py`. |
| 7. PayPal order and authorize endpoints | Done, sandbox-verified | `app/paypal/client.py` (+ README), `app/api/paypal.py`. Manual run on Nov 4: job `6900e783-c0a9-468b-b824-5769f041aa65`, order `2CP92300CA660471C`, authorization `85T08228WG173110G` ($10.00), 3 audit rows, chain verified, repeat authorize made no PayPal call. 11 client tests, 17 route tests. |
| 8. Tests | Done | 131 tests pass: state machine, audit log, booking API (16), PayPal client (11) and PayPal routes (17). |

Test setup as built: `tests/conftest.py` forces `DB_SCHEMA=test` and refuses to run otherwise. Each test runs inside an outer transaction that is rolled back (commits only release a savepoint). The suite takes about 144s (down from 194s with per-test truncation); the floor is Neon latency, about 118ms per round trip. Run one file at a time while developing.

Migration `11ad39a14edc` is now applied to `public`. `plans/` and `ideas.md` are uncommitted on purpose.

Open items: the authorize route does not check the payer identity (the spike did); the sandbox authorization `85T08228WG173110G` is still open (no void in the client yet); the test job in `public` can't be removed because `audit_log` is append-only.

## Definition of done

1. `alembic upgrade head` creates the schema on a clean Postgres (Neon or local).
2. `POST /api/jobs` books a job; `GET /api/jobs/{id}` returns it with its checklist.
3. `POST /api/jobs/{id}/paypal/order` creates an `AUTHORIZE` order and returns the order ID for the JS SDK button.
4. `POST /api/jobs/{id}/paypal/authorize` authorizes the approved order, stores the authorization ID and moves the job `BOOKED → AUTHORIZED`.
5. Every state change writes an audit row in the same transaction. Illegal transitions are rejected.
6. pytest covers the state machine and the audit log. The PayPal client is mocked.
7. One manual end-to-end run against the sandbox.

## Steps

### ✅ 1. Project setup (~20 min)
- Add `pyproject.toml` with: `fastapi`, `uvicorn`, `sqlalchemy>=2` (sync, to keep it simple), `psycopg[binary]`, `alembic`, `pydantic-settings`, `httpx`, and dev deps `pytest`, `pytest-httpx` (or `respx`).
- `app/config.py`: pydantic `Settings` reading `.env` (PayPal credentials, `DATABASE_URL`, `PAYPAL_BASE_URL`). Add `DATABASE_URL` to `.env.example`.
- Schema switch: env var `DB_SCHEMA` (default `public`; tests set `test`). `db.py` applies it to every connection with `search_path`, and Alembic's `env.py` reads the same setting, so `DB_SCHEMA=test alembic upgrade head` builds the test schema with the real migration. Add `DB_SCHEMA=public` to `.env.example`.
- Layout:
  ```
  app/
    main.py            FastAPI app, router includes
    config.py
    db.py              engine, SessionLocal, get_db dependency
    models/            one module per table, imported in __init__
    state_machine.py   transition table + transition() function
    audit.py           append_audit()
    paypal/client.py   token cache, create_order, authorize_order
    api/jobs.py        booking routes
    api/paypal.py      order + authorize routes
    schemas.py         pydantic request/response models
  alembic/
  tests/
  ```

### ✅ 2. Models (~40 min)
Create all the tables from plan section 2 now, so one migration covers the week. Only `jobs`, `checklist_items`, `payments` and `audit_log` are used today; the others are empty shells that later days fill in.

| Table | Key columns |
|---|---|
| `jobs` | `id` (UUID), `status` (enum), `customer_name`, `customer_email`, `address`, `service_type`, `scheduled_at`, `amount` (`Numeric(10,2)`), `currency`, `authorized_at`, timestamps |
| `checklist_items` | `id`, `job_id` FK, `label`, `required` bool, `position` |
| `photos` | `id`, `job_id` FK, `kind` (before/after), `data` (`LargeBinary`), `content_type`, `created_at` |
| `verifications` | `id`, `job_id` FK, `score`, `results` (JSONB per-item), `model`, `created_at` |
| `payments` | `id`, `job_id` FK (unique), `order_id`, `authorization_id` (mutable), `capture_id`, `authorized_amount`, `authorized_at`, `status` |
| `payouts` | `id`, `job_id` FK, `batch_id`, `item_id`, `amount`, `status` |
| `mandates` | `id`, `monthly_cap`, `approved_subcontractors` (JSONB), `auto_release_ceiling`, `min_score`, `required_items` (JSONB) |
| `approvals` | `id`, `job_id` FK, `status`, `decided_by`, `decided_at`, `reason` |
| `audit_log` | `id` (bigserial), `job_id`, `actor`, `event`, `from_status`, `to_status`, `payload` (JSONB), `created_at`, `prev_hash`, `hash` |

Decisions:
- Money is `Numeric`, never float. Use `Decimal` in Python and a string such as `"10.00"` when talking to PayPal.
- Status is a native Postgres enum, or a string column plus a `CheckConstraint`. The enum is cheaper to extend with a string, so prefer the string column plus a check, because adding enum values in Alembic is awkward.
- Include `PENDING_APPROVAL`, `REJECTED`, `RELEASED`, `CAPTURED` and `PAID_OUT` now, even though nothing reaches them today.
- Unique constraint on `payments.job_id` and on `payments.order_id`.

### ✅ 3. Alembic (~20 min)
- `alembic init alembic`; set `env.py` to read `Settings.database_url` and use `Base.metadata`.
- Generate one initial migration with `--autogenerate`, then read it by hand (JSONB, check constraints, indexes on `job_id` and `status`).
- Add DB-level protection for the audit log: a trigger that raises on `UPDATE` or `DELETE` on `audit_log`, put in the migration with `op.execute`. This makes it genuinely append-only, which is the point of the table.
- Verify with `upgrade head`, `downgrade base`, `upgrade head`.

### ✅ 4. State machine (~30 min)
- `state_machine.py`: a `TRANSITIONS` dict mapping each status to the set of statuses it may move to, from plan section 2:
  `BOOKED→AUTHORIZED→SUBMITTED→VERIFIED→{RELEASED, PENDING_APPROVAL, REJECTED}`, `PENDING_APPROVAL→{RELEASED, REJECTED}`, `RELEASED→CAPTURED→PAID_OUT`.
  Also allow `REJECTED→SUBMITTED` for the re-clean loop (the README warning mentions it).
- `transition(db, job, to_status, actor, event, payload=None)`:
  1. Lock the row (`SELECT … FOR UPDATE`) so two requests can't race.
  2. Raise `InvalidTransition` (mapped to HTTP 409) if `to_status` is not allowed.
  3. Set the status and call `append_audit` in the same transaction.
- This is the only code path that sets `job.status`. Nothing else assigns it.

### ✅ 5. Audit log (~30 min)
- `append_audit(db, job_id, actor, event, from_status, to_status, payload)`: reads the latest row's `hash`, computes `sha256(prev_hash + canonical_json(row fields))`, inserts. Take a Postgres advisory lock (`pg_advisory_xact_lock`) so the chain stays linear under concurrent writes.
- `verify_chain(db)` helper that recomputes the hashes, used in tests (and later in the admin UI).
- Decided to include it (about 20 lines); drop it only if today overruns.
- Use `json.dumps(sort_keys=True, separators=(",", ":"), default=str)` so the hash is reproducible.

### ✅ 6. Booking API (~40 min)
- `POST /api/jobs`: body has customer fields, address, service type, scheduled time and `amount`. Creates the job in `BOOKED`, copies the checklist from a template keyed on `service_type`, and writes the `JOB_BOOKED` audit row. The `BOOKED` row has no `from_status`.
  - Checklist templates: a small Python dict for now (e.g. `standard_clean`: kitchen, bathroom, floors, surfaces, oven). Plan section 6 puts the proper templates on Nov 4's UI work.
  - Validate `amount > 0` and a currency whitelist (`USD`).
- `GET /api/jobs/{id}` and `GET /api/jobs` (for the admin view later), both with checklist and payment summary.
- `GET /healthz`.

### ✅ 7. PayPal client and authorize endpoint (~60 min)
Reuse the spike's request shapes, but use `httpx` and a thin class so tests can mock it.

- `paypal/client.py`:
  - `get_token()` cached in memory until shortly before expiry.
  - `create_order(job, request_id)` posts `intent=AUTHORIZE` with the job amount and the job ID as `custom_id` / `reference_id`. Send `PayPal-Request-Id` set to a value derived from the job ID, so a retry doesn't create a duplicate order.
  - `authorize_order(order_id, request_id)` posts to `/v2/checkout/orders/{id}/authorize` and returns the parsed authorization ID, status and amount.
  - Raise a `PayPalError` that keeps the `PayPal-Debug-Id` and response body; log them.
- `POST /api/jobs/{id}/paypal/order`: requires status `BOOKED`. Creates the order, upserts the `payments` row with `order_id`, writes a `PAYPAL_ORDER_CREATED` audit row (no status change), returns `{order_id}`. If an order already exists for the job, return it instead of making a second one.
- `POST /api/jobs/{id}/paypal/authorize`: body `{order_id}`, which must match the stored one. Calls `authorize_order`, then in one transaction stores `authorization_id`, `authorized_amount` and `authorized_at`, and calls `transition(BOOKED → AUTHORIZED)`.
  - Check the response: `purchase_units[0].payments.authorizations[0].id` exists and its status is `CREATED`. Any other status (e.g. `DENIED`, `PENDING`) leaves the job in `BOOKED`, writes an audit row and returns an error.
  - Idempotent: calling again on an `AUTHORIZED` job with the same order returns the existing result and doesn't call PayPal.
  - The PayPal call happens outside the DB transaction, and the job row is locked only for the write. If PayPal succeeds but the DB write fails, the audit row and logs carry the authorization ID so it can be recovered. (A full recovery job is out of scope.)
- The JS SDK on the widget (Nov 4 UI work) will call these two routes: create-order, then authorize in `onApprove`.

### 8. Tests (~40 min)
- Use the project's Postgres (the audit trigger, `FOR UPDATE` and advisory lock don't work on SQLite) in a separate `test` schema. Done: the fixture rolls back each test's transaction (state machine and audit tests). Still to write: booking API and authorize endpoint tests.
- State machine: every allowed transition succeeds; a table-driven test over all other pairs raises `InvalidTransition`; each success writes exactly one audit row with the right `from_status` / `to_status`.
- Audit: the hash chain verifies after N writes; mutating a row (as superuser, bypassing the trigger) makes `verify_chain` fail; `UPDATE`/`DELETE` through the app role is blocked by the trigger.
- Booking API: happy path, invalid amount, unknown service type, checklist copied.
- Authorize endpoint with a mocked PayPal client: success, non-`CREATED` authorization, order ID mismatch, wrong job status, repeat call is idempotent, PayPal 5xx leaves the job in `BOOKED`.
- Manual sandbox run (not in CI): book, create order, approve with the sandbox customer account in a browser, authorize, check the audit rows. For the approval step, run the SDK button from a throwaway HTML page, or reuse the approve link from `spikes/paypal_spike.py`.

## Order of work and checkpoints

1 setup → 2 models → 3 Alembic (**checkpoint: migration round-trips**, passed) → 4 state machine + 5 audit (**checkpoint: tests green**, passed) → 6 booking API → 7 PayPal endpoints (**checkpoint: sandbox run**) → 8 remaining tests.

Estimated total: about 4.5 hours; steps 1-5 are done, about 2 hours remain. If it slips, cut in this order: the manual sandbox run's browser flow (use the spike's approve link), the `GET /api/jobs` list, then the hash chain (per plan section 6).

## Risks

- **Approval flow:** the authorize call fails unless the buyer has approved the order, so the manual test needs a real approval step in a browser. Mitigation: reuse the spike's approve link.
- **Neon cold start and connection limits:** use the pooled connection string, and `pool_pre_ping=True`. Tests hit the same Neon database in a `test` schema, so the first test run after idle will be slow.
- **Honor period:** `authorized_at` is stored now so the 3-day rule in the README can be enforced or alerted on later.

## Decisions (Nov 4)

1. **Database:** tests use the same Postgres as the project (Neon). To keep test runs from touching demo data, tests run in a separate `test` schema in that database, selected with the `DB_SCHEMA` env var (`search_path`). A pytest fixture sets `DB_SCHEMA=test` and refuses to run if it resolves to `public`. This is still the same database, but the audit hash chain and truncates can't collide with real jobs.
2. **Sync SQLAlchemy.** Async isn't worth it at hackathon scale (see notes in chat); the PayPal calls use `httpx` sync and FastAPI runs sync routes in a threadpool.
3. **Audit hash chain: included** in step 5.
4. **Price:** supplied by the client in `POST /api/jobs`, validated (`amount > 0`, USD only). No price table; kept simple on purpose.
