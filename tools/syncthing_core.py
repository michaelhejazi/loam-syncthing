"""What the Syncthing plugin does: read and change the local Syncthing's own
configuration through its REST API on this machine, so an agent can tell the
person whether their vault is syncing and pair a new device with it.

Standard library only. It talks to one address: Syncthing's control address
on this machine, supplied with its API key by Loam.
It never contacts anything else and never reads the vault's files; Syncthing
itself moves them.

Environment (Loam gives every plugin process these):

- ``LOAM_VAULT``: the vault, the folder this plugin shares.
- ``LOAM_PLUGIN_KEYS``: the file Loam writes with the declared provider key
  and the local GUI URL.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import ssl
from pathlib import Path

VAULT_FOLDER_ID = "loam-vault"
DEVICE_ID = re.compile(r"^[A-Z2-7]{7}(-[A-Z2-7]{7}){7}$")
SETUP = ("Syncthing is not running on this machine. To set it up: install it "
         "(on Debian or Ubuntu, `sudo apt install syncthing`), then start it as "
         "your own user with `systemctl --user enable --now syncthing.service`, "
         "and ask again.")
NO_KEY = ("Loam has not supplied a Syncthing API key yet. Make sure Syncthing’s "
          "GUI is running on 127.0.0.1 and check Settings › Connections › API keys.")


class SyncthingError(Exception):
    """Something the person or the agent can act on, in a sentence."""


def gui() -> tuple[int, bool, str]:
    """Syncthing's loopback port, TLS setting and API key."""
    path = os.environ.get("LOAM_PLUGIN_KEYS")
    if not path:
        raise SyncthingError(NO_KEY)
    try:
        values = dict(line.split("=", 1) for line in Path(path).read_text().splitlines()
                      if "=" in line and not line.startswith("#"))
    except (OSError, UnicodeError):
        raise SyncthingError(NO_KEY) from None
    key = values.get("SYNCTHING_API_KEY")
    if not key:
        raise SyncthingError(NO_KEY)
    url = values.get("SYNCTHING_GUI_URL") or "http://127.0.0.1:8384"
    target = re.fullmatch(r"(https?)://127\.0\.0\.1:([0-9]{1,5})", url)
    if not target or not 1 <= int(target[2]) <= 65535:
        raise SyncthingError("Syncthing's control address must use 127.0.0.1 and a valid port")
    return int(target[2]), target[1] == "https", key


def call(method: str, path: str, body=None):
    port, tls, key = gui()
    # Use a direct connection to the declared IP. HTTPConnection does not
    # use proxies or follow redirects.
    if tls:
        # Syncthing's loopback GUI can use a self-signed certificate.
        connection = http.client.HTTPSConnection(
            "127.0.0.1", port, timeout=15, context=ssl._create_unverified_context())  # noqa: S323
    else:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        connection.request(method, path, body=None if body is None else json.dumps(body).encode(),
                           headers={"X-API-Key": key, "Content-Type": "application/json"})
        with connection.getresponse() as response:
            if response.status in (401, 403):
                raise SyncthingError("Syncthing rejected its API key. Loam will check its local "
                                     "settings again. Try again in a few minutes.")
            if not 200 <= response.status < 300:
                raise SyncthingError(f"Syncthing answered HTTP {response.status} for {path}")
            raw = response.read()
    except (http.client.HTTPException, OSError):
        raise SyncthingError(SETUP) from None
    finally:
        connection.close()
    try:
        return json.loads(raw) if raw.strip() else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SyncthingError(f"Syncthing returned an unreadable response for {path}") from None


def vault() -> Path | None:
    raw = os.environ.get("LOAM_VAULT")
    return Path(raw).expanduser().resolve() if raw else None


def _same(a: str, b: Path | None) -> bool:
    try:
        return b is not None and Path(a).expanduser().resolve() == b
    except OSError:
        return False


def normal_id(device_id: str) -> str:
    raw = re.sub(r"[\s-]", "", str(device_id or "")).upper()
    pretty = "-".join(raw[i:i + 7] for i in range(0, len(raw), 7))
    if not DEVICE_ID.match(pretty):
        raise SyncthingError("a device ID is 56 letters and digits in eight groups, "
                             "as Syncthing shows it under Actions › Show ID on that device")
    return pretty


def status() -> dict:
    """Whether Syncthing runs, this machine's device ID, its devices and
    folders, and which folder is the vault."""
    try:
        me = call("GET", "/rest/system/status")["myID"]
    except SyncthingError as exc:
        return {"ok": True, "running": False, "next": str(exc)}
    devices = call("GET", "/rest/config/devices") or []
    folders = call("GET", "/rest/config/folders") or []
    try:
        connections = (call("GET", "/rest/system/connections") or {}).get("connections") or {}
    except SyncthingError:
        connections = {}
    names = {d["deviceID"]: d.get("name") or d["deviceID"][:7] for d in devices}
    v = vault()
    out_folders = []
    for f in folders:
        out_folders.append({
            "id": f["id"], "label": f.get("label") or f["id"], "path": f.get("path"),
            "is_vault": _same(f.get("path") or "", v), "paused": bool(f.get("paused")),
            "shared_with": [names.get(d["deviceID"], d["deviceID"][:7])
                            for d in f.get("devices") or [] if d["deviceID"] != me]})
    out_devices = [{"id": d["deviceID"], "name": names[d["deviceID"]],
                    "connected": bool((connections.get(d["deviceID"]) or {}).get("connected"))}
                   for d in devices if d["deviceID"] != me]
    shared = any(f["is_vault"] and f["shared_with"] for f in out_folders)
    return {"ok": True, "running": True, "this_device_id": me, "vault": str(v) if v else None,
            "vault_shared": shared, "folders": out_folders, "devices": out_devices,
            "next": None if shared else (
                "The vault is not shared with any device yet. Ask for the device's ID "
                "(Syncthing on it: Actions › Show ID) and pair it.")}


def pair(device_id: str, name: str | None = None) -> dict:
    """Add a device (if Syncthing does not know it) and share the vault with it,
    making the vault a Syncthing folder first if it is not one."""
    did = normal_id(device_id)
    v = vault()
    if v is None or not v.is_dir():
        raise SyncthingError("this plugin shares the vault, and LOAM_VAULT names no folder")
    me = call("GET", "/rest/system/status")["myID"]
    if did == me:
        raise SyncthingError("that is this machine's own ID; give the ID of the other device")
    devices = call("GET", "/rest/config/devices") or []
    added = False
    if not any(d["deviceID"] == did for d in devices):
        device = call("GET", "/rest/config/defaults/device") or {}
        device.update({"deviceID": did, "name": (name or "").strip()[:64] or did[:7]})
        call("POST", "/rest/config/devices", device)
        added = True
    folders = call("GET", "/rest/config/folders") or []
    folder = next((f for f in folders if _same(f.get("path") or "", v)), None)
    made = False
    if folder is None:
        if any(f["id"] == VAULT_FOLDER_ID for f in folders):
            raise SyncthingError(f"Syncthing has a folder {VAULT_FOLDER_ID!r} somewhere else; "
                                 f"the vault is {v}")
        folder = call("GET", "/rest/config/defaults/folder") or {}
        folder.update({"id": VAULT_FOLDER_ID, "label": "Vault", "path": str(v),
                       "devices": [{"deviceID": me}, {"deviceID": did}]})
        call("PUT", f"/rest/config/folders/{VAULT_FOLDER_ID}", folder)
        made = True
        # A vault kept in git: its history stays on this machine.
        try:
            ignores = (call("GET", f"/rest/db/ignores?folder={VAULT_FOLDER_ID}") or {}).get("ignore") or []
            if ".git" not in ignores:
                call("POST", f"/rest/db/ignores?folder={VAULT_FOLDER_ID}", {"ignore": [*ignores, ".git"]})
        except SyncthingError:
            pass
    elif not any(d["deviceID"] == did for d in folder.get("devices") or []):
        call("PATCH", f"/rest/config/folders/{folder['id']}",
             {"devices": [*(folder.get("devices") or []), {"deviceID": did}]})
    return {"ok": True, "device": did, "device_added": added, "folder": folder["id"],
            "folder_made": made, "this_device_id": me,
            "next": ("On the other device, add this machine by its ID "
                     f"({me}) if it has not asked already, then accept the "
                     f"folder it offers ({folder.get('label') or folder['id']}) and choose "
                     "where it lives there. Syncing starts when both have said yes.")}


def unpair(device_id: str) -> dict:
    """Stop sharing the vault with a device (the device itself stays known)."""
    did = normal_id(device_id)
    v = vault()
    folders = call("GET", "/rest/config/folders") or []
    folder = next((f for f in folders if _same(f.get("path") or "", v)), None)
    if folder is None or not any(d["deviceID"] == did for d in folder.get("devices") or []):
        return {"ok": True, "device": did, "changed": False}
    call("PATCH", f"/rest/config/folders/{folder['id']}",
         {"devices": [d for d in folder["devices"] if d["deviceID"] != did]})
    return {"ok": True, "device": did, "changed": True, "folder": folder["id"]}
