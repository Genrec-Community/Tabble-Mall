"""The local print agent: one small program per store PC.

It dials out to the server, receives structured print jobs, renders them to ESC/POS
and acknowledges each one by job id. Nothing else in the system talks to a printer.

Why it exists at all: a restaurant's network is a domestic router with no static IP and
no port forwarding, so the server cannot reach a printer. This app makes the one
connection that can be relied on -- outbound -- and everything else follows from that.

The modules, in the order a job passes through them:

- `config`  - the server URL and the pairing token, from a TOML file beside the binary.
- `client`  - the socket, the reconnect loop, and the print-or-skip decision.
- `store`   - what has already come out of a printer, on disk. AGENT.md rule 9.
- `render`  - structured payload to ESC/POS bytes, for the two job kinds.
- `escpos`  - the control bytes themselves.
- `transports` - USB, LAN and Bluetooth, chosen by what the server sent with the job.
"""

from __future__ import annotations

#: Sent nowhere and compared against nothing -- the server does not negotiate an agent
#: version, because a store PC updates when someone gets round to it and a server that
#: refused old agents would stop a kitchen printing. It is here to appear in logs and
#: in `--help`, so a support conversation can establish what is actually installed.
__version__ = "0.1.0"
