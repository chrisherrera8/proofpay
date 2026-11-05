# ProofPay Step 1: Spikes

Companion to `plan.md` (sections 1, 3, 4 and 6). This file tracks the Day-1 spikes: small throwaway checks of the riskiest assumptions, run before the repo is scaffolded.

Started: Nov 2, 2026. Feature freeze: Nov 9.

## Done (Nov 2)

- Sandbox business and personal accounts, and a sandbox app with credentials in `.env`.
- Authorize → capture → payout by script (`spikes/paypal_spike.py`).
- Spike 1: Wix iframe + PayPal popup, using `spikes/wix_iframe_server.py` behind a Cloudflare quick tunnel (`cloudflared tunnel --url http://localhost:<port>`) in a Wix "Embed HTML" element (Website address mode).

### Verified findings

| Question | Finding | Design consequence |
|---|---|---|
| Payouts enablement | The sandbox accepts Payouts with no setup. The batch was created (HTTP 201) and funded from `BALANCE`. Live accounts still need a verified business account and a PayPal support request ([setup docs](https://developer.paypal.com/payouts/use-payouts/set-up.md)). | Payouts stay sandbox-only, which is allowed. |
| Payout timing | A created batch returns `PENDING`, not `SUCCESS`. | The app must wait for the payout webhooks before marking a job `PAID_OUT`. |
| Authorize → capture | An `intent=AUTHORIZE` order, once the buyer approves it, authorizes with `POST /v2/checkout/orders/{id}/authorize`. `POST /v2/payments/authorizations/{id}/capture` then captures it. The authorization expires 29 days out and carries `capture`, `void` and `reauthorize` links. | The core flow works as designed. |
| Approval link | Create the order with `payment_source.paypal.experience_context` set. The approval link comes back as `rel: payer-action`. | Build the widget flow on `payer-action`. |
| Three-party flow (spike 0, Nov 2) | Customer (`emily-cleaning-customer@…`) approved and authorized $10, the business captured it, and a $1 payout to a separate cleaner account (`amy-cleaning-business@…`) reached `SUCCESS`. | The full customer → business → cleaner money flow works with three distinct accounts. |
| Payout lifecycle | The batch went `PENDING` → `PROCESSING` → `SUCCESS` in about 25 seconds (created 01:17:41, completed 01:18:06). | Polling works as a fallback, but the app should rely on the payout webhooks (spike 2). |
| Payout fee | The sandbox charged a $0.25 fee on the $1 payout (`payout_item_fee`, also in `batch_header.fees`). The sandbox fee may not match live pricing. | The 70% split must be computed on the amount sent, and the business bears the fee unless the plan says otherwise. Check against PayPal's real Payouts pricing before quoting it anywhere. |
| Wix iframe + PayPal popup (spike 1, Nov 2) | The JS SDK button (`intent=authorize`) works from inside the Wix embed on desktop and mobile. Authorization and cancellation both work on both (`onApprove` and `onCancel` fire). The server sends `Content-Security-Policy: frame-ancestors *` and no `X-Frame-Options`, so Wix can frame it. On mobile the PayPal tab ends on the buyer's PayPal account page and does not return to the original tab. That is most likely the popup losing its link to the opener inside the iframe; this is unconfirmed. The embed worked on a Wix Premium plan. It works acceptably in Safari, which is enough for the demo. | The popup flow is good enough for the demo. If mobile return becomes a problem, fall back to a "Book now" link that opens the widget top-level, or the redirect flow with real `return_url` and `cancel_url`. A quick-tunnel URL changes on every restart, so the Wix embed must be updated each time. |
| Webhooks (spike 2, Nov 2) | One webhook URL on the sandbox app (all events subscribed) pointing at `/webhooks/paypal` on the tunnel. Signature verification via PayPal's `verify-webhook-signature` returned `SUCCESS` for every event. Confirmed: `CHECKOUT.ORDER.APPROVED` (about 8s before `PAYMENT.AUTHORIZATION.CREATED`), `PAYMENT.AUTHORIZATION.CREATED`, `PAYMENT.AUTHORIZATION.VOIDED` (8s after the void), `PAYMENT.CAPTURE.COMPLETED` (15s after the capture), `PAYMENT.PAYOUTSBATCH.PROCESSING`, `PAYMENT.PAYOUTS-ITEM.SUCCEEDED`, `PAYMENT.PAYOUTSBATCH.SUCCESS`. `PAYMENT.AUTHORIZATION.CREATED` and `PAYMENT.PAYOUTSBATCH.PROCESSING` were not in the plan's list. For a $1 payout the item event arrived about 9s before the batch `SUCCESS` event, and the whole payout took about 80s from creation to the final event. Not triggered: `PAYMENT.CAPTURE.DENIED/PENDING`, `PAYMENT.PAYOUTSBATCH.DENIED`, `PAYMENT.PAYOUTS-ITEM.FAILED/UNCLAIMED`. | The state machine marks `PAID_OUT` on the item event, not the batch event, and can't assume the batch event is first. Subscribe to the confirmed events plus the unconfirmed failure ones. A first dashboard registration without the `/webhooks/paypal` path returned 404; the URL path must match. |
| MCP tool check (spike 3, Nov 2) | Ran `npx -y @paypal/mcp --tools=all` against the sandbox with an access token. It exposes 28 tools (invoices, products, subscriptions, shipment tracking, disputes, transactions, refunds, orders) and none for authorize, capture-authorization, void or Payouts. `create_order` and `get_order` work, but `create_order` has no `intent` parameter and creates `CAPTURE` orders. `pay_order` on an authorized `AUTHORIZE` order returned HTTP 422 ("Order was created with an intent to 'AUTHORIZE'. Please use v2/checkout/orders/order_id/authorize") and changed nothing. The first `create_order` call returned a 503 and succeeded on retry. | The plan's fallback holds. MCP is for reads only (`get_order`, `get_dispute`, invoices); REST handles create order, authorize, capture, void and Payouts. Retry MCP calls. Script: `spikes/mcp_spike.py`. |
| Payer check | The authorize response returns the payer's email, which the script compares with the expected customer. | The app can verify who approved a booking before it captures. |

## Remaining, in order

Riskiest and design-changing first. Spikes 1 and 2 share one public HTTPS tunnel, so run them back to back.

| # | Spike | What it verifies | Needs | If it fails |
|---|---|---|---|---|
| 0 | ~~Three-party rerun~~ **Done Nov 2** | See verified findings above. | | |
| 1 | ~~Wix iframe + PayPal popup~~ **Done Nov 2** | The JS SDK button with `intent=AUTHORIZE` approves and authorizes from inside an "Embed a Site" iframe on a Wix page. See verified findings above. Tested on a Wix Premium plan (plan open question 3); whether a free plan can embed wasn't tested. | Local test page behind an HTTPS tunnel, plus a Wix test page | Fall back to a plain link from Wix to the hosted widget, and build `/widget` as a standalone page. |
| 2 | ~~Webhooks~~ **Done Nov 2** | The event names in plan section 1 (they're from memory), signature verification, and that the payout item events arrive after the batch. | The same tunnel as spike 1, and a webhook registered on the sandbox app | Correct the event list; the state machine must use whatever events actually arrive. |
| 3 | ~~MCP tool check~~ **Done Nov 2** | Whether `pay_order` can capture an authorized order, and which tools the sandbox token exposes. | Agent Toolkit MCP server running with the sandbox credentials | Call REST for everything except `create_order`, `get_order` and `get_dispute`, as the plan already assumes. |
| 4 | ~~Vision test~~ **Done Nov 4** | 10 before/after photos on two models; pick on accuracy. Result: `gemini-3.6-flash` 9/9 (default), `gemini-3.5-flash` 9/9, `claude-haiku-5-5` 7/9. See plan section 4. | Photos, and Gemini and one other model's API key | Pick the more accurate model; the provider interface keeps the swap to one config change. |
| 5 | ~~Docs checks (~15 min)~~ **Done Nov 4** | Re-fetch the honor-period docs page (still 404 at the old URL; the 3-day honor period and 29-day validity are confirmed by search summaries of current pages), and Neon's free-tier limits (1 GB storage, 100 CU-hours/month, scale-to-zero after 5 min). See plan sections 1 and 2. | Browser | Treat the 3-day honor period as the working assumption. |

Notes:
- Spike 4 doesn't depend on the others and can run any time, for example while waiting on a Wix plan or tunnel problem.
- Reauthorization (days 4-29) can't be tested in the sandbox without waiting days. It stays a stretch goal and is first in the plan's scope cuts.
- Repo scaffolded with an MIT license on Nov 2 (git initialised, nothing committed yet).
- The plan's schedule was re-based on Nov 2 (plan section 6). Spikes 4 and 5 run first thing Nov 3.
