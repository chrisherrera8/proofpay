"""Spike: PayPal sandbox authorize -> capture -> payout, by hand.

Run from the project root:  python3 spikes/paypal_spike.py
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

import requests

BASE = "https://api-m.sandbox.paypal.com"
ROOT = Path(__file__).resolve().parent.parent


def load_env():
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def show(title, resp):
    print(f"\n=== {title}: HTTP {resp.status_code} ===")
    try:
        print(json.dumps(resp.json(), indent=2))
    except ValueError:
        print(resp.text)
    print(f"(PayPal-Debug-Id: {resp.headers.get('PayPal-Debug-Id')})")


def main():
    load_env()
    client_id = os.environ["PAYPAL_CLIENT_ID"]
    secret = os.environ["PAYPAL_CLIENT_SECRET"]
    cleaner = os.environ["PAYPAL_CLEANER_EMAIL"]
    customer = os.environ["PAYPAL_CLEANING_CUSTOMER_EMAIL"]

    if cleaner.lower() == customer.lower():
        sys.exit("PAYPAL_CLEANER_EMAIL and PAYPAL_CLEANING_CUSTOMER_EMAIL are the same account; they must differ.")
    print(f"Customer (payer):  {customer}")
    print(f"Cleaner (payee of the payout): {cleaner}")
    print("Business (receives the capture, funds the payout): the account that owns this app")

    # 1. Access token
    resp = requests.post(
        f"{BASE}/v1/oauth2/token",
        auth=(client_id, secret),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    if resp.status_code != 200:
        show("token", resp)
        sys.exit("Token request failed: check client ID/secret and that the app is a Sandbox app.")
    token = resp.json()["access_token"]
    print("1. Got access token")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 2. Create an order with intent=AUTHORIZE
    resp = requests.post(
        f"{BASE}/v2/checkout/orders",
        headers={**headers, "PayPal-Request-Id": str(uuid.uuid4())},
        json={
            "intent": "AUTHORIZE",
            "purchase_units": [
                {"amount": {"currency_code": "USD", "value": "10.00"}, "description": "ProofPay spike: cleaning"}
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "return_url": "https://example.com/return",
                        "cancel_url": "https://example.com/cancel",
                        "user_action": "PAY_NOW",
                    }
                }
            },
        },
        timeout=30,
    )
    show("create order", resp)
    if resp.status_code not in (200, 201):
        sys.exit("Order creation failed.")
    order = resp.json()
    order_id = order["id"]
    approve = next(
        (l["href"] for l in order.get("links", []) if l["rel"] in ("payer-action", "approve")), None
    )
    print(f"\n2. Order {order_id} status={order['status']}")
    print(f"\nOpen this link, log in as the CUSTOMER ({customer}), and approve:\n  {approve}")
    print("(You'll land on example.com afterwards; that's expected.)")
    input("\nPress Enter once approved... ")

    # 3. Authorize the approved order
    resp = requests.post(
        f"{BASE}/v2/checkout/orders/{order_id}/authorize",
        headers={**headers, "PayPal-Request-Id": str(uuid.uuid4())},
        timeout=30,
    )
    show("authorize order", resp)
    if resp.status_code not in (200, 201):
        sys.exit("Authorize failed. Did you approve the order?")
    payer_email = resp.json().get("payer", {}).get("email_address", "")
    if payer_email.lower() != customer.lower():
        print(f"\nWARNING: the payer was {payer_email}, not the customer {customer}.")
        print("The authorization exists but is unusable for this test. Voiding it and stopping.")
        auth_id = resp.json()["purchase_units"][0]["payments"]["authorizations"][0]["id"]
        void = requests.post(f"{BASE}/v2/payments/authorizations/{auth_id}/void", headers=headers, timeout=30)
        print(f"Void: HTTP {void.status_code}")
        sys.exit("Approve with the customer account and run again.")
    auth = resp.json()["purchase_units"][0]["payments"]["authorizations"][0]
    auth_id = auth["id"]
    print(f"\n3. Authorization {auth_id} status={auth['status']}")

    # 4. Capture the authorization
    resp = requests.post(
        f"{BASE}/v2/payments/authorizations/{auth_id}/capture",
        headers={**headers, "PayPal-Request-Id": str(uuid.uuid4())},
        json={"final_capture": True},
        timeout=30,
    )
    show("capture authorization", resp)
    if resp.status_code not in (200, 201):
        sys.exit("Capture failed.")
    print(f"\n4. Captured, status={resp.json().get('status')}")

    # 5. Payout $1 to the cleaner
    batch_id = f"proofpay-spike-{int(time.time())}"
    resp = requests.post(
        f"{BASE}/v1/payments/payouts",
        headers=headers,
        json={
            "sender_batch_header": {
                "sender_batch_id": batch_id,
                "email_subject": "ProofPay spike payout",
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "receiver": cleaner,
                    "amount": {"value": "1.00", "currency": "USD"},
                    "sender_item_id": f"{batch_id}-1",
                    "note": "ProofPay spike",
                }
            ],
        },
        timeout=30,
    )
    show("create payout", resp)
    if resp.status_code not in (200, 201):
        sys.exit("Payout failed. The response above says why (likely Payouts not enabled).")
    payout_batch = resp.json()["batch_header"]["payout_batch_id"]

    final = {"SUCCESS", "DENIED", "CANCELED"}
    for attempt in range(1, 13):
        time.sleep(5)
        resp = requests.get(f"{BASE}/v1/payments/payouts/{payout_batch}", headers=headers, timeout=30)
        status = resp.json().get("batch_header", {}).get("batch_status")
        print(f"   poll {attempt}: batch_status={status}")
        if status in final:
            break
    show("payout batch details", resp)
    print(f"\n5. Batch status {status}. Check the cleaner account ({cleaner}) for the $1.")


if __name__ == "__main__":
    main()
