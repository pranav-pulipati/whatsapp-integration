"""Management commands.  Run `python -m app.cli --help`.

gen-key                     Print a new ENCRYPTION_KEY
create-user                 Create a dashboard user
add-account                 Onboard a WhatsApp number (no code changes needed)
list-accounts               Show numbers, their webhook URLs and status
set-api-key                 Set/rotate a number's 360dialog API key
register-webhook            Point a number's 360dialog webhook at this service
import-history              Import a coexistence history export into a number
retry-failed                Requeue dead events and failed media downloads
process                     Drain the queue once (without running the worker)
seed-demo                   Generate demo data through the real ingestion pipeline
"""

import argparse
import getpass
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import User, WhatsAppAccount
from app.phone import digits
from app.providers.registry import get_provider
from app.security import (
    decrypt_secret,
    encrypt_secret,
    generate_fernet_key,
    generate_webhook_token,
    hash_password,
)


def _account(db, ref: str) -> WhatsAppAccount:
    stmt = select(WhatsAppAccount)
    if ref.isdigit() and len(ref) < 7:
        stmt = stmt.where(WhatsAppAccount.id == int(ref))
    else:
        stmt = stmt.where(WhatsAppAccount.display_phone_number == digits(ref))
    acc = db.execute(stmt).scalar_one_or_none()
    if acc is None:
        sys.exit(f"No account matches '{ref}' (use the id or the phone number)")
    return acc


def _webhook_url(acc: WhatsAppAccount) -> str:
    from app.api.accounts import webhook_url

    return webhook_url(acc)


def cmd_gen_key(_: argparse.Namespace) -> None:
    print(generate_fernet_key())


def cmd_create_user(a: argparse.Namespace) -> None:
    password = a.password or getpass.getpass("Password (min 12 chars): ")
    if len(password) < 12:
        sys.exit("Password must be at least 12 characters")
    with session_scope() as db:
        db.add(User(email=a.email.strip(), password_hash=hash_password(password), role=a.role))
    print(f"Created {a.role} user {a.email}")


def cmd_add_account(a: argparse.Namespace) -> None:
    api_key = a.api_key
    if a.prompt_api_key:
        api_key = getpass.getpass("360dialog API key: ").strip()
    with session_scope() as db:
        acc = WhatsAppAccount(
            provider=a.provider,
            name=a.name,
            display_phone_number=digits(a.number),
            phone_number_id=a.phone_number_id,
            waba_id=a.waba_id,
            provider_account_id=a.channel_id,
            status="pending",
            webhook_token=generate_webhook_token(),
            api_key_encrypted=encrypt_secret(api_key) if api_key else None,
            metadata_={},
        )
        db.add(acc)
        db.flush()
        print(f"Added account #{acc.id} {acc.name} (+{acc.display_phone_number})")
        print(f"Webhook URL: {_webhook_url(acc)}")
        if not api_key:
            print("No API key stored yet: run set-api-key before register-webhook.")


def cmd_list_accounts(_: argparse.Namespace) -> None:
    with session_scope() as db:
        for acc in db.execute(select(WhatsAppAccount).order_by(WhatsAppAccount.id)).scalars():
            print(
                f"#{acc.id:<3} {acc.status:<8} +{acc.display_phone_number:<16} {acc.name}\n"
                f"     phone_number_id={acc.phone_number_id or '-'}  api_key="
                f"{'set' if acc.api_key_encrypted else 'MISSING'}  last_event={acc.last_event_at or '-'}"
                f"  last_echo={acc.last_echo_at or '-'}\n     webhook={_webhook_url(acc)}"
            )


def cmd_set_api_key(a: argparse.Namespace) -> None:
    key = getpass.getpass("360dialog API key: ").strip()
    if len(key) < 8:
        sys.exit("That does not look like an API key")
    with session_scope() as db:
        _account(db, a.account).api_key_encrypted = encrypt_secret(key)
    print("API key stored (encrypted).")


def cmd_register_webhook(a: argparse.Namespace) -> None:
    s = get_settings()
    if not s.webhook_shared_secret:
        sys.exit("Set WEBHOOK_SHARED_SECRET first")
    with session_scope() as db:
        acc = _account(db, a.account)
        if not acc.api_key_encrypted:
            sys.exit("Set the API key first (set-api-key)")
        url = _webhook_url(acc)
        if not url.startswith("https://"):
            sys.exit(f"PUBLIC_BASE_URL must be https:// (got {url.split('/webhooks')[0]})")
        get_provider(acc.provider).register_webhook(
            decrypt_secret(acc.api_key_encrypted),
            url,
            {s.webhook_secret_header: s.webhook_shared_secret},
        )
    print(f"Webhook registered for account #{acc.id}")


def _history_payloads(path: Path) -> list[dict]:
    """Accept a JSON object, a JSON array of objects, or JSON Lines."""
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        return [json.loads(line) for line in raw.splitlines() if line.strip()]


def cmd_import_history(a: argparse.Namespace) -> None:
    from app.ingestion.webhook import store_event

    with session_scope() as db:
        acc = _account(db, a.account)
        provider = get_provider(acc.provider)
        queued = dup = unknown = 0
        for path in a.files:
            for payload in _history_payloads(Path(path)):
                if not isinstance(payload, dict):
                    unknown += 1
                    continue
                kind = provider.classify(payload)
                if kind is None:
                    unknown += 1
                    continue
                raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
                eid = store_event(
                    db,
                    provider=acc.provider,
                    account_id=acc.id,
                    payload=payload,
                    raw=raw,
                    kind=kind,
                    source="history_import",
                )
                queued += eid is not None
                dup += eid is None
    print(f"Queued {queued} chunk(s); {dup} already imported; {unknown} unrecognised.")
    if unknown:
        print("Unrecognised chunks were skipped: compare the export with docs/360dialog.md.")
    print("The worker will process them (or run `python -m app.cli process`).")


def cmd_retry_failed(_: argparse.Namespace) -> None:
    from sqlalchemy import update

    from app.models import MessageMedia, WebhookEvent

    now = datetime.now(UTC)
    with session_scope() as db:
        e = db.execute(
            update(WebhookEvent)
            .where(WebhookEvent.status == "dead")
            .values(status="pending", attempts=0, next_attempt_at=now)
        ).rowcount
        m = db.execute(
            update(MessageMedia)
            .where(MessageMedia.download_status == "failed")
            .values(download_status="pending", attempts=0, next_attempt_at=now)
        ).rowcount
    print(f"Requeued {e} event(s) and {m} media download(s).")


def cmd_process(_: argparse.Namespace) -> None:
    from app.worker import drain

    print(f"Processed {drain()} item(s).")


# --- demo data --------------------------------------------------------------------

_DEMO_NUMBERS = [
    ("Sales — Bengaluru", "919800000001"),
    ("Sales — Mumbai", "919800000002"),
    ("Sales — Delhi NCR", "919800000003"),
    ("Sales — Hyderabad", "919800000004"),
    ("Sales — Pune", "919800000005"),
]
_FIRST = [
    "Aarav",
    "Vivaan",
    "Aditya",
    "Diya",
    "Ananya",
    "Ishaan",
    "Kavya",
    "Rohan",
    "Meera",
    "Arjun",
    "Saanvi",
    "Kabir",
    "Nisha",
    "Vikram",
    "Tara",
    "Neel",
    "Riya",
    "Dev",
    "Pooja",
    "Sameer",
]
_LAST = [
    "Sharma",
    "Iyer",
    "Reddy",
    "Kapoor",
    "Menon",
    "Gupta",
    "Nair",
    "Rao",
    "Shah",
    "Verma",
    "Joshi",
    "Das",
]
_IN = [
    "Hi, is the 2BHK still available?",
    "What is the final price?",
    "Can I visit this Saturday?",
    "Do you have anything closer to the metro?",
    "Please share the brochure",
    "Is parking included?",
    "What are the maintenance charges?",
    "Thanks, I'll discuss with family",
    "Can you do a better price?",
    "Ok, booking the visit",
]
_OUT = [
    "Yes, it is available. Would you like to visit?",
    "Sharing the brochure now.",
    "Saturday 11am works. See you at the site office!",
    "We have two options near the metro, sending details.",
    "Parking is included for 1 car.",
    "Maintenance is ₹3.5/sq ft per month.",
    "Let me check with my manager and revert.",
    "Thank you! Let me know if you have questions.",
]


def cmd_seed_demo(a: argparse.Namespace) -> None:
    """Synthesise 360dialog-format webhooks and push them through the real pipeline."""
    from app.ingestion.webhook import store_event
    from app.worker import drain

    if get_settings().is_production:
        sys.exit("Refusing to seed demo data in production")
    rng = random.Random(a.seed)
    now = datetime.now(UTC)
    with session_scope() as db:
        accounts = []
        for i, (name, number) in enumerate(_DEMO_NUMBERS):
            acc = db.execute(
                select(WhatsAppAccount).where(WhatsAppAccount.display_phone_number == number)
            ).scalar_one_or_none()
            if acc is None:
                acc = WhatsAppAccount(
                    provider="360dialog",
                    name=name,
                    display_phone_number=number,
                    phone_number_id=f"10000000000000{i + 1}",
                    waba_id="200000000000001",
                    status="pending",
                    webhook_token=generate_webhook_token(),
                    metadata_={"demo": True},
                )
                db.add(acc)
                db.flush()
            accounts.append(acc)

        seq = 0
        for c in range(a.contacts):
            wa_id = f"9197{rng.randrange(10**7, 10**8)}"
            profile = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
            for acc in rng.sample(accounts, k=1 if rng.random() < 0.85 else 2):
                t = now - timedelta(days=rng.uniform(0, a.days), hours=rng.uniform(0, 12))
                for turn in range(rng.randint(1, 8)):
                    if t > now:
                        break
                    seq += 1
                    meta = {
                        "display_phone_number": acc.display_phone_number,
                        "phone_number_id": acc.phone_number_id,
                    }
                    inbound = turn % 2 == 0 or rng.random() < 0.2
                    mid = f"wamid.DEMO.{c}.{acc.id}.{turn}.{seq}"
                    ts = str(int(t.timestamp()))
                    if inbound:
                        value = {
                            "messaging_product": "whatsapp",
                            "metadata": meta,
                            "contacts": [{"profile": {"name": profile}, "wa_id": wa_id}],
                            "messages": [
                                {
                                    "from": wa_id,
                                    "id": mid,
                                    "timestamp": ts,
                                    "type": "text",
                                    "text": {"body": rng.choice(_IN)},
                                }
                            ],
                        }
                        field = "messages"
                    else:
                        value = {
                            "messaging_product": "whatsapp",
                            "metadata": meta,
                            "message_echoes": [
                                {
                                    "from": acc.display_phone_number,
                                    "to": wa_id,
                                    "id": mid,
                                    "timestamp": ts,
                                    "type": "text",
                                    "text": {"body": rng.choice(_OUT)},
                                }
                            ],
                        }
                        field = "smb_message_echoes"
                    payloads = [value]
                    if not inbound:
                        for st, dt in (("delivered", 5), ("read", rng.randint(30, 3600))):
                            if rng.random() < 0.9:
                                payloads.append(
                                    {
                                        "messaging_product": "whatsapp",
                                        "metadata": meta,
                                        "statuses": [
                                            {
                                                "id": mid,
                                                "status": st,
                                                "timestamp": str(int(t.timestamp()) + dt),
                                                "recipient_id": wa_id,
                                            }
                                        ],
                                    }
                                )
                    for i, v in enumerate(payloads):
                        payload = {
                            "object": "whatsapp_business_account",
                            "entry": [
                                {
                                    "id": acc.waba_id,
                                    "changes": [
                                        {"field": field if i == 0 else "messages", "value": v}
                                    ],
                                }
                            ],
                        }
                        raw = json.dumps(payload, sort_keys=True).encode()
                        store_event(
                            db,
                            provider="360dialog",
                            account_id=acc.id,
                            payload=payload,
                            raw=raw,
                            kind=get_provider("360dialog").classify(payload),
                        )
                    t += timedelta(minutes=rng.uniform(2, 600))
    print(f"Queued demo events; processing… {drain(max_items=1_000_000)} item(s) processed.")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("gen-key", help="Print a new ENCRYPTION_KEY").set_defaults(fn=cmd_gen_key)

    s = sub.add_parser("create-user", help="Create a dashboard user")
    s.add_argument("email")
    s.add_argument("--role", choices=["admin", "viewer"], default="viewer")
    s.add_argument("--password", help="Prompted if omitted (preferred)")
    s.set_defaults(fn=cmd_create_user)

    s = sub.add_parser("add-account", help="Onboard a WhatsApp number")
    s.add_argument("--name", required=True, help='e.g. "Sales — Bengaluru"')
    s.add_argument("--number", required=True, help="International format, e.g. +919876543210")
    s.add_argument("--provider", default="360dialog")
    s.add_argument(
        "--phone-number-id", help="Meta phone number id (learned automatically if omitted)"
    )
    s.add_argument("--waba-id")
    s.add_argument("--channel-id", help="360dialog channel id")
    s.add_argument("--api-key", help=argparse.SUPPRESS)
    s.add_argument("--prompt-api-key", action="store_true", help="Prompt for the 360dialog API key")
    s.set_defaults(fn=cmd_add_account)

    sub.add_parser("list-accounts", help="List numbers").set_defaults(fn=cmd_list_accounts)

    for name, fn, help_ in (
        ("set-api-key", cmd_set_api_key, "Set/rotate a number's API key (prompted)"),
        ("register-webhook", cmd_register_webhook, "Register this service as the number's webhook"),
    ):
        s = sub.add_parser(name, help=help_)
        s.add_argument("account", help="Account id or phone number")
        s.set_defaults(fn=fn)

    s = sub.add_parser("import-history", help="Import coexistence history export file(s)")
    s.add_argument("--account", required=True, help="Account id or phone number")
    s.add_argument("files", nargs="+")
    s.set_defaults(fn=cmd_import_history)

    sub.add_parser("retry-failed", help="Requeue dead events/media").set_defaults(
        fn=cmd_retry_failed
    )
    sub.add_parser("process", help="Drain the queue once").set_defaults(fn=cmd_process)

    s = sub.add_parser("seed-demo", help="Generate demo data (development only)")
    s.add_argument("--contacts", type=int, default=120)
    s.add_argument("--days", type=int, default=45)
    s.add_argument("--seed", type=int, default=7)
    s.set_defaults(fn=cmd_seed_demo)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
