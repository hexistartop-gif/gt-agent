from __future__ import annotations

from .schemas import AttemptSummary


def append_attempt_summary_to_sketch(code: str, summary: AttemptSummary) -> str:
    block = "\n".join(
        [
            "",
            "/-",
            "GT_ATTEMPT_SUMMARY:",
            f"Status: {summary.status}",
            "Main idea:",
            summary.main_idea or "Not recorded.",
            "Closed lemmas:",
            *(f"- {item}" for item in summary.closed_lemmas),
            "Remaining gaps:",
            *(f"- {item}" for item in summary.remaining_gaps),
            "Why the current obstruction is nontrivial:",
            summary.rater_criticism or "Not recorded.",
            "Next suggested step:",
            summary.lean_feedback or "Inspect Lean feedback and split the next local lemma.",
            "-/",
        ]
    )
    return code.rstrip() + block + "\n"


def format_prior_attempts(prior_attempts: list[AttemptSummary] | None) -> str:
    if not prior_attempts:
        return "# Prior Attempts\n\nNone.\n"
    rendered = ["# Prior Attempts"]
    for index, attempt in enumerate(prior_attempts, start=1):
        rendered.append("")
        rendered.append(attempt.to_markdown(index))
    return "\n".join(rendered) + "\n"
