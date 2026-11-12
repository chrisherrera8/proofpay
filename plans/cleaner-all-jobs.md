# Cleaner Page: All Jobs by Section, with Status Filter

Branch from `main`, for example `feature/cleaner-all-jobs`.

**Goal:** `/cleaner` shows every job assigned to the signed-in cleaner (not only AUTHORIZED and REJECTED), grouped into sections, with a filter to narrow the list by status.

**Out of scope:** auth changes (privacy-hardening items 2-4), new job actions, pagination UI, search or sorting controls.

## Where things stand

- `web/src/pages/CleanerJobs.tsx` calls `listJobs("AUTHORIZED", id)` and `listJobs("REJECTED", id)` and shows them as one flat list (rejected first).
- `GET /api/jobs` already requires `cleaner_id`, takes an optional `status`, `limit` (max 200) and `offset`, and orders by `created_at desc`. **No backend change is needed for the first version.**
- `/cleaner/:id` (`CleanerJob.tsx`) already renders read-only for non-editable statuses (`editable` is only AUTHORIZED or REJECTED, photo slots lock, timeline and payment panel show), so linking every job row to it is safe.
- `StatusBadge` (`STATUS` map) is the single source of status labels, tones and icons.

## Design decisions

1. **One request, group on the client.** Call `listJobs` once with no status and `limit=200`, then group and filter in the browser. This replaces two requests with one and makes the filter instant with no refetch. A cleaner has at most a day's worth of demo jobs (cleaners expire 24h after last use), so 200 is ample; if the response length equals the limit, show a small "Showing the latest 200 jobs" note.
2. **Sections are groups of statuses by what the cleaner should do**, in this order:

   | Section | Statuses | Why |
   |---|---|---|
   | Needs your attention | REJECTED, AUTHORIZED | Action required: re-clean first, then new work (matches today's order) |
   | In review | SUBMITTED, VERIFIED, PENDING_APPROVAL | Photos are in, waiting on the check or a manager |
   | Payment | RELEASED, CAPTURED | Approved, money moving |
   | Completed | PAID_OUT | Done |
   | Upcoming | BOOKED | Booked but the customer's payment is not held yet |

   Put BOOKED last, or merge it into "In review" if five sections feels heavy on a phone. Empty sections are hidden (not shown with an empty message). Inside a section, REJECTED sorts before AUTHORIZED, then by `service_date` ascending (nulls last), so the next job to do is on top.
3. **Filter = a row of status chips** above the sections: `All` plus one chip per status that actually appears in the data, each with a count (for example `Re-clean needed 1`). Single-select, `All` by default. Chip labels come from `STATUS[...]` in `status-badge.tsx`. Selecting a status shows only that status's rows, still under their section heading (so the headings stay consistent and a section with no matches disappears).
   - Use `aria-pressed` toggle buttons in a labelled group (`role="group"`, `aria-label="Filter by status"`). They wrap on mobile; no horizontal scroll.
   - Keep the filter in the URL (`?status=REJECTED`) via `useSearchParams` so reload and back keep it; an unknown value falls back to `All`.
4. **Reuse the existing row markup** (the `Link` card) as a small `JobRow` component in the same file or `src/components/job-row.tsx`. Sections use a plain `<section aria-labelledby>` with an `h2` and a count, not nested `SectionCard`s (design.md: never nest cards).
5. **Copy:** the subtitle changes from "Jobs waiting for before and after photos…" to something like "All your jobs. Anything that needs your attention is listed first." Empty state (no jobs at all) keeps "No jobs waiting" wording adjusted to "No jobs yet". A filter that matches nothing cannot happen, because chips only exist for present statuses.

## Steps

### 1. API client (`web/src/api.ts`) — DONE
- Make `status` optional and add `limit`: `listJobs(cleanerId, { status?, limit? })` (builds the query string with `URLSearchParams`). Update the only caller and the existing `api.test.ts` cases.

### 2. Grouping logic (`web/src/lib/job-sections.ts`, new, pure and unit-tested) — DONE
- `JOB_SECTIONS`: ordered array of `{ id, title, statuses }` from the table above.
- `groupJobs(jobs, statusFilter | null)` returns `[{ section, jobs }]`, empty sections dropped, rows sorted as in decision 2.
- `statusCounts(jobs)` returns the chips data (ordered by section order, then status order within it).
- Unknown future statuses go into a trailing "Other" section so a new backend status never makes jobs vanish.

### 3. Page (`web/src/pages/CleanerJobs.tsx`) — DONE
- Replace the two `listJobs` calls with the single call; keep the cleaner fetch, 404 handling and redirect logic unchanged.
- Add the filter chips component (`web/src/components/status-filter.tsx`, small, with a test) and render sections via `groupJobs`.
- Keep the loading skeleton and the error alert as they are.

### 4. Tests — DONE
- `lib/job-sections.test.ts`: grouping order, within-section sort (REJECTED before AUTHORIZED, nulls last), empty sections dropped, unknown status lands in "Other", counts.
- `CleanerJobs.test.tsx`: update `serveJobs` (it currently switches on `status`) to serve one list; rewrite "lists REJECTED before AUTHORIZED" and "sends cleaner_id on both requests" (now a single request with `cleaner_id=c1` and no `status`). New cases: sections render with headings and counts in order; empty sections are hidden; clicking a chip narrows rows and sets `?status=`; `All` restores; `?status=` in the initial URL pre-selects; invalid `?status=` falls back to All; chips only for present statuses; every row links to `/cleaner/:id`, including PAID_OUT.
- Update `src/test/handlers.ts` default `/jobs` handler only if it assumes the status param. (Checked: it returns `[]` regardless of params, so no change.)
- Note: tests run under StrictMode, so the request test asserts the params of every `/api/jobs` call rather than a count of exactly one.

### 5. Verify (per `web/CLAUDE.md`) — web DONE, `pytest` blocked
- `npm test` and `npm run build` pass.
- Playwright against `npm run dev` with `/api/**` mocked, using a fixture with jobs in every status: screenshot `/cleaner` at 390×844 and 1280×800, with `All` and with one chip selected; check the console is clean; tab through the chips and confirm the focus ring. Report which screenshots were checked.
- Backend tests (`pytest`) need no change; run them once to confirm nothing regressed.

**Results (2026-11-11):** `npm test` 204 passed; `npm run build` passes. Playwright with `/api/**` mocked (10 jobs, every status): checked `/cleaner` at 390×844 and 1280×800, with `All` and with `Awaiting approval` selected (URL became `?status=PENDING_APPROVAL`, only "In review 1" shown). No horizontal overflow at either width; sections, counts and badges render as designed; chips wrap on mobile. Console had no errors, only the two existing React Router future-flag warnings. Tab order reaches the chips and the focused chip shows the 3px ring. A screenshot taken right after a click caught the chip colour transition mid-way; after it settled only the selected chip is pressed. `pytest`: all 412 tests error in setup because the local Postgres is stamped with alembic revision `f8a2d6c4b9e1`, which does not exist in this repo (no backend files differ from `main`). Needs the local test DB reset before it can confirm anything.

## Locked decisions

- Five sections as in the table above (BOOKED last as "Upcoming").
- The filter is single-status chips with counts, stored in `?status=`.
- Single request with `limit=200`; no paging UI. If it ever matters, add `offset` paging ("Load more") later.
