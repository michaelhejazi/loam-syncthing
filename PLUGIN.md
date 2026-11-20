---
id: syncthing
name: Syncthing
version: 1.1.0
author: Michael Hejazi
api: 0
kind: [extension]
description: "Your notes on your own phone and laptop, kept in sync with no cloud in between."
screenshots:
  - {src: assets/shots/syncthing-pair.webp, src_dark: assets/shots/syncthing-pair-dark.webp, caption: "Ask an agent to pair your phone; it tells you the two taps left."}
  - {src: assets/shots/syncthing-status.webp, src_dark: assets/shots/syncthing-status-dark.webp, caption: "Ask how syncing is going, any time."}
icon: assets/icon.svg
keys:
  - provider: syncthing
    why: Lets the plugin read and change which devices share your vault
    source:
      path: "~/.local/state/syncthing/config.xml"
      fallback: "~/.config/syncthing/config.xml"
      xml: gui/apikey
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

Keep your vault on your own phone and laptop, synced straight with this
machine, with no cloud in between. Syncthing does the syncing; this plugin
lets your agents set it up and tell you how it is going.

## What you can do

- **Pair a device by asking.** Give an agent your phone's Syncthing ID; it
  adds the device and shares your vault with it.
- **Know it's working.** Ask how syncing is going, any time.
- **No account, no cloud.** Your notes go only between your own devices.

## How to use it

1. Have Syncthing running on this machine and on your phone or laptop. If it
   isn't running here, ask an agent; it will tell you the two commands.
2. On your device, find its ID (Actions › Show ID) and give it to an agent:
   "share my vault with my phone, its ID is …".
3. On the device, accept this machine and the folder it offers.

---

## Technical details

The plugin's own code talks only to Syncthing's control address on this
machine (`127.0.0.1`). When you install, Loam reads the key and local GUI
address from Syncthing's settings on this server, as shown on the install
card. Loam saves the key in Settings › Connections › API keys and supplies
it to the plugin. Syncthing then
carries the whole vault both ways between this machine and the devices you
paired, conversation records and shared memory included, which is why it
declares that it reads and changes both. The vault becomes a Syncthing
folder with `.git` kept out. Loam is told that Syncthing may answer off this
machine, on its own port, so a drift check does not report it. To install
Syncthing here: `sudo apt install syncthing`, then
`systemctl --user enable --now syncthing.service`.
