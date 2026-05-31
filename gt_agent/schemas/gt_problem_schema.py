from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GTProblem:
    """Input problem metadata for GT Agent."""

    problem_path: Path
    mode: str = "basic"
    context_path: Path | None = None
    allowed_references: list[str] = field(default_factory=list)
    forbidden_assumptions: list[str] = field(default_factory=list)

    @classmethod
    def from_path(
        cls,
        problem_path: str | Path,
        mode: str = "basic",
        context_path: str | Path | None = None,
    ) -> "GTProblem":
        return cls(
            problem_path=Path(problem_path),
            mode=mode,
            context_path=Path(context_path) if context_path else None,
        )
