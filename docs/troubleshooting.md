# Troubleshooting

Start with two things:
- the **Ingestion** page (admin);
- the number's drawer on the **Numbers** page. Capture health lists the specific problem.

## No data from a number ("No data yet")

| Check | How |
|---|---|
| Webhook registered? | Numbers → number → **Register webhook**, or `python -m app.cli register-webhook <id>`. A `502 provider_error` means 360dialog rejected the call. Check the API key. |
| Is the URL reachable from the internet? | `curl -i -X POST https://$DOMAIN/webhooks/360dialog/<token>` should return **401** (missing secret). A timeout or TLS error means DNS, firewall or certificate problems. |
| Secret header mismatch | API logs show requests to `/webhooks/360dialog/***` with status 401. Re-register the webhook after changing `WEBHOOK_SHARED_SECRET`. |
| Wrong token / number | A 404 on `/webhooks/360dialog/***` means the token doesn't exist (the account was deleted, or a URL was copied from another environment). |
| Worker not running | **Ingestion** shows events stuck in *Queued*. Start or restart the `worker` service. |
| Number disconnected from coexistence | The WhatsApp Business App must be opened at least every 13 days and must never be uninstalled. Reconnect it in the 360dialog Hub. |

## Customer messages arrive but rep replies don't ("Needs attention: no app-sent replies")

- Confirm the number was onboarded with **coexistence** (not just as an API number). Only coexistence produces `smb_message_echoes`.
- Make sure reps reply **from the WhatsApp Business App on the phone**. Companion apps (WhatsApp for Windows, WearOS) are not supported by coexistence.
- **Unmatched statuses > 0** means WhatsApp sent delivery receipts for messages whose content never reached us. Contact 360dialog support with the message ids (Ingestion → Processed, or `message_statuses` where `message_id IS NULL`) and ask them to check that echo events are enabled for the channel.

## Events failing ("Failed events")

Open **Ingestion → Failed** and read the error:

| Error | Meaning / fix |
|---|---|
| `phone_number_id mismatch` | The webhook URL of account A is registered on a different number. Re-register the correct URL on each number, then click **Retry** if the events belong to this number after all (fix the account's `phone_number_id` first). |
| `display number mismatch` | Same cause, caught before `phone_number_id` was known. Check the number entered at onboarding. |
| `OperationalError …` | The database was unavailable. These retry automatically; once the DB is back, use **Retry all failed** for any that went dead. |
| `unrecognised payload shape` (Ignored) | 360dialog sent a format the parser doesn't know. Save the payload from `webhook_events.payload` and extend `app/providers/dialog360/parser.py` with a fixture and test. Then retry. |

## Media shows "Couldn't be downloaded"

- **No API key stored:** set it on the Numbers page.
- **The key was rotated in the Hub:** generating a new key revokes the old one. Update it here.
- **Media is too old:** WhatsApp media ids expire. Media is downloaded right after ingestion, so this only affects events processed long after they arrived.
- To retry after fixing, use **Ingestion → Retry all failed** (it covers media too).

## Dashboard issues

| Symptom | Fix |
|---|---|
| Login returns 429 | 10 attempts per minute per IP and email. Wait a minute. Behind a proxy, make sure `FORWARDED_ALLOW_IPS` lets the real client IP through. |
| Logged out unexpectedly | The session lasts `JWT_EXPIRES_MINUTES` (default 8 h), and closing the tab also ends it. Rotating `JWT_SECRET` signs everyone out. |
| Charts show different days than expected | Days are bucketed in the browser's timezone. |
| "Stored secret cannot be decrypted" | `ENCRYPTION_KEY` changed. Restore the old key, or re-enter every number's API key. |

## History import

- History can only be shared **once, within about 24 h of coexistence onboarding**. If you missed it, history for that number is unavailable through 360dialog.
- `import-history` reports *unrecognised* chunks when the Hub export format differs from the documented webhook shape. Keep the file (it contains customer data, so store it securely), compare it with `backend/tests/fixtures/dialog360/history.json`, and adapt the parser.

## Useful commands

```bash
python -m app.cli list-accounts          # ids, status, api key present, last event/echo, webhook URL
python -m app.cli process                # drain the queue once (no worker needed)
python -m app.cli retry-failed           # requeue dead events + failed media
docker compose logs -f api worker | grep -v '"/health'
```
