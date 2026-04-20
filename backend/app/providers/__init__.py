"""CLI provider adapters."""

from .base import ProviderResult, ProviderStatus
from .registry import ProviderRegistry, default_registry

__all__ = [
    "ProviderRegistry",
    "ProviderResult",
    "ProviderStatus",
    "default_registry",
]
