# 360dialog integration notes

What this project relies on from 360dialog. Each item is marked:

- **[verified]**: stated in the official 360dialog docs (links at the bottom).
- **[docs-assistant]**: answered by 360dialog's documentation assistant (GitBook `?ask=`). It is probably right, but confirm it with 360dialog support before relying on it in production.
- **[assumption]**: our own design decision or inference.

Researched October 2026.

## Our situation

All sales numbers currently run on the **WhatsApp Business App**, and sales reps reply from the app. So the integration uses **WhatsApp Coexistence**. The number stays in the WhatsApp Business App *and* is connected to the Cloud API through 360dialog. Reps keep working exactly as they do today.

## API basics

| Item | Value |
|---|---|
| Cloud API base URL | `https://waba-v2.360dialog.io` **[verified]** |
| Auth header | `D360-API-KEY: <key>` **[verified]** |
| Key scope | **One API key per phone number (channel)** **[docs-assistant]** |
| Key rotation | Generating a new key in the Hub **revokes the previous key** **[docs-assistant]** |
| Sandbox | Send `START` on WhatsApp to `+551146733492` to get a test key. Base URL `https://waba-sandbox.360dialog.io`. 200 requests. Can only message the test number. **[docs-assistant]** |

The app stores each number's API key **encrypted in the database** (`whatsapp_accounts.api_key_encrypted`), not in environment variables. This way, adding a number never requires a configuration or code change.

## Webhooks (live data)

- **Set the URL for each number:** `POST {base}/v1/configs/webhook` with body `{"url": "...", "headers": {"X-Webhook-Secret": "..."}}`. **[verified]** The `headers` field is optional; 360dialog sends those headers with every delivery. **[docs-assistant]**
- **URL rules:** HTTPS with a valid certificate, no underscores in the domain, no explicit port. **[docs-assistant]**
- **Delivery and retries:** anything other than HTTP 200 is retried with increasing delays for about 24 hours. **[verified]** Our endpoint therefore returns 200 as soon as the event has been stored.
- **Ordering:** "The order of these events may not reflect the actual timing" (statuses). **[verified]** Processing is designed to work regardless of order.
- **Multiple webhooks:** a number can have several destinations (`/multi_webhook`; the docs page says up to 3). **[verified]** The main destination must return 200 before the extra destinations receive the event.
- **Payload format:** Meta Cloud API format, i.e. `{"object":"whatsapp_business_account","entry":[{"changes":[{"field":"messages","value":{...}}]}]}`. **[verified]**
- **Signature:** 360dialog can sign webhooks with HMAC-SHA256 using the partner *platform secret*, in the `x-360dialog-signature` header. **[verified]** The docs assistant says this applies to callbacks forwarded through MBA and *should not be assumed* for direct clients. **[docs-assistant]**

**How we authenticate webhooks [assumption, our design]:**

1. Each number gets its own unguessable webhook path: `/webhooks/360dialog/{webhook_token}`.
2. A shared secret header (`X-Webhook-Secret`) is registered through the `headers` field and compared in constant time.
3. If `DIALOG360_PLATFORM_SECRET` is set, `x-360dialog-signature` is verified as well. It is mandatory only when `DIALOG360_REQUIRE_SIGNATURE=true`.

### Events we handle

| `field` | Meaning | Source |
|---|---|---|
| `messages` → `messages[]` | Inbound customer messages (text, image, video, audio, document, sticker, location, contacts, interactive, button, reaction, order, system, unsupported) | [verified] |
| `messages` → `statuses[]` | `sent`, `delivered`, `read`, `failed` (+ experimental `undeliverable`) for outbound messages | [verified] |
| `smb_message_echoes` | Messages **reps send from the WhatsApp Business App**, *including content* | [verified] (coexistence) |
| `smb_app_state_sync` | Contacts in the WhatsApp Business App address book (add/remove) | [verified] (coexistence) |
| `history` | Past chat history synced at coexistence onboarding | [verified] (coexistence) |

360dialog's coexistence docs show `history` / `smb_app_state_sync` in a wrapped format: `{"id":..., "event":"history", "data":{...}}`. The parser accepts this and the Meta `entry/changes` format equally.

### Limitations that affect the dashboard

- **Outbound messages sent through the API by *another* tool have no content in webhooks.** Only their statuses arrive. **[docs-assistant]** This doesn't affect us, because reps use the WhatsApp Business App and those messages arrive as `smb_message_echoes` with content.
- **No "assigned agent" field exists** in Cloud API webhooks. `conversations.assigned_agent` is kept, but it stays empty unless a source is added later.
- **WhatsApp has no conversation object for a chat thread.** We define a conversation as *one WhatsApp number × one contact*. "Active" means the last message was within `ACTIVE_CONVERSATION_HOURS` (default 24, the same as WhatsApp's customer-service window). **[assumption]**
- **No webhook is sent for deleted messages.** Reactions older than 30 days don't generate webhooks. **[verified]**

## Media

1. The webhook carries a media `id`, plus `mime_type`/`sha256`/`caption`/`filename`.
2. `GET {base}/{media-id}` (with the number's API key) returns a `url` on `https://lookaside.fbsbx.com/...`. **[verified]**
3. To download, **replace the host `https://lookaside.fbsbx.com` with `https://waba-v2.360dialog.io`** and `GET` it with the same API key. **[verified]**
4. Rate limit: no fixed RPS for retrieval, but too many errors are throttled (20 errors per 60 minutes). **[verified]**

The worker downloads media asynchronously right after ingestion and stores it in S3-compatible storage. Media links expire, so we never rely on them later. The database only keeps metadata and the storage key.

## Historical data

**The Cloud API has no endpoint to fetch past messages.** It only pushes new events. History is available **only through coexistence onboarding**:

- During onboarding, the business can choose to **"share chat history"**. Up to **6 months** of 1:1 chats are synced. **[verified via Meta-derived provider docs; 360dialog's page doesn't state the months]**
- The sync must happen **within 24 hours** of onboarding, with the WhatsApp Business App open. **[same]** **This is a one-time opportunity per number.**
- **For direct 360dialog clients (our case), synced history is downloaded from the 360dialog Hub**, not delivered to a webhook. **[verified]** The **file format is not documented**. **[docs-assistant]**
- The 360dialog Inbox API cannot import pre-activation history either. **[docs-assistant]**

**What we built:** `python -m app.cli import-history --account <id> FILE` imports history files in the documented `history` webhook shape. Each chunk goes through the same queue and processor as live webhooks, so imports are idempotent and can be re-run. Live `history` webhooks (if 360dialog sends them to the number's webhook) take the same path. **Once we have a real Hub export, check its format against `backend/tests/fixtures/dialog360/history.json`. If they differ, adjust only `providers/dialog360/parser.py`.**

## Coexistence requirements and caveats

- The number must be *actively used* in the WhatsApp Business App, on the latest app version, from a smartphone (QR-code signup). Very new accounts may not qualify. **[docs-assistant]**
- **Open the WhatsApp Business App at least once every 13 days**, or the API connection may drop. **[docs-assistant]** **Never uninstall the app.** Uninstalling disconnects the number. **[verified]**
- Not supported: Official Business Accounts (blue badge), migrating between WABAs, the calling API, and the WhatsApp for Windows / WearOS companion apps. **[verified]**
- Only 1:1 chats are synced (no groups). **[assumption based on Meta docs; verify]**

## Pilot verification checklist (what still needs real numbers)

The parts below cannot be proven with fixtures. Verify them during the pilot; the dashboard measures each one.

| To verify | How the dashboard shows it |
|---|---|
| Every number's app-sent replies arrive as `smb_message_echoes` | Numbers → number → *app-sent replies (7d)* > 0 and *Last app-sent reply* is recent |
| Echoes are attached to the right conversation and contact | Conversations → the customer's message and the rep's reply sit in one thread |
| No echoes are missing | *Unmatched statuses* = 0 (delivery receipts for messages whose content never arrived) |
| The real payload shape matches the fixtures | Ingestion → *Ignored* is empty (unknown shapes land there, nothing is dropped) |
| Whether 360dialog signs direct-client webhooks | Check incoming headers once; if `x-360dialog-signature` is present, set `DIALOG360_PLATFORM_SECRET` and `DIALOG360_REQUIRE_SIGNATURE=true` |
| The Hub history export format | `import-history` reports 0 unrecognised chunks |

## Sources

- Webhook reference: https://docs.360dialog.com/docs/messaging/webhook/webhook-reference
- Webhook configuration: https://docs.360dialog.com/partner/integrations-and-api-development/webhook-events-and-setup/webhook-configuration-and-management
- Signature validation: https://docs.360dialog.com/partner/onboarding/webhook-events-and-setup/signature-validation
- Media: https://docs.360dialog.com/docs/messaging/media/upload-retrieve-or-delete-media
- Coexistence: https://docs.360dialog.com/docs/hub/embedded-signup/whatsapp-coexistence
- Coexistence onboarding: https://docs.360dialog.com/docs/hub/embedded-signup/coexistence-onboarding
- Coexistence webhooks: https://docs.360dialog.com/partner/onboarding/whatsapp-coexistence/coexistence-webhooks
- Meta-derived window (6 months / 24 h): https://developers.telnyx.com/docs/messaging/whatsapp/coexistence
