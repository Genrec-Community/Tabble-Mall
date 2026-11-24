# Run MallT on your own computer (no Docker)

## Start

Double-click **`start.bat`**.

- The first run downloads everything MallT needs into `local\tools`: Python, Node.js and a
  portable PostgreSQL, about 150 MB. Nothing is installed on Windows itself, and no admin rights
  are needed. This takes a few minutes. Later starts take about 30 seconds.
- When it's ready, the customer page opens in your browser.
- **Keep the window open while you use MallT.** Close it, or press Ctrl+C, to stop.

You need Windows 10 or 11 and an internet connection for the first run. On macOS or Linux, run
`./start.sh` instead. That needs [uv](https://docs.astral.sh/uv/) and Node 22 installed.

| File | What it does |
|---|---|
| `start.bat` | Starts MallT. The demo mall is added on the first run. |
| `show-otp.bat` | Shows customer sign-in codes. Locally no SMS is sent. |
| `stop.bat` | Only needed if MallT was closed abruptly and won't start again. |
| `stop.bat reset` | Deletes all local data. The next start begins fresh with the demo mall. |
| `demo-logins.txt` | The demo logins. It's written on the first run. |
| `local\logs\` | Logs for the API, website and database, if something looks wrong. |

## Try the whole journey

Every staff password is `MallT-demo-2026`.

1. **Customer:** open http://localhost:8080/m/demo-mall and add items from both Burger Hub and
   Chai Point. Sign in with any 10-digit mobile number. The code comes from `show-otp.bat`.
   Pay, and you get one order with a pickup code for each store.
2. **Store:** in another browser or a private window, sign in at http://localhost:8080/login
   as `burger.owner`. The order appears live. Accept it, then Start preparing, then Mark ready.
3. **Pickup:** click the collect button and type the customer's pickup code for Burger Hub.
4. **Org owner:** `demo.owner` sees every store, mall and staff member.
5. **Platform admin:** `admin` also needs a code from an authenticator app. The key is in
   `demo-logins.txt`.

## Payments

Locally, payments use the **fake provider**. Pressing pay marks the order paid at once and records
each store's share, its 0.50% gateway fee and the transfer in the ledger. No money moves and no
Zoho account is needed.

To try real Zoho sandbox payments:

1. Fill in the `ZOHO_*` values in `.env` and set `PAYMENTS_PROVIDER=zoho`.
2. Restart MallT.
3. Each store adds its bank account on its **Payouts** tab and waits for Zoho to approve it.
   Until then, checkout refuses that store's items.

## How it works

`local\run_local.py` starts each part itself:

- PostgreSQL, from the `pgserver` package, on port 55433 with its data in `local\data`
- the API on port 8000
- the website on port 3000
- a small proxy on **8080**, which does nginx's job

Ports 8000, 3000 and 8080 must be free.
