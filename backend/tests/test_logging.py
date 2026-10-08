import json
import logging

from app.logging_setup import JsonFormatter, redact


def test_redacts_phone_numbers_but_not_hex_ids():
    assert redact("customer 919876543210 wrote") == "customer 919****10 wrote"
    assert redact("from +919876543210") == "from +919****10"
    assert redact("request 552cbc6b4361234567818b9941d3e8f1a9e8") == (
        "request 552cbc6b4361234567818b9941d3e8f1a9e8"
    )


def test_redacts_secrets():
    out = redact('headers {"D360-API-KEY": "abc123secret", "Authorization": "Bearer xyz"}')
    assert "abc123secret" not in out
    assert "xyz" not in out
    assert redact("password=hunter2") == "password=[REDACTED]"


def test_json_formatter_redacts_context_values():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg 919876543210", None, None)
    record.ctx = {"error": "token=supersecret", "account_id": 3}
    entry = json.loads(JsonFormatter().format(record))
    assert entry["msg"] == "msg 919****10"
    assert entry["error"] == "token=[REDACTED]"
    assert entry["account_id"] == 3
