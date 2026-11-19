---
id: syncthing
name: Syncthing
version: 1.0.1
author: Michael Hejazi
api: 0
kind: [extension]
icon: assets/icon.svg
touches:
  network:
    - host: 127.0.0.1
      why: Talks to Syncthing's own control address on this machine, to read and change which devices share your vault
  record: write
  memory: write
  server: false
contributes:
  box.listener:
    - process: syncthing
      why: Your devices sync your vault with this machine over Syncthing's own port
  agent.tool:
    - name: syncthing
      run: python3 tools/syncthing_mcp.py
      lanes: [persona]
  agent.prompt:
    - lanes: [persona]
      text: "Your owner's vault can sync with their own devices over Syncthing (the Syncthing plugin). syncthing_status says whether it runs here, this machine's device ID, and which devices share the vault. To add a device, ask for its ID (Syncthing on it: Actions › Show ID) and, on their word, call syncthing_pair; then tell them what its answer's `next` says to do on the device."
---

# Syncthing

Keep your vault on your own phone and laptop, and have it sync with this
machine directly, with no cloud in between. [Syncthing](https://syncthing.net)
does the syncing; this plugin lets your agents set it up and tell you how it
is going.

**What you need.** Syncthing running on this machine as your own user, and
on each device you want the vault on. If it is not running here, ask an
agent: it will tell you the two commands (`sudo apt install syncthing`, then
`systemctl --user enable --now syncthing.service`).

**Adding a device.** Open Syncthing on the device, find its ID (Actions ›
Show ID), and give it to an agent: "share my vault with my phone, its ID is
…". The agent adds the device here, makes the vault a Syncthing folder if it
is not one yet (keeping `.git` out of it), and shares it. On the device you
accept this machine and the folder it offers, and choose where it lives.

**What it reaches.** The plugin's own code talks only to Syncthing's control
address on this machine (`127.0.0.1`), with the key in Syncthing's own
config. Syncthing then carries the whole vault both ways between this machine
and the devices you paired, conversation records and shared memory included,
which is why it declares that it reads and changes both. Loam is told that
Syncthing may answer off this machine, on its own port, so a drift check
does not report it.
