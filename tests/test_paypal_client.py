import uuid
from decimal import Decimal

import httpx
import pytest
import respx

from app.paypal.client import PayPalClient, PayPalError, request_id

BASE = "https://paypal.test"
JOB = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def client():
    return PayPalClient("cid", "secret", BASE)


def token_route(mock, expires_in=3600):
    return mock.post(f"{BASE}/v1/oauth2/token").respond(
        200, json={"access_token": "tok", "expires_in": expires_in}
    )


@respx.mock
def test_token_is_cached(client):
    route = token_route(respx)
    respx.post(f"{BASE}/v2/checkout/orders").respond(201, json={"id": "O1", "status": "CREATED"})
    client.create_order(job_id=JOB, amount=Decimal("10"), currency="USD")
    client.create_order(job_id=JOB, amount=Decimal("10"), currency="USD")
    assert route.call_count == 1


@respx.mock
def test_token_refreshed_when_near_expiry(client):
    route = token_route(respx, expires_in=30)  # inside the safety margin, so never cached
    respx.post(f"{BASE}/v2/checkout/orders").respond(201, json={"id": "O1", "status": "CREATED"})
    client.create_order(job_id=JOB, amount=Decimal("10"), currency="USD")
    client.create_order(job_id=JOB, amount=Decimal("10"), currency="USD")
    assert route.call_count == 2


@respx.mock
def test_token_failure_raises(client):
    respx.post(f"{BASE}/v1/oauth2/token").respond(401, json={"error": "invalid_client"})
    with pytest.raises(PayPalError) as e:
        client.get_token()
    assert e.value.status_code == 401


@respx.mock
def test_create_order_request_shape(client):
    token_route(respx)
    route = respx.post(f"{BASE}/v2/checkout/orders").respond(201, json={"id": "O1", "status": "CREATED"})
    order = client.create_order(job_id=JOB, amount=Decimal("120"), currency="USD")

    assert (order.id, order.status) == ("O1", "CREATED")
    req = route.calls[0].request
    assert req.headers["authorization"] == "Bearer tok"
    assert req.headers["paypal-request-id"] == request_id("order", str(JOB))
    body = httpx.Response(200, content=req.content).json()
    assert body["intent"] == "AUTHORIZE"
    unit = body["purchase_units"][0]
    assert unit["custom_id"] == unit["reference_id"] == str(JOB)
    assert unit["amount"] == {"currency_code": "USD", "value": "120.00"}


def test_request_id_is_deterministic_and_scoped():
    assert request_id("order", "a") == request_id("order", "a")
    assert request_id("order", "a") != request_id("order", "b")
    assert request_id("order", "a") != request_id("authorize", "a")


AUTH_OK = {
    "id": "O1",
    "status": "COMPLETED",
    "payer": {"email_address": "buyer@example.com", "payer_id": "PAYER1"},
    "purchase_units": [
        {"payments": {"authorizations": [
            {"id": "A1", "status": "CREATED", "amount": {"currency_code": "USD", "value": "120.00"}}
        ]}}
    ],
}


@respx.mock
def test_authorize_order_parses_result(client):
    token_route(respx)
    route = respx.post(f"{BASE}/v2/checkout/orders/O1/authorize").respond(
        201, json=AUTH_OK, headers={"PayPal-Debug-Id": "dbg1"}
    )
    auth = client.authorize_order("O1")
    assert (auth.id, auth.status, auth.amount, auth.currency) == ("A1", "CREATED", Decimal("120.00"), "USD")
    assert auth.debug_id == "dbg1"
    assert (auth.payer_email, auth.payer_id) == ("buyer@example.com", "PAYER1")
    assert route.calls[0].request.headers["paypal-request-id"] == request_id("authorize", "O1")


@respx.mock
def test_authorize_non_created_status_is_returned_not_raised(client):
    token_route(respx)
    denied = {**AUTH_OK, "purchase_units": [{"payments": {"authorizations": [
        {"id": "A1", "status": "DENIED", "amount": {"currency_code": "USD", "value": "120.00"}}]}}]}
    respx.post(f"{BASE}/v2/checkout/orders/O1/authorize").respond(201, json=denied)
    assert client.authorize_order("O1").status == "DENIED"


@respx.mock
def test_authorize_without_authorization_block(client):
    token_route(respx)
    respx.post(f"{BASE}/v2/checkout/orders/O1/authorize").respond(201, json={"id": "O1", "status": "COMPLETED"})
    auth = client.authorize_order("O1")
    assert auth.id is None and auth.status is None


@respx.mock
def test_http_error_keeps_debug_id_and_body(client):
    token_route(respx)
    respx.post(f"{BASE}/v2/checkout/orders/O1/authorize").respond(
        422, json={"name": "ORDER_NOT_APPROVED"}, headers={"PayPal-Debug-Id": "dbg2"}
    )
    with pytest.raises(PayPalError) as e:
        client.authorize_order("O1")
    assert e.value.status_code == 422
    assert e.value.debug_id == "dbg2"
    assert "ORDER_NOT_APPROVED" in e.value.body


@respx.mock
def test_5xx_raises(client):
    token_route(respx)
    respx.post(f"{BASE}/v2/checkout/orders").respond(503, text="unavailable")
    with pytest.raises(PayPalError) as e:
        client.create_order(job_id=JOB, amount=Decimal("1"), currency="USD")
    assert e.value.status_code == 503


@respx.mock
def test_network_error_wrapped(client):
    token_route(respx)
    respx.post(f"{BASE}/v2/checkout/orders").mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(PayPalError) as e:
        client.create_order(job_id=JOB, amount=Decimal("1"), currency="USD")
    assert e.value.status_code is None


# --- capture ---

CAPTURE_OK = {"id": "C1", "status": "COMPLETED"}


@respx.mock
def test_capture_authorization_request_shape(client):
    token_route(respx)
    route = respx.post(f"{BASE}/v2/payments/authorizations/A1/capture").respond(
        201, json=CAPTURE_OK, headers={"PayPal-Debug-Id": "dbgc"}
    )
    cap = client.capture_authorization("A1", Decimal("10"), "USD")

    assert (cap.id, cap.status, cap.debug_id) == ("C1", "COMPLETED", "dbgc")
    req = route.calls[0].request
    assert req.headers["authorization"] == "Bearer tok"
    assert req.headers["paypal-request-id"] == request_id("capture", "A1")
    body = httpx.Response(200, content=req.content).json()
    assert body == {"amount": {"currency_code": "USD", "value": "10.00"}, "final_capture": True}


@pytest.mark.parametrize("status", ["PENDING", "DECLINED"])
@respx.mock
def test_capture_non_completed_is_returned_not_raised(client, status):
    token_route(respx)
    respx.post(f"{BASE}/v2/payments/authorizations/A1/capture").respond(
        201, json={"id": "C1", "status": status}
    )
    assert client.capture_authorization("A1", Decimal("10"), "USD").status == status


@respx.mock
def test_capture_http_error_raises_with_debug_id(client):
    token_route(respx)
    respx.post(f"{BASE}/v2/payments/authorizations/A1/capture").respond(
        422, json={"name": "AUTHORIZATION_VOIDED"}, headers={"PayPal-Debug-Id": "dbgx"}
    )
    with pytest.raises(PayPalError) as e:
        client.capture_authorization("A1", Decimal("10"), "USD")
    assert (e.value.status_code, e.value.debug_id) == (422, "dbgx")


# --- payouts ---

PAYOUT_CREATED = {"batch_header": {"payout_batch_id": "B1", "batch_status": "PENDING"}}
PAYOUT_BATCH = {
    "batch_header": {"payout_batch_id": "B1", "batch_status": "SUCCESS"},
    "items": [{"payout_item_id": "I1", "transaction_status": "SUCCESS"}],
}


@respx.mock
def test_create_payout_request_shape(client):
    token_route(respx)
    route = respx.post(f"{BASE}/v1/payments/payouts").respond(201, json=PAYOUT_CREATED)
    batch = client.create_payout(JOB, "cleaner@example.com", Decimal("20"), "USD")

    assert (batch.batch_id, batch.status, batch.item_id) == ("B1", "PENDING", None)
    req = route.calls[0].request
    assert req.headers["paypal-request-id"] == request_id("payout", str(JOB))
    body = httpx.Response(200, content=req.content).json()
    assert body["sender_batch_header"]["sender_batch_id"] == f"proofpay-{JOB}"
    (item,) = body["items"]
    assert item["recipient_type"] == "EMAIL"
    assert item["receiver"] == "cleaner@example.com"
    assert item["amount"] == {"value": "20.00", "currency": "USD"}
    assert item["sender_item_id"] == f"proofpay-{JOB}"


@respx.mock
def test_create_payout_http_error_raises(client):
    token_route(respx)
    respx.post(f"{BASE}/v1/payments/payouts").respond(
        400, json={"name": "USER_BUSINESS_ERROR"}, headers={"PayPal-Debug-Id": "dbgp"}
    )
    with pytest.raises(PayPalError) as e:
        client.create_payout(JOB, "cleaner@example.com", Decimal("10"), "USD")
    assert e.value.debug_id == "dbgp"


@respx.mock
def test_get_payout_batch_parses_item(client):
    token_route(respx)
    route = respx.get(f"{BASE}/v1/payments/payouts/B1").respond(200, json=PAYOUT_BATCH)
    batch = client.get_payout_batch("B1")

    assert route.calls[0].request.headers["authorization"] == "Bearer tok"
    assert (batch.batch_id, batch.item_id, batch.item_status) == ("B1", "I1", "SUCCESS")
    assert batch.status == "SUCCESS"


@respx.mock
def test_get_payout_batch_without_items(client):
    token_route(respx)
    respx.get(f"{BASE}/v1/payments/payouts/B1").respond(
        200, json={"batch_header": {"payout_batch_id": "B1", "batch_status": "PROCESSING"}}
    )
    batch = client.get_payout_batch("B1")
    assert (batch.item_id, batch.item_status) == (None, None)


@respx.mock
def test_get_payout_batch_error_raises(client):
    token_route(respx)
    respx.get(f"{BASE}/v1/payments/payouts/B1").respond(404, json={"name": "RESOURCE_NOT_FOUND"})
    with pytest.raises(PayPalError):
        client.get_payout_batch("B1")


@respx.mock
def test_network_error_on_get_wrapped(client):
    token_route(respx)
    respx.get(f"{BASE}/v1/payments/payouts/B1").mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(PayPalError) as e:
        client.get_payout_batch("B1")
    assert e.value.status_code is None


# --- webhook signature ---

WH_HEADERS = {
    "paypal-auth-algo": "SHA256withRSA",
    "paypal-cert-url": "https://api.paypal.test/cert",
    "paypal-transmission-id": "tid",
    "paypal-transmission-sig": "sig",
    "paypal-transmission-time": "2026-11-09T10:00:00Z",
}
WH_BODY = b'{"id": "WH-1",  "event_type": "PAYMENT.PAYOUTS-ITEM.SUCCEEDED"}'


@pytest.fixture
def wh_client():
    return PayPalClient("cid", "secret", BASE, webhook_id="WHID")


@respx.mock
def test_verify_webhook_success_sends_raw_body(wh_client):
    token_route(respx)
    route = respx.post(f"{BASE}/v1/notifications/verify-webhook-signature").respond(
        200, json={"verification_status": "SUCCESS"}
    )
    assert wh_client.verify_webhook(WH_HEADERS, WH_BODY) is True

    sent = route.calls[0].request.content
    parsed = httpx.Response(200, content=sent).json()
    assert parsed["webhook_id"] == "WHID"
    assert parsed["transmission_id"] == "tid"
    assert parsed["transmission_sig"] == "sig"
    assert parsed["cert_url"] == "https://api.paypal.test/cert"
    assert parsed["auth_algo"] == "SHA256withRSA"
    assert parsed["transmission_time"] == "2026-11-09T10:00:00Z"
    # The event is embedded byte for byte (the double space survives), not re-serialized.
    assert WH_BODY in sent


@respx.mock
def test_verify_webhook_failure_status_is_false(wh_client):
    token_route(respx)
    respx.post(f"{BASE}/v1/notifications/verify-webhook-signature").respond(
        200, json={"verification_status": "FAILURE"}
    )
    assert wh_client.verify_webhook(WH_HEADERS, WH_BODY) is False


@respx.mock
def test_verify_webhook_http_error_fails_closed(wh_client):
    token_route(respx)
    respx.post(f"{BASE}/v1/notifications/verify-webhook-signature").respond(500, text="boom")
    assert wh_client.verify_webhook(WH_HEADERS, WH_BODY) is False


@respx.mock
def test_verify_webhook_network_error_fails_closed(wh_client):
    token_route(respx)
    respx.post(f"{BASE}/v1/notifications/verify-webhook-signature").mock(
        side_effect=httpx.ConnectTimeout("slow")
    )
    assert wh_client.verify_webhook(WH_HEADERS, WH_BODY) is False


def test_verify_webhook_without_webhook_id_is_false(client):
    assert client.verify_webhook(WH_HEADERS, WH_BODY) is False
