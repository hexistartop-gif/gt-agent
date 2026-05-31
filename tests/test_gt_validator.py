from __future__ import annotations

from gt_agent.compiler import LeanFeedback
from gt_agent.controller import GTAgent
from gt_agent.gap_ledger import detect_unverified_claims
from gt_agent.rater_subagent import GTRaterSubagent
from gt_agent.schemas import GTProblem
from gt_agent.validator import GTValidator


class FakeCompiler:
    def check_code(self, code: str) -> LeanFeedback:
        ok = "sorry" not in code and "admit" not in code
        return LeanFeedback(compiles=ok, output="" if ok else "unsolved goals", checked=True)


def lean_problem(body: str = "sorry") -> str:
    return f"""import Mathlib

namespace GTProblem

-- EVOLVE-BLOCK-START
-- helper area
-- EVOLVE-BLOCK-END

theorem target_theorem : True := by
  -- EVOLVE-BLOCK-START
  {body}
  -- EVOLVE-BLOCK-END

end GTProblem
"""


def test_marker_integrity_rejects_statement_change() -> None:
    original = lean_problem()
    candidate = original.replace("theorem target_theorem : True", "theorem target_theorem : False")
    validator = GTValidator(compiler=FakeCompiler(), require_compile=False)

    result = validator.validate_candidate(original, candidate)

    assert not result.accepted
    assert result.to_rejection_json()["status"] == "REJECTED"
    assert "outside EVOLVE markers" in result.reason


def test_no_fake_theorem_is_marked_unverified() -> None:
    text = "Use the Smith-Jones compactness theorem to finish the proof."

    claims = detect_unverified_claims(text, allowed_references=[])

    assert "Smith-Jones compactness theorem" in claims


def test_bad_gap_is_penalized_by_rater() -> None:
    sketch = """theorem target_statement : True := by
  trivial

lemma main_hidden_gap : target_statement := by
  sorry
"""
    rating = GTRaterSubagent().rate(sketch)

    assert rating.critical_flaws
    assert "Bad strategic gap" in rating.critical_flaws[0]


def test_geometry_hypothesis_audit_blocks_overbroad_poincare_duality(tmp_path) -> None:
    problem_path = tmp_path / "problem.md"
    problem_path.write_text(
        "Prove Poincare duality holds on any non-compact oriented manifold.",
        encoding="utf-8",
    )
    agent = GTAgent(compiler=FakeCompiler(), output_root=tmp_path / "runs")

    result = agent.run(GTProblem.from_path(problem_path, mode="basic"))

    assert result.status == "MISFORMALIZED"
    assert "compact-support" in result.assumption_audit.read_text(encoding="utf-8")


def test_lean_smoke_true_theorem_becomes_proved(tmp_path) -> None:
    problem_path = tmp_path / "simple.lean"
    problem_path.write_text(lean_problem(), encoding="utf-8")
    agent = GTAgent(compiler=FakeCompiler(), output_root=tmp_path / "runs")

    result = agent.run(GTProblem.from_path(problem_path, mode="basic"))

    assert result.status == "PROVED"
    final_code = result.formal_artifact.read_text(encoding="utf-8")
    assert "trivial" in final_code
    assert "sorry" not in final_code


def test_evolution_mode_has_minimal_population_flow(tmp_path) -> None:
    problem_path = tmp_path / "simple.lean"
    problem_path.write_text(lean_problem(), encoding="utf-8")
    agent = GTAgent(compiler=FakeCompiler(), output_root=tmp_path / "runs")

    result = agent.run(GTProblem.from_path(problem_path, mode="evolution"))

    assert result.status == "PROVED"
    assert result.rater_report.exists()
    assert "<decision>" in result.rater_report.read_text(encoding="utf-8")
