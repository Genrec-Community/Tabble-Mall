# MallT print agent

One small program per store PC. It connects **out** to MallT, receives kitchen tickets and bills for
that store, and prints them on the printers attached to that PC. Nothing else talks to a printer.
Design and reasoning are adapted from the Tabble print agent; the code is MallT's.

```
MallT API ──(outbound WebSocket)──> agent on the store PC ──┬── USB / serial printer
                                                            ├── LAN printer (port 9100)
                                                            ├── Bluetooth / COM printer
                                                            └── any installed printer (Windows spooler / CUPS, raw)
```

## Installing on a store PC

1. In the store dashboard: **Printers → Pair a PC**. Name it after where it sits. The token is shown
   **once**, with a ready-made install command for Windows and Linux.
2. Unzip the release folder for that OS, open a terminal in it and paste the command:

   ```
   powershell -ExecutionPolicy Bypass -File install.ps1 -Url https://… -Token …
   sudo bash install.sh --url https://… --token …
   ```

   It installs the program, writes `agent.toml`, confirms the server accepts the token, registers
   start-on-boot, starts the agent and prints **Printing is live**. Re-running it is the upgrade.
3. The agent lists the printers on the PC; back in the dashboard, pick which is the **kitchen** printer
   and which is the **bill** printer. Press **Test print** to check.

Nothing prints until an agent is paired and running. A printer on the network but not on the PC shows
up after **Scan network** (the dashboard asks the agent; it never scans on its own).

## What it does

* Detects printers (`detect.py`): Windows print queues and COM ports, Linux CUPS queues and device
  files; LAN scan on request.
* Renders **structured jobs** to ESC/POS (`render.py`, `escpos.py`, `layout.py`). A kitchen ticket
  carries no prices and no pickup code. Store owners control the design in the dashboard (header,
  footer, logo, labels, which lines show, text size, copies, cut, cash drawer).
* Prints each job **once**: the job id is recorded on disk after the paper is out and before the
  server is told (`store.py`); a redelivered job is acknowledged, not reprinted.
* Reconnects forever with jittered backoff; a printer that is off fails only its own jobs, which the
  server retries (lease 120 s, up to 10 attempts).

## Configuration (`agent.toml`, beside the program)

| Key | Default | Notes |
| --- | --- | --- |
| `url` | — | Required. The address you use in the browser (`https://` is rewritten to `wss://`). |
| `token` | — | Required. Shown once when you pair the PC. |
| `paper_width` | `32` | Fallback characters per line (the dashboard sets it per printer). |
| `print_timeout` | `20.0` | Seconds to wait for one printer before reporting the job failed. |
| `state_dir` | beside config | Holds `printed-jobs.log` — do not delete while the agent is stopped. |
| `verify_tls` | `true` | Only turn off for a self-signed proxy. |

Every key can also be an environment variable (`MALLT_AGENT_URL`, `MALLT_AGENT_TOKEN`, …).

## Printer addresses

| Connection | Looks like |
| --- | --- |
| Installed printer | the queue's name, e.g. `POS-80` |
| Network | `192.168.1.50` or `192.168.1.50:9100` |
| USB / serial | `/dev/usb/lp0`, `/dev/ttyUSB0` |
| Bluetooth | `COM3` (Windows) or a MAC address / `/dev/rfcomm0` (Linux) |

## Exit codes

`0` stopped (Ctrl-C) · `2` unusable config · `3` server refused the token (re-pair; do not restart) ·
`4` another agent already running here · `5` `--check` could not reach the server. Both supervisors
restart on anything except 0, 2, 3, 4.

## Development

```
cd print-agent
uv run --no-project --with websockets --with pytest --with pytest-asyncio python -m pytest
```

No printer and no server are needed. `build.sh` / `build.ps1` build the release on each OS
(PyInstaller cannot cross-compile). **Not yet built:** signed self-update.
