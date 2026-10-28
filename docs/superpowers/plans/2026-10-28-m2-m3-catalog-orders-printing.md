# M2 Catalog + M3 Orders + Printing Implementation Plan

> Scope change (owner, 2026-10-28): MallT is **food and beverages only**, and it gets a
> **print agent** (KOT + customer bill). Supersedes the generic-retail parts of spec §6/§7.
> Reference implementation analysed: `Genrec-Community/tabble` → `print-agent/` (agent) and
> `backend/app/{ws/print_agent.py, services/print_queue.py, services/agents.py, services/dispatch.py,
> models/printing.py, schemas/print_layout.py, services/receipt_logo.py}` (server half).

**Goal:** a customer scans the mall QR, orders food/drinks from several stores, pays (fake
provider), each store sees the order live, the store's counter PC prints a KOT and a bill
automatically, and the customer collects with a 4-digit code.

**Execution:** native, inline (executing-plans), TDD, final whole-branch review. Same rules as
`AGENTS.md`. Order: Part A (M2) → Part B (M3) → Part C (printing). Each part ends with a verified,
committed state.

---

## What we take from Tabble, and what changes

| Tabble (hotel) | MallT (mall) | Why |
|---|---|---|
| `hotel_id` tenant | `organization_id` + `mall_id` + `store_id` | Our hierarchy. Printers, agents, templates and jobs are **per store**; a store's PC prints only that store's slips. |
| Kitchens, tables, dine-in/parcel | Store only; origin is always `PICKUP` | No tables, no delivery. KOT header shows pickup code + customer first name. |
| Bill = dine-in session bill | Bill = one **StoreOrder** (never the whole CustomerOrder) | Stores must never see other stores' items or MallT commission. |
| Printers configured by hand (connection + target typed in) | **Agent detects printers** and reports them; owner picks from a list | Owner's requirement: "detecting the printers". Tabble has no detection. |
| Win USB = shared queue path / COM | Adds an **OS print-queue transport** (Windows spooler RAW via `ctypes`/`winspool`, Linux `lp -o raw`) | Most Windows thermal printers are installed as a driver queue, not a share. Still zero third-party deps. |
| Logo in DB, dithered server-side with Pillow | Same | Printing must never wait on storage. Needs Pillow (approval, see Rulings). |
| Signed self-update + rollback + installers | Installers and pairing in Part C; **signed self-update is Task C9, last** | Large and needs a signing key we do not have yet. |
| Poll every 3 s over `/ws/print-agent`, lease 120 s, 10 attempts, ack-after-record idempotency | **Keep exactly** | Battle-tested; copy the design and its tests, not just the code. |
| JSON `payload` is structured, agent owns ESC/POS | **Keep** | Template/layout changes need no backend deploy. |

**Non-negotiables carried over from Tabble's AGENT.md:** agent dials out (no inbound ports); job
id is the idempotency key; record-then-ack; a kitchen slip has **no prices**; printing never
blocks ordering (dispatch is best-effort and transactional with the order, never awaited on a
printer); an agent never names its own tenant (store comes from the authenticated row); token is
`<agent_id>.<secret>`, argon2-hashed, shown once; probe flag for `--check`.

---

## Decisions to make for food and beverages (calls, overturnable)

1. **Food model.** Product (name, description, image, veg/non-veg/egg tag, allergens, prep
   minutes, GST rate) → **Variants** (size: Half/Full, Small/Large; ≥1) → **Option groups**
   (add-ons, e.g. "Extra cheese", min/max) with price deltas. Colour/SKU-style retail fields are
   dropped. Spec §6 is amended.
2. **Stock.** Default `MANUAL` (available/sold out), which is what kitchens use. `COUNTED` stays
   for limited items ("only 20 samosas"), reserved at checkout, committed on paid, released on
   failure/expiry — unchanged from spec.
3. **Availability windows.** Each product may be hidden outside given hours (breakfast menu). Store
   open/closed + "pause new orders" toggle.
4. **Prep time.** Product `prep_minutes`; order ETA = max over the store's items (+ queue factor
   later). Shown to the customer.
5. **Tax.** Prices are GST-inclusive paise; per-product rate (default 5%, beverages possibly 12/18)
   and a per-store GSTIN. Bill shows CGST/SGST split per rate like Tabble.
6. **Mall discovery categories** become food types ("Fast food", "Beverages", "Desserts",
   "Meals", "Bakery"), seeded, not free text.
7. **Payments** stay behind `PaymentProvider`; `FakePaymentProvider` marks the order paid at once
   (owner choice). Commission is computed and recorded (platform-only, bps on the order) even
   though nothing is settled.
8. **Print triggers (per store setting).** `kot_when`: `paid` or `accepted` (default `accepted`).
   `bill_when`: `accepted`, `ready`, `picked_up`, `manual` (default `ready`). Copies come from the
   printer layout. Auto-print can be switched off; "Reprint" button always works.

---

# Part A — M2 Food catalog and store settings

### Task A1: Catalog schema and migration
Tables (all carry `organization_id`, `mall_id`, `store_id`; PK uuid7; FK indexes):
`menu_categories` (per store, position, name), `products` (name, description, `diet`
veg/nonveg/egg, `allergens`, `prep_minutes`, `tax_bps`, `stock_mode`, `is_available`,
`image_key`, `category_id`, sort), `product_variants` (name, `price_paise`, `stock_count`,
`is_default`), `option_groups` (product-linked, `min_select`, `max_select`), `options`
(`price_delta_paise`), `availability_windows` (product, weekday mask, start/end local time),
`store_settings` (open/paused, accept timeout override, `gstin`, `fssai`, bill/KOT triggers,
timezone default Asia/Kolkata, `theme` JSON of design tokens, template id, banner/logo keys,
opening hours), `mall_food_types` (seeded), `store_food_types` join.
Tests: migration up/down, drift test, FK-index test, seed test.

### Task A2: Catalog service + API (store scope)
Repository/service/router per AGENTS.md. Endpoints: categories CRUD+reorder; products CRUD with
variants/options in one document; availability toggle (`store.stock.update`); presigned image
upload (`POST …/images/presign` → PUT key `org/{o}/store/{s}/products/{uuid}.webp`; API stores key
only; content-type + size limits in the presign).
Permissions: reuse `store.product.read/write`, `store.stock.update`. Cross-tenant 404 tests on
every endpoint; Store Staff can toggle stock but not edit prices.

### Task A3: Store settings, hours, pause, theme tokens
`PATCH /stores/{id}/settings` (profile/theme/hours/triggers). Theme = validated tokens only (colour
hex, font from curated list, template 1–3). Commission untouched (platform-only). Calls
`refreshMallPage` on the web side after change.

### Task A4: Public menu read API (customer)
`GET /public/malls/{slug}/stores` and `/public/stores/{id}/menu`: only available items, only
within windows, store open flag, prices/ETA. Cached (60 s, tag-purged by server action). No auth.
N+1 test (query-count assertion).

### Task A5: Store menu manager UI (plain)
`/store/menu`: categories, product form (variants, add-ons, diet tag, allergens, prep time, tax),
stock toggles, image upload via presigned PUT, store settings page. Generated client only.

### Task A6: Customer menu UI
`/m/[mallSlug]` lists stores by food type; `/m/[mallSlug]/s/[storeSlug]` menu with variant/add-on
picker and diet badges. Server components + small client island for add-to-cart. Budget check.

**Gate A:** full backend + frontend suites, contract in sync, e2e extended (owner creates store →
adds product → customer sees it).

---

# Part B — M3 Cart, checkout, orders, live updates

### Task B1: Orders schema and migration
`carts`/`cart_lines` (server-side, per customer+mall), `customer_orders` (one payment,
`total_paise`, `commission_bps`, `commission_paise`, `status`, `fulfilment_type='PICKUP'` check),
`store_orders` (per store, status enum per spec §7, `pickup_code`, `accept_by`, `ready_at`, totals,
`prep_eta`, customer first name + masked phone snapshot), `store_order_lines` (name/variant/options
snapshot, qty, unit paise, tax paise, note), `order_events` (append-only), `stock_reservations`,
`payments` + `ledger` skeleton owned by `payments` module (Fake only).

### Task B2: State machine
One `transition()` function: validates edge, writes `order_events`, emits domain event.
`PENDING_PAYMENT→PAID→ACCEPTED→PREPARING→READY→PICKED_UP`; `REJECTED/EXPIRED/CANCELLED→REFUNDED`.
Exhaustive transition-table test; direct status assignment forbidden (lint test greps for it).

### Task B3: Cart service/API
Add/update/remove lines, price re-computed server-side every time (client price ignored), refuses
closed/paused store, unavailable items, out-of-window items, wrong mall. Multi-store cart.

### Task B4: Checkout + FakePaymentProvider
Checkout splits cart into StoreOrders, reserves counted stock, computes tax + commission
(5% default per org, platform-editable), creates `CustomerOrder`, calls `PaymentProvider.charge`
(Fake → success) → `PAID` in one transaction. Failure path releases stock. Idempotency key on
checkout. Tests: split correctness to the paisa (sum of parts = total), stock race (two buyers, one
left), double-submit.

### Task B5: Store order handling + pickup code
Store lists/reads **only its own** StoreOrders (cross-tenant + cross-store 404 tests); accept /
reject / start / ready; 4-digit code unique among the store's open orders; `PICKED_UP` requires the
code, rate-limited via KV (5 tries / 10 min / order, 30 / 10 min / store); constant-time compare.
Accept-timeout sweeper (ARQ if Redis, else an in-process task started by the API lifespan) →
`EXPIRED` → refund via provider.

### Task B6: Real-time
WebSocket `/ws/orders` for store dashboard (new order, status) and customer order page. Fan-out via
Redis pub/sub when present, otherwise Postgres `LISTEN/NOTIFY` (keeps Redis optional). Auth = same
JWT as REST; subscribe scope enforced server-side. Reconnect + resync-on-open test.
SMS (Fast2SMS) only on "confirmed" and "ready"; masked phone in logs.

### Task B7: Store dashboard UI (live orders)
`/store/orders`: live board (New / Preparing / Ready), sound alert on new order, accept/reject with
reason, mark ready, "Enter pickup code" dialog, order detail, reprint buttons (wired in Part C).
Plain shadcn.

### Task B8: Customer cart / checkout / order page UI
Cart drawer (client island), checkout (fake pay), order page with per-store status cards, big
pickup code per store, live updates, cancel-before-accept.

### Task B9: Org/admin order views
Org owner/manager: orders across their stores (read), cancel with refund; platform admin read-only
overview. Cross-tenant tests.

**Gate B:** e2e: customer orders from two stores → both stores see only theirs → accept → ready →
pickup with code → customer sees PICKED_UP; refund path on reject.

---

# Part C — Printing (print agent + server queue + dashboard)

### Task C1: Server schema + queue
Port `models/printing.py` and `services/print_queue.py` adapted to store scope:
`print_agents` (store-scoped, argon2 token hash, prefix, `last_seen_at`, `version`),
`printers` (store-scoped; `role` KITCHEN|COUNTER, `connection` usb|lan|bluetooth|system,
`target`, `paper_width`, `layout` JSONB, `is_active`, `last_seen_at`, `detected_key` nullable),
`detected_printers` (agent-reported, replaced wholesale on each report),
`store_bill_settings` (header name/address/phone/extra, footer, `logo_png`, `options` JSONB),
`print_jobs` (`kind` ticket|bill|test, `store_order_id`, `revision`, partial unique index for
ticket per printer per revision, `payload`, status, attempts, lease timestamps).
Claim = `FOR UPDATE SKIP LOCKED`, lease 120 s, max 10 attempts, oldest first, scoped by `store_id`
taken from the authenticated agent. Tests ported: claim/lease/requeue/ack idempotent/failed retry/
cross-store isolation/inactive printer excluded.

### Task C2: Agent pairing + WebSocket `/ws/print-agent`
Port `services/agents.py` and `ws/print_agent.py` (probe flag, policy close code for every
refusal, `ready`, heartbeat, `pull`, `printed`/`failed`, in-flight set, requeue on disconnect).
**New frames:** agent→server `{"type":"printers","items":[…]}` after `ready` and on change;
server→agent `{"type":"scan_lan"}` / `{"type":"test"}` handled in C5. Nginx: `/ws/print-agent` with
upgrade headers, `proxy_read_timeout 3600s`. Permissions: add `store.printer.manage`
(Store Owner, Org Owner, Platform Admin; **not** Store Staff, who get `store.order.print`).
Tests: Tabble's `test_ws_print_agent.py` scenarios re-created for our fixtures.

### Task C3: Print dispatch + payloads
`dispatch.queue_kot(store_order)` / `queue_bill(store_order)` build structured payloads:
KOT = pickup code (big), customer first name, order number, time, ETA, items with variant + add-ons
+ notes + allergens, **no money**; bill = store header, GSTIN, invoice no, lines, subtotal,
CGST/SGST per rate, round-off, total, optional UPI QR later, footer, `copy_number` on reprints.
Never includes commission or other stores' lines. Called from the state machine hooks (per store
`kot_when`/`bill_when`) inside the order transaction; no printer = no job, order unaffected.
Reprint endpoints (`store.order.print`), copy counter. Tests: payload has no price keys on KOT;
bill totals equal order totals; rollback leaves no job.

### Task C4: Printer + template management API
List agents, pair (token shown once + install commands), rotate, revoke; list detected printers;
create printer from a detected one (or manual LAN IP:port); per-printer `PrinterLayout`
(font, text/heading/item sizes, spacing, margins, rule char, feeds, cut, copies, drawer, beep, bold
items — Tabble's schema verbatim) and bill settings with `SlipOptions` (show/hide fields, custom
labels). Logo upload: Pillow normalise → ≤256 KB greyscale PNG stored in DB, dithered per paper at
print time (port `receipt_logo.py`). `POST …/printers/{id}/test` queues a test job.

### Task C5: Print agent port (`print-agent/`)
Copy Tabble's `print_agent/` (client, render, layout, escpos, transports, store, config, lock,
`__main__`) with names changed to `mallt`, keep its tests and add ours. Changes:
- `render.py`: ticket/bill renderers adapted to pickup fields (`pickup_code`, `customer_name`,
  `eta_minutes`, `order_no`); remove table/dine-in labels; add `test` kind (prints printer name,
  width ruler, sample line, date).
- **Printer detection (`detect.py`, new, stdlib only):** Windows — `EnumPrintersW` via `ctypes`
  (installed queues, driver name, port, default flag) + `HKLM\HARDWARE\DEVICEMAP\SERIALCOMM` for COM
  ports; Linux — `lpstat -v` (CUPS queues), `/dev/usb/lp*`, `/dev/ttyUSB*`, `/dev/rfcomm*`;
  both — optional on-demand LAN scan of the local /24 for TCP 9100 (only when the dashboard asks,
  throttled, 300 ms connect timeout, 64 workers). Each result: `{key, name, connection, target,
  driver, is_default}`. Heuristics only rank likely thermal printers (name contains POS, TM-, RP,
  Epson, Xprinter, TSP, 58, 80); everything is listed.
- **`system` transport (`transports.py`):** Windows `OpenPrinter/StartDocPrinterW(datatype="RAW")/
  WritePrinter` via `ctypes`; Linux `lp -d NAME -o raw`. Same timeout/`TransportError` contract.
- Report detected printers to the server on connect and on a 60 s diff.
Tests: Tabble's suite adapted (render, layout, escpos, transports, store, client against a fake
server and a recording printer), plus detection parsers fed canned `lpstat` / EnumPrinters output,
and the system transport with an injected fake `winspool`. **No real Windows or hardware here →
reported as unverified.**

### Task C6: Dashboard UI — Printers
`/store/printers`: Agents (pair a PC, shown-once token, copy-paste install command for Windows and
Linux, last seen, version); **Detected printers** list with "Use as Kitchen / Counter printer" and
"Scan network"; printer cards (rename, role, paper 58/80 mm, active, last printed, **Test print**,
layout editor); error text from failed jobs.

### Task C7: Dashboard UI — Bill & KOT designer
`/store/printing/design`: header name/address/phone/GSTIN/FSSAI/extra, footer, logo upload (with
rendered black-and-white preview), paper width, show/hide switches, custom labels, font size
presets (small/normal/large mapped to layout scales), copies, auto-print rules (`kot_when`,
`bill_when`, on/off), **live preview** (a TS text-mode mock of the same layout rules, labelled
"approximate"; **Test print** is the true check). Mirrors Tabble's `layout-editor.tsx` /
`bill-settings.tsx` behaviour.

### Task C8: Installers + packaging
Port `packaging/{windows,linux}` (install/uninstall, run-agent supervisor, systemd unit,
rollback-guard), `build.sh/ps1`, PyInstaller entry. Windows: scheduled task at logon (so it sees the
user's printers). Install command generated by the dashboard embeds URL + token; token validated by
the character whitelist; `--check` gate. Linux tested here; Windows script reviewed + lint-only.

### Task C9: Signed self-update + rollback (last)
Port `updater.py`, `ed25519.py`, `trial.py`, `agent_releases`, `agent_updates` API, per-org switch
and rollback metric. Needs an Ed25519 release key generated by the owner (private key never in
git). Skipped if the owner prefers manual updates for now.

### Task C10: End-to-end
Real agent process (Linux, fake LAN printer = TCP listener capturing bytes) against the running
API: pair → detected list shows the fake printer → set as Kitchen → customer order → accepted → KOT
bytes captured and decoded (assert pickup code and items, no prices) → ready → bill bytes decoded
(assert totals/GST). Reconnect test: kill agent mid-job, restart, no duplicate (record file).
Plus Playwright for the dashboard flow.

**Gate C / milestone:** `make lint test e2e` green; independent whole-branch review; report with
"Rulings I made", deferred minors and the unverified list.

---

## Rulings (need your OK or an overrule)

- Pillow added as a backend dependency for logo processing (AGENTS.md says approval first).
- The logo upload goes through the API (small, normalised) instead of presigned PUT, because the
  server must process it. Everything else stays presigned-PUT.
- Approximate TS live preview + true Test print, instead of sharing the Python renderer.
- Self-update is last and optional.
- Windows spooler/ctypes code cannot be run in this Linux environment.

## Unverifiable here (will be reported as such)

Real thermal printer output, Windows spooler transport, Windows installer/scheduled task, USB/
Bluetooth transports, Docker image builds, Neon storage uploads.

## Self-review

Every Tabble guarantee maps to a task: idempotency (C1/C5), lease/attempts (C1), probe (C2),
no-money KOT (C3 test), tenancy (C1/C2 tests), printing-never-blocks-ordering (C3), detection (C5/C6),
template editing (C4/C7), installers (C8), updates (C9), end-to-end proof (C10).
