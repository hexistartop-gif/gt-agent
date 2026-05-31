from __future__ import annotations

import re
from dataclasses import dataclass, field


GAP_TYPES = {"routine", "technical", "strategic", "library-missing", "conjectural"}


@dataclass
class Gap:
    identifier: str
    statement: str
    gap_type: str = "technical"
    depends_on: list[str] = field(default_factory=list)
    why_needed: str = ""
    current_evidence: str = ""
    lean_status: str = "not formalized"
    risk: str = ""
    next_step: str = ""

    def to_markdown(self) -> str:
        depends = ", ".join(self.depends_on) if self.depends_on else "None"
        return "\n".join(
            [
                f"## Gap {self.identifier}",
                f"Statement: {self.statement}",
                f"Type: {self.gap_type}",
                f"Depends on: {depends}",
                f"Why needed: {self.why_needed or 'Not recorded.'}",
                f"Current evidence: {self.current_evidence or 'Not recorded.'}",
                f"Lean status: {self.lean_status}",
                f"Risk: {self.risk or 'Not recorded.'}",
                f"Next step: {self.next_step or 'Not recorded.'}",
            ]
        )


def render_gap_ledger(gaps: list[Gap]) -> str:
    if not gaps:
        return "# GT Gap Ledger\n\nNo open gaps recorded.\n"
    return "# GT Gap Ledger\n\n" + "\n\n".join(gap.to_markdown() for gap in gaps) + "\n"


def default_gap_ledger(reason: str, lean_status: str = "not checked") -> str:
    return render_gap_ledger(
        [
            Gap(
                identifier="G1",
                statement=reason,
                gap_type="technical",
                why_needed="The agent cannot certify PROVED until this item is closed.",
                lean_status=lean_status,
                risk="May hide a real geometry/topology hypothesis or formalization mismatch.",
                next_step="State the missing lemma precisely and check it independently.",
            )
        ]
    )


def extract_gap_ledger(text: str) -> str:
    marker = "# GT Gap Ledger"
    if marker in text:
        return text[text.index(marker) :].strip()
    lean_marker = "GT_GAP_LEDGER:"
    if lean_marker in text:
        return text[text.index(lean_marker) :].strip()
    gaps = infer_gaps_from_sketch(text)
    return render_gap_ledger(gaps)


def infer_gaps_from_sketch(text: str) -> list[Gap]:
    gaps: list[Gap] = []
    if re.search(r"\bsorry\b|\badmit\b", text):
        gaps.append(
            Gap(
                identifier="G1",
                statement="Lean proof contains unresolved sorry/admit placeholder.",
                gap_type="technical",
                why_needed="Final GT output cannot contain unchecked proof holes.",
                lean_status="open",
                risk="The placeholder may contain the core theorem.",
                next_step="Replace the placeholder with a smaller checked lemma or proof.",
            )
        )
    fake_claims = detect_unverified_claims(text, allowed_references=[])
    for index, claim in enumerate(fake_claims, start=len(gaps) + 1):
        gaps.append(
            Gap(
                identifier=f"G{index}",
                statement=f"Unverified literature claim: {claim}",
                gap_type="library-missing",
                why_needed="The proof cannot rely on unnamed or unsupplied external theorems.",
                current_evidence="Claim was detected in the input but not in allowed references.",
                lean_status="unformalized",
                risk="May be fabricated or may require stronger hypotheses.",
                next_step="Provide an exact statement and either a Lean theorem name or user-supplied reference.",
            )
        )
    return gaps


def detect_unverified_claims(text: str, allowed_references: list[str] | None = None) -> list[str]:
    allowed = {item.lower() for item in (allowed_references or [])}
    claims: list[str] = []
    theorem_pattern = re.compile(
        r"([A-Z][A-Za-z]+(?:[-\u2013\u2014][A-Z][A-Za-z]+)*(?:\s+[A-Z][A-Za-z]+(?:[-\u2013\u2014][A-Z][A-Za-z]+)*)*\s+(?:compactness\s+)?theorem)"
    )
    for match in theorem_pattern.finditer(text):
        claim = match.group(1).strip()
        if claim.lower() not in allowed:
            claims.append(claim)
    return sorted(set(claims))


def detect_bad_gaps(text: str, target_statement: str | None = None) -> list[str]:
    findings: list[str] = []
    if re.search(r"lemma\s+main_hidden_gap\b[\s\S]*?:=\s*by\s*\n\s*sorry", text):
        findings.append("lemma main_hidden_gap hides the main argument behind sorry")
    if target_statement:
        escaped = re.escape(target_statement.strip())
        if re.search(rf"lemma\s+\w+\s*:\s*{escaped}\s*:=\s*by\s*\n\s*sorry", text):
            findings.append("gap lemma restates the target theorem")
    if re.search(r"standard theorem", text, re.IGNORECASE) and "exact statement" not in text:
        findings.append("gap invokes an unverified standard theorem without an exact statement")
    return findings
