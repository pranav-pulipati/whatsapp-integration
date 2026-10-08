# Local development

## 1. Install

| Tool | Version | Notes |
|---|---|---|
| Docker or Podman | any recent | For PostgreSQL and SeaweedFS (S3) |
| Python | 3.12 or 3.13 | Managed by [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh \| sh`) |
| Node.js | 22 | For the dashboard |

```bash
cd backend && uv sync          # creates backend/.venv
cd ../frontend && npm install
```

## 2. Environment variables

```bash
cp .env.example .env
```

Fill in these values (each command prints a fresh one):

| Variable | Generate with |
|---|---|
| `JWT_SECRET` | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ENCRYPTION_KEY` | `cd backend && uv run python -m app.cli gen-key` |
| `WEBHOOK_SHARED_SECRET` | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |

The backend reads `.env` from the repo root or from `backend/`. Never commit `.env`; `.gitignore` already excludes it.

## 3. Start PostgreSQL and S3 storage

```bash
docker compose up -d     # postgres:5432, SeaweedFS S3 API :9000 (any access key works locally)
```

The worker creates the `wa-media` bucket on startup if it does not exist.

## 4. Migrations and first user

```bash
cd backend
uv run alembic upgrade head
uv run python -m app.cli create-user you@company.com --role admin   # prompts for a password (min 12 chars)
```

## 5. Start the backend

Two processes, each in its own terminal:

```bash
uv run uvicorn app.main:app --reload    # API  → http://localhost:8000, OpenAPI → /api/docs
uv run python -m app.worker             # worker
```

## 6. Start the dashboard

```bash
cd frontend && npm run dev              # http://localhost:5173 (proxies /api to :8000)
```

To fill the dashboard with demo data (5 numbers and about 120 contacts, created as 360dialog-format webhooks pushed through the real pipeline):

```bash
cd backend && uv run python -m app.cli seed-demo
```

## 7. Test webhook ingestion locally

Create a number and grab its webhook URL:

```bash
uv run python -m app.cli add-account --name "Test number" --number +15550001111
uv run python -m app.cli list-accounts     # shows webhook=http://localhost:8000/webhooks/360dialog/<token>
```

Post a fixture as if 360dialog sent it:

```bash
TOKEN=<token from list-accounts>
SECRET=$(grep ^WEBHOOK_SHARED_SECRET ../.env | cut -d= -f2)
curl -X POST http://localhost:8000/webhooks/360dialog/$TOKEN \
  -H "X-Webhook-Secret: $SECRET" -H "Content-Type: application/json" \
  --data @tests/fixtures/dialog360/inbound_text.json
# {"status":"accepted"}; send it again → {"status":"duplicate"}
curl … --data @tests/fixtures/dialog360/echo_text.json        # rep reply from the app
curl … --data @tests/fixtures/dialog360/status_read.json      # read receipt
```

With the worker running, the conversation appears under **Conversations** within about a second. Without the worker, run `uv run python -m app.cli process`.

The fixtures in `backend/tests/fixtures/dialog360/` cover:
- text, image and mixed message types;
- echoes;
- delivered, read, failed and orphan statuses;
- coexistence history;
- address-book sync;
- Brazilian number variants.

### Receiving real webhooks on your laptop

360dialog needs a public HTTPS URL. Use a tunnel such as `cloudflared tunnel --url http://localhost:8000` or `ngrok http 8000`. Then:
1. Set `PUBLIC_BASE_URL` to the tunnel URL.
2. Restart the API.
3. Run `uv run python -m app.cli register-webhook <account>`.

You can test the whole flow risk-free with the **360dialog sandbox**:
1. Send `START` on WhatsApp to `+551146733492` to get a sandbox key.
2. Set `DIALOG360_API_BASE_URL=https://waba-sandbox.360dialog.io`.

## 8. Tests

```bash
# backend: needs a reachable Postgres; the suite drops and recreates the schema of this DB
docker run -d --name wa-test-pg -e POSTGRES_USER=wa -e POSTGRES_PASSWORD=wa -e POSTGRES_DB=wa_test -p 55432:5432 postgres:16
cd backend && TEST_DATABASE_URL=postgresql+psycopg://wa:wa@localhost:55432/wa_test uv run pytest
uv run ruff check . && uv run ruff format --check .

# frontend
cd frontend && npm run typecheck && npm test && npm run build
```

`TEST_DATABASE_URL` defaults to `postgresql+psycopg://wa:wa@localhost:55432/wa_test`. **Never point it at a database you care about.**

## Running everything in containers

```bash
docker compose --profile app up --build   # postgres, s3, api (+migrations), worker
```

The API serves the built dashboard at http://localhost:8000.
