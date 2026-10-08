"""WhatsApp id / phone number helpers.

A WhatsApp id (wa_id) is usually the E.164 number without '+', but not always:
Brazilian mobile numbers may be reported with or without the extra leading '9',
and Mexican numbers with or without the '1' after the country code. Inbound
webhooks use the wa_id, while echoes carry the number as the business dialled it.
`equivalent_ids` returns the variants so both can be matched to one contact.
"""

import re

_NON_DIGITS = re.compile(r"\D+")


def digits(value: str | None) -> str:
    return _NON_DIGITS.sub("", value or "")


def equivalent_ids(wa_id: str) -> list[str]:
    n = digits(wa_id)
    variants = [n]
    # Brazil: 55 + 2-digit area code + optional '9' + 8-digit subscriber.
    if n.startswith("55"):
        if len(n) == 13 and n[4] == "9":
            variants.append(n[:4] + n[5:])
        elif len(n) == 12:
            variants.append(n[:4] + "9" + n[4:])
    # Mexico: 52 + optional '1' + 10-digit number.
    if n.startswith("52"):
        if len(n) == 13 and n[2] == "1":
            variants.append("52" + n[3:])
        elif len(n) == 12:
            variants.append("521" + n[2:])
    return variants


def format_display(wa_id: str | None) -> str | None:
    n = digits(wa_id)
    return f"+{n}" if n else None
