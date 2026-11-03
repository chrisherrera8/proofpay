"""Spike: send a $1 sandbox payout and record which webhooks arrive, and in what order.

Run from the project root:  python3 spikes/payout_spike.py
Reads spikes/webhook_events.jsonl (written by wix_iframe_server.py) for PAYMENT.PAYOUT* events.
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

BASE = "https://api-m.sandbox.paypal.com"
ROOT = Path(__file__).resolve().parent.parent
EVENT_LOG = ROOT / "spikes" / "webhook_events.jsonl"


def load_env():
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def payout_events(batch_id):
    out = []
    if EVENT_LOG.exists():
        for line in EVENT_LOG.read_text().splitlines():
            r = json.loads(line)
            if r["event_type"].startswith("PAYMENT.PAYOUT") and batch_id in json.dumps(r["event"]):
                out.append(r)
    return out


def main():
    load_env()
    tok = requests.post(f"{BASE}/v1/oauth2/token",
                        auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]),
                        data={"grant_type": "client_credentials"}, timeout=30)
    tok.raise_for_status()
    headers = {"Authorization": f"Bearer {tok.json()['access_token']}",
               "Content-Type": "application/json"}
    sender_id = f"proofpay-spike-{int(time.time())}"
    resp = requests.post(f"{BASE}/v1/payments/payouts", headers=headers, timeout=30, json={
        "sender_batch_header": {"sender_batch_id": sender_id, "email_subject": "ProofPay spike payout"},
        "items": [{"recipient_type": "EMAIL", "receiver": os.environ["PAYPAL_CLEANER_EMAIL"],
                   "amount": {"value": "1.00", "currency": "USD"},
                   "sender_item_id": f"{sender_id}-1", "note": "ProofPay spike"}],
    })
    print(f"create payout: HTTP {resp.status_code} (debug id {resp.headers.get('PayPal-Debug-Id')})")
    if resp.status_code not in (200, 201):
        sys.exit(resp.text)
    batch_id = resp.json()["batch_header"]["payout_batch_id"]
    print(f"batch {batch_id} status={resp.json()['batch_header']['batch_status']}")

    started = time.time()
    seen = set()
    final_batch = False
    while time.time() - started < 150:
        detail = requests.get(f"{BASE}/v1/payments/payouts/{batch_id}", headers=headers, timeout=30).json()
        status = detail["batch_header"]["batch_status"]
        for r in payout_events(batch_id):
            if r["event_id"] not in seen:
                seen.add(r["event_id"])
                print(f"  +{time.time() - started:3.0f}s webhook {r['event_type']} "
                      f"status={r['resource_status']} verified={r['verification']} (received {r['received_at']})")
        types = {r["event_type"] for r in payout_events(batch_id)}
        if status in ("SUCCESS", "DENIED") and any("BATCH" in t for t in types) and any("ITEM" in t for t in types):
            final_batch = True
            break
        time.sleep(4)
    print(f"batch final status via polling: {status}")
    print("both batch and item webhooks seen" if final_batch else "timed out waiting for batch + item webhooks")


if __name__ == "__main__":
    main()
