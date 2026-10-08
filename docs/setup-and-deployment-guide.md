# SETUP & DEPLOYMENT GUIDE

This guide takes you from nothing to all 5 sales numbers flowing into the dashboard, and shows how to add more numbers later. Every secret and id below is a placeholder like `<THIS>`; never paste real values into files that get committed.

---

## 1. Accounts and services you need

| # | Service | Why | Cost note |
|---|---|---|---|
| 1 | **360dialog account** (direct client) at https://hub.360dialog.com | WhatsApp Business Platform provider | Per-number monthly plan. Pick the one that includes coexistence. |
| 2 | **Meta Business Manager**, ideally verified, at https://business.facebook.com | Required to onboard numbers | Free |
| 3 | **The 5 phones** that run the WhatsApp Business App, with the latest app version | Coexistence onboarding uses a QR code scanned from each phone | – |
| 4 | **A domain/subdomain** you control, e.g. `wa.yourcompany.com` | Public HTTPS webhook URL and dashboard | – |
| 5 | **A server**: a small Linux VM (2 vCPU / 4 GB) with Docker | Runs the API, worker and HTTPS proxy | ~$10–25/mo |
| 6 | **Managed PostgreSQL 14+** | The database | ~$15+/mo |
| 7 | **S3-compatible bucket** (AWS S3 or Cloudflare R2) | Stores photos, voice notes and documents | Usage-based |

> **Important history note:** past chats can **only** be imported during each number's coexistence onboarding, by choosing **"share chat history"**. That gives up to about 6 months of 1:1 chats, and it must be done within about 24 h. There is no other way to fetch old conversations through 360dialog. Decide before onboarding whether you want history. See [360dialog.md](360dialog.md#historical-data).

---

## 2. How to obtain each credential

| Credential | Where to get it | Format |
|---|---|---|
| **360dialog API key, one per number** | Hub → **Channels** → select the number → **API Settings / API key** → **Generate**. It is shown **once**; copy it straight into the dashboard. Generating a new key **revokes the old one**. | `<D360_API_KEY_NUMBER_1>` … |
| **Phone number ID** (optional) | Hub channel details, or Meta WhatsApp Manager → Phone numbers. If you leave it empty, the app learns it from the first webhook. | digits |
| **WABA ID** (optional) | Hub channel details / WhatsApp Manager | digits |
| `JWT_SECRET` | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` | random string |
| `WEBHOOK_SHARED_SECRET` | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` | random string |
| `ENCRYPTION_KEY` | `cd backend && uv run python -m app.cli gen-key` (or with Docker: `docker run --rm <image> python -m app.cli gen-key`) | Fernet key |
| `DATABASE_URL` | Your managed Postgres console | `postgresql+psycopg://<USER>:<PASSWORD>@<HOST>:5432/<DB>?sslmode=require` |
| `S3_*` | Bucket console → create an access key restricted to the bucket | key id + secret |
| `DIALOG360_PLATFORM_SECRET` (optional) | Only if 360dialog confirms they sign your webhooks; ask support | string |

---

## 3. Where each credential goes

| Credential | Goes into | Never |
|---|---|---|
| `JWT_SECRET`, `ENCRYPTION_KEY`, `WEBHOOK_SHARED_SECRET`, `DATABASE_URL`, `S3_*`, `DOMAIN`, `PUBLIC_BASE_URL` | `.env` on the server (or your platform's secret manager) | git, chat, email |
| **360dialog API keys** (one per number) | The **dashboard**: Numbers → *Connect number* or *Set API key*. They are stored encrypted in the database. | `.env`, code |
| Phone number ID / WABA ID | The dashboard onboarding form (optional) | – |

`.env.example` in the repo lists every variable with comments.

---

## 4. Configure 360dialog

1. Sign up at https://hub.360dialog.com as a **direct client** and connect your Meta Business Manager.
2. Choose a plan for **5 numbers** that includes **WhatsApp Coexistence**. (Your reps keep the WhatsApp Business App; the API runs alongside it.)
3. Nothing else needs configuring in the Hub up front. This app sets each number's webhook through the API (step 8).

Before onboarding, check that each phone:
- has the **latest WhatsApp Business App**;
- has been actively used for a while (very new accounts may not qualify);
- is not an Official Business Account (blue badge), which coexistence doesn't support.

---

## 5. Connect the first WhatsApp number

**a. In 360dialog (on the phone + Hub):**

1. Hub → add a number → choose **"Connect WhatsApp Business App" (coexistence)**.
2. Follow the Meta signup. On the phone, the WhatsApp Business App shows a QR code / prompt; scan and confirm.
3. When asked, choose **"Share chat history"** if you want past chats (up to about 6 months). **Keep the app open** until sync finishes.
4. Generate the number's **API key** (step 2) and keep it on your clipboard.

**b. In the dashboard (signed in as admin):**

1. **Numbers → Connect number.**
2. Fill in:
   - **Name**, e.g. `Sales — Bengaluru`;
   - **WhatsApp number** in international format, `<+CC NUMBER>`;
   - **360dialog API key** (paste it);
   - optionally the phone number ID and WABA ID.
3. Open the new number → **Register webhook with 360dialog**. You should see "Webhook registered".

CLI alternative (on the server):

```bash
docker compose -f deploy/docker-compose.prod.yml exec api python -m app.cli add-account \
  --name "Sales — Bengaluru" --number "<+CC NUMBER>" --prompt-api-key
docker compose -f deploy/docker-compose.prod.yml exec api python -m app.cli register-webhook "<+CC NUMBER>"
```

**c. Import history (only if you shared it in step a.3):**

1. In the Hub, download the synced history for that number. This option exists for direct clients.
2. Copy the file to the server. **It contains customer data**, so delete it afterwards.
3. Run:

```bash
docker compose -f deploy/docker-compose.prod.yml cp ./<history-file>.json api:/tmp/history.json
docker compose -f deploy/docker-compose.prod.yml exec api python -m app.cli import-history --account "<+CC NUMBER>" /tmp/history.json
```

The import is idempotent, so running it twice creates no duplicates.

> The Hub export format is not publicly documented. If the command reports *unrecognised* chunks, keep the file safe and see [troubleshooting](troubleshooting.md#history-import). Only the parser needs adapting.

---

## 6. Connect numbers 2–5

Repeat **step 5** for each phone. Each number gets:
- its **own API key** (store it with that number);
- its **own webhook URL**, which the dashboard generates; you never type URLs by hand.

After all five, **Numbers** shows five cards. Each turns **Capturing** once both a customer message and an app-sent reply have arrived.

---

## 7. Add number #6 or any future number (no code changes)

Exactly the same as step 5: onboard it in the Hub, click **Connect number**, then **Register webhook**. That's all.
- No environment variables, deploys or code changes are needed.
- The dashboard, filters, charts and capture health include the new number automatically.

To stop collecting from a number, open it and choose **Disable number**. Its history stays in the dashboard; new events are kept but not processed.

---

## 8. Configure the webhook

The **Register webhook** button (or `register-webhook` CLI) does this for you. It calls:

```
POST https://waba-v2.360dialog.io/v1/configs/webhook
D360-API-KEY: <that number's API key>
{"url": "https://<DOMAIN>/webhooks/360dialog/<per-number-token>",
 "headers": {"X-Webhook-Secret": "<WEBHOOK_SHARED_SECRET>"}}
```

Requirements:
- `PUBLIC_BASE_URL=https://<DOMAIN>` must be set;
- the domain must have a valid certificate (Caddy provides it automatically);
- no underscores in the hostname and no port in the URL.

If you ever change `WEBHOOK_SHARED_SECRET` or `DOMAIN`, register the webhook again for **every** number.

If another tool already uses a number's webhook, 360dialog supports up to three destinations per number (`/multi_webhook`). Ask before replacing an existing integration.

---

## 9. Run locally

Short version (full detail in [setup.md](setup.md)):

```bash
cp .env.example .env            # fill JWT_SECRET, ENCRYPTION_KEY, WEBHOOK_SHARED_SECRET
docker compose up -d            # Postgres + SeaweedFS (S3)
cd backend && uv sync && uv run alembic upgrade head
uv run python -m app.cli create-user <you@company.com> --role admin
uv run python -m app.cli seed-demo           # optional demo data
uv run uvicorn app.main:app --reload         # terminal 1
uv run python -m app.worker                  # terminal 2
cd ../frontend && npm install && npm run dev # terminal 3 → http://localhost:5173
```

---

## 10. Test with real WhatsApp messages

**Option A: 360dialog sandbox (no real numbers involved)**

1. On WhatsApp, send `START` to `+551146733492` and save the sandbox key you receive.
2. Expose your laptop: `cloudflared tunnel --url http://localhost:8000` (or `ngrok http 8000`).
3. In `.env`, set:
   - `PUBLIC_BASE_URL=<tunnel https URL>`
   - `DIALOG360_API_BASE_URL=https://waba-sandbox.360dialog.io`

   Then restart the API.
4. Connect a number using the sandbox key, then **Register webhook**.
5. Message the sandbox number from your phone. The message appears under **Conversations** within seconds.

**Option B: the pilot (real numbers, production)**

For **each** of the 5 numbers:
1. From a personal phone, send a test message to the sales number.
2. From the **sales phone's WhatsApp Business App**, reply to it.
3. Check the dashboard (step 12).

---

## 11. Deploy production

Full detail is in [deployment.md](deployment.md).

```bash
# DNS: A record <DOMAIN> → server IP. Server: Docker installed, ports 80/443 open.
git clone <repo-url> wa-dashboard && cd wa-dashboard
cp .env.example .env && chmod 600 .env && nano .env
#   APP_ENV=production
#   DOMAIN=<DOMAIN>
#   PUBLIC_BASE_URL=https://<DOMAIN>
#   DATABASE_URL=postgresql+psycopg://<USER>:<PASSWORD>@<HOST>:5432/<DB>?sslmode=require
#   JWT_SECRET=<...>  ENCRYPTION_KEY=<...>  WEBHOOK_SHARED_SECRET=<...>
#   S3_ENDPOINT_URL=<empty for AWS | R2 endpoint>  S3_BUCKET=<...>  S3_ACCESS_KEY_ID=<...>  S3_SECRET_ACCESS_KEY=<...>
docker compose -f deploy/docker-compose.prod.yml --env-file .env up -d --build
docker compose -f deploy/docker-compose.prod.yml exec api python -m app.cli create-user <you@company.com> --role admin
curl https://<DOMAIN>/health/ready     # → {"status":"ok"}
```

Open `https://<DOMAIN>`, sign in, then do steps 5–6.

---

## 12. Verify data is reaching the dashboard

Go through this list for each number during the pilot:

- [ ] **Numbers:** the card shows **Active** and **Capturing**, and "Last event" is recent.
- [ ] Open the number. In the *Capture · last 7 days* section, **customer messages > 0** and **app-sent replies > 0**.
- [ ] **Unmatched statuses = 0.** If it is above 0, some replies sent from the app are not arriving as echoes; see troubleshooting.
- [ ] **Conversations:** filter by the number. The test chat shows the customer message on the left and the rep's reply on the right, in the **same** conversation, with ✓✓ ticks once read.
- [ ] Send a **photo** from the customer phone. It appears in the timeline; if it says "Downloading…" for more than a minute, check the API key.
- [ ] **Overview:** today's point on *Messages per day* increases; *Activity by number* lists the number.
- [ ] **Ingestion** (admin): *Failed events = 0*, and the queue is empty or draining.

API equivalent:

```bash
curl -s https://<DOMAIN>/api/v1/accounts -H "Authorization: Bearer <TOKEN>" | jq '.[] | {name, status, health}'
```

---

## 13. Troubleshoot common failures

| Symptom | Most likely cause | Fix |
|---|---|---|
| Number stays "No data yet" | Webhook not registered, wrong domain/TLS, or worker down | Register the webhook again. `curl -i -X POST https://<DOMAIN>/webhooks/360dialog/<token>` should return 401. Check `docker compose logs worker`. |
| "Register webhook" → 502 | API key wrong or revoked | Generate a fresh key in the Hub → **Set API key** → register again |
| Customer messages arrive, rep replies don't | Not onboarded as coexistence, or reps use WhatsApp for Windows/WearOS | Reconnect via coexistence; reply from the phone app |
| Unmatched statuses > 0 | Some echoes not delivered by the provider | Send the message ids to 360dialog support |
| Failed event: `phone_number_id mismatch` | Webhook URLs swapped between numbers | Register each number's own URL again |
| Media "Couldn't be downloaded" | No/rotated API key, or very old media | Set the key, then **Ingestion → Retry all failed** |
| Number disconnected after a few weeks | WhatsApp Business App not opened for 13+ days, or uninstalled | Open the app regularly; reconnect in the Hub |
| "Stored secret cannot be decrypted" | `ENCRYPTION_KEY` changed | Restore the original key from your password manager |

More detail: [troubleshooting.md](troubleshooting.md).
