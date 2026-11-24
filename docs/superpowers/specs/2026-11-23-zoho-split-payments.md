# Payments: Zoho Payments Split (M4)

Owner reopened payments on 2026-11-23 and chose **Zoho Payments** with split ("distributed")
payments. This replaces the Razorpay Route concept in the main spec §8; every rule in §8 still
holds (integer paise, signed + idempotent webhooks, append-only ledger, store must be onboarded
before it takes orders).

## Money model

**MallT keeps no money and pays no money** (owner decision, 2026-11-23). It takes no commission and
bears no fee, refunds included. Zoho Split still needs one platform account: the customer's single
payment lands there, and MallT immediately forwards all of it to the stores. That account's
balance should net to zero.

- The customer pays the **whole cart once** (one Zoho payment session per `CustomerOrder`).
- Each store is a Zoho **connected account** (its *payout account* in MallT).
- **As soon as the payment is confirmed** (owner decision), MallT transfers each store
  `total_paise − gateway_fee_paise` (Zoho `POST /transfers`, fixed amount, one per store order).
  Transfers run from the money outbox (below) seconds after the order is marked paid, rather than
  through the session's `transfer_details`, so every movement has an id MallT can reverse and
  reconcile.
- **The gateway fee is borne by the stores, pro-rata** (owner decision): each store pays
  `GATEWAY_FEE_BPS` (default 50 = 0.50%) of its **own** share, rounded half up. It is stored as
  `store_orders.gateway_fee_paise` and recorded in the ledger as `gateway_fee`. That amount stays
  in the platform account to cover Zoho's fee on the payment.
  - Example: a ₹10,000 cart split ₹5,000 / ₹3,000 / ₹2,000 costs those stores ₹25, ₹15 and ₹10.
  - Zoho's own per-transfer platform fee, if any, is deducted by Zoho from the transfer (Zoho
    behaviour), so the store bears that too.
- **The gateway fee is not refunded** (owner decision, 2026-11-24). On a refund the customer
  gets back what the store received, `total_paise − gateway_fee_paise`. Zoho keeps its fee, so
  neither MallT nor the store pays anything for a refund. This replaces the earlier `fee_owed`
  hold-back, which is no longer written (the ledger kind stays for old rows).
- The M3 commission setting is removed from the API and screens. Its columns are retired
  (migration 0010 makes them nullable; nothing reads or writes them) and a later migration drops them.
- **Refunds stay per StoreOrder.** Reject / expire / cancel refunds `total_paise − gateway_fee_paise`
  of that store order. If the store's transfer already ran, it is **reversed first** (Zoho
  `POST /transferreversals`; this debits the store's Zoho balance and can fail when it is too
  low, in which case the task retries and then waits for a person), then the customer is
  refunded. A transfer that had not run yet is simply cancelled. Other stores in the cart are untouched.

## Checkout flow (asynchronous)

1. `POST /malls/{slug}/checkout` creates the CustomerOrder (`placed`) and its StoreOrders
   (`pending_payment`), takes counted stock, and asks the provider to **start** a payment.
   - Fake provider: paid at once, exactly as in M3 (tests and local dev keep working).
   - Zoho: creates a payment session (`reference_number` = customer order id, expires 15 min)
     and returns widget parameters in `CustomerOrderOut.payment`.
2. The browser opens Zoho's widget (`zpayments.js`) and gets a `payment_id`.
3. `POST /orders/{id}/payment` `{payment_id}` — the server **fetches the payment from Zoho**
   and settles only if it succeeded, belongs to this session and matches the amount. The browser
   is never trusted.
4. The `payment.succeeded` webhook settles the same way (whichever arrives first wins; settling
   is idempotent under a row lock).
5. Unpaid orders are swept after the session expiry plus grace: the provider is asked once more
   (by reference); if still unpaid, the store orders become `payment_failed` and stock returns.
6. A payment that succeeds for an order already failed is refunded automatically, minus the gateway
   fee like any refund.

The cart is cleared when payment settles, not when checkout starts.

## Money outbox

Provider calls with side effects (transfer, reversal, refund) are written as `payment_tasks`
rows inside the order transaction and executed **after commit** (and retried by the sweeper with
backoff, `FOR UPDATE SKIP LOCKED`). Accepting or rejecting an order never waits on Zoho and never
fails because Zoho is down. Before retrying a task whose earlier attempt had an unknown outcome,
the worker checks Zoho (transfers by payment + account + description; refunds via the payment's
`amount_refunded`) so money never moves twice. Tasks that exhaust retries become `failed` and
are listed for the Platform Admin.

`StoreOrder.REFUNDED` means the refund is **queued irrevocably**; its completion is tracked on
the task and in the ledger.

## Ledger

`ledger_entries` is append-only: `charge`, `gateway_fee`, `transfer`,
`transfer_reversal`, `refund`, each with amount in paise, provider reference and the store order it belongs to.

## Payout accounts (store onboarding)

- `PUT /stores/{id}/payout-account` (`store.kyc.submit`: Store Owner, Org Owner): account name,
  email, PAN, MCC, business description, IFSC, bank account number. MallT creates the Zoho
  connected account and stores **only** its id, the account name, masked PAN / account number and
  status. Full PAN and account number are never stored or logged.
- `POST /stores/{id}/payout-account/refresh` re-reads status from Zoho (`under_writing_status`,
  `transfer_status`). The account is `active` only when Zoho enables transfers.
- `GET /admin/payout-accounts` (`platform.kyc.approve`) lists every account and failed money task.
- With the Zoho provider, checkout refuses carts containing a store without an active payout
  account (`store_not_payable`).

## Webhook

`POST /api/v1/payments/zoho/webhook`. Verified with `X-Zoho-Webhook-Signature`
(`t=<ts>,v=<hex>`; HMAC-SHA256 of `"{t}.{raw body}"` with the webhook signing key), rejected if
the timestamp is older than 5 minutes, deduplicated by `event_id`. Handles `payment.succeeded`,
`payment.failed`, `transfer.success|failed`, `transfer_reversal.success|failed`,
`refund.succeeded|failed`; ignores the rest with 200.

## Config

`PAYMENTS_PROVIDER` (`fake` | `zoho`, default `fake`), `ZOHO_ACCOUNT_ID`, `ZOHO_CLIENT_ID`,
`ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN` (offline OAuth, ORG client, scopes
`ZohoPay.payments.CREATE,READ`, `ZohoPay.refunds.CREATE,READ`, `ZohoPay.transfers.CREATE,READ`,
`ZohoPay.connectedaccounts.CREATE,READ`), `ZOHO_API_KEY` (widget key), `ZOHO_WEBHOOK_SIGNING_KEY`,
`ZOHO_SANDBOX`. Access tokens are cached in `KV` (Redis optional).

## Zoho prerequisites (owner)

- Ask Zoho support to enable **Split** on the account (20 connected accounts by default; ask for
  more).
- Create the webhook in Zoho (Settings → Developer Space) pointing at the URL above.

## Unknowns (inferred, verify in sandbox)

- Amounts are sent and read as **rupees with two decimals**; MallT converts from paise with
  integer arithmetic only.
- Whether a transfer can be made before the payment settles (docs are silent; failures retry).
- Webhook digest encoding is hex (sample looks hex); retry policy undocumented.
