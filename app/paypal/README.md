# PayPal client

`client.py` is the only module that talks to PayPal. Routes depend on `PayPalClient` through the
`get_paypal_client()` FastAPI dependency, so tests replace it with a fake and never hit the network.
Request shapes come from `spikes/paypal_spike.py`; the client uses sync `httpx`.

## Configuration

Read from `app/config.py` (`.env`): `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_BASE_URL`
(default `https://api-m.sandbox.paypal.com`). `get_paypal_client()` is `lru_cache`d, so one client and
one token cache are shared by all requests.

## Methods

| Method | PayPal call | Returns |
|---|---|---|
| `get_token()` | `POST /v1/oauth2/token` (client credentials) | access token string |
| `create_order(job_id, amount, currency, description=None)` | `POST /v2/checkout/orders` | `Order(id, status)` |
| `authorize_order(order_id)` | `POST /v2/checkout/orders/{id}/authorize` | `Authorization` |

### Token cache
The token is kept in memory with its expiry, refreshed 60 seconds early (`_TOKEN_MARGIN`). A lock
means concurrent requests trigger one refresh. The cache is per process; it is lost on restart.

### create_order
Sends `intent=AUTHORIZE` with one purchase unit. The job ID is used as both `reference_id` and
`custom_id`. The amount is formatted as a string with two decimals (`"120.00"`), never a float.
No `payment_source` or return URLs are sent: the JS SDK button handles buyer approval.

### authorize_order
Call this only after the buyer has approved the order. It returns an `Authorization`:

| Field | Meaning |
|---|---|
| `id` | authorization ID (needed later for capture); `None` if the response had no authorization block |
| `status` | authorization status. `CREATED` means funds are held. |
| `amount`, `currency` | amount PayPal authorized (`Decimal`) |
| `order_status` | status of the order itself |
| `debug_id` | `PayPal-Debug-Id` header |

A non-`CREATED` status (`DENIED`, `PENDING`, ...) is **returned, not raised**. The route decides what
to do with it: leave the job in `BOOKED`, write an audit row, return an error. The client does not
judge business outcomes.

## Retries and idempotency

Every POST sends a `PayPal-Request-Id`, built by `request_id(kind, key)` as a deterministic UUIDv5:

- orders: `request_id("order", job_id)`
- authorizations: `request_id("authorize", order_id)`

Retrying the same call sends the same ID, so PayPal returns the original result instead of creating a
second order or authorization. PayPal only remembers request IDs for a limited time, so the routes
also keep their own idempotency (stored `order_id`, stored authorization).

## Errors

`PayPalError` is raised for any failure and carries:

- `status_code`: HTTP status, or `None` for network errors (timeouts, connection failures)
- `debug_id`: the `PayPal-Debug-Id` header, which PayPal support uses to trace a call
- `body`: raw response text

Cases covered: non-200/201 responses (including the token call), network errors (`httpx.HTTPError`)
and invalid JSON. Each is logged at error level with the debug ID and body. Routes should map it to
a 502 and write the debug ID into the audit row.

## Not covered yet

Capture, void, reauthorization, payouts and webhooks. They are out of scope for the Nov 4 foundation
(see `plans/plan.md`). There are no automatic retries; a failed call surfaces as `PayPalError` and the
caller decides.

## Tests

`tests/test_paypal_client.py` mocks HTTP with `respx`. Route tests should override
`get_paypal_client` with a fake class instead.
