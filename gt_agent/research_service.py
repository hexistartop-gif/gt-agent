from __future__ import annotations

from dataclasses import dataclass

from .assumption_audit import audit_gt_hypotheses
from .gap_ledger import default_gap_ledger, detect_unverified_claims
from .model_client import ModelClientError, ModelConfig, OpenAICompatibleClient
from .prompt_builder import select_gt_context


@dataclass(frozen=True)
class ResearchRequest:
    problem: str
    domain_context: str = ""
    mode: str = "plan"
    model: str = "gpt-4.1"
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    temperature: float = 0.2


@dataclass(frozen=True)
class ResearchResponse:
    status: str
    answer: str
    assumption_audit: str
    gap_ledger: str
    warnings: list[str]
    provider_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "answer": self.answer,
            "assumption_audit": self.assumption_audit,
            "gap_ledger": self.gap_ledger,
            "warnings": self.warnings,
            "provider_error": self.provider_error,
        }


GT_RESEARCH_SYSTEM = """You are GT agent, a careful geometry/topology research assistant.

You help formalize, decompose, and audit geometry/topology problems. Never claim a result is proved unless every strategic gap is closed. Label claims as proved, conjectural, heuristic, Lean-formalized, unverified literature claim, or blocked gap.

Required output:
1. Status: PROVED / PARTIAL / MISFORMALIZED / COUNTEREXAMPLE / BLOCKED
2. Restatement of the problem
3. Assumption audit
4. Proof strategy or counterexample route
5. Gap ledger with routine / technical / strategic / library-missing / conjectural labels
6. Next executable steps
"""


class GTResearchService:
    def __init__(self, client: OpenAICompatibleClient | None = None) -> None:
        self.client = client or OpenAICompatibleClient()

    def research(self, request: ResearchRequest) -> ResearchResponse:
        text = request.problem + "\n" + request.domain_context
        assumption_audit, warnings, status_override = audit_gt_hypotheses(text)
        unverified_claims = detect_unverified_claims(text, allowed_references=[])
        if unverified_claims:
            warnings.extend(f"Unverified claim detected: {claim}" for claim in unverified_claims)
        gap_ledger = (
            default_gap_ledger("; ".join(warnings), lean_status="natural-language model request")
            if warnings
            else default_gap_ledger("Model response must still be checked before being treated as proof.")
        )

        user_prompt = "\n".join(
            [
                "# Problem",
                request.problem,
                "",
                "# Domain Context",
                select_gt_context(request.domain_context),
                "",
                assumption_audit,
                "",
                gap_ledger,
            ]
        )

        try:
            model_response = self.client.complete(
                system=GT_RESEARCH_SYSTEM,
                user=user_prompt,
                model=request.model,
                temperature=request.temperature,
                api_key=request.api_key,
                base_url=request.base_url,
            )
            answer = model_response.text
            status = status_override or _extract_status(answer) or "PARTIAL"
            return ResearchResponse(status, answer, assumption_audit, gap_ledger, warnings)
        except ModelClientError as exc:
            return ResearchResponse(
                status=status_override or "BLOCKED",
                answer=(
                    "The local GT audit completed, but the external model call failed. "
                    "Check the API key, base URL, model name, and network access."
                ),
                assumption_audit=assumption_audit,
                gap_ledger=gap_ledger,
                warnings=warnings,
                provider_error=str(exc),
            )


def _extract_status(text: str) -> str | None:
    upper = text.upper()
    for status in ("PROVED", "PARTIAL", "MISFORMALIZED", "COUNTEREXAMPLE", "BLOCKED"):
        if f"STATUS: {status}" in upper or upper.startswith(status):
            return status
    return None
