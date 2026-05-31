from __future__ import annotations

from pathlib import Path

from .attempt_summary import format_prior_attempts
from .gap_ledger import extract_gap_ledger
from .schemas import AttemptSummary, GTProblem

PACKAGE_ROOT = Path(__file__).resolve().parent


def build_gt_prover_prompt(
    problem: GTProblem,
    sketch: object,
    prior_attempts: list[AttemptSummary] | None,
    lean_feedback: str,
    domain_context: str,
) -> str:
    template = (PACKAGE_ROOT / "prompts" / "gt_prover_system.md").read_text(encoding="utf-8")
    code = getattr(sketch, "code", str(sketch))
    sections = [
        template,
        "",
        "# Current Lean/Natural-Language Sketch",
        "```lean",
        code,
        "```",
        "",
        format_prior_attempts(prior_attempts),
        "",
        "# Lean Feedback",
        lean_feedback or "No Lean feedback supplied.",
        "",
        "# Domain Context",
        select_gt_context(domain_context),
        "",
        extract_gap_ledger(code),
        "",
        "# Allowed References",
        _format_list(problem.allowed_references),
        "",
        "# Forbidden Assumptions",
        _format_list(problem.forbidden_assumptions),
    ]
    return "\n".join(sections)


def select_gt_context(domain_context: str | None) -> str:
    checklist = (PACKAGE_ROOT / "knowledge" / "gt_domain_checklist.md").read_text(encoding="utf-8")
    if not domain_context:
        return checklist
    lowered = domain_context.lower()
    headings = {
        "general topology": ["topology", "compact", "hausdorff", "covering"],
        "algebraic topology": ["homotopy", "homology", "spectral", "hurewicz"],
        "differential topology": ["smooth", "manifold", "transversality", "sard"],
        "fiber bundles and characteristic classes": ["bundle", "chern", "stiefel", "euler"],
        "low-dimensional topology": ["3-manifold", "surface", "dehn", "heegaard"],
        "symplectic/contact topology": ["symplectic", "contact", "floer"],
        "algebraic/log geometry interface": ["scheme", "stack", "moduli", "log"],
    }
    selected: list[str] = []
    for heading, needles in headings.items():
        if any(needle in lowered for needle in needles):
            selected.append(_extract_section(checklist, heading))
    return domain_context.strip() + "\n\n" + ("\n\n".join(selected) if selected else checklist)


def _extract_section(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip().lower() == f"## {heading}".lower():
            start = index
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end]).strip()


def _format_list(values: list[str]) -> str:
    if not values:
        return "- None supplied."
    return "\n".join(f"- {value}" for value in values)
