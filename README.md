# ProofPay

Proof-of-work payment release for home-service jobs, with agent spend mandates.
A customer's PayPal payment is authorized at booking and only captured once a
vision model verifies the cleaner's before/after photos against the job
checklist and a deterministic policy engine approves the release.

Built for the PayPal AI Hackathon (Devpost). See `plan.md` for the design and
`step1-spikes.md` for the verified PayPal findings.

## Layout

- `app/` FastAPI service (API, state machine, policy engine, webhooks)
- `web/` Vite app: `/widget` (Wix embed), `/cleaner`, `/admin`
- `spikes/` throwaway PayPal/Wix/MCP experiments

## Setup

Copy `.env.example` to `.env` and fill in PayPal sandbox credentials.
(Full setup instructions to follow.)

## License

MIT, see `LICENSE`.
