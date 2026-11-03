"""Spike: PayPal JS SDK button (intent=authorize) inside a Wix "Embed a Site" iframe.

Run from the project root:  python3 spikes/wix_iframe_server.py
Serves on localhost:3000. The server creates and authorizes orders so the
client secret never reaches the browser. It authorizes only; it never captures.
"""
import json
import os
import re
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

BASE = "https://api-m.sandbox.paypal.com"
ROOT = Path(__file__).resolve().parent.parent
PORT = 3000


def load_env():
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()
CLIENT_ID = os.environ["PAYPAL_CLIENT_ID"]
SECRET = os.environ["PAYPAL_CLIENT_SECRET"]
WEBHOOK_ID = os.environ.get("PAYPAL_WEBHOOK_ID")  # from the dashboard after registering the webhook
EVENT_LOG = ROOT / "spikes" / "webhook_events.jsonl"
_token = {"value": None, "expires": 0.0}


def access_token():
    if _token["value"] and time.time() < _token["expires"]:
        return _token["value"]
    resp = requests.post(
        f"{BASE}/v1/oauth2/token",
        auth=(CLIENT_ID, SECRET),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    _token["value"] = body["access_token"]
    _token["expires"] = time.time() + body["expires_in"] - 60
    return _token["value"]


def paypal(method, path, payload=None):
    resp = requests.request(
        method,
        f"{BASE}{path}",
        headers={
            "Authorization": f"Bearer {access_token()}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": str(uuid.uuid4()),
        },
        json=payload,
        timeout=30,
    )
    print(f"  PayPal {method} {path} -> {resp.status_code} (debug id {resp.headers.get('PayPal-Debug-Id')})")
    return resp


def verify_webhook(headers, raw):
    """Ask PayPal to verify the signature. The event is embedded as the exact raw
    body, because re-serializing parsed JSON can change it and break verification."""
    if not WEBHOOK_ID:
        return "SKIPPED (PAYPAL_WEBHOOK_ID not set in .env)"
    head = json.dumps({
        "auth_algo": headers.get("PAYPAL-AUTH-ALGO"),
        "cert_url": headers.get("PAYPAL-CERT-URL"),
        "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID"),
        "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG"),
        "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME"),
        "webhook_id": WEBHOOK_ID,
    })[:-1]
    body = head + ', "webhook_event": ' + raw.decode() + "}"
    resp = requests.post(
        f"{BASE}/v1/notifications/verify-webhook-signature",
        headers={"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json"},
        data=body.encode(),
        timeout=30,
    )
    if resp.status_code != 200:
        return f"ERROR HTTP {resp.status_code}"
    return resp.json().get("verification_status", "UNKNOWN")


def handle_webhook(headers, raw):
    event = json.loads(raw or b"{}")
    status = verify_webhook(headers, raw)
    resource = event.get("resource", {})
    # Payout batch events carry no item detail; note the batch id so we can fetch details later.
    batch_id = resource.get("batch_header", {}).get("payout_batch_id") or resource.get("payout_batch_id")
    record = {
        "received_at": time.strftime("%H:%M:%S"),
        "event_type": event.get("event_type"),
        "event_id": event.get("id"),
        "verification": status,
        "resource_id": resource.get("id"),
        "resource_status": resource.get("status") or resource.get("transaction_status"),
        "payout_batch_id": batch_id,
        "event": event,
    }
    with EVENT_LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")
    print(f"[webhook] {record['received_at']} {record['event_type']} "
          f"resource={record['resource_id']} status={record['resource_status']} verified={status}")


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ProofPay iframe spike</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 16px; max-width: 480px; }
  h1 { font-size: 1.1rem; margin: 0 0 4px; }
  #env { font-size: .85rem; color: #555; margin-bottom: 12px; }
  #log { background: #f4f4f4; border-radius: 6px; padding: 8px; font: 12px/1.4 ui-monospace, monospace;
         white-space: pre-wrap; margin-top: 12px; min-height: 60px; }
  #result { margin-top: 8px; font-weight: 600; }
</style>
</head>
<body>
<h1>Book a cleaning: $10.00 (authorize only)</h1>
<div id="env"></div>
<div id="paypal-button"></div>
<div id="result"></div>
<div id="log"></div>
<script>
  const inIframe = window.self !== window.top;
  const logEl = document.getElementById("log");
  function log(msg) {
    logEl.textContent += new Date().toISOString().slice(11, 19) + "  " + msg + "\\n";
    fetch("/api/log", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({msg, inIframe})}).catch(() => {});
  }
  document.getElementById("env").textContent = "Inside iframe: " + inIframe + " | origin: " + location.origin;
  log("page loaded; inIframe=" + inIframe);
  window.addEventListener("error", e => log("JS error: " + e.message));
</script>
<script src="https://www.paypal.com/sdk/js?client-id=__CLIENT_ID__&currency=USD&intent=authorize"
        onload="log('PayPal SDK loaded')" onerror="log('PayPal SDK FAILED to load')"></script>
<script>
  if (window.paypal) {
    paypal.Buttons({
      createOrder: async () => {
        log("createOrder");
        const r = await fetch("/api/orders", {method: "POST"});
        const d = await r.json();
        log("order " + d.id);
        return d.id;
      },
      onApprove: async (data) => {
        log("onApprove (popup approved) order=" + data.orderID);
        const r = await fetch("/api/orders/" + data.orderID + "/authorize", {method: "POST"});
        const d = await r.json();
        log("authorize -> " + JSON.stringify(d));
        document.getElementById("result").textContent =
          d.status === "COMPLETED" && d.authorization_status === "CREATED"
            ? "AUTHORIZED " + d.authorization_id + " (payer " + d.payer_email + ")"
            : "Unexpected: " + JSON.stringify(d);
        try { window.parent.postMessage({type: "proofpay:booked", authorizationId: d.authorization_id}, "*"); } catch (e) {}
      },
      onCancel: () => log("onCancel (popup closed by buyer)"),
      onError: err => log("onError: " + err)
    }).render("#paypal-button").then(() => log("button rendered"))
      .catch(e => log("render failed: " + e));
  }
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        # Allow framing by Wix; no X-Frame-Options.
        self.send_header("Content-Security-Policy", "frame-ancestors *")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?")[0] == "/":
            self._send(200, PAGE.replace("__CLIENT_ID__", CLIENT_ID), "text/html; charset=utf-8")
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        path = self.path.split("?")[0]
        try:
            if path == "/webhooks/paypal":
                handle_webhook(self.headers, raw)
                self._send(200, json.dumps({"ok": True}))  # always 200 so PayPal doesn't retry
            elif path == "/api/log":
                body = json.loads(raw or b"{}")
                print(f"[browser inIframe={body.get('inIframe')}] {body.get('msg')}")
                self._send(204, b"")
            elif path == "/api/orders":
                resp = paypal("POST", "/v2/checkout/orders", {
                    "intent": "AUTHORIZE",
                    "purchase_units": [{"amount": {"currency_code": "USD", "value": "10.00"},
                                        "description": "ProofPay iframe spike"}],
                })
                self._send(resp.status_code, json.dumps({"id": resp.json().get("id")}))
            elif m := re.fullmatch(r"/api/orders/([A-Z0-9]+)/authorize", path):
                resp = paypal("POST", f"/v2/checkout/orders/{m.group(1)}/authorize")
                body = resp.json()
                if resp.status_code not in (200, 201):
                    self._send(resp.status_code, json.dumps(body))
                    return
                auth = body["purchase_units"][0]["payments"]["authorizations"][0]
                self._send(200, json.dumps({
                    "status": body["status"],
                    "authorization_id": auth["id"],
                    "authorization_status": auth["status"],
                    "payer_email": body.get("payer", {}).get("email_address"),
                }))
            else:
                self._send(404, json.dumps({"error": "not found"}))
        except Exception as exc:  # spike code: surface everything
            print(f"  server error: {exc!r}")
            self._send(500, json.dumps({"error": str(exc)}))

    def log_message(self, fmt, *args):
        pass  # request lines are noise; app events print above


if __name__ == "__main__":
    print(f"Serving on http://localhost:{PORT}  (point your tunnel at this port)")
    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except OSError as exc:
        sys.exit(f"Could not bind port {PORT}: {exc}")
