from __future__ import annotations

import re
from dataclasses import dataclass

from .gap_ledger import detect_bad_gaps, detect_unverified_claims
from .prover_subagent import has_lean_holes


@dataclass(frozen=True)
class RatedSketch:
    index: int
    score: float
    summary: str
    critical_flaws: list[str]
    gap_quality: str


class GTRaterSubagent:
    """Deterministic local rater for GT sketches.

    This is a minimal adapter, not an LLM judge. It enforces the policy items
    that can be checked locally and exposes a stable interface for richer raters.
    """

    def rate(self, sketch: str, *, index: int = 1, target_statement: str | None = None) -> RatedSketch:
        flaws: list[str] = []
        score = 100.0

        bad_gaps = detect_bad_gaps(sketch, target_statement)
        if bad_gaps:
            flaws.extend(f"Bad strategic gap: {item}" for item in bad_gaps)
            score -= 35 * len(bad_gaps)

        claims = detect_unverified_claims(sketch, allowed_references=[])
        if claims:
            flaws.extend(f"Unverified claim: {claim}" for claim in claims)
            score -= 15 * len(claims)

        if has_lean_holes(sketch):
            score -= 10
        if re.search(r"\bcompact\b|\borient|\bboundary|\btransvers", sketch, re.IGNORECASE):
            score += 5
        if "# GT Gap Ledger" in sketch or "GT_GAP_LEDGER" in sketch:
            score += 8

        gap_quality = "bad strategic gaps detected" if bad_gaps else "no bad strategic gap detected locally"
        summary = "Sketch exposes some auditable structure." if not flaws else "Sketch has policy violations."
        return RatedSketch(index, score, summary, flaws, gap_quality)

    def rank(self, sketches: list[str]) -> tuple[list[RatedSketch], str]:
        rated = [self.rate(sketch, index=index) for index, sketch in enumerate(sketches, start=1)]
        rated.sort(key=lambda item: item.score, reverse=True)
        decision = " > ".join(str(item.index) for item in rated)
        report_lines = ["# GTRater Report", ""]
        for item in rated:
            flaws = "\n".join(f"- {flaw}" for flaw in item.critical_flaws) or "- None detected locally."
            report_lines.extend(
                [
                    f"## Sketch {item.index}",
                    f"Score: {item.score:.1f}",
                    f"Summary: {item.summary}",
                    "Critical flaw analysis:",
                    flaws,
                    f"Gap quality analysis: {item.gap_quality}",
                    "",
                ]
            )
        report_lines.append(f"<decision>{decision}</decision>")
        return rated, "\n".join(report_lines) + "\n"
