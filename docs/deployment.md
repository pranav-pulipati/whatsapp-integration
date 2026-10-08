# Deployment

## Recommended topology

```mermaid
flowchart LR
  D360[360dialog] -->|HTTPS| C[Caddy<br/>auto TLS]
  U[Staff browser] -->|HTTPS| C
  C --> API[api container<br/>FastAPI + dashboard]
  W[worker container] --> PG
  API --> PG[(Managed PostgreSQL)]
  API --> S3[(S3 / R2 bucket)]
  W --> S3
  W -->|media download| D360
```

- **One small VM** (2 vCPU, 2–4 GB) running `deploy/docker-compose.prod.yml`: Caddy, `api`, `worker`, and a one-shot `migrate` job.
- **Managed PostgreSQL** with automated backups and point-in-time recovery (AWS RDS, Cloud SQL, Neon, Supabase, DigitalOcean…).
- **S3-compatible bucket**, private, with versioning on (AWS S3, Cloudflare R2, …).

Alternatives work unchanged with the same image. On a PaaS such as Render, Railway or Fly.io, run the image twice:
- a web service with the default command;
- a worker with `python -m app.worker`.

Add a release command `alembic upgrade head`.

## Production environment variables

Set these in `.env` on the server (or your platform's secret manager). See `.env.example` for all of them.

| Variable | Production value |
|---|---|
| `APP_ENV` | `production`. This enables strict config validation and HSTS. |
| `DOMAIN` | e.g. `wa.yourcompany.com` (used by Caddy) |
| `PUBLIC_BASE_URL` | `https://wa.yourcompany.com`, which **must** be https |
| `DATABASE_URL` | `postgresql+psycopg://USER:PASSWORD@HOST:5432/DB?sslmode=require` |
| `JWT_SECRET` | 48+ random characters |
| `ENCRYPTION_KEY` | Fernet key (`python -m app.cli gen-key`). **Back it up.** If you lose it, the stored API keys can't be decrypted. |
| `WEBHOOK_SHARED_SECRET` | 32+ random characters |
| `S3_ENDPOINT_URL` | empty for AWS S3; the R2/MinIO endpoint otherwise |
| `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | bucket credentials, limited to that bucket |
| `S3_SERVER_SIDE_ENCRYPTION` | `AES256` on AWS S3 |
| `CORS_ORIGINS` | leave empty (the dashboard is same-origin) |
| `WEB_CONCURRENCY` | API worker processes (default 2) |

The app refuses to start in production if `JWT_SECRET`, `ENCRYPTION_KEY` or `WEBHOOK_SHARED_SECRET` are missing or weak, or if `PUBLIC_BASE_URL` isn't https.

## First deployment

```bash
# on the VM (Docker installed, DNS A record for $DOMAIN pointing at it, ports 80/443 open)
git clone <repo> wa-dashboard && cd wa-dashboard
cp .env.example .env && nano .env            # fill in the production values above
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d --build
docker compose -f deploy/docker-compose.prod.yml exec api python -m app.cli create-user you@company.com --role admin
curl https://$DOMAIN/health/ready             # {"status":"ok"}
```

Caddy obtains and renews the Let's Encrypt certificate automatically. This matters because 360dialog requires a valid certificate, no underscores in the hostname and no explicit port.

## Webhook URL configuration

Each number has its own URL, `https://$DOMAIN/webhooks/360dialog/<token>`. Register it from the dashboard (**Numbers → number → Register webhook**) or with:

```bash
docker compose -f deploy/docker-compose.prod.yml exec api python -m app.cli register-webhook <account-id-or-number>
```

This sends `POST https://waba-v2.360dialog.io/v1/configs/webhook` with the URL and the `X-Webhook-Secret` header.

## Migrations

Migrations run automatically in the `migrate` job before `api` and `worker` start. They are forward-only and additive by default. For a destructive change:
1. Ship the code that stops using the column.
2. Drop it in a later release.

To run them by hand: `docker compose … run --rm migrate`.

## Updating

```bash
git pull
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d --build
```

Webhooks received during the restart (a few seconds) get a non-200, and 360dialog retries them for up to about 24 h, so nothing is lost. Events already accepted wait in the queue.

## Rollback

1. `git checkout <previous-tag>` and run `up -d --build` again.
2. If the bad release included a migration, run `docker compose … run --rm api alembic downgrade -1` **before** switching code, but only if that migration's downgrade is safe for your data. Otherwise roll forward with a fix.
3. Events that failed because of the bad release are in **Ingestion → Failed**. Click **Retry all failed** (or run `python -m app.cli retry-failed`) after the fix.

## Monitoring

| What | How |
|---|---|
| Liveness / readiness | `GET /health/live`, `GET /health/ready` (checks the DB). Point an uptime monitor (UptimeRobot, Better Stack…) at `/health/ready`. |
| Queue backlog / failures | `GET /api/v1/ops/summary` (admin) or the **Ingestion** page: failed events, retrying, oldest pending. |
| Per-number capture | Numbers page / Overview **Capture health**: no events, no echoes, unmatched statuses, missing API key. |
| Logs | JSON on stdout (`docker compose logs -f api worker`). Ship them to your log platform. Logs contain ids only, never message text or secrets. |
| Alerts worth setting | `/health/ready` down; `events.dead > 0`; `oldest_pending_event_at` older than 5 min; a number with no events for over 24 h during business days. |

## Security checklist

- [ ] `.env` is readable only by the deploy user (`chmod 600 .env`). It is never committed.
- [ ] DB user has rights on this database only. TLS is required (`sslmode=require`).
- [ ] The bucket is private, and the S3 key is scoped to that bucket.
- [ ] VM firewall: only 80/443 (and SSH from your IPs) are open.
- [ ] Admin accounts for the people who onboard numbers; `viewer` for everyone else.
- [ ] `ENCRYPTION_KEY` and `JWT_SECRET` are backed up in your password manager.
- [ ] Rotate `WEBHOOK_SHARED_SECRET` by updating `.env`, restarting, then re-running `register-webhook` for every number.
