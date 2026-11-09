# Customer Site Plan (React web app)

Scope from `plans/plan.md` section 3: a self-hosted cleaning-company mock-up site where a customer picks one of three tiers, books a clean and authorizes payment through PayPal. It replaces the earlier Wix embed. The cleaner upload (`/cleaner`) and admin (`/admin`) screens live in the same Vite app but are separate work.

Branch: `feature/customer-site`, merged to `main` as PR #2 on Nov 5. Stack: Vite, React 18, TypeScript, react-router, `@paypal/react-paypal-js`. Hosting: Cloudflare (site) and Render (API).

## Tiers

| Tier | Service type | Price |
|---|---|---|
| Basic Clean | `basic` | $10 |
| Deep Clean | `deep` | $20 |
| Deluxe Clean | `deluxe` | $30 |

## Status

| Step | State | Notes |
|---|---|---|
| 1. Scaffold `web/` | Done | `package.json`, Vite and TypeScript config, `index.html`, `.env.example` (`VITE_API_URL`, `VITE_PAYPAL_CLIENT_ID`), `public/_redirects` for Cloudflare Pages routing. `npm run build` compiles. |
| 2. Tier data | Done | `src/tiers.ts`: id, name, price, blurb, features. |
| 3. API client | Done | `src/api.ts`: `createJob`, `createOrder`, `authorize`, `getJob`. |
| 4. Home page `/` | Done | Hero and the three tier cards with "Book" buttons. The dev server serves it (HTTP 200); it hasn't been reviewed in a browser yet. |
| 5. Booking page `/book` | Done, tested once | Tier picker, form, PayPal button (`intent=authorize`) that creates the job, creates the order, then authorizes on approval. Needs a sandbox client ID in `web/.env` and the API running. Fixed a CORS error found in the first run: the API now allows both `localhost` and `127.0.0.1` on port 5173. |
| 5a. Sandbox booking | Done (Basic only) | Nov 5: a Basic booking authorized through the PayPal button; job `AUTHORIZED`, 3 audit rows, chain intact. Deep, Deluxe and cancel are left for a manual test at the end of the project. |
| 6. Confirmation page `/booked/:jobId` | Done | Shows the status, schedule and checklist. |
| 7. Backend: three checklist templates | Done | `basic`, `deep`, `deluxe` in `app/checklists.py`, replacing `standard_clean`. Tests updated, 132 pass. |
| 8. Backend: CORS | Done | `CORS_ORIGINS` setting (JSON list, comma list or a single URL), default `localhost:5173` and `127.0.0.1:5173`. |
| 9. Docs | Done | `plans/plan.md` and `README.md` updated; Wix removed. |
| 10. Server-side price check | Done | `app/pricing.py` holds the tier prices; `JobCreate` rejects an amount that doesn't match its `service_type` (422). 8 new tests. |
| 12. Form validation and errors | Done, not browser-tested | `Book.tsx`: per-field messages (shown on blur or on a failed pay click), future-date check, field length limits matching the API, form locked while finishing. The pay button won't open PayPal while fields are invalid. `api.ts` turns 422 details and network failures into readable messages. A retry with identical details reuses the same job; changing details makes a new job, so an abandoned attempt can leave a `BOOKED` job with no payment (no job-update endpoint). |
| 15. Deploy | Done Nov 5 | Site on Cloudflare (Workers static assets, `web/wrangler.jsonc`) at `https://proofpay.chris88herrera.workers.dev`; API on Render (`render.yaml`) at `https://proofpay-api-o584.onrender.com`; Neon database. A Basic booking from the live site authorized (job `ec28495e…`, 3 audit rows). Fixes on the way: wrangler config for Vite 5, `CORS_ORIGINS` accepts plain URLs. |

## To do

| Step | Work | Done when |
|---|---|---|
| 16. Routes for later work | `/cleaner` and `/admin` stubs so the app has one router. Built in the schedule rows for Nov 4-6. | Routes exist; content is separate work. |

## Status summary (end of Nov 5)

The customer site is **live and working end to end**: the three tiers, validated booking form, PayPal sandbox authorization, confirmation page. Only the `/cleaner` and `/admin` route stubs remain, and those belong with the work in `plans/plan.md` section 6.

**Housekeeping to do first thing:** Render and Cloudflare still deploy from `feature/customer-site`. Repoint both to `main` (Render: Settings > Branch; Cloudflare: Settings > Build > Branch control), confirm a deploy from `main` works, then the feature branch can be deleted.

**Manual tests you planned to run at the end:** Deep ($20) and Deluxe ($30) bookings, the cancel path, and a phone.

## Left out for now

Mobile testing (including the redirect-flow fallback) and visual polish (brand, how-it-works, FAQ, accessibility pass) were removed from this plan on Nov 5. Revisit after deploy if time allows.

## Open items

- The authorize route doesn't check the payer identity (carried over from the backend plan).
- Booked jobs have no customer-facing "check status" link beyond the confirmation URL; fine for the demo.
- `web/.env` holds a PayPal client ID, which is public by design; the secret stays on the API only.
