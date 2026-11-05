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
