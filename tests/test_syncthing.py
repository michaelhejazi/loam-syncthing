#!/usr/bin/env python3
"""The Syncthing plugin against a fake API on loopback, with keys supplied
as Loam supplies them.

Run: python3 tests/test_syncthing.py
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="test-syncthing-"))
VAULT = TMP / "vault"
VAULT.mkdir()
ME = "AAAAAAA-BBBBBBB-CCCCCCC-DDDDDDD-EEEEEEE-FFFFFFF-GGGGGGG-HHHHHHH"
PHONE = "MFZWI3D-BONSGYC-YLTMRWG-C43ENR5-QXGZDMM-FZWI3DP-BONSGYC-YLTMRWA"
KEY = "fake-api-key"
STATE = {"devices": [{"deviceID": ME, "name": "box"}], "folders": [], "ignores": {}}
SEEN: list[tuple[str, str]] = []


class Fake(http.server.BaseHTTPRequestHandler):
    def _send(self, status, body=None):
        raw = b"" if body is None else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"null")

    def handle_one(self, method):
        SEEN.append((method, self.path))
        if self.headers.get("X-API-Key") != KEY:
            return self._send(403, {"error": "key"})
        path, _, query = self.path.partition("?")
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/rest/system/status")
            self.end_headers()
            return
        if (method, path) == ("GET", "/rest/system/status"):
            return self._send(200, {"myID": ME})
        if (method, path) == ("GET", "/rest/config/devices"):
            return self._send(200, STATE["devices"])
        if (method, path) == ("POST", "/rest/config/devices"):
            STATE["devices"].append(self._body())
            return self._send(200)
        if (method, path) == ("GET", "/rest/config/defaults/device"):
            return self._send(200, {"deviceID": "", "name": "", "addresses": ["dynamic"]})
        if (method, path) == ("GET", "/rest/config/defaults/folder"):
            return self._send(200, {"id": "", "label": "", "path": "", "type": "sendreceive", "devices": []})
        if (method, path) == ("GET", "/rest/config/folders"):
            return self._send(200, STATE["folders"])
        if method in ("PUT", "PATCH") and path.startswith("/rest/config/folders/"):
            fid, body = path.rsplit("/", 1)[1], self._body()
            have = next((f for f in STATE["folders"] if f["id"] == fid), None)
            if method == "PUT":
                STATE["folders"] = [f for f in STATE["folders"] if f["id"] != fid] + [body]
            elif have is None:
                return self._send(404)
            else:
                have.update(body)
            return self._send(200)
        if (method, path) == ("GET", "/rest/system/connections"):
            return self._send(200, {"connections": {PHONE: {"connected": True}}})
        if path == "/rest/db/ignores":
            fid = query.split("=", 1)[1]
            if method == "POST":
                STATE["ignores"][fid] = self._body()["ignore"]
            return self._send(200, {"ignore": STATE["ignores"].get(fid, [])})
        return self._send(404, {"error": "no route"})

    def do_GET(self):  # noqa: N802
        self.handle_one("GET")

    def do_POST(self):  # noqa: N802
        self.handle_one("POST")

    def do_PUT(self):  # noqa: N802
        self.handle_one("PUT")

    def do_PATCH(self):  # noqa: N802
        self.handle_one("PATCH")

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=server.serve_forever, daemon=True).start()
KEYS = TMP / "keys.env"
PORT = server.server_address[1]


def write_keys(url, key=KEY):
    KEYS.write_text(f"SYNCTHING_GUI_URL={url}\nSYNCTHING_API_KEY={key}\n")


write_keys(f"http://127.0.0.1:{PORT}")
os.environ.update(LOAM_PLUGIN_KEYS=str(KEYS), LOAM_VAULT=str(VAULT))
sys.path.insert(0, str(HERE / "tools"))
import syncthing_core as core  # noqa: E402

results: list[bool] = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  | {detail}"))


s = core.status()
check("running, with this machine's ID", s["running"] and s["this_device_id"] == ME, s)
check("an unshared vault says what to do next", not s["vault_shared"] and "device's ID" in s["next"], s)
check("the supplied URL reaches the API on 127.0.0.1", SEEN and SEEN[0][1] == "/rest/system/status")

for address in (f"192.0.2.1:{PORT}", f"0.0.0.0:{PORT}", f"localhost:{PORT}",
                f"127.0.0.1.example:{PORT}", f"[::]:{PORT}",
                f"127.0.0.1@192.0.2.1:{PORT}", "127.0.0.1:65536"):
    write_keys(f"http://{address}")
    with patch.object(core.http.client, "HTTPConnection") as connect:
        s = core.status()
        check(f"{address} is refused before connecting",
              not s["running"] and "control address" in s["next"] and not connect.called, s)
write_keys(f"http://127.0.0.1:{PORT}", "old-fixture-key")
check("a rejected key says Loam will check the local settings", "Loam will check" in core.status()["next"])
write_keys(f"http://127.0.0.1:{PORT}")

with patch.dict(os.environ, {"http_proxy": f"http://127.0.0.1:{PORT}", "no_proxy": ""}):
    check("the API request goes straight to Syncthing even with a proxy set",
          core.status()["running"] and SEEN[-1][1] == "/rest/system/connections", SEEN)
try:
    core.call("GET", "/redirect")
    check("the client refuses a redirect", False)
except core.SyncthingError as exc:
    check("the client refuses a redirect", "HTTP 302" in str(exc) and SEEN[-1][1] == "/redirect", exc)

for bad in ("short", ME.replace("A", "1"), ""):
    try:
        core.pair(bad)
        check(f"a bad device ID {bad!r} is refused", False)
    except core.SyncthingError as exc:
        check(f"a bad device ID {bad!r} is refused", "eight groups" in str(exc), exc)
try:
    core.pair(ME)
    check("this machine's own ID is refused", False)
except core.SyncthingError as exc:
    check("this machine's own ID is refused", "own ID" in str(exc), exc)

out = core.pair(PHONE.lower().replace("-", " "), "Phone")
check("pairing adds the device, by its normal ID and name",
      out["device_added"] and any(d["deviceID"] == PHONE and d["name"] == "Phone" for d in STATE["devices"]), STATE)
check("and makes the vault a folder shared with both",
      out["folder_made"] and STATE["folders"][0]["path"] == str(VAULT)
      and [d["deviceID"] for d in STATE["folders"][0]["devices"]] == [ME, PHONE], STATE["folders"])
check("keeping .git out of it", STATE["ignores"].get("loam-vault") == [".git"], STATE["ignores"])
check("its next step names this machine's ID", ME in out["next"], out)

again = core.pair(PHONE, "Phone")
check("pairing again changes nothing", not again["device_added"] and not again["folder_made"]
      and len(STATE["devices"]) == 2 and len(STATE["folders"][0]["devices"]) == 2, STATE)

s = core.status()
check("status now: the vault is shared with the phone, which is connected",
      s["vault_shared"] and s["folders"][0]["is_vault"] and s["folders"][0]["shared_with"] == ["Phone"]
      and s["devices"] == [{"id": PHONE, "name": "Phone", "connected": True}], s)

# An existing vault folder (someone set it up by hand) is shared, not remade.
STATE["folders"] = [{"id": "abcd-1234", "label": "Notes", "path": str(VAULT) + "/", "devices": [{"deviceID": ME}]}]
out = core.pair(PHONE)
check("an existing vault folder is shared as it is",
      not out["folder_made"] and out["folder"] == "abcd-1234"
      and [d["deviceID"] for d in STATE["folders"][0]["devices"]] == [ME, PHONE], STATE["folders"])

out = core.unpair(PHONE)
check("unpairing stops sharing the vault", out["changed"]
      and [d["deviceID"] for d in STATE["folders"][0]["devices"]] == [ME], STATE["folders"])
check("and a second unpair changes nothing", not core.unpair(PHONE)["changed"])

# The MCP server end to end.
msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "syncthing_status", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "syncthing_pair", "arguments": {"device_id": "nope"}}}]
run = subprocess.run([sys.executable, str(HERE / "tools" / "syncthing_mcp.py")],
                     input="\n".join(json.dumps(m) for m in msgs) + "\n",
                     capture_output=True, text=True, timeout=30, env=os.environ)
answers = [json.loads(line) for line in run.stdout.splitlines()]
check("the tool lists its three tools",
      [t["name"] for t in answers[1]["result"]["tools"]] == ["syncthing_status", "syncthing_pair", "syncthing_unpair"], answers)
check("status answers through MCP", json.loads(answers[2]["result"]["content"][0]["text"])["this_device_id"] == ME)
check("a refusal is an error result with its sentence",
      answers[3]["result"].get("isError") and "eight groups" in answers[3]["result"]["content"][0]["text"], answers[3])

# Not running: the setup sentence, not a crash.
server.shutdown()
server.server_close()
s = core.status()
check("Syncthing not running says how to set it up", s == {"ok": True, "running": False, "next": core.SETUP}, s)
KEYS.unlink()
check("missing credentials take the owner to Loam’s API keys", core.status()["next"] == core.NO_KEY)

failed = results.count(False)
print(f"\n{len(results) - failed}/{len(results)} passed")
sys.exit(1 if failed else 0)
