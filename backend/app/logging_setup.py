"""Structured JSON logging with PII redaction.

Rules: never log message bodies, raw payloads, API keys or secrets. Log internal
ids instead. As a safety net, phone-number-like digit runs and anything resembling
a credential are masked before a record is emitted.
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

# Digit runs that stand alone (not part of hex ids / tokens).
_PHONE_RE = re.compile(r"(?<![\w.])(\+?\d{3})\d{4,}(\d{2})(?![\w])")
_SECRET_RE = re.compile(
    r"(?i)(d360-api-key|authorization|x-webhook-secret|api[_-]?key|password|secret|token)"
    r"([\"']?\s*[:=]\s*[\"']?)((?:bearer|basic)\s+)?([^\s\"',}]+)"
)


def redact(value: str) -> str:
    value = _SECRET_RE.sub(r"\1\2\3[REDACTED]", value)
    return _PHONE_RE.sub(r"\1****\2", value)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        ctx = getattr(record, "ctx", None)
        if isinstance(ctx, dict):
            entry.update({k: redact(v) if isinstance(v, str) else v for k, v in ctx.items()})
        if record.exc_info:
            entry["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Access logs include full paths (webhook tokens); we log requests ourselves.
    logging.getLogger("uvicorn.access").disabled = True
    for noisy in ("httpx", "httpcore", "botocore", "boto3", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
