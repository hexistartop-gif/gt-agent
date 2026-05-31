from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import Any


@dataclass
class PopulationEntry:
    id: int
    code: str
    score: float = 0.0
    visits: int = 0
    wins: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class PopulationDB:
    """In-memory population database for evolution mode."""

    def __init__(self, elite_pool_size: int = 64) -> None:
        self.elite_pool_size = elite_pool_size
        self._ids = count(1)
        self._entries: list[PopulationEntry] = []

    def initialize(self, initial_sketch: str) -> PopulationEntry:
        self._entries.clear()
        return self.add(initial_sketch, score=0.0, metadata={"origin": "initial"})

    def add(
        self,
        code: str,
        *,
        score: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> PopulationEntry:
        entry = PopulationEntry(next(self._ids), code, score=score, metadata=metadata or {})
        self._entries.append(entry)
        self._entries.sort(key=lambda item: item.score, reverse=True)
        del self._entries[self.elite_pool_size :]
        return entry

    def entries(self) -> list[PopulationEntry]:
        return list(self._entries)

    def best(self) -> PopulationEntry:
        if not self._entries:
            raise ValueError("population is empty")
        return max(self._entries, key=lambda item: item.score)
