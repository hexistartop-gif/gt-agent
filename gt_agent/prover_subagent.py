from __future__ import annotations

import re
from dataclasses import dataclass

from .compiler import LeanCompiler, LeanFeedback
from .schemas import AttemptSummary
from .validator import EVOLVE_END_RE, EVOLVE_START_RE, GTValidator, ValidationResult


@dataclass
class ProverStep:
    code: str
    changed: bool
    validation: ValidationResult
    lean_feedback: LeanFeedback
    summary: AttemptSummary


class GTProverSubagent:
    """Small local prover adapter.

    Real projects can replace ``propose_next_code`` with an LLM/search_replace
    implementation. The built-in adapter only performs conservative repairs
    inside EVOLVE markers, enough for smoke tests and local wiring.
    """

    def __init__(self, validator: GTValidator | None = None, compiler: LeanCompiler | None = None) -> None:
        self.compiler = compiler or LeanCompiler()
        self.validator = validator or GTValidator(self.compiler)

    def mutate(self, original_code: str, parent_code: str) -> ProverStep:
        candidate, changed = self.propose_next_code(parent_code)
        validation = self.validator.validate_candidate(original_code, candidate, final=False)
        if not validation.accepted:
            summary = AttemptSummary(
                status="BLOCKED",
                main_idea="Local prover proposed an edit rejected by GTValidator.",
                remaining_gaps=[validation.reason],
                lean_feedback=validation.repair_hint,
            )
            return ProverStep(parent_code, False, validation, LeanFeedback(False, validation.reason), summary)

        lean_feedback = self.compiler.check_code(candidate)
        holes = has_lean_holes(candidate)
        status = "PARTIAL"
        main_idea = "Applied a local proof repair inside EVOLVE markers." if changed else "No safe local edit was available."
        remaining_gaps: list[str] = []
        if holes:
            remaining_gaps.append("Lean sketch still contains sorry/admit placeholders.")
        if not lean_feedback.checked:
            remaining_gaps.append("Lean executable is unavailable; compilation was not checked.")
        elif not lean_feedback.compiles:
            remaining_gaps.append("Lean compilation failed.")
        if not holes and lean_feedback.checked and lean_feedback.compiles:
            status = "PROVED"
        elif not changed and not holes and not lean_feedback.checked:
            status = "BLOCKED"

        summary = AttemptSummary(
            status=status,  # type: ignore[arg-type]
            main_idea=main_idea,
            closed_lemmas=["No proof holes remain."] if status == "PROVED" else [],
            remaining_gaps=remaining_gaps,
            lean_feedback=lean_feedback.output,
        )
        return ProverStep(candidate, changed, validation, lean_feedback, summary)

    def propose_next_code(self, code: str) -> tuple[str, bool]:
        replacement = _replacement_for_trivial_theorem(code)
        if replacement is None:
            return code, False
        return replace_first_hole_inside_evolve(code, replacement)


def has_lean_holes(code: str) -> bool:
    return re.search(r"\bsorry\b|\badmit\b", code) is not None


def replace_first_hole_inside_evolve(code: str, replacement: str) -> tuple[str, bool]:
    lines = code.splitlines(keepends=True)
    inside = False
    for index, line in enumerate(lines):
        if EVOLVE_START_RE.search(line):
            inside = True
        if inside and re.search(r"\b(sorry|admit)\b", line):
            indent = re.match(r"\s*", line).group(0)
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = f"{indent}{replacement}{newline}"
            return "".join(lines), True
        if EVOLVE_END_RE.search(line):
            inside = False
    return code, False


def _replacement_for_trivial_theorem(code: str) -> str | None:
    if not re.search(r"\b(sorry|admit)\b", code):
        return None
    if re.search(r":\s*True\s*:=\s*by", code):
        return "trivial"
    if re.search(r":\s*([A-Za-z0-9_'.]+)\s*=\s*\1\s*:=\s*by", code):
        return "rfl"
    return None
