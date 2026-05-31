from __future__ import annotations

import re


def audit_gt_hypotheses(text: str) -> tuple[str, list[str], str | None]:
    """Return markdown audit, warnings, and optional status override."""

    warnings: list[str] = []
    lowered = text.lower()

    if "poincare duality" in lowered or "poincar" in lowered:
        if "non-compact" in lowered or "noncompact" in lowered:
            warnings.append(
                "Poincare duality on non-compact manifolds needs compact-support, "
                "closed-manifold, or finite-type hypotheses; the supplied statement is too strong."
            )
        if "orient" not in lowered:
            warnings.append("Poincare duality usually needs orientability or twisted coefficients.")
        if "boundary" in lowered and "relative" not in lowered:
            warnings.append("Manifolds with boundary require relative/cohomology-with-compact-support variants.")

    if "compactness theorem" in lowered and re.search(r"[A-Z][A-Za-z]+[- ][A-Z][A-Za-z]+", text):
        warnings.append("Named compactness theorem is not verified unless supplied as an allowed reference.")

    status_override = "MISFORMALIZED" if any("too strong" in warning for warning in warnings) else None
    lines = [
        "# Geometry/topology assumption audit",
        "",
        "## Category and objects",
        "Not fully specified by the local adapter." if not text.strip() else "Derived from the supplied problem text/sketch.",
        "",
        "## Hypothesis warnings",
    ]
    lines.extend(f"- {warning}" for warning in warnings)
    if not warnings:
        lines.append("- No obvious geometry/topology hypothesis issue detected by the local audit.")
    lines.extend(
        [
            "",
            "## Required manual checks",
            "- category and morphisms",
            "- equivalence relation",
            "- compactness and finite-type assumptions",
            "- basepoints and orientations",
            "- boundary terms and signs",
            "- functoriality/naturality",
            "- local-to-global steps",
        ]
    )
    return "\n".join(lines) + "\n", warnings, status_override
