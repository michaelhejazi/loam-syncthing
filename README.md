# Syncthing, a Loam plugin

Your vault syncs with your own devices over Syncthing, and your agents can
pair a new device and say whether syncing is working. What it does and what
it reaches is in [PLUGIN.md](PLUGIN.md), which is also its manifest.

- **Needs** Syncthing on this machine (run as your own user) and on each
  device. Nothing else: no key, no account.
- **No dependencies**: Python 3.11's standard library. `tools/syncthing_mcp.py`
  is the agents' tool (MCP over stdio); `tools/syncthing_core.py` talks to
  Syncthing's REST API on loopback, with the API key from its `config.xml`.
- **Tests**: `python3 tests/test_syncthing.py` runs it against a fake
  Syncthing, with no network.

Install it from Settings › Market, or from Settings › Plugins with this
folder's link at a tag.
