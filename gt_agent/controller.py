from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .assumption_audit import audit_gt_hypotheses
from .compiler import LeanCompiler
from .gap_ledger import default_gap_ledger, detect_unverified_claims, extract_gap_ledger
from .population_db import PopulationDB
from .p_ucb_sampler import PUcbSampler
from .prover_subagent import GTProverSubagent, has_lean_holes
from .rater_subagent import GTRaterSubagent
from .schemas import AttemptSummary, GTProblem, GTResult
from .validator import GTValidator


@dataclass(frozen=True)
class BasicModeConfig:
    num_provers: int = 8
    max_episodes_per_problem: int = 200
    max_search_replace_per_episode: int = 60
    compile_after_each_edit: bool = True
    allow_sorry_in_intermediate_sketch: bool = True
    allow_sorry_in_final_output: bool = False


@dataclass(frozen=True)
class EvolutionModeConfig:
    num_provers: int = 10
    num_raters: int = 3
    rater_match_size: int = 7
    elite_pool_size: int = 64
    p_ucb_exploration_c: float = 0.2
    goal_cache: bool = True


class GeometryTopologyResearchAgent:
    """Minimal, local GT Agent implementation."""

    def __init__(
        self,
        *,
        validator: GTValidator | None = None,
        compiler: LeanCompiler | None = None,
        output_root: str | Path = "gt_agent_runs",
        basic_config: BasicModeConfig | None = None,
        evolution_config: EvolutionModeConfig | None = None,
    ) -> None:
        self.compiler = compiler or LeanCompiler()
        self.validator = validator or GTValidator(self.compiler)
        self.output_root = Path(output_root)
        self.basic_config = basic_config or BasicModeConfig()
        self.evolution_config = evolution_config or EvolutionModeConfig()
        self.prover = GTProverSubagent(self.validator, self.compiler)
        self.rater = GTRaterSubagent()

    def run(self, problem: GTProblem) -> GTResult:
        if problem.mode == "basic":
            return self.run_basic(problem)
        if problem.mode == "evolution":
            return self.run_evolution(problem)
        raise ValueError(f"unsupported GT mode: {problem.mode}")

    def run_basic(self, problem: GTProblem) -> GTResult:
        source = problem.problem_path.read_text(encoding="utf-8")
        context = self._read_context(problem)
        run_dir = self._run_dir(problem)
        run_dir.mkdir(parents=True, exist_ok=True)

        audit_text, audit_warnings, audit_status = audit_gt_hypotheses(source + "\n" + context)
        if audit_status:
            return self._write_result(
                run_dir,
                problem,
                status=audit_status,
                final_code=source,
                summary=AttemptSummary(
                    status=audit_status,  # type: ignore[arg-type]
                    main_idea="The supplied statement appears to miss required geometry/topology hypotheses.",
                    remaining_gaps=audit_warnings,
                ),
                gap_ledger=default_gap_ledger(audit_warnings[0], lean_status="not attempted"),
                assumption_audit=audit_text,
                rater_report=self.rater.rank([source])[1],
            )

        if problem.problem_path.suffix.lower() != ".lean":
            claims = detect_unverified_claims(source + "\n" + context, problem.allowed_references)
            gaps = (
                default_gap_ledger(
                    f"Unverified literature claim: {', '.join(claims)}",
                    lean_status="natural-language only",
                )
                if claims
                else default_gap_ledger("Natural-language problem has not been formalized into Lean.")
            )
            return self._write_result(
                run_dir,
                problem,
                status="PARTIAL",
                final_code=source,
                summary=AttemptSummary(
                    status="PARTIAL",
                    main_idea="Produced a conservative natural-language audit; no Lean theorem was modified.",
                    remaining_gaps=claims or ["Formal Lean statement is missing."],
                ),
                gap_ledger=gaps,
                assumption_audit=audit_text,
                rater_report=self.rater.rank([source])[1],
            )

        step = self.prover.mutate(source, source)
        final_validation = self.validator.validate_candidate(source, step.code, final=True)
        status = "PROVED" if final_validation.accepted and not has_lean_holes(step.code) else "PARTIAL"
        if status != "PROVED" and final_validation.reason:
            step.summary.remaining_gaps.append(final_validation.reason)
            if final_validation.lean_feedback and final_validation.lean_feedback.output:
                step.summary.lean_feedback = final_validation.lean_feedback.output
        step.summary.status = status  # type: ignore[assignment]
        gap_ledger = extract_gap_ledger(step.code) if status != "PROVED" else "# GT Gap Ledger\n\nNo open gaps recorded.\n"
        if status != "PROVED" and "No open gaps recorded" in gap_ledger:
            gap_ledger = default_gap_ledger("; ".join(step.summary.remaining_gaps) or "Proof remains uncertified.")

        return self._write_result(
            run_dir,
            problem,
            status=status,  # type: ignore[arg-type]
            final_code=step.code,
            summary=step.summary,
            gap_ledger=gap_ledger,
            assumption_audit=audit_text,
            rater_report=self.rater.rank([step.code])[1],
        )

    def run_evolution(self, problem: GTProblem) -> GTResult:
        source = problem.problem_path.read_text(encoding="utf-8")
        context = self._read_context(problem)
        audit_text, audit_warnings, audit_status = audit_gt_hypotheses(source + "\n" + context)
        run_dir = self._run_dir(problem)
        run_dir.mkdir(parents=True, exist_ok=True)

        if audit_status:
            return self._write_result(
                run_dir,
                problem,
                status=audit_status,
                final_code=source,
                summary=AttemptSummary(
                    status=audit_status,  # type: ignore[arg-type]
                    main_idea="Evolution mode stopped before mutation due to hypothesis mismatch.",
                    remaining_gaps=audit_warnings,
                ),
                gap_ledger=default_gap_ledger(audit_warnings[0], lean_status="not attempted"),
                assumption_audit=audit_text,
                rater_report=self.rater.rank([source])[1],
            )

        population = PopulationDB(elite_pool_size=self.evolution_config.elite_pool_size)
        population.initialize(source)
        sampler = PUcbSampler(self.evolution_config.p_ucb_exploration_c)
        parent = sampler.sample(population.entries())
        step = self.prover.mutate(source, parent.code)
        rated = self.rater.rate(step.code)
        if step.validation.accepted:
            population.add(step.code, score=rated.score, metadata={"mode": "evolution-local"})

        final_validation = self.validator.validate_candidate(source, step.code, final=True)
        status = "PROVED" if final_validation.accepted and not has_lean_holes(step.code) else "PARTIAL"
        if status != "PROVED":
            step.summary.status = "PARTIAL"
            step.summary.remaining_gaps.append(
                final_validation.reason or "Evolution adapter completed one local mutation only."
            )

        return self._write_result(
            run_dir,
            problem,
            status=status,  # type: ignore[arg-type]
            final_code=step.code,
            summary=step.summary,
            gap_ledger=extract_gap_ledger(step.code)
            if status != "PROVED"
            else "# GT Gap Ledger\n\nNo open gaps recorded.\n",
            assumption_audit=audit_text,
            rater_report=self.rater.rank([entry.code for entry in population.entries()])[1],
        )

    def _write_result(
        self,
        run_dir: Path,
        problem: GTProblem,
        *,
        status: str,
        final_code: str,
        summary: AttemptSummary,
        gap_ledger: str,
        assumption_audit: str,
        rater_report: str,
    ) -> GTResult:
        formal_path = run_dir / ("final.lean" if problem.problem_path.suffix.lower() == ".lean" else "final.md")
        summary_path = run_dir / "summary.md"
        gap_path = run_dir / "gap_ledger.md"
        audit_path = run_dir / "assumption_audit.md"
        rater_path = run_dir / "rater_report.md"
        result_path = run_dir / "result.json"

        formal_path.write_text(final_code, encoding="utf-8")
        summary_path.write_text(_render_summary(status, problem, summary), encoding="utf-8")
        gap_path.write_text(gap_ledger, encoding="utf-8")
        audit_path.write_text(assumption_audit, encoding="utf-8")
        rater_path.write_text(rater_report, encoding="utf-8")

        result = GTResult(
            status=status,  # type: ignore[arg-type]
            formal_artifact=formal_path,
            natural_language_summary=summary_path,
            gap_ledger=gap_path,
            assumption_audit=audit_path,
            rater_report=rater_path,
        )
        result_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        return result

    def _read_context(self, problem: GTProblem) -> str:
        if problem.context_path and problem.context_path.exists():
            return problem.context_path.read_text(encoding="utf-8")
        default_context = problem.problem_path.with_name("gt_context.md")
        if default_context.exists():
            return default_context.read_text(encoding="utf-8")
        return ""

    def _run_dir(self, problem: GTProblem) -> Path:
        return self.output_root / f"{problem.problem_path.stem}_{problem.mode}"


def _render_summary(status: str, problem: GTProblem, summary: AttemptSummary) -> str:
    closed = "\n".join(f"- {item}" for item in summary.closed_lemmas) or "- None"
    gaps = "\n".join(f"- {item}" for item in summary.remaining_gaps) or "- None"
    return "\n".join(
        [
            "# GT Agent Result",
            "",
            "## Status",
            status,
            "",
            "## Formal theorem",
            str(problem.problem_path) if problem.problem_path.suffix.lower() == ".lean" else "No Lean theorem supplied.",
            "",
            "## Natural-language theorem",
            str(problem.context_path) if problem.context_path else "See supplied problem text/sketch.",
            "",
            "## Match between formal and informal statement",
            "Not automatically certified by the local adapter.",
            "",
            "## Proof strategy",
            summary.main_idea or "Not recorded.",
            "",
            "## Closed components",
            closed,
            "",
            "## Remaining gaps",
            gaps,
            "",
            "## Geometry/topology assumption audit",
            "See assumption_audit.md.",
            "",
            "## Potential counterexamples checked",
            "Low-dimensional, non-orientable, boundary, and non-compact cases are flagged by the audit when detected.",
            "",
            "## Next executable steps",
            summary.lean_feedback or "Provide a precise local lemma and run Lean validation.",
            "",
        ]
    )


GTAgent = GeometryTopologyResearchAgent
