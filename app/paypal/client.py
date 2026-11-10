"""Thin PayPal REST client (orders v2). The only module that talks to PayPal.

Request shapes follow spikes/paypal_spike.py. Routes depend on this class (via
get_paypal_client) so tests can swap in a fake.
"""
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

# Refresh the token this many seconds before PayPal says it expires.
_TOKEN_MARGIN = 60
_NAMESPACE = uuid.UUID("6f1c2b7e-3a54-4d0e-9a39-5b0d6a6a7c11")


class PayPalError(Exception):
    """A failed PayPal call. Keeps the debug ID and body so it can be traced with PayPal."""

    def __init__(self, message: str, *, status_code: int | None = None,
                 debug_id: str | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.debug_id = debug_id
        self.body = body


@dataclass(frozen=True)
class Order:
    id: str
    status: str


@dataclass(frozen=True)
class Authorization:
    """Parsed result of authorizing an order. `status` is the authorization's status
    (CREATED means funds are held); the caller decides what to do with anything else."""
    id: str | None
    status: str | None
    amount: Decimal | None
    currency: str | None
    order_status: str | None
    debug_id: str | None
    payer_email: str | None = None
    payer_id: str | None = None


@dataclass(frozen=True)
class Capture:
    """Result of capturing an authorization. Only COMPLETED means the money moved;
    the caller decides what to do with PENDING or DECLINED."""
    id: str | None
    status: str | None
    debug_id: str | None


@dataclass(frozen=True)
class PayoutBatch:
    """A payout batch with its single item. `item_status` is None until PayPal has created the item."""
    batch_id: str
    status: str | None
    item_id: str | None = None
    item_status: str | None = None


def request_id(kind: str, key: str) -> str:
    """Deterministic PayPal-Request-Id, so a retry of the same call is deduplicated by PayPal."""
    return str(uuid.uuid5(_NAMESPACE, f"{kind}:{key}"))


class PayPalClient:
    def __init__(self, client_id: str, client_secret: str, base_url: str,
                 http: httpx.Client | None = None, webhook_id: str = ""):
        self._client_id = client_id
        self._webhook_id = webhook_id
        self._client_secret = client_secret
        self._http = http or httpx.Client(base_url=base_url, timeout=30)
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._lock = threading.Lock()

    def get_token(self) -> str:
        with self._lock:
            if self._token and time.monotonic() < self._token_expires_at:
                return self._token
            resp = self._http.post(
                "/v1/oauth2/token",
                auth=(self._client_id, self._client_secret),
                data={"grant_type": "client_credentials"},
            )
            data = self._json_or_raise(resp, "token request")
            self._token = data["access_token"]
            self._token_expires_at = time.monotonic() + max(int(data.get("expires_in", 0)) - _TOKEN_MARGIN, 0)
            return self._token

    def create_order(self, *, job_id: uuid.UUID, amount: Decimal, currency: str,
                     description: str | None = None) -> Order:
        """Create an intent=AUTHORIZE order. Retrying for the same job returns the same order."""
        unit: dict = {
            "reference_id": str(job_id),
            "custom_id": str(job_id),
            "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
        }
        if description:
            unit["description"] = description
        resp = self._post(
            "/v2/checkout/orders",
            {"intent": "AUTHORIZE", "purchase_units": [unit]},
            request_id=request_id("order", str(job_id)),
        )
        data = self._json_or_raise(resp, "create order")
        return Order(id=data["id"], status=data["status"])

    def authorize_order(self, order_id: str) -> Authorization:
        """Authorize an order the buyer has approved."""
        resp = self._post(
            f"/v2/checkout/orders/{order_id}/authorize", None,
            request_id=request_id("authorize", order_id),
        )
        data = self._json_or_raise(resp, "authorize order")
        debug_id = resp.headers.get("PayPal-Debug-Id")
        payer = data.get("payer") or {}
        payer_email, payer_id = payer.get("email_address"), payer.get("payer_id")
        try:
            auth = data["purchase_units"][0]["payments"]["authorizations"][0]
        except (KeyError, IndexError, TypeError):
            return Authorization(None, None, None, None, data.get("status"), debug_id,
                                 payer_email, payer_id)
        amount = auth.get("amount") or {}
        return Authorization(
            id=auth.get("id"),
            status=auth.get("status"),
            amount=Decimal(amount["value"]) if "value" in amount else None,
            currency=amount.get("currency_code"),
            order_status=data.get("status"),
            debug_id=debug_id,
            payer_email=payer_email,
            payer_id=payer_id,
        )

    def capture_authorization(self, authorization_id: str, amount: Decimal, currency: str) -> Capture:
        """Capture the held funds in full. Retrying for the same authorization is deduplicated by PayPal."""
        resp = self._post(
            f"/v2/payments/authorizations/{authorization_id}/capture",
            {"amount": {"currency_code": currency, "value": f"{amount:.2f}"}, "final_capture": True},
            request_id=request_id("capture", authorization_id),
        )
        data = self._json_or_raise(resp, "capture authorization")
        return Capture(id=data.get("id"), status=data.get("status"),
                       debug_id=resp.headers.get("PayPal-Debug-Id"))

    def create_payout(self, job_id: uuid.UUID, receiver_email: str, amount: Decimal,
                      currency: str) -> PayoutBatch:
        """Pay one receiver. The sender_batch_id is per job, so PayPal rejects a second payout for it."""
        sender_id = f"proofpay-{job_id}"
        resp = self._post(
            "/v1/payments/payouts",
            {
                "sender_batch_header": {"sender_batch_id": sender_id,
                                        "email_subject": "ProofPay payout"},
                "items": [{
                    "recipient_type": "EMAIL",
                    "receiver": receiver_email,
                    "amount": {"value": f"{amount:.2f}", "currency": currency},
                    "sender_item_id": sender_id,
                    "note": "ProofPay job payout",
                }],
            },
            request_id=request_id("payout", str(job_id)),
        )
        data = self._json_or_raise(resp, "create payout")
        header = data["batch_header"]
        return PayoutBatch(batch_id=header["payout_batch_id"], status=header.get("batch_status"))

    def get_payout_batch(self, batch_id: str) -> PayoutBatch:
        resp = self._get(f"/v1/payments/payouts/{batch_id}")
        data = self._json_or_raise(resp, "get payout batch")
        header = data["batch_header"]
        items = data.get("items") or []
        item = items[0] if items else {}
        return PayoutBatch(
            batch_id=header["payout_batch_id"],
            status=header.get("batch_status"),
            item_id=item.get("payout_item_id"),
            item_status=item.get("transaction_status"),
        )

    def verify_webhook(self, headers, body: bytes) -> bool:
        """Ask PayPal to verify a webhook delivery. Fails closed: any problem returns False.

        The event is embedded as the exact raw body, because re-serializing parsed JSON can
        change it and break the signature.
        """
        if not self._webhook_id:
            return False
        try:
            head = json.dumps({
                "auth_algo": headers.get("paypal-auth-algo"),
                "cert_url": headers.get("paypal-cert-url"),
                "transmission_id": headers.get("paypal-transmission-id"),
                "transmission_sig": headers.get("paypal-transmission-sig"),
                "transmission_time": headers.get("paypal-transmission-time"),
                "webhook_id": self._webhook_id,
            })[:-1]
            payload = head.encode() + b', "webhook_event": ' + body + b"}"
            resp = self._http.post(
                "/v1/notifications/verify-webhook-signature",
                headers={"Authorization": f"Bearer {self.get_token()}",
                         "Content-Type": "application/json"},
                content=payload,
            )
            if resp.status_code != 200:
                log.error("PayPal webhook verification failed: HTTP %s", resp.status_code)
                return False
            return resp.json().get("verification_status") == "SUCCESS"
        except (httpx.HTTPError, PayPalError, ValueError) as exc:
            log.error("PayPal webhook verification error: %r", exc)
            return False

    def _get(self, path: str) -> httpx.Response:
        try:
            return self._http.get(path, headers={"Authorization": f"Bearer {self.get_token()}"})
        except httpx.HTTPError as exc:
            log.error("PayPal request to %s failed: %r", path, exc)
            raise PayPalError(f"PayPal request failed: {exc!r}") from exc

    def _post(self, path: str, body: dict | None, *, request_id: str) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.get_token()}", "PayPal-Request-Id": request_id}
        try:
            if body is None:
                headers["Content-Type"] = "application/json"
                return self._http.post(path, headers=headers)
            return self._http.post(path, headers=headers, json=body)
        except httpx.HTTPError as exc:
            log.error("PayPal request to %s failed: %r", path, exc)
            raise PayPalError(f"PayPal request failed: {exc!r}") from exc

    @staticmethod
    def _json_or_raise(resp: httpx.Response, what: str) -> dict:
        if resp.status_code not in (200, 201):
            debug_id = resp.headers.get("PayPal-Debug-Id")
            log.error("PayPal %s failed: HTTP %s debug_id=%s body=%s",
                      what, resp.status_code, debug_id, resp.text)
            raise PayPalError(f"PayPal {what} failed with HTTP {resp.status_code}",
                              status_code=resp.status_code, debug_id=debug_id, body=resp.text)
        try:
            return resp.json()
        except ValueError as exc:
            raise PayPalError(f"PayPal {what} returned invalid JSON",
                              status_code=resp.status_code, body=resp.text) from exc


@lru_cache
def get_paypal_client() -> PayPalClient:
    """FastAPI dependency. Cached so the token cache is shared across requests."""
    s = get_settings()
    return PayPalClient(s.paypal_client_id, s.paypal_client_secret, s.paypal_base_url,
                        webhook_id=s.paypal_webhook_id)
