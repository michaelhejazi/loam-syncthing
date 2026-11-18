"""What the Syncthing plugin does: read and change the local Syncthing's own
configuration through its REST API on this machine, so an agent can tell the
person whether their vault is syncing and pair a new device with it.

Standard library only. It talks to one address: Syncthing's control address
on this machine, read with its API key from Syncthing's own ``config.xml``.
It never contacts anything else and never reads the vault's files; Syncthing
itself moves them.

Environment (Loam gives every plugin process these):

- ``LOAM_VAULT``: the vault, the folder this plugin shares.
- ``SYNCTHING_CONFIG``: optional, Syncthing's ``config.xml`` when it is not
  in one of the usual places (tests, or a Syncthing run with ``--home``).
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

VAULT_FOLDER_ID = "loam-vault"
DEVICE_ID = re.compile(r"^[A-Z2-7]{7}(-[A-Z2-7]{7}){7}$")
SETUP = ("Syncthing is not running on this machine. To set it up: install it "
         "(on Debian or Ubuntu, `sudo apt install syncthing`), then start it as "
         "your own user with `systemctl --user enable --now syncthing.service`, "
         "and ask again.")


class SyncthingError(Exception):
    """Something the person or the agent can act on, in a sentence."""


def config_paths() -> list[Path]:
    env = os.environ.get("SYNCTHING_CONFIG")
    if env:
        return [Path(env)]
    home = Path.home()
    state = Path(os.environ.get("XDG_STATE_HOME") or home / ".local" / "state")
    conf = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    return [state / "syncthing" / "config.xml", conf / "syncthing" / "config.xml"]


def gui() -> tuple[str, str]:
    """Syncthing's control address (a URL) and its API key."""
    for path in config_paths():
        try:
            root = ET.parse(path).getroot()
        except FileNotFoundError:
            continue
        except (OSError, ET.ParseError) as exc:
            raise SyncthingError(f"Syncthing's config at {path} cannot be read ({exc})") from None
        node = root.find("gui")
        if node is None:
            raise SyncthingError(f"Syncthing's config at {path} has no control address")
        address = (node.findtext("address") or "127.0.0.1:8384").strip()
        key = (node.findtext("apikey") or "").strip()
        if not key:
            raise SyncthingError("Syncthing has no API key yet; open its web page once, or restart it")
        scheme = "https" if node.get("tls") == "true" else "http"
        host, _, port = address.rpartition(":")
        if host in ("0.0.0.0", "", "[::]", "::"):
            host = "127.0.0.1"
        return f"{scheme}://{host}:{port}", key
    raise SyncthingError(SETUP)


def call(method: str, path: str, body=None):
    base, key = gui()
    req = urllib.request.Request(base + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"X-API-Key": key, "Content-Type": "application/json"})
    # The control address is this machine's own; with TLS it is Syncthing's
    # self-signed certificate.
    ctx = ssl._create_unverified_context() if base.startswith("https") else None  # noqa: S323
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        said = exc.read().decode("utf-8", "replace").strip()[:200]
        raise SyncthingError(f"Syncthing answered {exc.code} for {path}: {said}") from None
    except (urllib.error.URLError, OSError):
        raise SyncthingError(SETUP) from None
    return json.loads(raw) if raw.strip() else None


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
