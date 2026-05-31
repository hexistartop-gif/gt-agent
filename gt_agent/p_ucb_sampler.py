from __future__ import annotations

import math

from .population_db import PopulationEntry


class PUcbSampler:
    def __init__(self, exploration_c: float = 0.2) -> None:
        self.exploration_c = exploration_c

    def sample(self, entries: list[PopulationEntry]) -> PopulationEntry:
        if not entries:
            raise ValueError("cannot sample an empty population")
        total_visits = sum(entry.visits for entry in entries) + 1

        def value(entry: PopulationEntry) -> float:
            exploitation = entry.score
            exploration = self.exploration_c * math.sqrt(math.log(total_visits + 1) / (entry.visits + 1))
            return exploitation + exploration

        selected = max(entries, key=value)
        selected.visits += 1
        return selected
