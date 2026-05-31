from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

GTStatus = Literal["PROVED", "PARTIAL", "MISFORMALIZED", "COUNTEREXAMPLE", "BLOCKED"]


@dataclass
class AttemptSummary:
    """Human-readable summary of a proof-search attempt."""

    status: GTStatus
    main_idea: str = ""
    closed_lemmas: list[str] = field(default_factory=list)
    remaining_gaps: list[str] = field(default_factory=list)
    lean_feedback: str = ""
    rater_criticism: str = ""
    elo: int | None = None

    def to_markdown(self, index: int | None = None) -> str:
        heading = f"Attempt {index}" if index is not None else "Attempt"
        closed = "\n".join(f"- {item}" for item in self.closed_lemmas) or "- None"
        gaps = "\n".join(f"- {item}" for item in self.remaining_gaps) or "- None"
        return "\n".join(
            [
                heading,
                f"Status: {self.status}",
                f"Elo: {self.elo if self.elo is not None else 'unrated'}",
                "Main idea:",
                self.main_idea or "Not recorded.",
                "Closed lemmas:",
                closed,
                "Remaining gaps:",
                gaps,
                "Rater criticism:",
                self.rater_criticism or "Not rated.",
                "Lean feedback:",
                self.lean_feedback or "No Lean feedback.",
            ]
        )


@dataclass
class GTResult:
    """Output protocol for a GT Agent run."""

    status: GTStatus
    formal_artifact: Path
    natural_language_summary: Path
    gap_ledger: Path
    assumption_audit: Path
    rater_report: Path

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {key: str(value) for key, value in data.items()}
