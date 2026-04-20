"""Provider registry.

The registry is the product boundary for CLI integrations. Keep SessionManager
provider-agnostic; add new providers here or load them from config later.
"""

from __future__ import annotations

from .base import ProviderAdapter, ProviderStatus
from .claude import ClaudeProvider
from .codex import CodexProvider


class ProviderRegistry:
    """In-process registry for CLI provider adapters."""

    def __init__(self, providers: list[ProviderAdapter] | None = None) -> None:
        self._providers: dict[str, ProviderAdapter] = {}
        for provider in providers or [ClaudeProvider(), CodexProvider()]:
            self.register(provider)

    def register(self, provider: ProviderAdapter) -> None:
        if not provider.id:
            raise ValueError("Provider id is required")
        if provider.id in self._providers:
            raise ValueError(f"Provider already registered: {provider.id}")
        self._providers[provider.id] = provider

    def get(self, provider_id: str) -> ProviderAdapter:
        provider = self._providers.get(provider_id)
        if not provider:
            known = ", ".join(sorted(self._providers)) or "(none)"
            raise ValueError(f"Unknown provider: {provider_id}. Available providers: {known}")
        return provider

    def list(self) -> list[ProviderAdapter]:
        return [self._providers[k] for k in sorted(self._providers)]

    def statuses(self) -> list[ProviderStatus]:
        return [provider.status() for provider in self.list()]


default_registry = ProviderRegistry()
