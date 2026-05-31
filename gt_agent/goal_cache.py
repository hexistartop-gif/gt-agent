from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GoalCache:
    """Small cache for repeated Lean goal/feedback strings."""

    enabled: bool = True
    _cache: dict[str, str] = field(default_factory=dict)

    def get(self, key: str) -> str | None:
        if not self.enabled:
            return None
        return self._cache.get(key)

    def set(self, key: str, value: str) -> None:
        if self.enabled:
            self._cache[key] = value
