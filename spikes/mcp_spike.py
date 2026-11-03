"""Spike: talk to the PayPal Agent Toolkit MCP server (@paypal/mcp) over stdio.

Run from the project root:
  python3 spikes/mcp_spike.py tools                 # list the tools the sandbox token exposes
  python3 spikes/mcp_spike.py create                # create_order + get_order, print approval link
  python3 spikes/mcp_spike.py pay <order_id>        # pay_order on an order the buyer has approved
"""
import json
import os
import subprocess
import sys
import threading
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


def sandbox_token():
    r = requests.post(f"{BASE}/v1/oauth2/token",
                      auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]),
                      data={"grant_type": "client_credentials"}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


class Mcp:
    def __init__(self):
        env = {**os.environ, "PAYPAL_ACCESS_TOKEN": sandbox_token(), "PAYPAL_ENVIRONMENT": "SANDBOX"}
        self.proc = subprocess.Popen(
            ["npx", "-y", "@paypal/mcp", "--tools=all"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env)
        self.stderr = []
        threading.Thread(target=lambda: [self.stderr.append(l) for l in self.proc.stderr], daemon=True).start()
        self.next_id = 0
        self.call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "proofpay-spike", "version": "0"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def call(self, method, params=None):
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        while True:
            line = self.proc.stdout.readline()
            if not line:
                sys.exit("server closed. stderr:\n" + "".join(self.stderr))
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == self.next_id:
                return msg

    def tool(self, name, args):
        resp = self.call("tools/call", {"name": name, "arguments": args})
        if "error" in resp:
            return {"error": resp["error"]}
        text = "".join(c.get("text", "") for c in resp["result"].get("content", []))
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = text
        return {"isError": resp["result"].get("isError", False), "result": parsed}

    def close(self):
        self.proc.terminate()


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    load_env()
    mcp = Mcp()
    try:
        cmd = sys.argv[1]
        if cmd == "tools":
            tools = mcp.call("tools/list")["result"]["tools"]
            print(f"{len(tools)} tools:")
            for t in tools:
                print(f"  {t['name']}: {t.get('description', '')[:90]}")
        elif cmd == "create":
            out = mcp.tool("create_order", {"currencyCode": "USD", "items": [
                {"name": "ProofPay MCP spike", "quantity": 1, "itemCost": 10.00, "itemTotal": 10.00}]})
            print("create_order:", json.dumps(out, indent=2)[:1500])
            oid = out.get("result", {}).get("id") if isinstance(out.get("result"), dict) else None
            if oid:
                print("get_order:", json.dumps(mcp.tool("get_order", {"id": oid}), indent=2)[:2500])
        elif cmd == "pay":
            out = mcp.tool("pay_order", {"id": sys.argv[2]})
            print("pay_order:", json.dumps(out, indent=2)[:2500])
        elif cmd == "get":
            out = mcp.tool("get_order", {"id": sys.argv[2]})
            print("get_order:", json.dumps(out, indent=2)[:2500])
    finally:
        mcp.close()


if __name__ == "__main__":
    main()
