# Run MallT on your own computer

## Once

1. Install **Docker Desktop**: https://www.docker.com/products/docker-desktop/
2. Start Docker Desktop and wait until it says *Engine running*.

## Every time

| Do | What happens |
|---|---|
| Double-click **`start.bat`** | Builds and starts everything, adds the demo mall, opens the customer page. The first run takes 5 to 15 minutes. |
| **`show-otp.bat`** | Shows customer sign-in codes. No SMS is sent locally. |
| **`logs.bat`** | Live logs of every part, for when something looks wrong. |
| **`stop.bat`** | Stops MallT and keeps your data. |
| **`stop.bat reset`** | Stops MallT and deletes all data, so the next start is fresh. |

On macOS or Linux, run `./start.sh` instead.

## Try the whole journey

Logins are printed by `start.bat` and saved in `demo-logins.txt`. Every staff password is
`MallT-demo-2026`.

1. **Customer:** open http://localhost:8080/m/demo-mall and add items from both Burger Hub and
   Chai Point. Sign in with any 10-digit mobile number. The code comes from `show-otp.bat`.
   Pay, and you get one order with a pickup code for each store.
2. **Store:** in another browser (or a private window), sign in at http://localhost:8080/login
   as `burger.owner`. The order shows up live. Accept it, mark it Preparing, then Ready.
3. **Pickup:** enter the customer's pickup code on the store's order to mark it picked up.
4. **Org owner:** `demo.owner` sees every store, mall and staff member.
5. **Platform admin:** `admin` also needs a code from an authenticator app. The key is in
   `demo-logins.txt`.

## Payments

Locally, payments use the **fake provider**. Pressing pay marks the order paid at once and records
each store's share, its 0.50% gateway fee and the transfer in the ledger. No money moves and no
Zoho account is needed.

To try real Zoho sandbox payments, fill in the `ZOHO_*` values in `.env`, set
`PAYMENTS_PROVIDER=zoho`, then run `stop.bat` and `start.bat`. With Zoho on, each store must first
add its bank account on its **Payouts** tab and be approved by Zoho, or checkout refuses its items.

## Also works locally

- **Printing:** the store's **Printers** tab pairs the desktop print agent (`print-agent/`) on the
  same PC, with KOT and bill printing.
- **Product photos** upload to the shared dev bucket in `.env`, so they need internet.

## Ports

The website is on **8080**. If something else uses that port, stop it first.
