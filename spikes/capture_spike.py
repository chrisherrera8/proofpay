"""Spike: capture a sandbox authorization and confirm the capture webhook fires.

Run from the project root:  python3 spikes/capture_spike.py <authorization_id>
Captures the full authorized amount, then polls spikes/webhook_events.jsonl
(written by wix_iframe_server.py) for the PAYMENT.CAPTURE.* event.
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
EVENT_LOG = ROOT / "spikes" / "webhook_events.jsonl"


def load_env():
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: python3 spikes/capture_spike.py <authorization_id>")
    auth_id = sys.argv[1]
    load_env()
    tok = requests.post(f"{BASE}/v1/oauth2/token",
                        auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]),
                        data={"grant_type": "client_credentials"}, timeout=30)
    tok.raise_for_status()
    headers = {"Authorization": f"Bearer {tok.json()['access_token']}",
               "Content-Type": "application/json"}

    before = requests.get(f"{BASE}/v2/payments/authorizations/{auth_id}", headers=headers, timeout=30)
    print(f"before: HTTP {before.status_code} status={before.json().get('status')}")
    if before.status_code != 200:
        sys.exit(json.dumps(before.json(), indent=2))

    started = time.time()
    resp = requests.post(f"{BASE}/v2/payments/authorizations/{auth_id}/capture",
                         headers={**headers, "PayPal-Request-Id": str(uuid.uuid4())},
                         json={"final_capture": True}, timeout=30)
    print(f"capture: HTTP {resp.status_code} (debug id {resp.headers.get('PayPal-Debug-Id')})")
    body = resp.json()
    if resp.status_code not in (200, 201):
        sys.exit(json.dumps(body, indent=2))
    capture_id = body["id"]
    print(f"capture id={capture_id} status={body.get('status')}")

    after = requests.get(f"{BASE}/v2/payments/authorizations/{auth_id}", headers=headers, timeout=30)
    print(f"authorization after: status={after.json().get('status')}")

    print("waiting up to 90s for a PAYMENT.CAPTURE.* webhook...")
    while time.time() - started < 90:
        if EVENT_LOG.exists():
            for line in EVENT_LOG.read_text().splitlines():
                r = json.loads(line)
                if r["event_type"].startswith("PAYMENT.CAPTURE.") and r["resource_id"] == capture_id:
                    print(f"webhook: {r['event_type']} resource={r['resource_id']} "
                          f"status={r['resource_status']} verified={r['verification']} "
                          f"after {time.time() - started:.0f}s")
                    return
        time.sleep(3)
    print("no capture webhook seen within 90s")


if __name__ == "__main__":
    main()
