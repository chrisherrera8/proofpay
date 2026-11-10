"""Shared fakes. No test touches the network."""
from decimal import Decimal

from app.paypal.client import Authorization, Capture, Order, PayoutBatch, PayPalClient


class FakePayPal(PayPalClient):
    """Records every call and succeeds by default. Set an `*_error` to make that call raise,
    or change `capture_status` / `batch_item_status` to simulate PayPal's other answers."""

    def __init__(self):
        self.order_calls = []
        self.authorize_calls = []
        self.capture_calls = []
        self.payout_calls = []
        self.batch_calls = []
        self.order_error = None
        self.authorize_error = None
        self.capture_error = None
        self.payout_error = None
        self.batch_error = None
        self.auth = Authorization(
            "A1", "CREATED", Decimal("10.00"), "USD", "COMPLETED", "dbg", "buyer@example.com", "PAYER1"
        )
        self.capture_status = "COMPLETED"
        self.batch_item_status = "SUCCESS"
        self.webhook_valid = True

    def create_order(self, *, job_id, amount, currency, description=None):
        self.order_calls.append(job_id)
        if self.order_error:
            raise self.order_error
        return Order(id="ORDER1", status="CREATED")

    def authorize_order(self, order_id):
        self.authorize_calls.append(order_id)
        if self.authorize_error:
            raise self.authorize_error
        return self.auth

    def capture_authorization(self, authorization_id, amount, currency):
        self.capture_calls.append((authorization_id, amount, currency))
        if self.capture_error:
            raise self.capture_error
        return Capture(id="CAP1", status=self.capture_status, debug_id="capdbg")

    def create_payout(self, job_id, receiver_email, amount, currency):
        self.payout_calls.append((job_id, receiver_email, amount, currency))
        if self.payout_error:
            raise self.payout_error
        return PayoutBatch(batch_id="BATCH1", status="PENDING")

    def get_payout_batch(self, batch_id):
        self.batch_calls.append(batch_id)
        if self.batch_error:
            raise self.batch_error
        return PayoutBatch(batch_id=batch_id, status="SUCCESS", item_id="ITEM1",
                           item_status=self.batch_item_status)

    def verify_webhook(self, headers, body):
        return self.webhook_valid
