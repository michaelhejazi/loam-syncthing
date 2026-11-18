#!/usr/bin/env python3
"""The Syncthing tool for agents: a stdio MCP server with no dependencies
(JSON-RPC 2.0, one message per line). The work is syncthing_core.py's."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import syncthing_core as core  # noqa: E402

PROTOCOL = "2025-06-18"
ID = {"type": "string", "description": "The other device's ID, as Syncthing on it shows "
      "under Actions › Show ID (eight groups of seven letters and digits)."}
TOOLS = [
    {"name": "syncthing_status",
     "description": ("Whether the vault syncs with the owner's devices over Syncthing: "
                     "whether Syncthing runs here, this machine's device ID (the owner "
                     "adds it on a new device), the devices it knows and whether each is "
                     "connected, and its folders, marking the vault. When Syncthing is not "
                     "running, `next` says how to set it up."),
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "syncthing_pair",
     "description": ("Share the vault with one of the owner's devices: adds the device "
                     "to Syncthing here if it is new, makes the vault a Syncthing folder "
                     "if it is not one (keeping .git out), and shares it. Only on the "
                     "owner's word, with the ID they gave you. The answer's `next` is "
                     "what they do on the device."),
     "inputSchema": {"type": "object", "properties": {
         "device_id": ID,
         "name": {"type": "string", "description": "What to call the device, e.g. 'Phone'."}},
         "required": ["device_id"]}},
    {"name": "syncthing_unpair",
     "description": "Stop sharing the vault with a device. Only on the owner's word.",
     "inputSchema": {"type": "object", "properties": {"device_id": ID}, "required": ["device_id"]}},
]


def run(name: str, args: dict) -> dict:
    try:
        if name == "syncthing_status":
            return core.status()
        if name == "syncthing_pair":
            return core.pair(args.get("device_id"), args.get("name"))
        if name == "syncthing_unpair":
            return core.unpair(args.get("device_id"))
        return {"ok": False, "error": f"no tool {name!r}"}
    except core.SyncthingError as exc:
        return {"ok": False, "error": str(exc)}


def handle(msg: dict):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": (msg.get("params") or {}).get("protocolVersion") or PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "syncthing", "version": "1.0.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        out = run(params.get("name"), params.get("arguments") or {})
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=1)}],
            **({"isError": True} if not out.get("ok") else {})}}
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        out = handle(msg)
        if out is not None:
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
