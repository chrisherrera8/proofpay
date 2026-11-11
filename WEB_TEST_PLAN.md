# Web test plan: Vitest, RTL and MSW

As of 2026-11-10 · Live copy: https://claude.ai/artifact/12bHJpZhgcCykUsBpyficQ

## How to use this plan

Work through the phases in order, one per branch or PR. Each phase reuses the helpers built in the phases before it. Phase 0 is the foundation, and Book (Phase 5) waits until the MSW and router helpers have been proven on simpler pages.

- **Tick tasks as you go.** Each box is one test or one small code change.
- **Phase done when:** `npm test` passes, `npm run build` still passes, and you've watched each new test fail once (break the code or the assertion) so you know it can fail.
- **Approval before every commit.** When a phase is done, stop and show what changed (files, test results and anything that deviates from the plan). Commit only after the owner approves. Phase 0 was committed before this rule was added.
- **Query style:** use `getByRole` and `getByLabelText` first. Use `container.querySelector` only for the hidden file input.
- **Check behaviour, not markup:** assert on text, roles and requests sent, never on Tailwind classes.
- **Bugs found while testing:** note them in Phase 8 instead of fixing them mid-phase, unless the test can't pass without the fix.

## Phase 0: Setup

The goal is one passing smoke test that renders a page, serves it data through MSW and finds it by role.

**Install and configure**

- [x] `npm i -D vitest jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom msw` (done with `vitest@3` and `msw@2`: the latest majors need Vite 6+, and the app is on Vite 5)
- [x] Add a `test` block to `vite.config.ts`: `environment: "jsdom"`, `setupFiles: ["src/test/setup.ts"]`, `globals: true`. Reuse the existing `@` alias.
- [x] Add scripts: `"test": "vitest run"` and `"test:watch": "vitest"`.
- [x] Add `vitest/globals` and `@testing-library/jest-dom` to the tsconfig `types` so `npm run build` still type-checks.

**`src/test/setup.ts`**

- [x] Import `@testing-library/jest-dom/vitest`.
- [x] Start the MSW `setupServer` with `onUnhandledRequest: "error"`. Reset handlers after each test and close after all.
- [x] Clear `localStorage` after each test, and call `vi.unstubAllEnvs()` and `vi.useRealTimers()`.

**Shared helpers (`src/test/`)**

- [x] `fixtures.ts`: `makeJob(overrides)`, `makeCleaner(overrides)`, `makeVerification(overrides)`. Defaults match the types in `api.ts`.
- [x] `handlers.ts`: default happy-path handlers on `http://localhost:8000/api/*`. `.env` doesn't set `VITE_API_URL`, so the default base is used.
- [x] `requests.ts`: a recorder that pushes each request's method, URL, headers and JSON body to an array. Payload tests assert against it.
- [x] `render.tsx`: `renderRoute(path, { state })`, which wraps `MemoryRouter` + `Routes` (same paths as `main.tsx`) in `StrictMode`. Add a `<LocationProbe>` that prints `pathname` and `state` so redirects can be asserted.
- [x] `paypal-stub.tsx`: a `vi.mock("@paypal/react-paypal-js")` factory. `PayPalScriptProvider` just renders its children. `PayPalButtons` renders a button and saves its latest props to a module-level `paypal.props` so tests can call `onClick`, `createOrder`, `onApprove`, `onCancel` and `onError`. Version 8.9.2 sends the latest props to the real buttons, so the latest props are the faithful thing to save.
- [ ] `vi.mock("../resize")` in the CleanerJob tests only, returning `new Blob(["x"], { type: "image/jpeg" })`.

**Gotchas to settle now**

- **The PayPal client id loads with the module.** `Book.tsx` reads `VITE_PAYPAL_CLIENT_ID` once, when the module loads, and `web/.env` sets it. A plain `vi.stubEnv` after the import does nothing. For the missing-id test, call `vi.stubEnv("VITE_PAYPAL_CLIENT_ID", "")`, then `vi.resetModules()`, then `await import("../pages/Book")`.
- **Fix today's date for date tests.** Use `vi.useFakeTimers({ toFake: ["Date"] })` + `vi.setSystemTime(...)`. Faking every timer stalls `userEvent` and `findBy*`.
- **Date inputs:** if `user.type` on `type="date"` doesn't stick in jsdom, use `fireEvent.change(input, { target: { value: "2026-11-20" } })` and then blur.
- **Upload input:** the file input is `hidden` with no label. Find it with `container.querySelector('input[type=file]')` and use `user.upload`. Files need an image MIME type to pass `accept="image/*"`.

- [x] Smoke test: render `/booked/j1` with a `getJob` handler, and find the "You're booked" heading.

## Phase 1: api.ts

Every page relies on these error messages, so this phase goes first. File: `src/api.test.ts`, using MSW only, with no rendering.

**Errors**

- [ ] Network failure (`HttpResponse.error()`): `ApiError` with "Can't reach the booking server…" and `status` undefined.
- [ ] Non-OK response with a string `detail`: the message is the detail, and `status` matches.
- [ ] 422 with a list detail: `"name: too long; email: bad"`, with `"Value error, "` stripped.
- [ ] 422 list items with no `loc` or `msg`: show `field: invalid`.
- [ ] `detail` that's an object (not a string or list): the fallback `Something went wrong (400)…`.
- [ ] 500 with no JSON body: the fallback with `(500)`.
- [ ] OK response whose body isn't JSON. Today this throws a raw `SyntaxError`, not an `ApiError`. Write the test for the behaviour you want, and log the fix in Phase 8.

**Success and requests**

- [ ] 204 from `deletePhoto` resolves to `undefined`.
- [ ] `listJobs("AUTHORIZED")` has no `cleaner_id`. `listJobs("A B", "x/y")` encodes both values.
- [ ] `getCleaner("a/b")` and `listCleaners(date)` encode their values.
- [ ] `createJob` sends `POST` with a JSON body and `Content-Type: application/json`.
- [ ] `uploadPhoto` sends the raw blob with the blob's own `Content-Type` (`image/jpeg`) and `?kind=before`.
- [ ] `photoUrl` builds the expected URL.

## Phase 2: Pure helpers and small components

These are fast and need no network. Use table tests (`it.each`) wherever there's one case per status.

**`lib/format.ts`**

- [ ] `formatDay("2026-11-10")` shows the 10th in both `TZ=Pacific/Auckland` and `TZ=America/Los_Angeles`. `TZ` must be set before the first `Date` is used, so either add a second Vitest project with `env: { TZ }`, or run `TZ=... vitest run format`.
- [ ] `todayLocal()` at 23:30 local and 00:30 local (with `setSystemTime`) returns the local date in both timezones.
- [ ] `formatMoney("20.00")`, `formatMoney(20)` and `formatMoney(5, "EUR")`. Pin the locale or match loosely (`/20\.00/`).

**`lib/cleaner-session.ts`**

- [ ] A set, get and clear round trip.
- [ ] With `localStorage` methods replaced by ones that throw: `getCleanerId` returns `null`, and `set` and `clear` don't throw.

**`tiers.ts`**

- [ ] `tierById("deep")` finds the tier. `"nope"` and `null` return `undefined`.

**`components/job-timeline.tsx`**

- [ ] For each status, the step marked `aria-current="step"` matches `POSITION`.
- [ ] `PAID_OUT`: every step reads "(done)" and none is current.
- [ ] An unknown status falls back to step 0.
- [ ] `REJECTED` shows "Some items need a re-clean". `PENDING_APPROVAL` shows "Waiting for a manager to approve".

**`components/status-badge.tsx`**

- [ ] For each key in `STATUS`, the badge shows its label.
- [ ] Unknown `"ON_HOLD"` renders `"on hold"`.

**`components/field.tsx`**

- [ ] Hint only: `aria-describedby="x-hint"`.
- [ ] Error only: `aria-describedby="x-err"` and `aria-invalid="true"`.
- [ ] Both set: the hint is hidden but its id stays in `aria-describedby`. Decide whether that's intended. As written, the id points at an element that isn't rendered. Log the result in Phase 8.

## Phase 3: CleanerSignup

This is the first page test, and it proves out `renderRoute`, the request recorder and the navigation check. Start with the one-line fix, because a test that uses `getByRole("alert")` would hit it.

- [ ] **Fix first:** remove the `<div role="alert">` wrapper at `CleanerSignup.tsx:100`. `ErrorAlert` already renders `role="alert"`, so today there are two nested alerts.

**Validation**

- [ ] Submitting an empty form shows "Enter your name." and "Enter your PayPal email.", and records no `POST /api/cleaners`.
- [ ] Before blur, typing shows no error. After blur, the field's own error shows.
- [ ] Whitespace-only name and a bad email (`a@b`) each show their message.

**Submit**

- [ ] A valid submit sends `{ name, paypal_email }` trimmed, stores the id under `proofpay.cleanerId`, and lands on `/cleaner`.
- [ ] While the request is pending, the button reads "Signing up" and the inputs are disabled. Hold the handler open with a deferred promise to check this.
- [ ] A 422 failure shows the formatted message in one alert, and the form is enabled again.
- [ ] Typing after a failure clears the alert.

**Banner and demo link**

- [ ] With `state: { expired: true }`, the expired banner shows. Without it, there's no banner.
- [ ] When `listCleaners` returns a seed cleaner, "Continue as Demo" shows. Clicking it stores the seed id and navigates to `/cleaner`.
- [ ] No seed cleaner, or a `listCleaners` 500, shows no demo link and no error.

## Phase 4: CleanerJobs

This phase covers the cleaner's session: redirects, expiry and list order. Before each test, seed `localStorage` with `setCleanerId("c1")` unless the test says otherwise.

**Session**

- [ ] No stored id redirects to `/cleaner/signup` and makes no API calls.
- [ ] `getCleaner` 404 clears the stored id and lands on `/cleaner/signup` with `state.expired === true`. Combined with Phase 3, the banner then shows.
- [ ] `getCleaner` 500 shows the error alert, and the id stays stored.
- [ ] On success, the heading reads "Ana's jobs". Before `getCleaner` resolves, it reads "Your jobs".

**Job list**

- [ ] While loading, the "Loading jobs" status shows.
- [ ] When both lists are empty, "No jobs waiting" shows.
- [ ] When `listJobs` fails, the error alert shows and the skeleton goes away.
- [ ] Order: REJECTED jobs come before AUTHORIZED ones. Check the order of the link names.
- [ ] The request recorder shows both calls carry `cleaner_id=c1`.
- [ ] `service_type: "deep"` shows "Deep Clean". An unknown type shows its raw value. A null `service_date` shows "Date to be confirmed".
- [ ] Each row links to `/cleaner/:id`.

**Switching cleaner**

- [ ] Clicking "Switch cleaner" clears the stored id and lands on `/cleaner/signup`.

## Phase 5: Book

This page handles money and has the most logic. Split it into `Book.form.test.tsx` and `Book.payment.test.tsx`. Fix the date at 2026-11-10 12:00 local in every test, and use the PayPal stub from Phase 0.

**Service tier**

- [ ] No `?tier=` and `?tier=bogus` both select Basic at $10.
- [ ] Clicking Deep Clean sets `?tier=deep` and shows $20.00 in the summary twice.

**Validation and error timing**

- [ ] Before blur, there are no errors. After blur, each field shows its own message.
- [ ] Bad email, whitespace-only name and whitespace-only address each show their message.
- [ ] A past date shows "Pick a date that isn't in the past." and hides the cleaner picker. Today and tomorrow are both accepted.
- [ ] Typing in any field clears the top-level error alert.

**Cleaner picker**

- [ ] It's hidden until a valid date is set. Then it shows "Loading cleaners", then the list.
- [ ] Unavailable cleaners are disabled and read "Booked on Fri, Nov 20". Available ones read "Free".
- [ ] When everyone is unavailable, "Everyone is booked that day" shows.
- [ ] When `listCleaners` fails, the error shows inside the fieldset.
- [ ] Picking a cleaner adds "· Ana" to the summary's Day row.
- [ ] Change the date to one where the picked cleaner is booked: the selection is dropped. Where they're still free, it's kept.
- [ ] Stale response: change the date twice, and make the first response resolve last (with deferred handlers). The second date's list wins.

**makeOrder (through the stub's `createOrder`)**

- [ ] When the form is invalid, it throws "Please fix the highlighted fields." and sends no `createJob`.
- [ ] The payload is trimmed, with `service_type` and `amount` taken from the tier, plus `cleaner_id` and `service_date`.
- [ ] Calling it twice with identical details sends one `createJob` and two `createOrder`.
- [ ] Changing only whitespace (`"Ana"` to `"Ana "`) still reuses the job.
- [ ] Changing any detail or the tier sends a new `createJob`.
- [ ] `createJob` succeeds but `createOrder` fails: on retry, only `createOrder` is called.
- [ ] `createJob` 409: the cleaner is cleared, `listCleaners` is called again, focus moves to the "Choose your cleaner" legend, and the alert ends with "Please choose a cleaner again."
- [ ] `createJob` 404 behaves the same as 409.
- [ ] `createJob` 500 shows the API message as-is, and the cleaner stays selected.

**PayPal callbacks**

- [ ] `onClick` on an invalid form calls `actions.reject`, shows every field error at once, and shows "Please fix the highlighted fields before paying."
- [ ] `onClick` on a valid form calls `actions.resolve` and clears the error.
- [ ] `onApprove` success: `authorize` gets the job id and order id, and the page lands on `/booked/:id`.
- [ ] `onApprove` failure: the alert says "…you have not been charged." and the fields and tiers are enabled again.
- [ ] While `onApprove` is pending, the fields, tiers and cleaner buttons are disabled.
- [ ] `onCancel` shows "Payment was cancelled…". It **replaces** an existing error; this differs from the other agent's spec.
- [ ] `onError` shows the PayPal message only when no error is showing. It keeps an existing one, such as a 409 message.

**Config**

- [ ] With `VITE_PAYPAL_CLIENT_ID` empty (stub, reset modules, dynamic import), the "Set VITE_PAYPAL_CLIENT_ID…" alert shows and no PayPal button does.

## Phase 6: CleanerJob

This page holds the job's state machine: photos, submit, verification, decision and payment. Mock `../resize`. Most panel cases need only a `makeJob` fixture and a `getJob` handler.

**Loading**

- [ ] While loading, the "Loading job" skeleton shows. If `getJob` fails on first load, a full-page error alert shows.
- [ ] A null `service_date` falls back to `formatWhen(scheduled_at)`.

**Submit and retry**

- [ ] AUTHORIZED with no photos: Submit is disabled and the hint "Add at least one before and one after photo." shows.
- [ ] With only before photos, Submit stays disabled. With one before and one after, it's enabled and the hint is gone.
- [ ] REJECTED is editable too: the same Submit button shows.
- [ ] While `submitJob` is pending, the button reads "Checking the photos…" and is disabled.
- [ ] `submitJob` success shows the returned job's status badge.
- [ ] `submitJob` fails and the refreshed job is now SUBMITTED: the error stays visible **after** the refresh, and "Retry verification" shows.
- [ ] SUBMITTED: "Retry verification" calls `POST /verify`.
- [ ] VERIFIED, PENDING_APPROVAL and the payment statuses show neither button.

**Verification panel**

- [ ] When `overall_pass` is true, the title reads "Checks passed". When false, it reads "Some items need attention".
- [ ] Each item reads "Passed", "Failed" or "Not visible" (screen-reader text). A not-visible item shows "Not visible in the after photos" instead of its note.
- [ ] A null score shows "Score –". The model name shows in "Checked by …".

**Decision panel** (one row per case)

- [ ] `auto_release` shows on RELEASED, CAPTURED and PAID_OUT. `needs_approval` shows on PENDING_APPROVAL. `reject` shows on REJECTED. Each shows its title and reasons.
- [ ] A stale decision shows nothing, for example `auto_release` on PENDING_APPROVAL, or `reject` on AUTHORIZED after a re-clean.

**Payment panel**

| Status | Payout | Title | Retry button |
| --- | --- | --- | --- |
| RELEASED | none | Payment not collected yet | yes |
| CAPTURED | PENDING | Payout on the way | yes |
| CAPTURED | FAILED | Payout failed | no |
| PAID_OUT | amount 18.00 | $18.00 paid to your PayPal | no |
| PAID_OUT | none | the job amount, paid | no |
| AUTHORIZED | none | no panel | no |

- [ ] Write the table above as `it.each`.
- [ ] Retry calls `POST /settle`, shows "Retrying…" while pending, and then shows the new status.

**Photos**

- [ ] The counter reads "n/4". At 4 photos, the add tile is gone.
- [ ] Uploading 2 files sends 2 `POST /photos?kind=before` and then refreshes.
- [ ] With 3 existing photos, uploading 3 files sends only 1. Decide first whether dropped files need a message (see Phase 8).
- [ ] While uploading, the tile reads "Uploading…" and is disabled. Afterwards, the input value is reset.
- [ ] Partial failure: file 1 is fine and file 2 fails. File 1 still shows after the refresh, and the error alert shows.
- [ ] Starting a new upload clears a previous error.
- [ ] Remove calls `DELETE` and refreshes. When the delete fails, the error shows and the page still refreshes.
- [ ] When the job isn't editable (such as VERIFIED), there are no add or remove controls, and an empty kind reads "No photos."
- [ ] Photo `src` uses `photoUrl(jobId, id)`, and the alt text reads "Before photo 1".

Out of scope: switching straight from one job to another. Today the only way between jobs is through `/cleaner`, which unmounts this page.

## Phase 7: Booked and routing

This is light coverage of pages with little logic.

**Booked**

- [ ] While loading, the "Loading your booking" skeleton shows. A `getJob` 404 shows the error alert.
- [ ] The happy path shows "Thanks, Sam.", the tier name as the card title, the formatted amount and the checklist labels.
- [ ] A null `cleaner_name` shows "Your cleaner (their demo data has been deleted)".
- [ ] A null `service_date` falls back to `scheduled_at`. An unknown `service_type` shows its raw value.

**Routing smoke test**

- [ ] Move the `<Routes>` tree from `main.tsx` into an exported `AppRoutes` so tests and `main.tsx` share it, and use it in `renderRoute`.
- [ ] `/`, `/book`, `/cleaner/signup` and `/nope` each render without errors. `/nope` shows Home.
- [ ] `/cleaner/signup` matches the signup page, not `/cleaner/:jobId`.

## Phase 8: Fixes and follow-ups

These are issues found while reading the code. Each one becomes a small change with its own test. They're listed by value.

**Code fixes**

- [ ] `api.ts:97`: wrap `res.json()` on success so that a body that isn't JSON throws an `ApiError` instead of "Unexpected end of JSON input".
- [ ] `Book.tsx:52`: give `loadCleaners` (used after a 409) the same stale guard as the date effect, so a late list for an old date can't overwrite the current one.
- [ ] `CleanerJob.tsx:34`: decide what happens to files beyond the 4-photo cap. Today they're silently dropped. A short "Only the first n were added" message is the likely fix.
- [ ] `field.tsx:13`: when both a hint and an error are set, leave the hint id out of `aria-describedby` (the hint isn't rendered then).
- [ ] `Book.tsx:44`: the refs work around stale PayPal callbacks, but 8.9.2 already passes the latest props. Keep the refs as a safety net, and update the comment to say why.

**Backend**

- [ ] Add a pytest that checks the API accepts exactly 10, 20 and 30 for basic, deep and deluxe. `tiers.ts` says the prices must match, and nothing checks that today.

**Playwright (later, against mocked routes)**

- [ ] Booking flow: pick a tier, date and cleaner, fill in the details, check the summary, and check the PayPal area renders. PayPal's real popup is out of scope.
- [ ] Cleaner flow: sign up, open a job, upload before and after photos through `resize.ts` (real canvas), submit, and see the verification panel.
- [ ] Cover `resize.ts` scaling here. It needs `createImageBitmap` and a canvas, which jsdom doesn't have.
