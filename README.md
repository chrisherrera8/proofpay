# ProofPay

Proof-of-work payment release for home-service jobs, with agent spend mandates.
A customer's PayPal payment is authorized at booking and only captured once a
vision model verifies the cleaner's before/after photos against the job
checklist and a deterministic policy engine approves the release.

Built for the PayPal AI Hackathon (Devpost).

## Layout

- `app/` FastAPI service (API, state machine, policy engine, webhooks)
- `web/` Vite app: `/widget` (Wix embed), `/cleaner`, `/admin`
- `spikes/` throwaway PayPal/Wix/MCP experiments

## Setup

Copy `.env.example` to `.env` and fill in PayPal sandbox credentials.
(Full setup instructions to follow.)

## Warning: PayPal authorization honor period

A PayPal authorization is valid for 29 days, but only the first 3 are the
"honor period". Capturing after that can be declined by the card issuer. The
clock starts when a job reaches `AUTHORIZED` and stops at `CAPTURED`, so a job
stuck in `PENDING_APPROVAL` or in a re-clean loop past day 3 may fail to
capture. Reauthorizing (day 4 onward) returns a new authorization ID and
restarts the window, so always capture against the latest ID. Automatic
reauthorization is not implemented yet. The demo finishes in minutes, so it is
unaffected.

## License

MIT, see `LICENSE`.
