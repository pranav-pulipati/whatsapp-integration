"""Provider lookup. Adding a provider = implementing `Provider` and registering it here."""

from functools import lru_cache

from app.providers.base import Provider
from app.providers.dialog360.provider import Dialog360Provider

_FACTORIES = {
    Dialog360Provider.name: Dialog360Provider,
}

PROVIDER_NAMES = tuple(_FACTORIES)


@lru_cache
def get_provider(name: str) -> Provider:
    try:
        return _FACTORIES[name]()
    except KeyError:
        raise ValueError(f"Unknown provider: {name}") from None
