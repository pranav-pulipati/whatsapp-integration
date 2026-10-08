import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures" / "dialog360"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()
