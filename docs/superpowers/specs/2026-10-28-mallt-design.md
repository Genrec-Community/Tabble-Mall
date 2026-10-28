# MallT — Product & Architecture Design

- **Status:** Draft for approval
- **Date:** 2026-10-28
- **Repo:** `Tabble-Mall` · **Product name:** MallT

Decisions marked **(owner)** were made by the product owner during planning.
Decisions marked **(call)** are engineering defaults chosen by the agent with a
stated reason; they can be overturned.

---

## 1. Intent

MallT lets a customer walking through a shopping mall scan **one QR code**,
browse the products of **every store in that mall** (food, clothing, anything),
put items from several stores into **one cart**, **pay once**, and then collect
each item at the store's counter by showing a **4-digit pickup code** on their
phone. Think Swiggy/Zomato, but scoped to a single mall and built around
pickup.

MallT earns a **commission (default 5%)** on each order. The payment is split
automatically: each store's share goes straight to that store's bank account
and MallT's commission goes to MallT's account. The split uses
**Razorpay Route**. Payments are **on hold** and will be designed in detail
later (see §8).

### Why it matters

- Customers don't have to queue at each shop or carry cash. They browse
  everything from one place.
- Stores get a digital ordering channel without building their own app.
- Mall operators get a modern experience they can offer their tenants.

### What success looks like

Ordering is fast and reliable at lunch-hour peak. A store never loses or
misses an order. Money always reconciles. Onboarding a new mall and its stores
takes minutes and needs no engineering work.

---

## 2. Goals, non-goals, anti-goals

### Goals (v1)

- Multi-tenant hierarchy: **Organization → Malls → Stores** **(owner)**.
- **IAM first** **(owner)**: platform admin, org owners, org managers, store
  owners, store staff, customers. Includes role-based access control with
  premade roles.
- One QR per mall that opens a mobile-first web app. There is no native
  app **(owner)**.
- Catalog: products with **variants** (size/colour, each with its own price,
  SKU and stock) and **option groups** (food add-ons) **(owner)**.
- Stock tracking, chosen per product: counted stock or a manual
  in-stock/out-of-stock toggle **(owner)**.
- A multi-store cart paid in a single payment, split into one store order per
  store **(owner)**.
- **Pickup only**. Each store order has a 4-digit pickup code that the store
  verifies **(owner)**.
- A real-time store dashboard: new orders arrive instantly with a sound
  alert, and the customer's order page updates live **(owner)**.
- Store theming: design tokens (logo, banner, colours, font) plus 2–3 fixed
  layout templates **(owner)**.
- Automatic per-store refunds when a store rejects an order or doesn't accept
  it in time **(owner)**.
- GST-inclusive pricing, with a per-product tax rate and a per-store invoice
  **(owner, to be confirmed with a CA)**.

### Non-goals (v1, may come later)

- **Delivery** of any kind **(owner)**. Orders still carry a
  `fulfilment_type` field (only `PICKUP` allowed for now) so delivery can be
  added without a redesign.
- Native iOS/Android apps.
- WhatsApp notifications, loyalty points, coupons, reviews and ratings.
- Custom roles defined by org owners. The schema supports them, but there is
  no UI.
- Custom CSS or a page builder for stores.
- Microservices.

### Anti-goals (a failure even if it "works")

- Showing a customer as paid when the store never received the order, or the
  reverse.
- One tenant's staff seeing or changing another tenant's data.
- Slow customer pages on a 4G phone. The QR-to-menu page must be fast.
- Money stored as floats, or the same payment webhook processed twice.

---

## 3. Actors & roles

| Actor | Who | How they get access |
|---|---|---|
| **Platform Admin** | The MallT team | Seeded / created by another platform admin |
| **Org Owner** | Company that runs one or more malls | Account created by a Platform Admin (username + password handed over) |
| **Org Manager** | Helps run the org; no billing/commission/ownership powers | Created by Org Owner |
| **Store Owner** | Runs one store (or several) inside a mall | Created by Org Owner / Org Manager |
| **Store Staff** | Cashier/kitchen; handles orders only | Created by Store Owner (or above) |
| **Customer** | Shopper in the mall | Self sign-up: Google or phone OTP |

**Staff identities and customer identities are separate (call).** They live in
different tables, use different login flows and have different security
requirements. A person who is both a store owner and a shopper has two
accounts. This rules out a whole class of privilege bugs.

---

## 4. Tenancy model

```
Platform
└── Organization            (e.g. "Phoenix Group")
    └── Mall                (e.g. "Phoenix Marketcity Pune")  ← one QR
        └── Store           (e.g. "Burger Hub", "Zara")
            ├── Products → Variants, Option Groups
            └── Store Orders
```

- An org can have **many malls** **(owner)**. If an org has a single mall,
  the UI can hide the mall level.
- Every tenant-owned row carries its owning `organization_id`. Store-owned
  rows also carry `mall_id` and `store_id`. This keeps authorization checks
  and indexes simple.
- **Commission %** is configurable per organization, with an optional
  per-store override **(call; stored now, used when payments land)**.
- **Customers are global.** One MallT account works in every mall.

---

## 5. IAM (Milestone 1, the first thing we build)

### 5.1 Authentication

**Staff (all roles except customer)** **(owner)**

- Login with a **username and password**. Email is optional and used for
  password reset notices.
- Usernames are **globally unique and case-insensitive**: lowercase
  `[a-z0-9._-]`, 3–40 characters **(call)**.
- A Platform Admin creates an Organization together with its first Org Owner
  account. A temporary password is shown once, and the owner must change it
  at first login **(call)**.
- Passwords are hashed with **Argon2id**.
- **Mandatory TOTP 2FA** for Platform Admin. Optional TOTP 2FA for Org
  Owner **(call)**.
- Password reset happens through the parent scope: a platform admin resets
  an org owner, an org owner or manager resets a store owner, and a store
  owner resets staff. Self-service email reset is an optional later addition
  **(call; avoids depending on an email provider in v1)**.
- Accounts can be suspended. A suspended account loses access immediately.

**Customers** **(owner)**

- **Phone OTP**:
  - The backend generates a 6-digit OTP and sends it with **Fast2SMS**.
  - The OTP is stored **hashed in Redis** with a 5-minute TTL.
  - At most 5 verification attempts are allowed.
  - Sending is rate-limited per phone number and per IP address.
- **Google login**: the frontend uses Google Identity Services, and the
  backend verifies the Google ID token. No Firebase dependency is needed for
  this **(call; the auth provider sits behind an interface, so Firebase can
  be swapped in if wanted)**.
- Browsing is anonymous. Login is required only at checkout.
- **A verified phone number is the customer's identity key (call):**
  - A customer who signs in with Google must verify a phone number by OTP
    once, before their first checkout. Orders, SMS and payments all need it.
  - If that phone already belongs to another account, the Google identity is
    **linked** to the existing account, not duplicated.
  - Each phone number maps to exactly one customer account.

**Tokens (both identity types)** **(call)**

- The backend issues its own **JWT access token** (15 min) and a
  **refresh token** (30 days for customers, 12 hours for staff). The refresh
  token is rotating, stored hashed in Postgres, and sent as an
  `httpOnly; Secure; SameSite=Lax` cookie.
- Refresh tokens rotate on every use. If an old refresh token is reused, the
  backend revokes that whole token family.
- The token carries `sub`, `identity_type` (`staff` | `customer`) and a
  session id. **Permissions are never baked into the token.** They are
  resolved per request (cached in Redis for 60 s and busted on role change),
  so revoking a role takes effect immediately.

### 5.2 Authorization: RBAC with scopes

- **Permissions** are fine-grained strings defined in code, for example
  `store.product.write`.
- **Roles** are named bundles of permissions. Each role has a `scope_type`
  (`platform` | `organization` | `mall` | `store`).
- A **role assignment** is `(staff_user, role, scope_type, scope_id)`.
- **Inheritance:** a permission granted at a scope applies to everything
  beneath it (platform ⊃ org ⊃ mall ⊃ store).
- **Anti-escalation rule:** a user can assign a role only if
  1. they hold every permission in that role, at a scope that contains the
     target scope, and
  2. they have `*.staff.manage` at that scope.
- **Every authorization check** has the form
  `can(user, permission, resource_scope)`. It is enforced in the service
  layer, not only in the router, and is covered by tests for cross-tenant
  access.

**Premade (system) roles** **(owner)**: these are seeded and can't be edited
in v1.

| Permission | Platform Admin | Org Owner | Org Manager | Store Owner | Store Staff |
|---|:-:|:-:|:-:|:-:|:-:|
| `platform.org.manage` (create/suspend orgs) | ✅ | | | | |
| `platform.kyc.approve` | ✅ | | | | |
| `org.settings.update` | ✅ | ✅ | | | |
| `org.billing.manage` (commission, payouts) | ✅ | ✅ | | | |
| `org.mall.manage` | ✅ | ✅ | ✅ | | |
| `org.store.manage` (create/suspend stores) | ✅ | ✅ | ✅ | | |
| `org.staff.manage` | ✅ | ✅ | ✅* | | |
| `store.profile.update` / `store.theme.update` | ✅ | ✅ | ✅ | ✅ | |
| `store.product.write` | ✅ | ✅ | ✅ | ✅ | |
| `store.product.read` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `store.stock.update` (toggle in/out of stock) | ✅ | ✅ | ✅ | ✅ | ✅ |
| `store.order.read` / `store.order.update` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `store.order.verify_pickup` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `store.order.cancel` (after acceptance → refund) | ✅ | ✅ | ✅ | ✅ | |
| `store.kyc.submit` | ✅ | ✅ | | ✅ | |
| `store.staff.manage` | ✅ | ✅ | ✅ | ✅ | |
| `store.report.read` | ✅ | ✅ | ✅ | ✅ | |
| `audit.read` | ✅ | ✅ | | | |

\* An Org Manager can't create or assign the Org Owner or Org Manager roles.
This follows from the anti-escalation rule.

### 5.3 Audit log

Every mutation made by a staff member writes an **append-only audit row**:
actor, action, target, scope, before/after diff, IP address and request id.
Org Owners can read their org's log. Platform Admins can read all logs.

### 5.4 Milestone 1 deliverables

- A seed command that creates the first Platform Admin.
- CRUD for Organizations (platform admin), Malls and Stores (as entities: name,
  slug, status, basic profile).
- Staff user management, role assignment, suspension and password reset, all
  following the rules above.
- Customer sign-up and login (phone OTP + Google) and a customer profile.
- Session management: list sessions, log out everywhere.
- The audit log.
- Dashboards in Next.js:
  - `/admin`: orgs, org owners, audit.
  - `/org`: malls, stores, staff, roles, audit.
  - `/store`: staff management, profile placeholder.
- A customer login screen.

---

## 6. Catalog & store theming (later milestone; captured now)

- **Product** → one or more **Variants**. Each variant has its own SKU, price
  (paise, GST-inclusive), tax rate, stock mode and stock count. A "simple"
  product is just a product with exactly one variant.
- **Option groups** (food add-ons): a group like "Extras" has min/max
  selections and options, each with a price delta.
- **Stock mode per product** **(owner)**:
  - `COUNTED`: stock is reserved when checkout starts, committed when
    payment succeeds, and released when payment fails or times out. The
    product auto-hides when stock reaches 0.
  - `MANUAL`: an in-stock/out-of-stock toggle, typical for kitchens.
- **Categories** are per store. **Mall-level discovery categories** ("Food",
  "Fashion") let the mall page group stores.
- **Images** are uploaded **directly from the browser to the bucket** using a
  presigned PUT URL. The API never streams file bytes. After upload the API
  records the object key and serves the image through a CDN URL.
- **Store theming** **(owner)**:
  - The store can set: logo, banner, primary/accent colour, font from a
    curated list, description, opening hours and an open/closed toggle.
  - The store can choose one of 2–3 fixed layout templates.
  - Stores can't write raw CSS or HTML.
- **Opening hours and pause**: a closed or paused store's products show as
  unavailable.

---

## 7. Cart & orders (later milestone; captured now)

- A cart belongs to one customer and one mall. It can contain items from many
  stores.
- **Checkout** creates one **CustomerOrder** (one payment). It also creates
  **N StoreOrders**, one per store. Each store sees only its own StoreOrder.
- **StoreOrder states (pickup)**:

```
PENDING_PAYMENT → PAID → ACCEPTED → PREPARING → READY → PICKED_UP
                    │        │
                    │        └→ CANCELLED (by store/org) → REFUNDED
                    ├→ REJECTED (by store)                → REFUNDED
                    └→ EXPIRED (not accepted in N min)    → REFUNDED
PENDING_PAYMENT → PAYMENT_FAILED / ABANDONED (stock released)
```

- **Accept timeout:** 5 minutes by default, configurable per org
  **(owner)**.
- A customer may cancel a StoreOrder only before the store accepts it
  **(owner)**.
- **Refunds are per StoreOrder.** The other stores' parts of the same cart
  are unaffected **(owner)**.
- **Pickup code** **(owner)**:
  - Each StoreOrder gets its own random 4-digit code.
  - The customer's order screen shows the items with the code.
  - The store enters the code to move the order from `READY` to
    `PICKED_UP`.
  - Failed attempts are rate-limited.
  - The code is unique only among that store's open orders. That is enough
    because the store also sees the order on screen.
- **Real-time** **(owner)**:
  - The store dashboard receives new orders over a WebSocket and plays a
    sound alert.
  - The customer's order page receives status updates live.
  - SMS through Fast2SMS is sent only for key events: order confirmed and
    order ready.
  - Redis pub/sub fans events out across API containers.
- Every state transition is recorded in an `order_events` table, which
  provides history and a timeline.

---

## 8. Payments: Razorpay Route (ON HOLD; concept only)

> **Development of payments is paused by the owner.** Nothing here gets built
> until the owner reopens it. The concept is recorded so other modules leave
> room for it.

- **Concept (owner):**
  - The customer pays the whole cart once through Razorpay.
  - Razorpay **Route** transfers each store's share to that store's **Linked
    Account**.
  - MallT keeps its **commission (default 5%)** in its own account.
  - Stores are paid directly. MallT never holds and later pays out store
    money by hand.
- **Store KYC (owner):**
  - The Store Owner or Org Owner submits the store's KYC (PAN, bank account,
    GSTIN) to create its Route linked account.
  - A Platform Admin sees and approves the status.
  - **A store can't take orders until its KYC is active.**
- **Rules that hold whenever payments are built (call):**
  - All money is stored as **integer paise**. Never floats.
  - Webhooks are verified by signature and processed **idempotently**,
    deduplicated by event id.
  - An **append-only ledger** records payment, transfer, commission and
    refund entries for reconciliation.
- **Open questions for the owner:**
  - Who bears the ~2% gateway fee?
  - Is commission calculated on the pre-tax subtotal or on the grand total?
  - What GST applies to the commission invoice? Confirm with a CA.
- **Until payments land**, the orders module talks to a `PaymentProvider`
  interface. A `FakePaymentProvider` (dev/test only) marks orders paid, so the
  ordering flow can be built and tested end-to-end.

---

## 9. Architecture

### 9.1 Approaches considered

| Approach | Trade-off | Verdict |
|---|---|---|
| **Modular monolith**: one FastAPI app with strict domain modules, stateless containers behind Nginx, scaled horizontally | Simple to build, deploy and debug. Modules can be split out later if one becomes hot. | **Chosen (owner agreed)** |
| Microservices per domain | Independent scaling, but far more ops, network failure modes and slower delivery at v1 scale | Rejected: no benefit at 1–5 malls |
| Django + DRF | Built-in admin and batteries included, but weaker async/WebSocket support | Rejected: FastAPI chosen **(owner)** for async real-time ordering |

**Design target (owner):** 1–5 malls, 50–200 stores, a few thousand orders per
day, a lunch peak of around 50 orders per minute. The system scales by adding
containers.

### 9.2 Components

```
            Customer phone / Staff browser
                         │ HTTPS
                ┌────────▼────────┐
                │ AWS ALB (TLS)   │   (prod)    CloudFront ← S3 images
                └────────┬────────┘
                ┌────────▼────────┐
                │     Nginx       │  routing, gzip/brotli, rate limits,
                └──┬──────────┬───┘  WebSocket upgrade, static caching
          /api, /ws│          │ /
          ┌────────▼───┐  ┌───▼────────┐
          │ FastAPI    │  │ Next.js    │
          │ (N copies) │  │ (N copies) │
          └──┬──────┬──┘  └────────────┘
             │      │ enqueue / pub-sub
   ┌─────────▼┐  ┌──▼─────┐   ┌──────────────┐
   │ Postgres │  │ Redis  │◄──│ ARQ worker   │  SMS, webhooks, timeouts,
   └──────────┘  └────────┘   └──────────────┘  refunds, invoices
```

- **Backend:** Python 3.13, FastAPI, SQLAlchemy 2.0 (async, asyncpg),
  Alembic, Pydantic v2, ARQ worker **(owner: FastAPI; call: the rest)**.
- **Frontend:** **one** Next.js app (App Router, TypeScript strict) with
  Tailwind, shadcn/ui, TanStack Query and pnpm **(owner)**. It has four route
  areas:
  - `/m/[mallSlug]/…`: customer pages. Server-rendered and cached hard with
    tag-based revalidation.
  - `/store/…`: store dashboard. Client-heavy, behind auth.
  - `/org/…`: org dashboard.
  - `/admin/…`: platform admin.
- **API contract:**
  - REST under `/api/v1`. Errors use RFC 9457 problem+json. Lists use cursor
    pagination.
  - FastAPI's OpenAPI spec **generates the TypeScript client** used by the
    frontend. A contract break fails the frontend build **(owner)**.
- **Nginx** **(owner)**:
  - Routes `/api` and `/ws` to FastAPI and everything else to Next.js.
  - Compresses responses.
  - Applies `limit_req` on auth endpoints.
  - Keeps the request body limit small, since images go straight to the
    bucket.
  - Caches static assets.

### 9.3 Environments

| | Development **(owner)** | Production **(owner: AWS; call: specifics)** |
|---|---|---|
| Postgres | **Neon** (a branch per developer/feature as needed) | **AWS RDS PostgreSQL** (Multi-AZ), behind RDS Proxy |
| Object storage | **Neon Object Storage** (S3-compatible) | **AWS S3 + CloudFront** |
| Redis | `redis` container in docker-compose | **ElastiCache Redis** |
| App runtime | `docker compose up`: nginx, web, api, worker, redis | Same images. v1 runs on **EC2 behind an ALB**, moving to **ECS Fargate** when traffic needs it |
| Secrets | `.env` **committed** (owner decision; private repo) | **AWS SSM Parameter Store / Secrets Manager** |
| SMS | Fast2SMS `otp` route; `SMS_BACKEND=console` option logs the OTP instead of sending | Fast2SMS `otp` route |

- **One codebase, configured by env vars only.** Examples: `DATABASE_URL`,
  `REDIS_URL`, `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_PUBLIC_BASE_URL`.
- Storage uses one S3 client (boto3/aioboto3). Neon and AWS differ only in
  endpoint and credentials.
- **Docker (owner: "single docker")** means one `docker-compose.yml` with a
  **separate image per service**, so each service scales independently.
  Postgres is not in compose for dev, because dev uses Neon.
- **Tests** run against a **local Postgres 17 container**. This makes them
  fast, isolated and possible offline **(call)**. Neon dev and RDS prod use
  the same major version.

### 9.4 Performance

- Customer catalog reads are cached at three layers:
  1. Next.js server cache with tag revalidation.
  2. Redis (API responses, per store/mall).
  3. CDN for images.
- The catalog cache is invalidated on product, stock or theme writes.
- Database:
  - Connection pooling through Neon's pooler in dev and RDS Proxy in prod.
  - Indexes for every hot query, reviewed with `EXPLAIN`.
  - No N+1 queries: eager-load explicitly.
- IDs are **UUIDv7**, which are time-ordered and give good index locality
  without leaking counts **(call)**.
- Heavy or slow work (SMS, webhooks, refunds, invoice PDFs, order timeouts)
  runs in the ARQ worker, never in the request path.
- The API is stateless: no in-process state. That allows horizontal scaling.

### 9.5 Frontend phase (owner)

v1 screens are **plain and functional**: stock shadcn/ui and no custom design.
The owner will provide design inspiration after functionality is fully
tested, and UI polish is a separate later pass.

### 9.6 Security

- Argon2id passwords, TOTP 2FA, rotating refresh tokens, httpOnly cookies,
  CSRF protection for cookie-authenticated mutations, and a strict CORS
  allowlist.
- Rate limits in Redis on login, OTP send/verify and pickup-code verify.
- Tenant isolation is enforced in the service layer and tested.
- Uploads:
  - Only presigned PUT URLs are used.
  - Content type and size are restricted.
  - Each object key is server-generated and scoped by tenant.
- Secrets never live in the repo. Structured JSON logs, with a request id on
  every request and no PII in logs (phone numbers masked).

---

## 10. Milestones

| # | Milestone | Contents |
|---|---|---|
| **M0** | Foundation | Monorepo scaffold, docker-compose (nginx, web, api, worker, redis), Neon + Neon storage wiring, config, logging, error format, health checks, Alembic, generated API client, CI (lint, types, tests, Docker build) |
| **M1** | **IAM** | Everything in §5 |
| M2 | Catalog & theming | §6 |
| M3 | Cart & orders | §7 with `FakePaymentProvider`, real-time dashboard, pickup code |
| M4 | Payments | §8. **On hold until the owner reopens it** |
| M5 | Production | AWS infra (RDS, ElastiCache, S3/CloudFront, EC2/ALB), deploy pipeline, backups, monitoring |

---

## 11. Open items for the owner

1. **Payments:** gateway fee bearer, commission base and GST on commission
   (§8). Deferred by the owner.
2. **Fast2SMS:** the owner has provided an API key for the **`otp` route**
   (`GET https://www.fast2sms.com/dev/bulkV2?route=otp&variables_values=<otp>&numbers=<10-digit>`).
   Send the key in the `authorization` **header**, not the query string, so
   it never appears in access logs. Confirm with Fast2SMS whether this route
   needs DLT registration; switch to a DLT route if it does.
3. **Google OAuth client:** create a Google Cloud OAuth client ID for
   Sign-in with Google (dev and prod origins).
4. **Domain:** the production domain name, needed for cookies, CORS and
   OAuth origins.

## 12. Left to the builder

Exact table and column names, endpoint paths beyond the conventions above,
UI component design within shadcn/ui, choice of minor libraries, and test
fixture design. Follow `AGENTS.md`.
