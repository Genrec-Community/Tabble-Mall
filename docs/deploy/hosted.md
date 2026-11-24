# Hosted MallT (Vercel + Render + Neon)

Live since 2026-11-24. Free tiers everywhere; nothing here is AWS yet.

| Piece | Where | Notes |
|---|---|---|
| Website | Vercel project `tabble-mall` → https://tabble-mall.vercel.app | Functions in `sin1`. `/api/*` is proxied to the API by `next.config.ts` rewrites (`API_PROXY_URL`), so auth cookies stay first-party. |
| API | Render web service `mallt-api` (Singapore, free) → https://mallt-api.onrender.com | Docker `infra/docker/api.Dockerfile`, auto-deploys branch `jaisamyukth-changes`. `MIGRATE_ON_START=true` runs `alembic upgrade head` on every start. |
| Database | Neon project `mallt-prod` (AWS ap-southeast-1, Postgres 17) | Pooled connection string in Render's `DATABASE_URL`. |
| Images | Neon Object Storage bucket `mallt-prod` (public read) on the same Neon branch | `S3_*` variables on Render. Browser PUTs straight to it (CORS allows any origin). |
| Live updates | Browser opens `wss://mallt-api.onrender.com/ws/orders` (`NEXT_PUBLIC_WS_BASE`) | Vercel can't proxy WebSockets. Print agents also point at `https://mallt-api.onrender.com`. |

## Vercel environment

- `DEMO_API=0` (set `1` only to go back to the built-in sample data)
- `API_PROXY_URL`, `API_INTERNAL_URL`, `NEXT_PUBLIC_WS_BASE` = `https://mallt-api.onrender.com`

## Render environment (values live only in Render)

`ENV=prod`, `MIGRATE_ON_START=true`, `DATABASE_URL`, `JWT_SECRET`, `OTP_PEPPER`, `COOKIE_SECURE=true`,
`CORS_ORIGINS=["https://tabble-mall.vercel.app"]`, `SMS_BACKEND=fast2sms`, `FAST2SMS_API_KEY`,
`S3_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`,
`S3_PUBLIC_BASE_URL`, `PAYMENTS_PROVIDER=fake`, `GATEWAY_FEE_BPS=50`.

Switching to real payments later: set `PAYMENTS_PROVIDER=zoho`, the six `ZOHO_*` values and
`ZOHO_SANDBOX`; the API refuses to start in prod if any are missing.

## Limits of the free plans

- Render free sleeps after 15 minutes idle; the next request waits about a minute while it wakes.
  Render Starter removes that.
- Neon free: 0.5 GB storage, compute scales to zero when idle (wakes in under a second).

## First admin

Created with `mallt.cli seed-admin` on a scratch database and copied into Neon (the cloud
sandbox can't reach Postgres port 5432). Later admins are created from the admin dashboard.
