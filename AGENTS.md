# AGENTS.md — MallT

Instructions for every coding agent (and human) working in this repo.
Read this file fully before changing anything. The product spec is in
[`docs/superpowers/specs/2026-10-28-mallt-design.md`](docs/superpowers/specs/2026-10-28-mallt-design.md).
If this file and the spec disagree, the spec wins on *what* we build and this
file wins on *how*.

## 1. What MallT is (one paragraph)

MallT is a multi-tenant mall ordering platform.

- **Tenancy:** Organization → Malls → Stores.
- **Customer flow:**
  1. A customer scans one QR per mall.
  2. They browse every store's products and build one multi-store cart.
  3. They pay once.
  4. They collect each store's part at the counter by showing a 4-digit
     pickup code.
- **Money:** MallT takes a commission (default 5%) through Razorpay Route.
- **Payments are ON HOLD.** Do not build them until told to.
- **Fulfilment:** v1 is **pickup only**. There is no delivery.

## 2. Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.13, FastAPI, SQLAlchemy 2.0 async (asyncpg), Alembic, Pydantic v2, ARQ worker |
| Frontend | Next.js App Router, TypeScript (strict), Tailwind, shadcn/ui, TanStack Query, pnpm |
| Data | PostgreSQL 17 (dev: **Neon**, prod: **AWS RDS**) · Redis is **optional** (`REDIS_URL`; dev: container, prod: ElastiCache) |
| Files | S3 API only (dev: **Neon Object Storage**, prod: **AWS S3 + CloudFront**) |
| Edge | Nginx (routing, compression, rate limits, WebSocket upgrade) |
| Runtime | Docker: one `docker-compose.yml`, separate image per service |
| SMS | Fast2SMS · Google login through Google Identity Services |
| Tooling | uv, ruff, mypy (strict), pytest · pnpm, eslint, prettier, vitest, Playwright · GitHub Actions |

Do not add a new framework, ORM, state library or infrastructure service
without updating the spec and getting approval.

## 3. Repository layout

```
backend/
  pyproject.toml  uv.lock  alembic.ini  alembic/
  src/mallt/
    main.py                  # app factory, router mounting
    core/                    # config, db, redis, security, storage, errors, logging, rbac
    modules/<domain>/        # iam, tenancy, catalog, orders, payments, notifications, audit
      router.py              # HTTP only: parse → call service → serialize
      schemas.py             # Pydantic request/response models
      service.py             # business rules + authorization checks
      repository.py          # SQLAlchemy queries; the only place with SQL
      models.py              # ORM tables owned by this domain
      events.py              # (optional) domain events published to Redis
    workers/                 # ARQ tasks
  tests/                     # mirrors src/mallt; unit + integration
frontend/
  src/app/(customer)/m/[mallSlug]/...   # public, SSR + cached
  src/app/(store)/store/...             # store dashboard
  src/app/(org)/org/...                 # org dashboard
  src/app/(admin)/admin/...             # platform admin
  src/components/ui/                    # shadcn components
  src/lib/api/                          # GENERATED client — never hand-edit
infra/
  nginx/  docker/  aws/
docs/
  superpowers/specs/  superpowers/plans/
docker-compose.yml  .env  Makefile
```

## 4. Commands

`Makefile` is the single entry point. It is created in milestone M0. Until it
exists, these targets are the contract to implement.

| Command | Does |
|---|---|
| `make dev` | `docker compose up` (nginx, web, api) against Neon; no Redis needed |
| `make dev-redis` | the same plus Redis and the ARQ worker |
| `make test` | backend pytest (local Postgres 17 container) + frontend vitest |
| `make lint` | ruff check + ruff format --check + mypy + eslint + tsc --noEmit |
| `make fmt` | auto-format backend and frontend |
| `make migrate` | `alembic upgrade head` |
| `make migration m="msg"` | `alembic revision --autogenerate -m "msg"` (always review the output) |
| `make api-client` | regenerate `frontend/src/lib/api` from FastAPI's OpenAPI |
| `make seed-admin` | create the first Platform Admin |
| `make e2e` | Playwright; it starts API + web + nginx itself (`infra/e2e/local-stack.sh`) and needs local Postgres |

Run `make lint test` before every commit that touches code.

## 5. Backend rules

- **Layering is strict:** `router → service → repository`.
  - Routers hold no business logic and no SQL.
  - Services hold no FastAPI imports.
  - Repositories hold no business rules.
- **Module boundaries:**
  - A domain touches another domain's data only through that domain's
    `service`.
  - Never import another module's `repository` or `models`.
  - Cross-domain side effects go through events or worker jobs.
- **Redis is optional.** Everything that wants a fast key-value store (OTPs, rate limits, the
  permission cache) goes through `core/kv.py` (`KV`): Redis when `REDIS_URL` is set, otherwise a
  Postgres table. Never import `redis` anywhere else, and never make a feature require it. Tests
  run on both backends.
- **Async everywhere.** No blocking I/O in request handlers. Run any CPU-heavy
  or slow work (SMS, webhooks, PDFs, timeouts) as an ARQ job.
- **Config:** use only `pydantic-settings` and environment variables. Never
  hardcode URLs, keys or credentials in code. Every new variable goes into
  `.env` (dev values, committed by owner decision; the repo is private) with
  a comment. Production secrets live in AWS SSM / Secrets Manager, not in
  git.
- **Errors:** raise domain exceptions from `core/errors.py`. They are rendered
  as RFC 9457 `application/problem+json`. Never leak stack traces or SQL.
- **API:** REST under `/api/v1`. Use cursor pagination for lists. Name
  request/response models `XCreate`, `XUpdate` and `XOut`. Every endpoint has
  an explicit response model, because it feeds the generated TS client.
- **Database:**
  - Primary keys are **UUIDv7**.
  - Timestamps are `timestamptz` in UTC.
  - Every tenant-owned table has `organization_id`. Store-owned tables also
    have `mall_id` and `store_id`.
  - Add an index for every foreign key and every hot filter.
  - Eager-load explicitly. N+1 queries are bugs.
  - Migrations are generated with Alembic, reviewed by hand and must be
    reversible. Never edit an applied migration.
  - Destructive changes take two steps: expand, then contract.
- **Money:** always integer **paise** (`BIGINT`). Never `float` or `Decimal`
  arithmetic on rupees. Field names end in `_paise`.
- **Logging:** structured JSON, with a request id on every line. Never log
  passwords, tokens, OTPs, pickup codes or full phone numbers (mask them).

## 6. IAM & authorization rules (non-negotiable)

- **Identities:**
  - Staff and customers are **separate identity types** and separate tables.
  - Staff log in with username and password (Argon2id). Platform Admin must
    use TOTP 2FA.
  - Customers log in with phone OTP (Fast2SMS; the OTP is stored hashed in
    Redis with a TTL) or Google.
- **Tokens:**
  - JWT access tokens last 15 minutes.
  - Refresh tokens rotate, are stored hashed and are sent as an `httpOnly`
    cookie. Reusing an old refresh token revokes the whole token family.
  - **Never put permissions in the JWT.** Resolve them per request; a 60 s
    Redis cache is invalidated on role change.
- **Authorization** is RBAC with scopes:
  - Use `can(actor, permission, scope)`, where scope is one of
    platform ⊃ organization ⊃ mall ⊃ store.
  - Check it **in the service layer** for every mutation and every read of
    tenant data.
  - Router dependencies may pre-check, but the service check is the one that
    counts.
- **Anti-escalation:** a user may grant a role only if they hold all of that
  role's permissions at a containing scope and hold the matching
  `*.staff.manage` permission.
- **Permissions** are string constants in `core/rbac.py` (for example
  `store.product.write`). The premade roles (Platform Admin, Org Owner, Org
  Manager, Store Owner, Store Staff) are seeded by migration. The matrix lives
  in spec §5.2.
- **Staff management follows one rule:** you may manage someone only if you could have granted each
  of their roles yourself (`GRANT_RULES` in `core/rbac.py`, plus holding every permission in the
  role). Owners can create owners; managers can't create managers or owners; nobody manages
  themselves; an organization always keeps one active owner.
- **Commission** (`commission_bps`) is MallT's revenue, so only `platform.org.manage` may edit it.
- **Anything that changes roles, status or passwords must call `AuthzService.invalidate(staff_id)`**
  (Redis caches a principal for 60 s). It clears the cache now *and again after commit*
  (`defer_after_commit`); use that helper for any cache you invalidate from inside a request. Tests that change those by raw SQL must call it too.
- **Audit:** every staff mutation writes an append-only audit log row.
- **Tests:** every new tenant-scoped endpoint gets a **cross-tenant test**.
  Staff of org A must get 404 (not 403) for org B's resources, so the
  response doesn't reveal that the resource exists.

## 7. Domain rules to keep in mind

- One `CustomerOrder` (one payment) contains N `StoreOrder`s (one per store).
  Stores only ever see their own `StoreOrder`.
- StoreOrder state machine:
  `PENDING_PAYMENT → PAID → ACCEPTED → PREPARING → READY → PICKED_UP`.
  Side exits are `REJECTED`, `EXPIRED` and `CANCELLED`, each followed by
  `REFUNDED`.
- Transitions go through one function that validates the transition and
  writes an `order_events` row. Never set `status` directly.
- `READY → PICKED_UP` requires the 4-digit pickup code, and attempts are
  rate-limited.
- Stock mode is per product. `COUNTED` stock is reserved when checkout starts,
  committed when payment succeeds and released when payment fails or expires.
  `MANUAL` stock is a toggle.
- `fulfilment_type` exists, but only `PICKUP` is valid in v1.
- Payments go through a `PaymentProvider` interface. Use only
  `FakePaymentProvider` until payments are reopened. When payments are built:
  verify webhook signatures, process each webhook idempotently, and record
  every movement in an append-only ledger.
- Images:
  1. The browser uploads straight to the bucket using a presigned PUT URL
     with a server-generated, tenant-scoped key.
  2. The API stores only the key.
  3. Images are served from the CDN URL.

## 8. Frontend rules

> **Current phase: functionality first.** Build plain, clean,
> functional screens with stock shadcn/ui components and default styling. No
> custom visual design, animation or branding work until the owner supplies
> design inspiration. UI polish is a separate later pass after everything is
> tested end to end. Keep components cleanly separated from data logic so
> restyling later doesn't touch behaviour.

- TypeScript `strict`. No `any` without a comment explaining why.
- **All API calls go through the generated client** in `src/lib/api`.
  Regenerate it with `make api-client` after any backend schema change, and
  commit the result. Never hand-write fetch calls to `/api/v1`.
- Customer pages (`/m/...`):
  - Mobile-first.
  - Server components by default.
  - Cached with tag revalidation.
  - Only small client islands (cart, add-to-cart).
  - Budget: first load ≤ 150 KB of JS, LCP < 2.5 s on mid-range 4G.
- Dashboards (`/store`, `/org`, `/admin`):
  - Client components with TanStack Query.
  - Route guards check the session.
  - The UI hides actions the user lacks permission for, but the backend is
    still the authority.
- Dashboards nest: a higher role may open the dashboards beneath it (an org owner manages a
  store's team from the store's pages), never the reverse (`lib/auth/home.ts`).
- The public mall page is cached for 60 s. Anything that changes a mall or its stores must call
  `refreshMallPage(slug)` (a Server Action using `updateTag`) so customers see it at once.
- Store theming is limited to design tokens: CSS variables from the store's
  theme plus a fixed template. Never render store-supplied HTML or CSS.
- Accessible by default: semantic HTML, labelled inputs, keyboard navigable.

## 9. Testing

- **Test-first** for features and bug fixes: write the failing test, watch it
  fail, then implement. Use the `test-driven-development` skill.
- Backend:
  - Unit tests for services.
  - Integration tests that hit the real HTTP app against a real Postgres 17
    container. No SQLite and no mocked database.
  - Mock only external services: Fast2SMS, Google, Razorpay, S3.
- Must-have tests:
  - permission matrix
  - cross-tenant isolation
  - anti-escalation
  - token rotation and reuse detection
  - OTP rate limits
  - order state machine
  - pickup-code verification
- Frontend: vitest for logic and components, and Playwright for critical
  flows (login, scan → cart → order, store accepts → ready → pickup).
- Never skip, delete or weaken a test to make CI pass.

## 10. Git & workflow

- Branch from the default branch: `feat/…`, `fix/…`, `chore/…`. Agent
  branches may be named by the harness.
- Use **Conventional Commits**, for example `feat(iam): add role assignment
  endpoint`. Keep commits small and focused.
- Every change goes through a PR, and CI (lint, types, tests, Docker build)
  must be green before merge.
- **Dev `.env` is committed** (owner decision; private repo). Never commit
  **production** secrets or generated build output. The generated API client
  in `src/lib/api` **is** committed.
- Large work follows this flow:
  1. **brainstorming**: produces the spec in `docs/superpowers/specs/`.
  2. **writing-plans**: produces the plan in `docs/superpowers/plans/`.
  3. **executing-plans** or **subagent-driven-development**.
  4. **verification-before-completion**.
  5. **requesting-code-review**.
- When something breaks, use **systematic-debugging** before proposing fixes.
- Before saying something is "done" or "fixed", run the commands and show the
  output.

## 11. Things to never do

- Build payments, delivery or a native app before they are reopened.
- Put permissions in JWTs, or skip the service-layer authorization check.
- Use floats for money.
- Let the API stream image bytes, or render store-supplied HTML or CSS.
- Hand-edit the generated API client or an applied migration.
- Commit production secrets, or log OTPs, tokens, passwords, pickup codes
  or API keys.
- Make a feature depend on Redis being present.
- Add a dependency, framework or AWS service not listed above without
  approval.
