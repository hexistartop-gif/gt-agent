from __future__ import annotations

import re
from dataclasses import dataclass, field

from .compiler import LeanCompiler, LeanFeedback


EVOLVE_START_RE = re.compile(r"EVOLVE-(?:BLOCK|VALUE)-START")
EVOLVE_END_RE = re.compile(r"EVOLVE-(?:BLOCK|VALUE)-END")
THEOREM_RE = re.compile(r"^\s*(?:theorem|lemma)\s+([A-Za-z0-9_'.]+)\b", re.MULTILINE)


@dataclass
class ValidationResult:
    accepted: bool
    status: str
    reason: str = ""
    repair_hint: str = ""
    lean_feedback: LeanFeedback | None = None
    details: dict[str, object] = field(default_factory=dict)

    def to_rejection_json(self) -> dict[str, str]:
        return {
            "status": "REJECTED",
            "reason": self.reason,
            "repair_hint": self.repair_hint,
        }


class GTValidator:
    """Validator for GT Agent Lean sketches."""

    forbidden_final_patterns = (
        (re.compile(r"\bsorry\b"), "final output contains sorry"),
        (re.compile(r"\badmit\b"), "final output contains admit"),
        (re.compile(r"^\s*axiom\b", re.MULTILINE), "final output declares an axiom"),
        (re.compile(r"\bunsafe\b"), "final output contains unsafe"),
        (re.compile(r"set_option\s+maxHeartbeats\s+0"), "final output disables maxHeartbeats"),
        (re.compile(r"by\s+native_decide"), "final output uses by native_decide"),
    )

    environment_exploit_patterns = (
        re.compile(r"set_option\s+maxHeartbeats\s+0"),
        re.compile(r"^\s*axiom\b", re.MULTILINE),
        re.compile(r"\bunsafe\b"),
    )

    def __init__(
        self,
        compiler: LeanCompiler | None = None,
        *,
        allow_import_changes: bool = False,
        require_compile: bool = True,
    ) -> None:
        self.compiler = compiler or LeanCompiler()
        self.allow_import_changes = allow_import_changes
        self.require_compile = require_compile

    def validate_candidate(
        self,
        original_code: str,
        candidate_code: str,
        *,
        final: bool = False,
    ) -> ValidationResult:
        checks: list[ValidationResult] = [
            self.check_marker_integrity(original_code, candidate_code),
            self.check_theorem_statement_unchanged(original_code, candidate_code),
            self.check_namespace_preserved(original_code, candidate_code),
            self.check_imports_unchanged(original_code, candidate_code),
            self.check_environment_exploit(candidate_code),
        ]
        if final:
            checks.append(self.check_forbidden_final_tokens(candidate_code))

        for result in checks:
            if not result.accepted:
                return result

        if final and self.require_compile:
            feedback = self.compiler.check_code(candidate_code)
            if not feedback.checked:
                return ValidationResult(
                    False,
                    "REJECTED",
                    "Lean compile check could not be run",
                    "install Lean or inject a compiler adapter before accepting a final proof",
                    feedback,
                )
            if not feedback.compiles:
                return ValidationResult(
                    False,
                    "REJECTED",
                    "final Lean compile failed",
                    "repair the Lean errors before returning PROVED",
                    feedback,
                )
            return ValidationResult(True, "ACCEPTED", lean_feedback=feedback)

        return ValidationResult(True, "ACCEPTED")

    def final_accepts(self, original_code: str, candidate_code: str) -> bool:
        return self.validate_candidate(original_code, candidate_code, final=True).accepted

    def integrity_failed(self, original_code: str, candidate_code: str) -> bool:
        return not self.validate_candidate(original_code, candidate_code, final=False).accepted

    def check_marker_integrity(self, original_code: str, candidate_code: str) -> ValidationResult:
        if _outside_evolve_text(original_code) != _outside_evolve_text(candidate_code):
            return ValidationResult(
                False,
                "REJECTED",
                "theorem statement changed outside EVOLVE markers",
                "revert theorem signature and only add helper lemmas inside EVOLVE-BLOCK",
            )
        return ValidationResult(True, "ACCEPTED")

    def check_theorem_statement_unchanged(
        self,
        original_code: str,
        candidate_code: str,
    ) -> ValidationResult:
        original = _theorem_headers_without_evolve(original_code)
        candidate = _theorem_headers_without_evolve(candidate_code)
        if original != candidate:
            return ValidationResult(
                False,
                "REJECTED",
                "theorem statement changed outside EVOLVE markers",
                "restore the original theorem or lemma signature",
            )
        return ValidationResult(True, "ACCEPTED")

    def check_imports_unchanged(self, original_code: str, candidate_code: str) -> ValidationResult:
        if self.allow_import_changes:
            return ValidationResult(True, "ACCEPTED")
        if _imports(original_code) != _imports(candidate_code):
            return ValidationResult(
                False,
                "REJECTED",
                "imports changed",
                "keep imports unchanged unless the run configuration explicitly allows it",
            )
        return ValidationResult(True, "ACCEPTED")

    def check_namespace_preserved(self, original_code: str, candidate_code: str) -> ValidationResult:
        if _namespaces(original_code) != _namespaces(candidate_code):
            return ValidationResult(
                False,
                "REJECTED",
                "namespace declarations changed",
                "preserve the original namespace structure",
            )
        return ValidationResult(True, "ACCEPTED")

    def check_environment_exploit(self, code: str) -> ValidationResult:
        for pattern in self.environment_exploit_patterns:
            if pattern.search(code):
                return ValidationResult(
                    False,
                    "REJECTED",
                    "environment exploit or forbidden declaration detected",
                    "remove unsafe options, axioms, and unsafe declarations",
                )
        return ValidationResult(True, "ACCEPTED")

    def check_forbidden_final_tokens(self, code: str) -> ValidationResult:
        for pattern, reason in self.forbidden_final_patterns:
            if pattern.search(code):
                return ValidationResult(
                    False,
                    "REJECTED",
                    reason,
                    "replace the placeholder or forbidden construct with a checked proof",
                )
        return ValidationResult(True, "ACCEPTED")


def _outside_evolve_text(code: str) -> str:
    lines = code.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if EVOLVE_START_RE.search(line):
            inside = True
            out.append(line)
            continue
        if EVOLVE_END_RE.search(line):
            inside = False
            out.append(line)
            continue
        if not inside:
            out.append(line.rstrip())
    return "\n".join(out).strip()


def _imports(code: str) -> list[str]:
    return [line.strip() for line in code.splitlines() if line.strip().startswith("import ")]


def _namespaces(code: str) -> list[str]:
    return [
        line.strip()
        for line in code.splitlines()
        if line.strip().startswith("namespace ") or line.strip().startswith("end ")
    ]


def _theorem_headers_without_evolve(code: str) -> list[str]:
    return [line.strip() for line in _outside_evolve_text(code).splitlines() if THEOREM_RE.match(line)]
