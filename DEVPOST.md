# Devpost Description: DRAFT 1 (Nov 11)

Status: first draft, step 2 started. Claims checked against the repo: 424 tests pass (`uv run pytest`, Nov 11), tiers are $10/$20/$30 (`app/pricing.py`), the policy engine has seven rules (`app/policy.py`), the sandbox run to `PAID_OUT` is recorded in `plans/plan.md`. **Still to fill in:** [VIDEO LINK], [GITHUB LINK], screenshots, team line, and a check against the official Devpost field names and character limits.

**Tagline:** Pay for the result, not the promise. PayPal holds the money until the photos prove the job got done.

### Inspiration
Paying for home services runs on trust. The customer pays up front and hopes the cleaner shows up and does the work, or pays after and the cleaner hopes to be paid. Escrow fixes this but is built for big transactions. We wanted escrow for a $10 job. We also wanted to try a harder question for AI that spends money: how much should the model be allowed to decide? Our answer is that the model should report what it sees and plain code should decide what happens to the money.

### What it does
ProofPay is a booking site for home-cleaning jobs that releases payment only on proof of work.
1. **Book.** The customer picks a tier (Basic $10, Deep $20, Deluxe $30) and a free cleaner for a whole day, and approves a PayPal authorization. Nothing is charged yet.
2. **Do the work.** The cleaner uploads before and after photos from their phone against a checklist.
3. **Verify.** A vision model checks each checklist item in the photos and returns a per-item result and a score.
4. **Decide.** A policy engine reads the result and picks one of three outcomes: auto-release, send to a human for approval, or reject.
5. **Settle.** A released job is captured and the cleaner is paid through PayPal Payouts. A signed webhook marks it paid.
Every state change is written to a hash-chained audit log, so the history of a job can't be quietly edited.

### How we built it
React + Vite site on Cloudflare, FastAPI on Render, Postgres on Neon. A job moves through an explicit state machine (`BOOKED, AUTHORIZED, SUBMITTED, VERIFIED, RELEASED / PENDING_APPROVAL / REJECTED, CAPTURED, PAID_OUT`) and illegal transitions are refused in one place. The tier price is checked on the server, so the browser can't underpay. Photos are resized in the browser before upload. 424 automated tests run against a throwaway Postgres in about 10 seconds.

### How we use PayPal
- **Orders v2 with `intent=AUTHORIZE`** holds the customer's money at booking.
- **Capture** runs only after the policy engine releases the job.
- **Payouts** sends the cleaner's share to their own PayPal account, per cleaner.
- **Webhooks** are verified with PayPal's `verify-webhook-signature` before any job changes state; a bad signature gets a 400.
- A full job went from booking to `PAID_OUT` on the hosted site in the PayPal sandbox, with the $10 visible in both sandbox accounts.

### How we use AI
Gemini vision looks at the before/after photos and reports, for each checklist item, whether it is visible and whether it passes. It sits behind a provider interface, so swapping the model is one config change. **The model never moves money.** The policy engine is a pure function with seven ordered rules (nothing visible, a required item failed, score under the minimum, a required item not visible, any other item failed, amount above the auto-release ceiling, otherwise release). A person sets the mandate: minimum score, auto-release ceiling, required items. Anything borderline goes to a human approval queue instead of being guessed at. This is a small working model of an agent spend mandate. An optional strict check, chosen at booking, makes an item that isn't visible in the after photos fail instead of being skipped.

### Challenges
- **PayPal tooling gaps.** The PayPal MCP server has no authorize, capture or Payouts tools, so those calls go straight to the REST API.
- **Authorization honor period.** A PayPal authorization is valid for 29 days but only 3 are guaranteed. We documented it and left automatic reauthorization out.
- **Deciding what AI owns.** Early on the model's pass/fail was the decision. Splitting "what's visible" (AI) from "what happens to the money" (code) made the system testable and explainable.
- **Privacy without accounts.** We have no passwords, so cleaner data is deleted 24 hours after last use, and signing up again with an existing PayPal email asks for confirmation.
- **Free-tier cold starts.** The API sleeps when idle; the first request can take 30-60 seconds.

### Accomplishments we're proud of
A real money path in the sandbox, from authorization to payout, with signed webhooks. A policy engine whose every decision lists the reasons behind it. 424 passing tests. Whole-day cleaner booking with a per-cleaner payee.

### What we learned
Put the model where it is strong (reading photos) and keep it out of where it is risky (moving money). Authorize-then-capture is a good fit for pay-on-proof flows. A pure policy function is far easier to test and trust than a prompt.

### What's next
Automatic reauthorization of aging authorizations, real accounts and per-customer mandates, monthly spend caps, a dispute flow with a re-clean draft, and a second vision provider to cross-check the first.

### Built with
Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL (Neon), React, Vite, TypeScript, Cloudflare, Render, PayPal (Orders v2, Payments, Payouts, Webhooks), Google Gemini.

### Links
Live demo: https://proofpay.chris88herrera.workers.dev · Repo: [GITHUB LINK] · Video: [VIDEO LINK]

### Open questions for Chris on this draft
- TypeScript confirmed (`web/tsconfig.json`, `.ts` sources). SQLAlchemy was assumed from `app/models` and Alembic; confirm.
- "Dispute flow with a re-clean draft" is on the old scope-cut list, so it's presented as future work. Confirm that's still accurate.
- Reject and needs-approval paths are untested on the hosted site; the text claims the engine supports them (true in code and tests), not that they ran live. Try them before filming.
