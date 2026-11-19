# Syncthing

Your Loam vault syncs with your own devices (your laptop, your phone) over
[Syncthing](https://syncthing.net), and your agents can pair a new device for
you and tell you whether syncing is working.

## What you need

Syncthing running on the machine Loam is on (as your own user) and on each
device you want the vault on. No key and no account: Syncthing is
peer-to-peer, and your files go only between your own devices.

## What it touches

- **Syncthing's own control address on this machine** (127.0.0.1), to read
  and change which devices share your vault. Nothing else on the network.
- **Your vault, both ways**: what a paired device changes arrives in the
  vault, threads and agents' memory included, and what changes here goes out.
- **Syncthing's transfer port**, which it declares so Loam's checks expect it.
- **A tool for your agents**, so they can pair a device and say how syncing
  is going.

## Getting it

In your Loam, open Settings › Market, find Syncthing, and press **Install**.
Or install it from Settings › Plugins with its link:

```
https://github.com/michaelhejazi/loam-syncthing/tree/v1.0.1
```

## For builders

[PLUGIN.md](PLUGIN.md) is its manifest. It needs only Python 3.11's standard
library: `tools/syncthing_mcp.py` is the agents' tool (MCP over stdio), and
`tools/syncthing_core.py` talks to Syncthing's REST API on loopback with the
API key from Syncthing's `config.xml`. `python3 tests/test_syncthing.py` runs
it against a fake Syncthing, with no network.

## Made by

Michael Hejazi. Under the AGPL-3.0 ([LICENSE](LICENSE)), as Loam is.
