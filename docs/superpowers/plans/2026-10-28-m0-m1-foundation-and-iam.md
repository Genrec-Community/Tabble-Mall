# M0 Foundation + M1 IAM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A running MallT stack (nginx + Next.js + FastAPI + ARQ worker + Redis, Neon Postgres) with complete IAM: staff and customer auth, scoped RBAC, orgs/malls/stores, staff management, audit log, and plain functional dashboards.

**Architecture:** A modular-monolith FastAPI app (`backend/src/mallt`) with domain modules: `iam` (identities, sessions, authz), `audit`, `tenancy` (orgs/malls/stores; depends on iam + audit), `staff` (staff management; depends on iam + tenancy + audit). There is one Next.js app with route groups for admin/org/store/customer, and it talks to the API only through a client generated from OpenAPI. Nginx routes `/api` and `/ws` to the API and everything else to Next.js.

**Tech Stack:** Python 3.13, uv, FastAPI, SQLAlchemy 2 async + asyncpg, Alembic, Pydantic v2 + pydantic-settings, redis-py (asyncio), ARQ, argon2-cffi, PyJWT, pyotp, httpx, boto3, google-auth · Next.js (App Router), TypeScript strict, Tailwind, shadcn/ui, TanStack Query, @hey-api/openapi-ts + @hey-api/client-fetch, vitest, Playwright · Docker Compose, Nginx, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-28-mallt-design.md` (§5 IAM, §9 architecture). Rules: `AGENTS.md`.

## Global Constraints

- Follow `AGENTS.md` for everything: layering `router → service → repository`, no cross-module repository or model imports, problem+json errors, UUIDv7 primary keys, `timestamptz` UTC, money in `_paise` BIGINT.
- Python 3.13. Postgres 17 in CI and prod. Tests read `TEST_DATABASE_URL` and `TEST_REDIS_URL`; locally, any Postgres ≥16 is acceptable if Docker Hub is unavailable.
- Access JWT TTL **900 s**. Refresh TTL: staff **43 200 s** (12 h), customer **2 592 000 s** (30 d). Refresh tokens rotate and are stored as SHA-256 hashes; reuse of a rotated token revokes the whole family.
- Refresh cookies: `mallt_srt` (staff) and `mallt_crt` (customer); `HttpOnly; SameSite=Lax; Path=/api/v1/auth`. `Secure` follows `settings.cookie_secure`. Cookie-authenticated endpoints (refresh/logout) require the header `X-Requested-With: mallt` (CSRF guard).
- Passwords use Argon2id (argon2-cffi defaults). Minimum length is 10.
- Usernames: lowercase `^[a-z0-9._-]{3,40}$`, globally unique. Input is trimmed and lowercased before lookup.
- Customer OTP: 6 digits, stored as an HMAC-SHA256 hash in Redis, TTL **300 s**, max **5** verify attempts. Send limits: **3 per 10 min per phone**, **20 per hour per IP**.
- Staff login rate limit: **10 per 15 min per (username, IP)**.
- Indian mobile numbers only. Normalise to 10 digits matching `^[6-9]\d{9}$`. Accept `+91`, `91` and `0` prefixes, plus spaces and dashes.
- Platform Admin must use TOTP. Org Owner TOTP is optional.
- Permissions are never stored in the JWT. A resolved principal is cached in Redis for **60 s** under `authz:staff:{id}` and deleted on any role or status change.
- Cross-tenant access returns **404**. A same-tenant missing permission returns **403**.
- Commission is stored as integer basis points (`commission_bps`, default **500** = 5%). This is storage only; no payments in this plan.
- Frontend: plain stock shadcn/ui and no custom design (AGENTS.md §8). All API calls go through `frontend/src/lib/api` (generated).
- Do not build payments, delivery, catalog or orders in this plan.

## Review Focus

1. **Two browser tabs refresh at the same moment.** The user must stay logged in, not trip reuse detection. The frontend serialises refresh across tabs with `navigator.locks`. Test: Task 18.
2. **Phone formats** `+91 93618 99061`, `09361899061`, `919361899061` and `9361899061` all resolve to one customer. `12345` and `5361899061` are rejected with 422. Test: Task 16.
3. **Suspended staff with a still-valid access token** is rejected on their next request (401), not after the 15-minute expiry. Test: Task 11.
4. **Removing the last Org Owner** (revoke the role or suspend the user) is refused with 409, so an org is never left ownerless. Test: Task 15.
5. **Username typed with capitals or spaces** (`" Ravi.K "`) logs in as `ravi.k`. Creating `Ravi.K` when `ravi.k` exists returns 409. Test: Task 12 / Task 15.

---

## File Structure

```
.env                                   # dev config (committed, owner decision)
Makefile  docker-compose.yml
.github/workflows/ci.yml
infra/nginx/nginx.conf
infra/docker/api.Dockerfile  infra/docker/web.Dockerfile
backend/
  pyproject.toml  alembic.ini
  alembic/env.py  alembic/versions/0001_iam_tenancy_audit.py
  src/mallt/
    main.py            # create_app()
    cli.py             # python -m mallt.cli seed-admin | openapi
    core/
      config.py        # Settings
      ids.py           # uuid7()
      db.py            # Base, engine, session dependency, mixins
      errors.py        # AppError hierarchy + problem+json handlers
      logging.py       # JSON logging + RequestIdMiddleware
      redis.py         # get_redis()
      ratelimit.py     # hit()
      storage.py       # presign_put(), public_url()
      security.py      # passwords, JWT, refresh tokens, TOTP, OTP hashing
      rbac.py          # Permission, ScopeType, Scope, SYSTEM_ROLES
      phone.py         # normalize_in_phone()
    modules/
      health/router.py
      audit/{models,repository,service,schemas,router}.py
      iam/{models,repository,schemas}.py
      iam/authz.py           # Principal, AuthzService
      iam/sessions.py        # SessionService (refresh-token families)
      iam/staff_auth.py      # StaffAuthService
      iam/customer_auth.py   # CustomerAuthService
      iam/sms.py             # SmsSender protocol, ConsoleSms, Fast2Sms
      iam/google.py          # GoogleVerifier protocol, GoogleIdTokenVerifier
      iam/deps.py            # FastAPI deps: current_staff, current_customer
      iam/router.py
      tenancy/{models,repository,service,schemas,router}.py
      staff/{repository,service,schemas,router}.py
    workers/main.py          # ARQ WorkerSettings (heartbeat job only for now)
  tests/
    conftest.py              # app, client, db, redis fixtures, factories
    core/test_*.py
    modules/<module>/test_*.py
frontend/
  package.json  next.config.ts  openapi-ts.config.ts  vitest.config.ts  playwright.config.ts
  src/lib/api/                # GENERATED
  src/lib/auth/               # token store, refresh single-flight, session hooks
  src/app/layout.tsx  src/app/providers.tsx
  src/app/login/page.tsx                       # staff login
  src/app/(admin)/admin/...  (org)/org/...  (store)/store/...
  src/app/(customer)/account/{login,page}.tsx  # customer login + profile
  src/app/(customer)/m/[mallSlug]/page.tsx     # placeholder
  e2e/iam.spec.ts
```

---

## Part A — M0 Foundation

### Task 1: Backend skeleton, config, errors, logging, health

**Files:**
- Create: `backend/pyproject.toml`, `backend/src/mallt/{__init__,main}.py`, `backend/src/mallt/core/{__init__,config,errors,logging}.py`, `backend/src/mallt/modules/health/router.py`, `backend/tests/conftest.py`, `backend/tests/core/test_app.py`

**Interfaces:**
- Produces:
  - `Settings` (pydantic-settings, env-file `.env` at repo root) with these fields:
    - `env: Literal["dev","test","prod"]`
    - `database_url: str`, `redis_url: str`
    - `jwt_secret: str`, `jwt_issuer="mallt"`
    - `access_ttl_s=900`, `staff_refresh_ttl_s=43200`, `customer_refresh_ttl_s=2592000`
    - `cookie_secure: bool`
    - `cors_origins: list[str]`
    - `sms_backend: Literal["console","fast2sms"]="console"`, `fast2sms_api_key: str=""`
    - `google_client_id: str=""`
    - `otp_pepper: str`
    - `s3_endpoint_url: str|None`, `s3_region: str`, `s3_bucket: str`, `s3_access_key_id: str`, `s3_secret_access_key: str`, `s3_public_base_url: str`
  - `get_settings() -> Settings` (lru_cache).
  - `create_app(settings: Settings | None = None) -> FastAPI`.
  - Errors in `core/errors.py`:
    - `AppError(status: int, code: str, title: str, detail: str | None = None, extra: dict | None = None)`.
    - Subclasses `BadRequest` 400, `Unauthorized` 401, `Forbidden` 403, `NotFound` 404, `Conflict` 409, `Unprocessable` 422, `RateLimited` 429 (adds a `Retry-After` header).
    - `install_error_handlers(app)` renders `application/problem+json` as `{type, title, status, detail, code, request_id, ...extra}` for AppError, for FastAPI `RequestValidationError` (422, `errors` list) and for unhandled exceptions (500, generic detail, no trace).
  - `RequestIdMiddleware`: reads `X-Request-ID` or generates a uuid4 hex, stores it in a contextvar, echoes it in the response header. `configure_logging()` emits single-line JSON that includes `request_id`.
  - `GET /api/v1/health` → `{"status":"ok"}` (liveness).

- [ ] **Step 1:** Create `backend/pyproject.toml` (uv project, `src` layout, package `mallt`).
  - Runtime deps: fastapi, uvicorn[standard], pydantic-settings, sqlalchemy[asyncio], asyncpg, alembic, redis, arq, argon2-cffi, pyjwt, pyotp, httpx, boto3, google-auth.
  - Dev group: pytest, pytest-asyncio, ruff, mypy.
  - Configure ruff (line length 100, rules `E,F,I,B,UP,S,ASYNC`, tests ignore `S101`).
  - Configure mypy (`strict = true`, `ignore_missing_imports` for boto3/botocore/google/arq/pyotp).
  - Configure pytest (`asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "session"`).
  - Run `cd backend && uv sync`. Expected: lockfile `uv.lock` created.
- [ ] **Step 2: Write failing tests** in `tests/core/test_app.py`:

```python
async def test_health(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}

async def test_unknown_route_is_problem_json(client):
    r = await client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == 404 and "request_id" in r.json()

async def test_request_id_echoed(client):
    r = await client.get("/api/v1/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"

async def test_validation_error_shape(app, client):
    # app fixture exposes a test-only route POST /api/v1/_test/echo taking {"n": int}
    r = await client.post("/api/v1/_test/echo", json={"n": "x"})
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
```

  `conftest.py` creates fixtures `settings` (env="test"), `app`, and `client` (an `httpx.AsyncClient` with `ASGITransport`, base_url `http://test`). The `app` fixture adds the `_test/echo` route.
- [ ] **Step 3:** Run `uv run pytest tests/core/test_app.py -v`. Expected: FAIL (import errors).
- [ ] **Step 4:** Implement `config.py`, `errors.py`, `logging.py`, `health/router.py` and `main.py` per the Interfaces above. Also add CORS middleware using `settings.cors_origins` with `allow_credentials=True`.
- [ ] **Step 5:** Run `uv run pytest -v && uv run ruff check . && uv run ruff format --check . && uv run mypy src`. Expected: all pass.
- [ ] **Step 6:** Commit `feat(core): fastapi skeleton with config, problem+json errors, request-id logging`.

### Task 2: Database layer, UUIDv7, Alembic, test DB fixtures, readiness

**Files:**
- Create: `backend/src/mallt/core/{ids,db}.py`, `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`, `backend/tests/core/test_ids.py`, `backend/tests/core/test_db.py`
- Modify: `backend/tests/conftest.py`, `backend/src/mallt/modules/health/router.py`

**Interfaces:**
- Produces:
  - `uuid7() -> uuid.UUID`: RFC 9562 layout (48-bit ms timestamp, version 7, variant 10xx, random tail). Monotonic within a millisecond via a 12-bit counter in `rand_a`.
  - In `db.py`:
    - `Base(DeclarativeBase)` with a naming convention for constraints (`ix_%(column_0_label)s`, `uq_%(table_name)s_%(column_0_name)s`, `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`, `pk_%(table_name)s`).
    - `IdMixin`: `id: Mapped[UUID]` primary key, default `uuid7`.
    - `TimestampMixin`: `created_at` / `updated_at` as `timestamptz`, server default `now()`, `updated_at` with `onupdate`.
  - `make_engine(url: str) -> AsyncEngine` (pool_pre_ping, pool_size 10, max_overflow 10).
  - `get_session(request) -> AsyncIterator[AsyncSession]` dependency: one session per request; it commits if the handler returns and rolls back on exception.
  - `alembic/env.py` is async, reads `DATABASE_URL` from Settings, and imports `mallt.models_registry` (a module importing every module's `models`) for autogenerate.
  - `GET /api/v1/ready` → 200 `{"status":"ready"}` when `SELECT 1` succeeds on DB and `PING` on Redis; otherwise 503 problem+json.
  - Test fixtures:
    - `db_engine` (session scope): runs `alembic upgrade head` against `TEST_DATABASE_URL` after dropping and recreating the `public` schema.
    - `db_session`: a connection-level transaction that is rolled back after each test; the app's `get_session` is overridden to use it with `join_transaction_mode="create_savepoint"`.

- [ ] **Step 1: Write failing tests**:

```python
def test_uuid7_version_and_order():
    ids = [uuid7() for _ in range(1000)]
    assert all(u.version == 7 for u in ids)
    assert ids == sorted(ids)            # time-ordered, monotonic
    assert len(set(ids)) == 1000

async def test_ready(client):
    r = await client.get("/api/v1/ready")
    assert r.status_code == 200 and r.json() == {"status": "ready"}
```

- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement `ids.py`, `db.py`, Alembic env, `models_registry.py` (empty list for now), the ready endpoint and the fixtures above. Redis for `ready` comes from Task 3. Until then, have `ready` check the DB only and extend it in Task 3.
- [ ] **Step 4:** Run `uv run pytest -v` (with `TEST_DATABASE_URL` set). Expected: PASS.
- [ ] **Step 5:** Commit `feat(core): async db layer, uuid7 ids, alembic, readiness probe`.

### Task 3: Redis client and rate limiter

**Files:**
- Create: `backend/src/mallt/core/{redis,ratelimit}.py`, `backend/tests/core/test_ratelimit.py`
- Modify: `health/router.py` (ready also pings Redis), `tests/conftest.py` (`redis` fixture on `TEST_REDIS_URL`, db 15, `FLUSHDB` per test)

**Interfaces:**
- Produces:
  - `get_redis(request) -> redis.asyncio.Redis`. A single client is created in the app lifespan and stored on `app.state.redis`.
  - `async def hit(redis, key: str, limit: int, window_s: int) -> None`: a fixed-window counter using `INCR` + `EXPIRE NX` on `rl:{key}`. It raises `RateLimited(retry_after=ttl)` when the count exceeds `limit`.

- [ ] **Step 1: Failing test**:

```python
async def test_hit_allows_up_to_limit_then_429(redis):
    for _ in range(3):
        await hit(redis, "t:a", limit=3, window_s=60)
    with pytest.raises(RateLimited) as e:
        await hit(redis, "t:a", limit=3, window_s=60)
    assert 0 < e.value.retry_after <= 60

async def test_keys_are_independent(redis):
    for _ in range(3):
        await hit(redis, "t:a", 3, 60)
    await hit(redis, "t:b", 3, 60)   # does not raise
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** Run `uv run pytest -v`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(core): redis client and fixed-window rate limiter`.

### Task 4: S3-compatible storage (Neon dev, AWS prod)

**Files:**
- Create: `backend/src/mallt/core/storage.py`, `backend/tests/core/test_storage.py`

**Interfaces:**
- Produces:
  - `@dataclass PresignedUpload(url: str, key: str, headers: dict[str,str], expires_in: int)`.
  - `class Storage`:
    - `__init__(settings)` builds a boto3 S3 client with `endpoint_url=settings.s3_endpoint_url` (None means AWS) and signature `s3v4`.
    - `presign_put(key: str, content_type: str, expires_in: int = 300) -> PresignedUpload`. Raises `BadRequest` unless `content_type` is in `{"image/jpeg","image/png","image/webp"}`.
    - `public_url(key: str) -> str` returns `f"{s3_public_base_url.rstrip('/')}/{key}"`.
    - `object_key(*, organization_id: UUID, kind: str, ext: str) -> str` returns `f"org/{organization_id}/{kind}/{uuid7()}.{ext}"`.
  - Presigning is CPU-only (no network), so calling it synchronously inside async code is fine.
  - No endpoint uses this yet. Catalog (M2) will.

- [ ] **Step 1: Failing tests:** `presign_put` returns a URL containing the bucket, the key and `X-Amz-Expires=300`. A disallowed content type raises `BadRequest`. `object_key` starts with `org/<id>/product/` and ends with `.webp`. `public_url` joins without a double slash.
- [ ] **Step 2–4:** Run (FAIL) → implement → run (PASS).
- [ ] **Step 5:** Commit `feat(core): s3-compatible storage with presigned uploads`.

### Task 5: Frontend skeleton with generated API client

**Files:**
- Create: `frontend/` via `pnpm create next-app@latest frontend --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --use-pnpm --no-turbopack`. Then `pnpm dlx shadcn@latest init` (defaults) and add components `button input label card table dialog form select badge sonner dropdown-menu`.
- Create: `frontend/openapi-ts.config.ts`, `frontend/src/app/providers.tsx`, `frontend/src/lib/api/` (generated), `frontend/vitest.config.ts`, `frontend/src/lib/api-config.ts`, `frontend/src/lib/api-config.test.ts`
- Create: `backend/src/mallt/cli.py` with an `openapi` subcommand
- Create: route-group placeholders `src/app/(admin)/admin/page.tsx`, `(org)/org/page.tsx`, `(store)/store/page.tsx`, `(customer)/m/[mallSlug]/page.tsx`

**Interfaces:**
- Produces:
  - `python -m mallt.cli openapi > ../frontend/openapi.json` writes the schema with no running server.
  - `openapi-ts.config.ts`: input `openapi.json`, output `src/lib/api`, plugins `@hey-api/client-fetch` and `@hey-api/typescript` and `@hey-api/sdk`.
  - `configureApiClient({ getAccessToken, onUnauthorized })` in `src/lib/api-config.ts`:
    - Sets `baseUrl` from `NEXT_PUBLIC_API_BASE` (default `""`, i.e. same origin through nginx).
    - Sets `credentials: "include"` and the header `X-Requested-With: mallt`.
    - A request interceptor adds `Authorization: Bearer`.
  - `Providers` wraps `QueryClientProvider` (`retry: 1`, `staleTime: 30_000`) and `<Toaster/>`.
  - The FastAPI app sets `generate_unique_id_function` to `f"{route.tags[0]}_{route.name}"`, so SDK function names are stable (e.g. `health_getHealth`).

- [ ] **Step 1:** Scaffold with the commands above. Add the deps `@tanstack/react-query`, `@hey-api/client-fetch`, and dev deps `@hey-api/openapi-ts vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/dom @playwright/test`. Add scripts: `"api:gen": "openapi-ts"`, `"test": "vitest run"`, `"typecheck": "tsc --noEmit"`.
- [ ] **Step 2: Failing test** `src/lib/api-config.test.ts`: after `configureApiClient({getAccessToken: () => "tok", onUnauthorized})`, a call to the generated `health_getHealth()`, with `fetch` stubbed, sends `Authorization: Bearer tok` and `X-Requested-With: mallt`.
- [ ] **Step 3:** Run `pnpm test`. Expected: FAIL.
- [ ] **Step 4:** Implement `cli.py openapi`, generate the client (`pnpm api:gen`) and implement `api-config.ts` and `providers.tsx`.
- [ ] **Step 5:** Run `pnpm test && pnpm typecheck && pnpm lint && pnpm build`. Expected: all pass.
- [ ] **Step 6:** Commit `feat(web): next.js skeleton with shadcn, react-query and generated api client`.

### Task 6: Docker, Nginx, Compose, Makefile, `.env`, worker

**Files:**
- Create: `infra/docker/api.Dockerfile`, `infra/docker/web.Dockerfile`, `infra/nginx/nginx.conf`, `docker-compose.yml`, `Makefile`, `.env`, `backend/src/mallt/workers/main.py`, `backend/tests/workers/test_worker.py`

**Interfaces:**
- Produces:
  - **api image:**
    - Base `python:3.13-slim`, multi-stage.
    - `uv sync --frozen --no-dev` into `/app/.venv`.
    - Runs as non-root user `mallt`.
    - CMD `uvicorn mallt.main:create_app --factory --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'`.
  - **worker:** same image, command `arq mallt.workers.main.WorkerSettings`. `WorkerSettings` has `redis_settings` from `settings.redis_url`, functions `[heartbeat]` where `async def heartbeat(ctx) -> str` returns `"ok"`, and `cron_jobs` empty.
  - **web image:** `node:22-alpine`, pnpm, `next build` with `output: "standalone"`, CMD `node server.js` on port 3000.
  - **nginx.conf:**
    - Upstream `api:8000`, `web:3000`.
    - `/api/` and `/ws/` go to api; `/ws/` gets `Upgrade` and `Connection` headers and `proxy_read_timeout 3600s`.
    - `/` goes to web; `/_next/static/` gets `expires 1y`.
    - gzip on.
    - `client_max_body_size 1m`.
    - `limit_req_zone $binary_remote_addr zone=auth:10m rate=10r/m`, applied to `location /api/v1/auth/` with `burst=20 nodelay`.
    - Sets `X-Request-ID $request_id` when absent, plus `X-Forwarded-For` and `X-Forwarded-Proto`.
  - **docker-compose.yml:**
    - Services `nginx` (port `8080:80`), `web`, `api`, `worker`, `redis` (`redis:7-alpine`).
    - `env_file: .env` for api and worker.
    - Profile `test` adds `postgres-test` (`postgres:17-alpine`, port `55432`, password `test`) and `redis-test` (port `56379`).
    - No dev Postgres service: dev uses Neon through `DATABASE_URL`.
  - **`.env`** (committed): every Settings field with a comment.
    - `DATABASE_URL`: the owner's Neon dev pooled connection string with `postgresql+asyncpg://` (fill from the Neon MCP `get_connection_string`).
    - `TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@localhost:55432/postgres`
    - `TEST_REDIS_URL=redis://localhost:56379/15`
    - `SMS_BACKEND=console`
    - `FAST2SMS_API_KEY`: the owner-provided key.
    - S3 values from a Neon Object Storage bucket `mallt-dev` (create via the Neon MCP `create_storage_bucket` and `create_credential`).
    - `JWT_SECRET` and `OTP_PEPPER`: random 64-hex values.
  - **Makefile targets:** exactly the `AGENTS.md` §4 table.
    - `make test` runs `docker compose --profile test up -d postgres-test redis-test`, then `cd backend && uv run pytest`, then `cd frontend && pnpm test`.
    - `make api-client` runs `cd backend && uv run python -m mallt.cli openapi > ../frontend/openapi.json && cd ../frontend && pnpm api:gen`.

- [ ] **Step 1: Failing test** `tests/workers/test_worker.py`: `await heartbeat({}) == "ok"` and `WorkerSettings.functions` contains `heartbeat`. Run it. Expected: FAIL.
- [ ] **Step 2:** Implement the worker. Run the test. Expected: PASS.
- [ ] **Step 3:** Write the Dockerfiles, nginx.conf, compose file, Makefile and `.env`. Run `docker compose config -q && docker run --rm -v $PWD/infra/nginx/nginx.conf:/etc/nginx/nginx.conf:ro nginx:1.27-alpine nginx -t`. Expected: config is valid. If Docker Hub rate-limits, retry later and note it in the PR.
- [ ] **Step 4:** Run `docker compose build && docker compose up -d && curl -fsS localhost:8080/api/v1/health && curl -fsS localhost:8080/ -o /dev/null`. Expected: `{"status":"ok"}` and HTTP 200.
- [ ] **Step 5:** Commit `chore(infra): docker images, nginx, compose, makefile, dev env`.

### Task 7: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces jobs on `pull_request` and `push` to the default branch:
  - **backend:** services `postgres:17` and `redis:7`; `astral-sh/setup-uv`; `uv sync --frozen`; `ruff check`; `ruff format --check`; `mypy src`; `pytest`.
  - **frontend:** pnpm + node 22 with cache; `pnpm install --frozen-lockfile`; `pnpm lint`; `pnpm typecheck`; `pnpm test`; `pnpm build`.
  - **api-contract:** regenerate the client and run `git diff --exit-code frontend/src/lib/api frontend/openapi.json`. This fails if the generated client wasn't committed after a schema change.
  - **docker:** `docker compose build`.

- [ ] **Step 1:** Write the workflow. Validate it with `uvx check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/ci.yml`. Expected: `ok`.
- [ ] **Step 2:** Commit `ci: lint, typecheck, test, contract and docker build`. Push, and confirm all four jobs are green on the PR.

---

## Part B — M1 IAM

### Task 8: RBAC core (pure)

**Files:**
- Create: `backend/src/mallt/core/rbac.py`, `backend/tests/core/test_rbac.py`

**Interfaces:**
- Produces:
  - `class ScopeType(StrEnum)`: `PLATFORM="platform"`, `ORGANIZATION="organization"`, `MALL="mall"`, `STORE="store"`.
  - `class P(StrEnum)`: exactly the permissions in spec §5.2:
    - `platform.org.manage`, `platform.kyc.approve`
    - `org.settings.update`, `org.billing.manage`, `org.mall.manage`, `org.store.manage`, `org.staff.manage`
    - `store.profile.update`, `store.theme.update`, `store.product.write`, `store.product.read`, `store.stock.update`, `store.order.read`, `store.order.update`, `store.order.verify_pickup`, `store.order.cancel`, `store.kyc.submit`, `store.staff.manage`, `store.report.read`
    - `audit.read`
  - `@dataclass(frozen=True) Scope(type: ScopeType, organization_id: UUID|None=None, mall_id: UUID|None=None, store_id: UUID|None=None)`. Constructors `Scope.platform()`, `Scope.org(org_id)`, `Scope.mall(org_id, mall_id)` and `Scope.store(org_id, mall_id, store_id)` validate that the chain is complete.
  - `def contains(outer: Scope, inner: Scope) -> bool`: platform contains everything. Otherwise the outer's level id must equal the inner's id at that level, and the inner must be at the same or a deeper level.
  - `@dataclass(frozen=True) RoleDef(key: str, name: str, scope_type: ScopeType, permissions: frozenset[P])`.
  - `SYSTEM_ROLES: dict[str, RoleDef]` with keys `platform_admin`, `org_owner`, `org_manager`, `store_owner` and `store_staff`. Permissions come **verbatim from the spec §5.2 matrix**. Scope types are: platform_admin → PLATFORM, org_owner/org_manager → ORGANIZATION, store_owner/store_staff → STORE.
  - `STAFF_MANAGE_FOR: dict[ScopeType, P]` = `{PLATFORM: platform.org.manage, ORGANIZATION: org.staff.manage, MALL: org.staff.manage, STORE: store.staff.manage}`.

- [ ] **Step 1: Failing tests**:

```python
def test_matrix_matches_spec():
    R = SYSTEM_ROLES
    assert R["store_staff"].permissions == {P.STORE_PRODUCT_READ, P.STORE_STOCK_UPDATE,
        P.STORE_ORDER_READ, P.STORE_ORDER_UPDATE, P.STORE_ORDER_VERIFY_PICKUP}
    assert P.ORG_BILLING_MANAGE in R["org_owner"].permissions
    assert P.ORG_BILLING_MANAGE not in R["org_manager"].permissions
    assert P.STORE_KYC_SUBMIT not in R["org_manager"].permissions
    assert P.AUDIT_READ in R["org_owner"].permissions and P.AUDIT_READ not in R["store_owner"].permissions
    assert R["platform_admin"].permissions == set(P)

def test_contains():
    o1, o2, m, s = uuid7(), uuid7(), uuid7(), uuid7()
    assert contains(Scope.platform(), Scope.store(o1, m, s))
    assert contains(Scope.org(o1), Scope.store(o1, m, s))
    assert not contains(Scope.org(o2), Scope.store(o1, m, s))
    assert not contains(Scope.store(o1, m, s), Scope.org(o1))
    assert contains(Scope.mall(o1, m), Scope.store(o1, m, s))

def test_incomplete_chain_rejected():
    with pytest.raises(ValueError):
        Scope(ScopeType.STORE, organization_id=uuid7())
```

- [ ] **Step 2–4:** FAIL → implement → PASS (`uv run pytest tests/core/test_rbac.py -v`).
- [ ] **Step 5:** Commit `feat(core): rbac permissions, scopes and system role matrix`.

### Task 9: Security primitives and phone normalisation

**Files:**
- Create: `backend/src/mallt/core/{security,phone}.py`, `backend/tests/core/{test_security,test_phone}.py`

**Interfaces:**
- Produces in `security.py`:
  - `hash_password(pw: str) -> str` and `verify_password(hash: str, pw: str) -> bool` (Argon2id; never raises on mismatch). `password_needs_rehash(hash) -> bool`.
  - `@dataclass(frozen=True) AccessClaims(sub: UUID, typ: Literal["staff","customer"], sid: UUID, exp: int)`.
  - `create_access_token(settings, *, sub, typ, sid) -> str` (HS256, `iss`, `iat`, `exp=now+access_ttl_s`).
  - `decode_access_token(settings, token) -> AccessClaims` raises `Unauthorized("invalid_token")` on any failure.
  - `new_opaque_token() -> tuple[str, str]` returns `(raw, sha256_hex(raw))`; raw is `secrets.token_urlsafe(48)`. `hash_opaque(raw) -> str`.
  - `new_totp_secret() -> str`, `totp_uri(secret, username) -> str` (issuer "MallT"), `verify_totp(secret, code) -> bool` (`valid_window=1`).
  - `new_otp() -> str` (6 digits, `secrets`) and `hash_otp(settings, phone, otp) -> str` (HMAC-SHA256 with `otp_pepper`).
  - `new_temp_password() -> str` (16 chars, url-safe).
- Produces in `phone.py`:
  - `normalize_in_phone(raw: str) -> str`: strip spaces, dashes and parens; drop a leading `+91`, `91` (only if 12 digits) or `0` (only if 11 digits); then require `^[6-9]\d{9}$` or raise `Unprocessable("invalid_phone")`.
  - `mask_phone(p) -> "******9061"`.

- [ ] **Step 1: Failing tests**:
  - Password round-trip, plus a wrong password returns False.
  - Token round-trip; a token signed with another secret raises `Unauthorized`; an expired token raises.
  - `new_opaque_token` hash equals `hash_opaque(raw)`.
  - TOTP verifies `pyotp.TOTP(secret).now()`.
  - `hash_otp` is deterministic per phone and differs across phones.
  - Phone cases from Review Focus #2 (`"+91 93618 99061"`, `"09361899061"`, `"919361899061"`, `"9361899061"` all return `"9361899061"`; `"12345"` and `"5361899061"` raise `Unprocessable`).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat(core): password, jwt, opaque token, totp, otp and phone helpers`.

### Task 10: Schema: tenancy, IAM, audit tables, initial migration with role seed

**Files:**
- Create: `backend/src/mallt/modules/tenancy/models.py`, `backend/src/mallt/modules/iam/models.py`, `backend/src/mallt/modules/audit/models.py`, `backend/src/mallt/models_registry.py`, `backend/alembic/versions/0001_iam_tenancy_audit.py`, `backend/tests/test_migrations.py`

**Interfaces:**
- Produces tables (all with `IdMixin` + `TimestampMixin` unless noted):
  - `organizations`: `name` (text), `slug` (citext-like: store lowercase, unique), `status` (`active|suspended`), `commission_bps` int default 500, `accept_timeout_s` int default 300.
  - `malls`: `organization_id` FK, `name`, `slug` (globally unique; it is the QR URL), `status`, `city`, `address`. Index on `organization_id`.
  - `stores`: `organization_id` FK, `mall_id` FK, `name`, `slug` (unique per mall: `uq_stores_mall_id_slug`), `status` (`active|suspended`), `commission_bps` int NULL (override). Indexes on `organization_id` and `mall_id`.
  - `staff_users`: `username` (unique), `display_name`, `email` NULL, `password_hash`, `status` (`active|suspended`), `must_change_password` bool default true, `totp_secret` NULL, `totp_enabled` bool default false, `last_login_at` NULL.
  - `customers`: `phone` NULL unique, `google_sub` NULL unique, `email` NULL, `name` NULL, `status`.
  - `roles`: `key` unique, `name`, `scope_type`, `is_system` bool. `role_permissions`: (`role_id` FK, `permission` text), primary key on both.
  - `role_assignments`:
    - Columns: `staff_user_id` FK (index), `role_id` FK, `scope_type`, `organization_id` NULL FK, `mall_id` NULL FK, `store_id` NULL FK, `granted_by` NULL FK → `staff_users`.
    - Unique `(staff_user_id, role_id, scope_type, organization_id, mall_id, store_id)` with `NULLS NOT DISTINCT`.
    - Indexes on `organization_id` and `store_id`.
  - `refresh_tokens`: `identity_type` (`staff|customer`), `subject_id` UUID (index), `family_id` UUID (index), `token_hash` unique, `expires_at`, `rotated_at` NULL, `revoked_at` NULL, `user_agent` NULL, `ip` NULL.
  - `audit_logs` (no `updated_at`): `actor_type` (`staff|customer|system`), `actor_id` NULL, `action` text, `target_type`, `target_id` NULL, `organization_id` NULL (index), `mall_id` NULL, `store_id` NULL, `before` JSONB NULL, `after` JSONB NULL, `ip` NULL, `request_id` NULL. Index on `(organization_id, created_at desc)`.
- Migration `0001`:
  - Creates all of the above.
  - Inserts the 5 system roles and their permissions as **literal data** (copied from `SYSTEM_ROLES`, not imported).
  - `downgrade()` drops everything.
- ORM status/type columns use `sqlalchemy.Enum(..., native_enum=False, length=20)` so values stay as checked text.

- [ ] **Step 1: Failing tests** in `tests/test_migrations.py`:
  - `test_upgrade_downgrade_roundtrip`: run alembic `downgrade base`, then `upgrade head`, on a throwaway schema. Neither step raises.
  - `test_seeded_roles_match_code`: query `roles` + `role_permissions` and assert, for every key, that the permission set equals `SYSTEM_ROLES[key].permissions`. This catches drift between the migration literal and the code.
  - `test_no_autogenerate_drift`: `alembic check` exits 0 (models match migrations).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Write the models, register them in `models_registry.py`, and write migration 0001 (autogenerate, then hand-edit the seed and `NULLS NOT DISTINCT`).
- [ ] **Step 4:** Run `uv run pytest tests/test_migrations.py -v`. Expected: PASS. Then run `uv run alembic upgrade head` against **Neon dev**. Expected: success.
- [ ] **Step 5:** Commit `feat(db): tenancy, iam and audit schema with seeded system roles`.

### Task 11: Audit service and authz service (principal, can, require)

**Files:**
- Create: `backend/src/mallt/modules/audit/{repository,service,schemas}.py`, `backend/src/mallt/modules/iam/{repository,authz,deps}.py`, `backend/tests/modules/iam/test_authz.py`, `backend/tests/factories.py`

**Interfaces:**
- Produces:
  - `AuditService(session).record(*, actor: Actor, action: str, target_type: str, target_id: UUID|None, scope: Scope|None, before: dict|None=None, after: dict|None=None) -> None`. It adds a row within the caller's transaction and takes `ip`/`request_id` from the contextvars set by the middleware. `Actor = (type, id)`.
  - `@dataclass(frozen=True) Grant(role_key: str, scope: Scope, permissions: frozenset[P])`.
  - `@dataclass(frozen=True) Principal(staff_id: UUID, username: str, status: str, must_change_password: bool, grants: tuple[Grant, ...])`.
  - `AuthzService(session, redis)` methods:
    - `load_principal(staff_id) -> Principal`: reads the Redis cache `authz:staff:{id}` (JSON, TTL 60). On a miss it builds the principal from `role_assignments` ⋈ `role_permissions`. It raises `Unauthorized("account_suspended")` if the status is suspended.
    - `can(p: Principal, perm: P, target: Scope) -> bool`: some grant has `perm` and `contains(grant.scope, target)`.
    - `require(p, perm, target) -> None`: if `can`, return. Otherwise, if any grant's scope shares `target.organization_id` (or the principal has a platform grant), raise `Forbidden("missing_permission")`; else raise `NotFound`.
    - `visible_org_ids(p) -> set[UUID] | None`: None means platform (all orgs).
    - `invalidate(staff_id) -> None` deletes the cache key.
  - `deps.py`:
    - `bearer_claims(request) -> AccessClaims`: requires `Authorization: Bearer`, otherwise `Unauthorized`.
    - `current_staff(...) -> Principal`: requires `typ=="staff"`, the session id not revoked (checked via `SessionService.is_active(sid)` in Task 12; stub it here as always-active and wire it in Task 12), then `load_principal`.
    - `current_customer(...) -> CustomerOut`: lands in Task 16.
  - `tests/factories.py` provides async helpers `make_org`, `make_mall`, `make_store`, `make_staff(username, password="Passw0rd!!", roles=[(role_key, Scope)])` and `auth_headers(client, username, password, totp=None)`. These insert directly through the session (test-only).

- [ ] **Step 1: Failing tests** (service-level, real DB + Redis):
  - `test_store_staff_can_update_order_in_own_store_only`: staff at store S1 → `can(order.update, S1)` True; `can(order.update, S2-same-mall)` False.
  - `test_org_owner_inherits_down_to_store`.
  - `test_require_cross_org_is_404_same_org_is_403`: a store_staff of org A requiring `store.product.write` on their own store gets Forbidden; on org B's store gets NotFound.
  - `test_principal_cached_and_invalidated`: load, then delete the assignment row, then load again → still cached; after `invalidate` → no grants.
  - `test_suspended_staff_rejected` (Review Focus #3): set status suspended + `invalidate` → `load_principal` raises `Unauthorized`.
  - `test_audit_record_persists_scope_ids`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat(iam): scoped authorization service with cached principals; audit recording`.

### Task 12: Sessions and staff authentication API

**Files:**
- Create: `backend/src/mallt/modules/iam/{sessions,staff_auth,schemas,router}.py`, `backend/tests/modules/iam/test_staff_auth.py`, `backend/tests/modules/iam/test_sessions.py`
- Modify: `iam/deps.py` (session-active check), `main.py` (mount router, tag `auth`)

**Interfaces:**
- Produces:
  - `SessionService(session, settings)` methods:
    - `issue(identity_type, subject_id, *, family_id=None, user_agent, ip) -> tuple[str, RefreshTokenRow]`.
    - `rotate(raw) -> tuple[str, RefreshTokenRow]`:
      - Unknown, expired or revoked → `Unauthorized("invalid_refresh")`.
      - Already rotated → revoke the entire family and raise `Unauthorized("refresh_reuse")`.
      - Otherwise mark it rotated and issue a new token in the same family.
    - `revoke_family(family_id)`, `revoke_all(identity_type, subject_id)`.
    - `is_active(family_id) -> bool`.
    - `list_active(identity_type, subject_id) -> list[SessionOut]`.
    - The access token's `sid` is the **family_id**, so logout and revoke kill access tokens on the next request.
  - Endpoints (prefix `/api/v1/auth/staff`, tag `auth`):
    - `POST /login` body `StaffLogin{username, password, totp_code: str|None}` → `TokenOut{access_token, token_type:"bearer", expires_in}` and sets the cookie `mallt_srt`.
      - Rate limited per Global Constraints.
      - Generic `Unauthorized("invalid_credentials")` for an unknown user or a wrong password (constant-time: verify against a dummy hash when the user is missing).
      - Suspended → `Unauthorized("account_suspended")`.
      - If `totp_enabled` and the code is missing → `Unauthorized("totp_required")`. A wrong code → `Unauthorized("invalid_totp")`.
      - A user with a platform grant whose `totp_enabled` is false → `Unauthorized("totp_enrollment_required")`. The seed command enrolls admins, so this should not happen.
      - Updates `last_login_at`; rehashes the password if needed.
    - `POST /refresh` (cookie + CSRF header) → `TokenOut`, rotated cookie.
    - `POST /logout` → revoke the current family, clear the cookie, return 204.
    - `POST /logout-all` (bearer) → revoke all, return 204.
    - `GET /me` (bearer) → `StaffMe{id, username, display_name, must_change_password, totp_enabled, grants: list[GrantOut{role_key, scope_type, organization_id, mall_id, store_id, permissions: list[str]}]}`.
    - `POST /password` body `{current_password, new_password}` → 204. It clears `must_change_password`, revokes the other families and writes an audit row `staff.password_changed`.
    - `POST /totp/setup` → `{secret, otpauth_uri}` (stored but not yet enabled). `POST /totp/confirm {code}` → 204, enables it, audit row.
    - `GET /sessions` → `list[SessionOut]`.
  - Until the password is changed, a principal with `must_change_password` may call only `/me`, `/password` and `/logout`. Every other staff endpoint returns `Forbidden("password_change_required")`. Enforce this in `current_staff`.

- [ ] **Step 1: Failing tests** (HTTP through `client`):
  - Login happy path returns a token and sets the `mallt_srt` cookie with HttpOnly and SameSite=Lax.
  - `" Ravi.K "` logs in as `ravi.k` (Review Focus #5).
  - A wrong password and an unknown user produce the identical body.
  - The 11th login attempt within 15 min returns 429 with `Retry-After`.
  - Refresh without `X-Requested-With` returns 403.
  - Refresh rotates the token. Reusing the old cookie returns 401 `refresh_reuse`, and after that the new cookie also returns 401 (family revoked).
  - After logout, the old access token gets 401 on `/me`.
  - TOTP-enabled user: no code → `totp_required`; a valid `pyotp` code → 200.
  - `must_change_password` user: `GET /me` 200, any other staff endpoint 403 `password_change_required`; after `POST /password`, allowed.
  - Suspending a user (factory sets status + invalidate) gets 401 on the next `/me` (Review Focus #3, HTTP level).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat(iam): staff login, refresh rotation with reuse detection, totp, sessions`.

### Task 13: `seed-admin` command

**Files:**
- Modify: `backend/src/mallt/cli.py`
- Create: `backend/tests/test_cli.py`

**Interfaces:**
- Produces:
  - `python -m mallt.cli seed-admin --username U --display-name D` with the password read from the `MALLT_ADMIN_PASSWORD` env var or prompted.
    - Creates the staff user with `must_change_password=false`, assigns `platform_admin` at `Scope.platform()`, generates and enables TOTP, and prints the `otpauth_uri` once.
    - Idempotent: if the username exists, exit code 1 with the message `already exists`.
  - `async def seed_admin(session, *, username, display_name, password) -> str` returns the otpauth URI. The CLI wraps it.

- [ ] **Step 1: Failing test:** `seed_admin` creates the user with a platform grant and `totp_enabled=True`. A second call raises `Conflict`. Logging in with a pyotp code from the returned URI works.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Commit `feat(iam): seed-admin command`.

### Task 14: Tenancy: organizations, malls, stores

**Files:**
- Create: `backend/src/mallt/modules/tenancy/{repository,service,schemas,router}.py`, `backend/tests/modules/tenancy/test_tenancy_api.py`
- Modify: `main.py` (tags `orgs`, `malls`, `stores`)

**Interfaces:**
- Consumes: `AuthzService.require`, `AuditService.record`, `IamUsers.create_staff_user` and `IamRoles.assign` (from Task 15's service, see the ordering note).
- Produces endpoints (all bearer staff):
  - `POST /api/v1/orgs` (`platform.org.manage`), body `OrgCreate{name, slug, owner: OwnerCreate{username, display_name, email?}}` → `OrgCreatedOut{org: OrgOut, owner_username, temp_password}`. The temp password is shown once. The owner is created with `must_change_password=true` and the `org_owner` role at `Scope.org(org.id)`. Everything happens in one transaction.
  - `GET /api/v1/orgs` → cursor page of `OrgOut`, filtered by `visible_org_ids`.
  - `GET/PATCH /api/v1/orgs/{org_id}` (PATCH: `org.settings.update`; `commission_bps` requires `org.billing.manage`).
  - `POST /api/v1/orgs/{org_id}/suspend` and `/activate` (`platform.org.manage`).
  - `POST/GET /api/v1/orgs/{org_id}/malls`, `GET/PATCH /api/v1/malls/{mall_id}`, `POST /api/v1/malls/{mall_id}/suspend` and `/activate` (`org.mall.manage`; GET needs any grant within the org).
  - `POST/GET /api/v1/malls/{mall_id}/stores`, `GET/PATCH /api/v1/stores/{store_id}`, `POST /api/v1/stores/{store_id}/suspend` and `/activate`:
    - create, suspend and activate need `org.store.manage`;
    - PATCH of `name` and `status` needs `org.store.manage`;
    - PATCH of profile fields needs `store.profile.update`.
  - `GET /api/v1/public/malls/{slug}` (no auth) → `PublicMallOut{name, slug, city, stores: [{name, slug}]}` with active stores only. It returns 404 if the mall or org is suspended. This feeds the `/m/[mallSlug]` placeholder.
  - `TenancyService.scope_for_org(org_id)`, `scope_for_mall(mall_id)` and `scope_for_store(store_id) -> Scope` (each raises NotFound). These are used by the staff module.
  - Slugs: `^[a-z0-9-]{3,60}$`. A duplicate returns `Conflict("slug_taken")`.
  - Mutations under a suspended org or mall by a non-platform principal return `Conflict("suspended")`.
  - Every mutation writes an audit row (`org.created`, `mall.updated`, …) with before and after.
- **Ordering note:** implement Task 15's `IamUsers.create_staff_user` / `IamRoles.assign` service functions **inside this task** (service layer only, no endpoints) because org creation needs them. Task 15 adds their endpoints and the anti-escalation rules.

- [ ] **Step 1: Failing tests:**
  - Admin creates an org and gets a temp password; the owner can log in with it and gets `must_change_password`.
  - Org owner A creates a mall and a store.
  - Org owner A GET/PATCH on org B's mall returns **404**.
  - Org manager PATCH `commission_bps` returns **403**.
  - Store owner PATCH store profile returns 200; store owner PATCH store `status` returns 403.
  - Duplicate mall slug returns 409 `slug_taken`.
  - A public mall lists active stores only; the public endpoint for a suspended mall returns 404.
  - `GET /orgs` as org owner A returns only org A.
  - Every mutation produces exactly one audit row.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** Run `make api-client` and commit the generated client. Commit `feat(tenancy): organizations, malls and stores with scoped access`.

### Task 15: Staff management API with anti-escalation

**Files:**
- Create: `backend/src/mallt/modules/staff/{repository,service,schemas,router}.py`, `backend/tests/modules/staff/test_staff_api.py`
- Modify: `main.py` (tag `staff`)

**Interfaces:**
- Consumes: `TenancyService.scope_for_*`, `AuthzService`, `IamUsers`, `IamRoles`, `AuditService`, `SessionService.revoke_all`.
- Produces endpoints (bearer staff; `{scope_type}` ∈ `org|mall|store`; `{scope_id}` is that entity's id):
  - `GET /api/v1/{scope_type}s/{scope_id}/staff` → staff with grants at or under that scope (requires `STAFF_MANAGE_FOR[scope]` or `audit.read`).
  - `POST /api/v1/{scope_type}s/{scope_id}/staff` body `StaffCreate{username, display_name, email?, role_key}` → `StaffCreatedOut{staff: StaffOut, temp_password}`.
  - `POST /api/v1/staff/{staff_id}/roles` body `{role_key, scope_type, scope_id}` → 201 `GrantOut`. `DELETE /api/v1/staff/{staff_id}/roles/{assignment_id}` → 204.
  - `POST /api/v1/staff/{staff_id}/suspend`, `/activate`, `/reset-password` (→ `{temp_password}`, sets `must_change_password`, revokes the user's sessions).
  - `GET /api/v1/roles` → the system roles with their permissions (for UI pickers).
- **Anti-escalation rule** (`StaffService._check_can_grant(actor, role, target_scope)`):
  - The role's `scope_type` must equal `target_scope.type`.
  - The actor must have `STAFF_MANAGE_FOR[target_scope.type]` on `target_scope`.
  - Every permission in the role must pass `can(actor, perm, target_scope)`.
  - Failing the rule gives `Forbidden("cannot_grant_role")`. A target outside the actor's tenancy gives `NotFound`.
- **Acting on a staff user** (suspend, reset, revoke): the actor must hold `STAFF_MANAGE_FOR` at a scope that contains **every** grant of the target user, otherwise 403/404. Nobody can act on themselves through these endpoints (`Conflict("self_action")`).
- **Last-owner protection** (Review Focus #4): revoking the `org_owner` assignment, or suspending a user, such that the org would have zero active org owners returns `Conflict("last_owner")`.
- Usernames are normalised; a duplicate returns `Conflict("username_taken")`.
- Every action writes an audit row and calls `AuthzService.invalidate(target_id)`.

- [ ] **Step 1: Failing tests:**
  - Org owner creates a store owner for store S → the temp password works.
  - Store owner creates store staff in their store → OK.
  - Store owner creates a store_owner in a **different** store of the same mall → 403.
  - Org manager assigns `org_owner` → 403 `cannot_grant_role`.
  - Org manager assigns `org_manager` → 403.
  - Org owner of A assigns a role in org B → 404.
  - Store owner suspends an org manager → 403.
  - Revoking the only org_owner → 409 `last_owner`; after adding a second owner → 204.
  - Suspended staff → 401 on the next request.
  - `Ravi.K` vs existing `ravi.k` → 409 (Review Focus #5).
  - Reset password → old sessions get 401, and the temp password logs in with `must_change_password`.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** `make api-client`; commit `feat(staff): staff management with scoped role assignment and anti-escalation`.

### Task 16: Customer authentication (phone OTP + Google) and profile

**Files:**
- Create: `backend/src/mallt/modules/iam/{customer_auth,sms,google}.py`, `backend/tests/modules/iam/test_customer_auth.py`, `backend/tests/modules/iam/test_sms.py`
- Modify: `iam/router.py`, `iam/deps.py` (`current_customer`), `tests/conftest.py` (override `get_sms_sender` with `FakeSms`, `get_google_verifier` with `FakeGoogle`)

**Interfaces:**
- Produces:
  - `class SmsSender(Protocol): async def send_otp(self, phone: str, otp: str) -> None`.
    - `ConsoleSms` logs `otp sent` with the masked phone and prints the OTP **only when `settings.env == "dev"`**.
    - `Fast2Sms(api_key, client: httpx.AsyncClient)` sends `GET https://www.fast2sms.com/dev/bulkV2` with params `route=otp`, `variables_values=<otp>`, `numbers=<10-digit>` and header `authorization: <key>`. It raises `AppError(502, "sms_failed")` when `return` is not true.
    - `get_sms_sender(settings)` picks the implementation by `sms_backend`.
  - `class GoogleVerifier(Protocol): async def verify(self, id_token: str) -> GoogleIdentity(sub, email, name)`. `GoogleIdTokenVerifier` uses `google.oauth2.id_token.verify_oauth2_token` with audience `google_client_id`, run in a threadpool.
  - Endpoints (prefix `/api/v1/auth/customer`, tag `auth`):
    - `POST /otp/request {phone}` → 202 `{expires_in: 300}`.
      - Normalises the phone and applies the rate limits from Global Constraints.
      - Stores `otp:{phone}` = hash with TTL 300 and resets `otp:tries:{phone}`.
      - Sends the OTP as an ARQ job when the worker is available, otherwise inline. **My call: inline in M1 for simplicity; move it to ARQ in M3.**
    - `POST /otp/verify {phone, otp}` → `TokenOut` + cookie `mallt_crt`. Wrong OTP → 401 `invalid_otp`. The sixth try → 429 and the OTP key is deleted. Success deletes the key and upserts the customer by phone.
    - `POST /google {id_token}` → `TokenOut` + cookie. Finds by `google_sub`, else creates a customer with `phone=NULL`.
    - `POST /phone/verify {phone, otp}` (bearer customer) → `TokenOut`. It links the phone to the current customer. If another customer already owns that phone, it moves `google_sub` to that customer, deletes the phone-less current customer and issues a session for the owner (spec §5.1 linking rule).
    - `POST /refresh`, `POST /logout` (cookie `mallt_crt`, CSRF header).
    - `GET /me` → `CustomerMe{id, phone_masked, has_phone, name, email}`. `PATCH /me {name?, email?}`.

- [ ] **Step 1: Failing tests:**
  - OTP flow with `FakeSms`, which captures the code: request → verify → `/me` 200.
  - All four phone formats from Review Focus #2 map to the same customer id. `12345` → 422.
  - The 4th request in 10 min → 429.
  - 5 wrong verifies then the right one → 429, and the OTP is gone.
  - An expired OTP (TTL forced to 0) → 401.
  - Google login creates a customer without a phone (`has_phone` false).
  - The phone/verify linking case merges into the existing phone customer and returns its id.
  - A customer token on a staff endpoint → 401, and a staff token on a customer endpoint → 401.
  - `test_sms.py`: `Fast2Sms` with `httpx.MockTransport` asserts the key is in the `authorization` header and **not** in the URL, and that the params match. A `{"return": false}` response raises 502.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** `make api-client`; commit `feat(iam): customer phone otp and google login with phone linking`.

### Task 17: Audit read API

**Files:**
- Create: `backend/src/mallt/modules/audit/router.py`, `backend/tests/modules/audit/test_audit_api.py`

**Interfaces:**
- Produces:
  - `GET /api/v1/orgs/{org_id}/audit?cursor&limit` (`audit.read` at org scope).
  - `GET /api/v1/admin/audit?organization_id?&cursor&limit` (platform `audit.read`).
  - Both return `Page[AuditOut{id, created_at, actor_type, actor_id, actor_username, action, target_type, target_id, before, after}]`, newest first. The cursor is keyset on `(created_at, id)`. `limit` ≤ 100, default 50.
  - `actor_username` comes from `IamUsers.usernames_by_ids` (one query).
- [ ] **Step 1: Failing tests:** org owner sees own-org entries only; org B → 404; store owner → 403; pagination returns disjoint pages that cover everything.
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5:** `make api-client`; commit `feat(audit): audit log read endpoints`.

### Task 18: Frontend auth plumbing (staff + customer)

**Files:**
- Create: `frontend/src/lib/auth/{token-store,refresh,staff-session,customer-session,guards}.ts(x)` with tests next to them, and `frontend/src/app/login/page.tsx`
- Modify: `frontend/src/app/providers.tsx`, `frontend/src/lib/api-config.ts`

**Interfaces:**
- Produces:
  - `tokenStore`: an in-memory access token per identity (`"staff" | "customer"`) with `get`, `set` and `clear`. Never stored in localStorage.
  - `refreshAccess(kind) -> Promise<string | null>`:
    - Single-flight inside a tab (one shared promise).
    - Across tabs it wraps the call in `navigator.locks.request("mallt-refresh-"+kind, …)`. Inside the lock it first re-checks whether another tab already refreshed, via a `BroadcastChannel("mallt-auth")` message carrying the new token (Review Focus #1).
  - The API client's response interceptor handles a 401 with code `invalid_token` by calling `refreshAccess` once, then retrying once. On failure it clears the token and calls `onUnauthorized`.
  - `useStaffSession()` → `{status: "loading"|"anon"|"authed", me: StaffMe|null, login(u,p,totp?), logout(), can(perm, scope?)}`. `can` mirrors the backend `contains` check using `me.grants`, for UI hiding only. `useCustomerSession()` is the customer equivalent.
  - `<RequireStaff>`:
    - Redirects `anon` to `/login?next=…`.
    - Redirects `must_change_password` to `/account/password`. (The page lives at `src/app/(staff)/account/password/page.tsx`. Create it in this task: two fields plus submit.)
  - `/login` page: shadcn Card with username, password, and a TOTP field that is shown after `totp_required`. Errors appear via toast. On success it routes to the first area the user has access to: platform grant → `/admin`, org grant → `/org`, store grant → `/store`.

- [ ] **Step 1: Failing vitest tests:**
  - Two concurrent `refreshAccess("staff")` calls in one tab produce exactly **one** fetch.
  - With a mocked `navigator.locks` and BroadcastChannel, a token broadcast by "another tab" while waiting makes this tab skip its own fetch.
  - On 401 `invalid_token` the interceptor refreshes and retries once; when the refresh fails it calls `onUnauthorized`.
  - `can()` mirrors the scope containment cases from Task 8.
- [ ] **Step 2–4:** FAIL → implement → PASS (`pnpm test && pnpm typecheck`).
- [ ] **Step 5:** Commit `feat(web): auth token handling, cross-tab refresh, staff login and guards`.

### Task 19: Admin and org dashboards (plain, functional)

**Files:**
- Create:
  - `frontend/src/app/(admin)/admin/{layout,page}.tsx`, `(admin)/admin/orgs/{page,[orgId]/page}.tsx`, `(admin)/admin/audit/page.tsx`
  - `frontend/src/app/(org)/org/{layout,page}.tsx`, `(org)/org/[orgId]/{page,malls/page,malls/[mallId]/page,staff/page,audit/page}.tsx`
  - `frontend/src/components/{data-table,temp-password-dialog,staff-manager,confirm-dialog}.tsx`
  - Component tests for `temp-password-dialog` and `staff-manager`

**Interfaces:**
- Consumes: the generated SDK functions for Tasks 14, 15 and 17, plus `useStaffSession`.
- Produces screens (stock shadcn; tables, forms and dialogs; no styling beyond defaults):
  - **Admin:**
    - Org list.
    - Create org + owner, showing `TempPasswordDialog` with a copy button and the text "shown once".
    - Org detail: suspend/activate, malls (read-only).
    - Global audit table.
  - **Org:**
    - Org picker if the user has more than one.
    - Settings form (commission field only if `can(org.billing.manage)`).
    - Malls CRUD; mall detail with stores CRUD.
    - Org-level staff via `StaffManager` (list, create with role select, assign/revoke role, suspend/activate, reset password).
    - Audit table with "Load more".
  - `StaffManager({scopeType, scopeId})` is reused in Task 20.
  - Errors appear as a toast showing the problem `title` and `detail`.
- [ ] **Step 1: Failing component tests:** `TempPasswordDialog` renders the password and copies it to the clipboard. `StaffManager` hides the "Reset password" action for a target whose grants lie outside the viewer's scope (computed via `can`), and the role select lists only roles the viewer can grant (mirroring the anti-escalation rule).
- [ ] **Step 2–4:** FAIL → implement → PASS. Then run `pnpm build`. Expected: success.
- [ ] **Step 5:** Commit `feat(web): admin and org dashboards`.

### Task 20: Store dashboard and customer account pages

**Files:**
- Create: `frontend/src/app/(store)/store/{layout,page}.tsx`, `(store)/store/[storeId]/{page,staff/page,profile/page}.tsx`, `frontend/src/app/(customer)/account/{login/page,page}.tsx`, `frontend/src/components/google-button.tsx`, `frontend/src/app/(customer)/m/[mallSlug]/page.tsx` (replaces the placeholder)

**Interfaces:**
- Consumes: the SDK for Tasks 14, 15 and 16, `useCustomerSession`, and `StaffManager`.
- Produces:
  - **Store dashboard:** store picker; store home showing name, mall and status; staff page using `StaffManager scopeType="store"`; a profile page placeholder form (name only — M2 adds theming).
  - **Customer `/account/login`:**
    - Phone step → OTP step (6 boxes or a single input), or the Google button.
    - The Google button loads `https://accounts.google.com/gsi/client` and calls `google.accounts.id.initialize({client_id: NEXT_PUBLIC_GOOGLE_CLIENT_ID, callback})`. It is hidden when the env var is empty.
    - After Google login without a phone, it prompts for phone verification.
  - **Customer `/account`:** masked phone, editable name/email, logout.
  - **`/m/[mallSlug]`:** a server component that fetches `GET /api/v1/public/malls/{slug}` with `next: { revalidate: 60, tags: ["mall:"+slug] }` and lists the stores. It shows `notFound()` on 404. This placeholder proves the QR route works end to end.
- [ ] **Step 1: Failing component tests:**
  - The OTP form submits the normalised flow (phone → request → verify) using a mocked SDK.
  - The Google button is not rendered without a client id.
  - The mall page renders the store names from a mocked fetch and calls `notFound` on 404.
- [ ] **Step 2–4:** FAIL → implement → PASS; `pnpm build`.
- [ ] **Step 5:** Commit `feat(web): store dashboard, customer login/account, public mall page`.

### Task 21: End-to-end IAM flow (Playwright) and milestone verification

**Files:**
- Create: `frontend/playwright.config.ts`, `frontend/e2e/iam.spec.ts`, `frontend/e2e/global-setup.ts`
- Modify: `Makefile` (`e2e` target), `.github/workflows/ci.yml` (`e2e` job: compose up with a Postgres 17 test DB as `DATABASE_URL` and `SMS_BACKEND=console`)

**Interfaces:**
- Consumes: the whole stack through nginx on `http://localhost:8080`.
- Produces:
  - `global-setup.ts` runs `seed-admin` inside the api container with a known password and captures the otpauth URI to compute TOTP codes using the `otpauth` dev dependency.
  - In e2e mode (`env == "test"`), an `E2E_FIXED_OTP=123456` setting makes `ConsoleSms`/OTP generation deterministic. It is **only honoured when `env == "test"`** — add a backend unit test asserting that it is ignored in dev and prod.

- [ ] **Step 1: Write the spec** `iam.spec.ts`:
  1. The admin logs in (with TOTP) and creates org "Phoenix Group" with owner `phoenix.owner`; the test captures the temp password.
  2. The owner logs in, is forced to change the password, then creates mall `phoenix-pune` and store `burger-hub`, and creates store owner `burger.owner`.
  3. The store owner logs in and lands on `/store`, sees Burger Hub and creates staff `burger.cashier`.
  4. The store owner can't see the org staff page (navigating there shows 404).
  5. The customer opens `/m/phoenix-pune` and sees Burger Hub, logs in at `/account/login` with phone `9361899061` and OTP `123456`, and the account shows `******9061`.
- [ ] **Step 2:** Run `make dev` (test env), then `make e2e`. Expected: all steps pass.
- [ ] **Step 3: Milestone verification** (superpowers:verification-before-completion). Run `make lint test e2e` and `docker compose build` and paste the outputs. Then run `alembic upgrade head` against Neon dev and `seed-admin` on Neon dev for the owner's real admin account (the owner provides the username).
- [ ] **Step 4:** Commit `test(e2e): iam end-to-end flow` and push. Open a PR only when the owner asks.

---

## Self-Review Notes

- **Spec coverage:**
  - §5.1 auth → Tasks 9, 12, 13, 16.
  - §5.2 RBAC and matrix → Tasks 8, 10, 11, 15.
  - §5.3 audit → Tasks 11, 17.
  - §5.4 deliverables → Tasks 13–20.
  - §9 architecture and environments → Tasks 1–7.
  - §9.4 performance (pooling, indexes, caching) → Tasks 2, 10, 11, 20.
  - §9.5 functional-first UI → Tasks 19–20.
  - §9.6 security → Tasks 3, 9, 12, 16, plus nginx in Task 6.
  - Payments, catalog and orders are intentionally absent.
- **Deferred within M1 (my calls):** OTP sending runs inline (moves to ARQ in M3). The worker runs only a heartbeat job. There is no email-based password reset (spec §5.1).
