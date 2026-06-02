from __future__ import annotations

from dataclasses import dataclass

from .assumption_audit import audit_gt_hypotheses
from .gap_ledger import default_gap_ledger, detect_unverified_claims
from .model_client import ModelClientError, ModelConfig, OpenAICompatibleClient
from .prompt_builder import select_gt_context
from .tools import run_enabled_tools


@dataclass(frozen=True)
class ResearchRequest:
    problem: str
    domain_context: str = ""
    mode: str = "plan"
    model: str = "gpt-4.1"
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    temperature: float = 0.2
    max_tokens: int | None = None


@dataclass(frozen=True)
class ResearchResponse:
    status: str
    answer: str
    assumption_audit: str
    gap_ledger: str
    warnings: list[str]
    provider_error: str | None = None
    finish_reason: str | None = None
    continuation_count: int = 0
    truncated: bool = False
    tool_results: list[dict[str, object]] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "answer": self.answer,
            "assumption_audit": self.assumption_audit,
            "gap_ledger": self.gap_ledger,
            "warnings": self.warnings,
            "provider_error": self.provider_error,
            "finish_reason": self.finish_reason,
            "continuation_count": self.continuation_count,
            "truncated": self.truncated,
            "tool_results": self.tool_results or [],
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

SEARCH_RESEARCH_SYSTEM = """You are a careful research retrieval assistant.

Your job is to answer literature-search, web-search, and reference-retrieval requests using grounded tool results when available.

Required behavior:
1. Do not frame bibliographic retrieval as a proof, formalization, or topology-audit task.
2. Prefer direct links, metadata, and short source-grounded summaries.
3. If a tool returns no matches, say so plainly and mention the exact query/date/category used.
4. Never invent that a search was executed if the tool results do not show it.
"""

MAX_CONTINUATION_ROUNDS = 3


class GTResearchService:
    def __init__(self, client: OpenAICompatibleClient | None = None) -> None:
        self.client = client or OpenAICompatibleClient()

    def research(self, request: ResearchRequest) -> ResearchResponse:
        text = request.problem + "\n" + request.domain_context
        search_mode = _is_search_request(request.problem, request.domain_context)
        if search_mode:
            assumption_audit = _search_assumption_audit(request.problem, request.domain_context)
            warnings: list[str] = []
            status_override = None
            gap_ledger = _search_gap_ledger()
        else:
            assumption_audit, warnings, status_override = audit_gt_hypotheses(text)
            unverified_claims = detect_unverified_claims(text, allowed_references=[])
            if unverified_claims:
                warnings.extend(f"Unverified claim detected: {claim}" for claim in unverified_claims)
            gap_ledger = (
                default_gap_ledger("; ".join(warnings), lean_status="natural-language model request")
                if warnings
                else default_gap_ledger("Model response must still be checked before being treated as proof.")
            )

        tool_results = run_enabled_tools(request.problem, request.domain_context)
        tool_context = _render_tool_context(tool_results)
        direct_answer = _direct_tool_answer(request.problem, tool_results)
        if direct_answer is not None:
            status = "COMPLETED" if search_mode and not direct_answer["warnings"] else "PARTIAL" if direct_answer["warnings"] else "PROVED"
            return ResearchResponse(
                status=status,
                answer=direct_answer["answer"],
                assumption_audit=assumption_audit,
                gap_ledger=gap_ledger,
                warnings=warnings + direct_answer["warnings"],
                tool_results=tool_results,
            )

        user_prompt = "\n".join(
            [
                "# Problem",
                request.problem,
                "",
                "# Domain Context",
                request.domain_context.strip() if search_mode and request.domain_context.strip() else select_gt_context(request.domain_context),
                "",
                tool_context,
                "",
                assumption_audit,
                "",
                gap_ledger,
            ]
        )

        try:
            model_response = self.client.complete(
                system=SEARCH_RESEARCH_SYSTEM if search_mode else GT_RESEARCH_SYSTEM,
                user=user_prompt,
                model=request.model,
                temperature=request.temperature,
                api_key=request.api_key,
                base_url=request.base_url,
                max_tokens=request.max_tokens,
            )
            answer = model_response.text
            finish_reason = getattr(model_response, "finish_reason", None)
            continuation_count = 0
            while _is_truncated_finish_reason(finish_reason) and continuation_count < MAX_CONTINUATION_ROUNDS:
                continuation_count += 1
                continuation = self.client.complete(
                    system=SEARCH_RESEARCH_SYSTEM if search_mode else GT_RESEARCH_SYSTEM,
                    user=_continuation_prompt(user_prompt, answer),
                    model=request.model,
                    temperature=request.temperature,
                    api_key=request.api_key,
                    base_url=request.base_url,
                    max_tokens=request.max_tokens,
                )
                answer = _append_continuation(answer, continuation.text)
                finish_reason = getattr(continuation, "finish_reason", None)

            if continuation_count:
                warnings.append(
                    f"Model hit its output token limit; requested {continuation_count} automatic continuation(s)."
                )
            truncated = _is_truncated_finish_reason(finish_reason)
            if truncated:
                warnings.append(
                    "Model output may still be truncated after automatic continuation; increase Max Tokens or narrow the problem."
                )
            fallback_status = "COMPLETED" if search_mode else "PARTIAL"
            status = status_override or _extract_status(answer) or fallback_status
            return ResearchResponse(
                status,
                answer,
                assumption_audit,
                gap_ledger,
                warnings,
                finish_reason=finish_reason,
                continuation_count=continuation_count,
                truncated=truncated,
                tool_results=tool_results,
            )
        except ModelClientError as exc:
            failure_message = (
                "The external retrieval/model call failed. Check the API key, base URL, model name, and network access."
                if search_mode
                else "The local GT audit completed, but the external model call failed. "
                "Check the API key, base URL, model name, and network access."
            )
            return ResearchResponse(
                status=status_override or ("BLOCKED" if not search_mode else "PARTIAL"),
                answer=failure_message,
                assumption_audit=assumption_audit,
                gap_ledger=gap_ledger,
                warnings=warnings,
                provider_error=str(exc),
                tool_results=tool_results,
            )


def _extract_status(text: str) -> str | None:
    upper = text.upper()
    for status in ("COMPLETED", "PROVED", "PARTIAL", "MISFORMALIZED", "COUNTEREXAMPLE", "BLOCKED"):
        if f"STATUS: {status}" in upper or upper.startswith(status):
            return status
    return None


def _render_tool_context(tool_results: list[dict[str, object]]) -> str:
    lines = ["# Tool Context"]
    if not tool_results:
        lines.append("No topology tools are enabled.")
        return "\n".join(lines)

    for tool_result in tool_results:
        lines.append(f"## {tool_result.get('display_name', tool_result.get('id'))}")
        result = tool_result.get("result")
        if not isinstance(result, dict):
            lines.append(str(result))
            continue
        status = result.get("status")
        if status:
            lines.append(f"Status: {status}")
        if result.get("reason"):
            lines.append(f"Reason: {result['reason']}")
        _append_tool_items(lines, result)
    return "\n".join(lines)


def _append_tool_items(lines: list[str], result: dict[str, object]) -> None:
    for key in ("matches", "results", "suggestions", "links", "steps"):
        value = result.get(key)
        if not value:
            continue
        lines.append(f"{key.title()}:")
        if isinstance(value, list):
            for item in value[:8]:
                if isinstance(item, dict):
                    title = item.get("title") or item.get("source") or item.get("statement") or "item"
                    url = item.get("url")
                    snippet = item.get("full_text_preview") or item.get("snippet") or item.get("statement") or item.get("use")
                    line = f"- {title}"
                    if url:
                        line += f" ({url})"
                    if item.get("local_pdf_path"):
                        line += f" [local PDF: {item['local_pdf_path']}]"
                    if snippet:
                        line += f": {snippet}"
                    lines.append(line)
                else:
                    lines.append(f"- {item}")
        else:
            lines.append(str(value))


def _direct_tool_answer(problem: str, tool_results: list[dict[str, object]]) -> dict[str, object] | None:
    lowered = problem.lower()
    arxiv_request = any(token in lowered for token in ("arxiv", "math.at", "math.gt", "math.dg", "paper", "papers", "article", "articles", "论文", "文章"))
    wants_inventory = any(
        token in lowered
        for token in (
            "url",
            "urls",
            "link",
            "links",
            "metadata",
            "download",
            "pdf",
            "article list",
            "paper list",
            "search",
            "retrieve",
            "return",
            "find",
            "list",
            "链接",
            "网址",
            "元数据",
            "搜索",
            "检索",
            "列出",
            "返回",
            "查找",
        )
    )
    if not (arxiv_request and wants_inventory):
        return None

    arxiv_result = next((item for item in tool_results if item.get("id") == "arxiv_search"), None)
    if not arxiv_result:
        return None
    result = arxiv_result.get("result")
    if not isinstance(result, dict):
        return None

    status = result.get("status")
    if status == "error":
        return {
            "answer": "arXiv search failed before a result list could be produced.",
            "warnings": [f"arXiv search error: {result.get('reason', 'unknown error')}"],
        }

    links_only = "metadata" not in lowered and "download" not in lowered and "pdf" not in lowered
    entries = result.get("results") or []
    filters = result.get("filters") or {}
    category_text = ", ".join(filters.get("categories", [])) or "requested categories"
    date_text = filters.get("date")
    source_text = result.get("source", "arxiv_api")

    lines = ["# arXiv Search Results", ""]
    requested_ids = [str(item) for item in filters.get("paper_ids", []) if item]
    if requested_ids:
        lines.append(f"Requested arXiv IDs: {', '.join(requested_ids)}")
    if date_text:
        lines.append(f"Requested date: {date_text}")
    matched_dates = sorted(
        {
            str(item.get("matched_announcement_date"))
            for item in entries
            if isinstance(item, dict) and item.get("matched_announcement_date")
        }
    )
    if matched_dates:
        lines.append(f"Matched announcement date: {', '.join(matched_dates)}")
    lines.append(f"Categories: {category_text}")
    lines.append(f"Source: {source_text}")
    if result.get("source_url"):
        lines.append(f"Source URL: {result['source_url']}")
    lines.append(f"Matches: {len(entries)}")
    lines.append("")

    if not entries:
        if status == "rate_limited":
            lines.append("arXiv temporarily rate-limited live retrieval, so no result list could be fetched in this attempt.")
            if result.get("source_url"):
                lines.append(f"You can verify the official arXiv listing here: {result['source_url']}")
            return {
                "answer": "\n".join(lines),
                "warnings": [f"arXiv live retrieval rate-limited: {result.get('reason', 'HTTP 429')}"],
            }
        lines.append("No matching arXiv entries were returned for the current query.")
        return {"answer": "\n".join(lines), "warnings": []}

    for item in entries:
        if not isinstance(item, dict):
            continue
        abs_url = item.get("abs_url") or item.get("url") or ""
        title = item.get("title", "")
        if links_only:
            line = f"- {abs_url}"
            if item.get("local_pdf_path"):
                line += f" [local PDF: {item['local_pdf_path']}]"
            lines.append(line)
            continue
        lines.append(f"## {title}")
        lines.append(f"- URL: {abs_url}")
        if item.get("pdf_url"):
            lines.append(f"- PDF: {item['pdf_url']}")
        if item.get("local_pdf_path"):
            lines.append(f"- Local PDF: {item['local_pdf_path']}")
        if item.get("pdf_download_status") == "error":
            lines.append(f"- PDF download error: {item.get('pdf_download_error', 'unknown error')}")
        if item.get("id"):
            lines.append(f"- arXiv ID: {item['id']}")
        if item.get("primary_category"):
            lines.append(f"- Primary category: {item['primary_category']}")
        if item.get("published"):
            lines.append(f"- Published: {item['published']}")
        if item.get("matched_announcement_date"):
            lines.append(f"- Matched announcement date: {item['matched_announcement_date']}")
        if item.get("date_match_note"):
            lines.append(f"- Date note: {item['date_match_note']}")
        if item.get("updated"):
            lines.append(f"- Updated: {item['updated']}")
        if item.get("authors"):
            lines.append(f"- Authors: {', '.join(item['authors'])}")
        if item.get("summary"):
            lines.append(f"- Summary: {item['summary']}")
        if item.get("full_text_preview"):
            lines.append(f"- PDF preview: {item['full_text_preview'][:1200]}")
        lines.append("")

    while lines and not lines[-1].strip():
        lines.pop()
    return {"answer": "\n".join(lines), "warnings": []}


def _is_search_request(problem: str, domain_context: str) -> bool:
    lowered = f"{problem}\n{domain_context}".lower()
    search_tokens = (
        "arxiv",
        "paper",
        "papers",
        "article",
        "articles",
        "metadata",
        "url",
        "urls",
        "link",
        "links",
        "search",
        "retrieve",
        "download",
        "pdf",
        "return the list",
        "find papers",
        "web search",
        "论文",
        "文章",
        "元数据",
        "链接",
        "网址",
        "搜索",
        "检索",
        "查找",
        "列出",
        "返回链接",
    )
    proof_tokens = ("prove", "proof", "show that", "counterexample", "证明", "定理", "命题", "引理")
    return any(token in lowered for token in search_tokens) and not (
        any(token in lowered for token in proof_tokens) and "arxiv" not in lowered
    )


def _search_assumption_audit(problem: str, domain_context: str) -> str:
    lines = [
        "# Retrieval assumption audit",
        "",
        "## Request type",
        "Treated as a literature/reference retrieval task rather than a proof-audit task.",
        "",
        "## Retrieval checks",
        "- exact date/category terms are taken from the user request when present",
        "- tool results should be preferred over freeform model reasoning",
        "- returned links should correspond to grounded search results",
    ]
    if domain_context.strip():
        lines.extend(["", "## Context", domain_context.strip()])
    return "\n".join(lines) + "\n"


def _search_gap_ledger() -> str:
    return "\n".join(
        [
            "# Retrieval Gap Ledger",
            "",
            "- No proof-gap analysis is required for a bibliographic retrieval request.",
            "- Remaining risk is limited to tool/provider coverage, rate limits, and source date semantics.",
            "",
        ]
    )


def _is_truncated_finish_reason(reason: str | None) -> bool:
    if not reason:
        return False
    normalized = reason.lower().replace("-", "_")
    return normalized in {"length", "max_tokens", "token_limit"} or "length" in normalized


def _continuation_prompt(original_prompt: str, partial_answer: str) -> str:
    context_tail = original_prompt[-4000:]
    answer_tail = partial_answer[-6000:]
    return "\n".join(
        [
            "# Original problem and audit context tail",
            context_tail,
            "",
            "# Tail of answer already produced",
            answer_tail,
            "",
            "# Continuation task",
            "The previous answer stopped because the model hit the output token limit.",
            "Continue exactly from the next character after the tail above.",
            "Do not repeat existing text, do not restart the answer, and complete any unfinished Markdown or LaTeX.",
        ]
    )


def _append_continuation(answer: str, continuation: str) -> str:
    if not answer:
        return continuation
    if not continuation:
        return answer
    overlap = _overlap_length(answer, continuation)
    return answer + continuation[overlap:]


def _overlap_length(prefix: str, suffix: str) -> int:
    max_size = min(len(prefix), len(suffix), 2000)
    for size in range(max_size, 0, -1):
        if prefix[-size:] == suffix[:size]:
            return size
    return 0
