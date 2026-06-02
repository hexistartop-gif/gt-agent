from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any

from .base import BaseTool

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - optional dependency fallback.
    BeautifulSoup = None

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency fallback.
    PdfReader = None


ARXIV_DOWNLOAD_TOKENS = (
    "download",
    "pdf",
    "full text",
    "full-text",
    "full paper",
    "download pdf",
    "阅读全文",
    "全文",
    "下载",
)
ARXIV_READ_TOKENS = (
    "read",
    "summarize",
    "summary",
    "analyze",
    "analysis",
    "review",
    "interpret",
    "介绍",
    "总结",
    "分析",
    "解读",
)


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web for current topology references and supporting context."
    category = "general"

    def status(self) -> dict[str, Any]:
        provider = self.config.provider or "tavily"
        if provider != "tavily":
            return {"available": False, "status": "unconfigured", "note": f"Provider {provider} is not implemented yet."}
        if not os.getenv("TAVILY_API_KEY"):
            return {
                "available": False,
                "status": "missing_api_key",
                "note": "Set TAVILY_API_KEY to enable live web search.",
            }
        return {"available": True, "status": "ready", "note": "Tavily API key detected."}

    def run(self, *, problem: str, domain_context: str = "") -> dict[str, Any]:
        provider = self.config.provider or "tavily"
        api_key = os.getenv("TAVILY_API_KEY")
        if provider != "tavily" or not api_key:
            return {"status": "skipped", "reason": self.status()["note"], "results": []}

        query = _compact_query(problem, domain_context)
        payload = {
            "api_key": api_key,
            "query": query,
            "max_results": 5,
            "search_depth": "basic",
            "include_answer": False,
        }
        request = urllib.request.Request(
            "https://api.tavily.com/search",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - tool failures should not block research.
            return {"status": "error", "reason": str(exc), "results": []}

        results = []
        for item in data.get("results", [])[:5]:
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", ""),
                }
            )
        return {"status": "ok", "query": query, "results": results}


class TheoremLookupTool(BaseTool):
    name = "theorem_lookup"
    description = "Look up a small local library of standard topology facts relevant to the prompt."
    category = "reference"

    def run(self, *, problem: str, domain_context: str = "") -> dict[str, Any]:
        text = f"{problem}\n{domain_context}".lower()
        matches = []
        for fact in LOCAL_TOPOLOGY_FACTS:
            if any(keyword in text for keyword in fact["keywords"]):
                matches.append({key: fact[key] for key in ("title", "statement", "use")})
        return {"status": "ok" if matches else "no_match", "matches": matches[:8]}


class ArxivSearchTool(BaseTool):
    name = "arxiv_search"
    description = "Search arXiv for math.AT/math.GT papers related to the prompt."
    category = "literature"

    def status(self) -> dict[str, Any]:
        downloader = _preferred_http_downloader()
        downloader_name = Path(downloader).name if downloader else "urllib"
        notes = [f"HTTP downloader: {downloader_name}"]
        if BeautifulSoup is not None:
            notes.append("BeautifulSoup available")
        if PdfReader is not None:
            notes.append("PDF text extraction available")
        return {"available": True, "status": "ready", "note": "; ".join(notes)}

    def run(self, *, problem: str, domain_context: str = "") -> dict[str, Any]:
        parsed = _parse_arxiv_request(problem, domain_context)
        if parsed["paper_ids"]:
            try:
                id_results = _fetch_arxiv_id_results(parsed)
            except Exception as exc:  # noqa: BLE001 - tool failures should not block research.
                return {"status": "error", "reason": str(exc), "results": []}
            id_results = _postprocess_arxiv_results(id_results[: parsed["max_results"]], parsed)
            return {
                "status": "ok",
                "query": parsed["query"],
                "request_type": "id_lookup",
                "source": "arxiv_api",
                "source_url": _arxiv_id_lookup_url(parsed["paper_ids"]),
                "filters": _arxiv_filters(parsed),
                "results": id_results,
            }
        list_error = ""
        if parsed["date"] and parsed["date_mode"] == "announcement":
            try:
                day_results = _fetch_recent_arxiv_day_results(parsed)
            except Exception as exc:  # noqa: BLE001 - fallback below keeps retrieval usable under rate limits.
                day_results = None
                list_error = str(exc)
            if day_results:
                return {
                    "status": "ok",
                    "query": parsed["query"],
                    "request_type": parsed["request_type"],
                    "source": "arxiv_list",
                    "source_url": _arxiv_listing_url(parsed),
                    "filters": {
                        "categories": parsed["categories"],
                        "date": parsed["date"],
                        "date_field": parsed["date_field"],
                        "date_mode": parsed["date_mode"],
                    },
                    "results": _postprocess_arxiv_results(day_results[: parsed["max_results"]], parsed),
                }
            if _should_bridge_to_next_arxiv_announcement(parsed):
                try:
                    bridged_results = _fetch_next_arxiv_announcement_results(parsed)
                except Exception as exc:  # noqa: BLE001 - fallback below keeps retrieval usable under rate limits.
                    bridged_results = None
                    list_error = _join_reasons(list_error, str(exc))
                if bridged_results is not None:
                    return {
                        "status": "ok",
                        "query": parsed["query"],
                        "request_type": parsed["request_type"],
                        "source": "arxiv_list",
                        "source_url": _arxiv_listing_url(parsed),
                        "filters": _arxiv_filters(parsed),
                        "results": _postprocess_arxiv_results(bridged_results[: parsed["max_results"]], parsed),
                    }
            if day_results is not None:
                return {
                    "status": "ok",
                    "query": parsed["query"],
                    "request_type": parsed["request_type"],
                    "source": "arxiv_list",
                    "source_url": _arxiv_listing_url(parsed),
                    "filters": _arxiv_filters(parsed),
                    "results": [],
                }
        elif _should_use_recent_arxiv_list(parsed):
            try:
                recent_results = _fetch_recent_arxiv_results(parsed)
            except Exception as exc:  # noqa: BLE001 - fallback below keeps retrieval usable under rate limits.
                recent_results = None
                list_error = str(exc)
            if recent_results is not None:
                return {
                    "status": "ok",
                    "query": parsed["query"],
                    "request_type": "recent_lookup",
                    "source": "arxiv_list",
                    "source_url": _arxiv_listing_url(parsed),
                    "filters": {
                        "categories": parsed["categories"],
                        "date": parsed["date"],
                        "date_field": parsed["date_field"],
                        "date_mode": parsed["date_mode"],
                    },
                    "results": _postprocess_arxiv_results(recent_results[: parsed["max_results"]], parsed),
                }
        search = _build_arxiv_search_query(parsed)
        params = urllib.parse.urlencode(
            {
                "search_query": search,
                "start": 0,
                "max_results": parsed["max_results"],
                "sortBy": parsed["sort_by"],
                "sortOrder": parsed["sort_order"],
            }
        )
        url = f"https://export.arxiv.org/api/query?{params}"
        try:
            xml_text = _fetch_url_text(url)
        except Exception as exc:  # noqa: BLE001 - tool failures should not block research.
            fallback = _arxiv_retrieval_fallback(parsed, list_error=list_error, api_error=str(exc))
            if fallback is not None:
                return fallback
            return {"status": "error", "reason": str(exc), "results": []}

        results = _parse_arxiv_api_entries(xml_text)
        if parsed["date"] and parsed["date_mode"] == "announcement":
            results = [item for item in results if _iso_prefix(item.get("published", "")) == parsed["date"]]
            if results:
                _store_arxiv_cache(parsed, results)
        results = _postprocess_arxiv_results(results[: parsed["max_results"]], parsed)
        return {
            "status": "ok",
            "query": parsed["query"],
            "request_type": parsed["request_type"],
            "source": "arxiv_api",
            "source_url": url,
            "filters": {
                "categories": parsed["categories"],
                "date": parsed["date"],
                "date_field": parsed["date_field"],
                "date_mode": parsed["date_mode"],
            },
            "results": results,
        }


class HomologyHomotopyTool(BaseTool):
    name = "homology_homotopy"
    description = "Compute basic homology or homotopy data when a supported backend is configured."
    category = "topology_compute"

    def status(self) -> dict[str, Any]:
        backend = self.config.backend or "sage"
        if backend == "sage" and shutil.which("sage"):
            return {"available": True, "status": "ready", "note": "SageMath executable detected."}
        return {"available": False, "status": "missing_backend", "note": f"{backend} backend is not configured."}

    def run(self, *, problem: str, domain_context: str = "") -> dict[str, Any]:
        return {"status": "skipped", "reason": self.status()["note"], "results": []}


class TopologicalInvariantsTool(BaseTool):
    name = "topological_invariants"
    description = "Suggest standard invariant computations such as Betti numbers and Euler characteristic."
    category = "topology_compute"

    def run(self, *, problem: str, domain_context: str = "") -> dict[str, Any]:
        text = f"{problem}\n{domain_context}".lower()
        suggestions = []
        if "sphere" in text or "s^" in text:
            suggestions.append("For S^n, reduced homology is Z in degree n and 0 elsewhere.")
        if "torus" in text or "t^" in text:
            suggestions.append("For T^n, Betti numbers are binomial coefficients C(n,k).")
        if "product" in text or "×" in text or " x " in text:
            suggestions.append("For products, check Kunneth and product formulas for characteristic classes.")
        return {"status": "ok" if suggestions else "no_match", "suggestions": suggestions}


class SympyPointsetTool(BaseTool):
    name = "sympy_pointset"
    description = "Placeholder for symbolic point-set topology checks."
    category = "verification"

    def status(self) -> dict[str, Any]:
        return {"available": False, "status": "not_implemented", "note": "Point-set checker is scaffolded only."}

    def run(self, *, problem: str, domain_context: str = "") -> dict[str, Any]:
        return {"status": "skipped", "reason": self.status()["note"], "results": []}


class TopologyDatabaseTool(BaseTool):
    name = "topology_database"
    description = "Suggest specialist topology database sources such as nLab and Manifold Atlas."
    category = "database"

    def run(self, *, problem: str, domain_context: str = "") -> dict[str, Any]:
        query = urllib.parse.quote_plus(_compact_query(problem, domain_context))
        sources = self.config.sources or ["nlab", "manifold_atlas"]
        links = []
        if "nlab" in sources:
            links.append({"source": "nLab", "url": f"https://ncatlab.org/nlab/search?query={query}"})
        if "manifold_atlas" in sources:
            links.append({"source": "Manifold Atlas", "url": "https://map.mpim-bonn.mpg.de/"})
        if "groupprops" in sources:
            links.append({"source": "GroupProps", "url": "https://groupprops.subwiki.org/"})
        return {"status": "ok", "links": links}


class ProofChainTool(BaseTool):
    name = "proof_chain"
    description = "Draft a theorem-dependency chain from hypotheses to the target."
    category = "reasoning"

    def run(self, *, problem: str, domain_context: str = "") -> dict[str, Any]:
        return {
            "status": "ok",
            "steps": [
                "Identify hypotheses and target invariant.",
                "List standard theorems needed for each reduction.",
                "Mark every non-routine implication as a gap until justified.",
            ],
        }


class ProofVerificationTool(BaseTool):
    name = "proof_verification"
    description = "Placeholder for Lean/Coq/Isabelle proof verification."
    category = "verification"

    def status(self) -> dict[str, Any]:
        backend = self.config.backend or "lean"
        executable = "lake" if backend == "lean" else backend
        if shutil.which(executable):
            return {"available": True, "status": "ready", "note": f"{backend} executable detected."}
        return {"available": False, "status": "missing_backend", "note": f"{backend} backend is not configured."}

    def run(self, *, problem: str, domain_context: str = "") -> dict[str, Any]:
        return {"status": "skipped", "reason": self.status()["note"], "results": []}


LOCAL_TOPOLOGY_FACTS = [
    {
        "keywords": ["so(4)", "spin(4)", "special orthogonal"],
        "title": "Spin(4) decomposition",
        "statement": "Spin(4) is isomorphic as a Lie group to SU(2) x SU(2), hence topologically S^3 x S^3.",
        "use": "For n >= 2, the covering Spin(4) -> SO(4) induces isomorphisms on pi_n.",
    },
    {
        "keywords": ["covering", "cover", "deck", "fiber"],
        "title": "Covering maps and higher homotopy groups",
        "statement": "A covering map p:E->B induces isomorphisms pi_n(E) -> pi_n(B) for n >= 2.",
        "use": "Useful when replacing a connected Lie group by its universal cover.",
    },
    {
        "keywords": ["pi_3", "π3", "homotopy group", "s^3", "sphere"],
        "title": "pi_3 of S^3",
        "statement": "pi_3(S^3) is isomorphic to Z; pi_3(S^3 x S^3) is Z x Z.",
        "use": "Combine with product and covering arguments for Lie groups such as SO(4).",
    },
    {
        "keywords": ["hurewicz", "simply connected"],
        "title": "Hurewicz theorem",
        "statement": "For a simply connected space with first nonzero homotopy in degree n, the Hurewicz map is an isomorphism in degree n.",
        "use": "Common route from homotopy to homology for spheres and highly connected spaces.",
    },
    {
        "keywords": ["poincare duality", "oriented", "closed manifold"],
        "title": "Poincare duality caveat",
        "statement": "Poincare duality for ordinary coefficients requires closed oriented manifolds; otherwise use variants such as twisted or compact-support cohomology.",
        "use": "Audit hidden orientability, compactness, and boundary assumptions.",
    },
    {
        "keywords": ["van kampen", "fundamental group", "union"],
        "title": "Seifert-van Kampen",
        "statement": "The fundamental group of a suitable union is the pushout of fundamental groups over the intersection.",
        "use": "Check path-connectedness and basepoint hypotheses carefully.",
    },
]


def _compact_query(problem: str, domain_context: str) -> str:
    text = " ".join(f"{problem} {domain_context}".split())
    return text[:300]


def _clean_text(text: str) -> str:
    return " ".join(text.split())


def _parse_arxiv_request(problem: str, domain_context: str) -> dict[str, Any]:
    text = " ".join(f"{problem} {domain_context}".split())
    lowered = text.lower()
    paper_ids = _extract_arxiv_ids(text)
    categories = sorted(set(re.findall(r"\b[a-z]+\.[A-Z]{2}\b", text)))
    if not categories:
        categories = sorted(set(re.findall(r"\b[a-z]+\.[a-z]{2}\b", lowered)))
    normalized_categories = [
        category.replace("math.at", "math.AT").replace("math.gt", "math.GT").replace("math.dg", "math.DG")
        for category in categories
    ]
    if not normalized_categories and not paper_ids:
        normalized_categories = ["math.AT", "math.GT", "math.DG"]

    date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    explicit_date = date_match.group(1) if date_match else _resolve_relative_date(lowered)
    wants_links = _contains_any(lowered, ("url", "urls", "link", "links", "链接", "网址", "文章链接", "论文链接"))
    wants_metadata = _contains_any(
        lowered,
        ("metadata", "full metadata", "article list", "paper list", "元数据", "文章列表", "论文列表"),
    )
    wants_inventory = wants_links or wants_metadata or _contains_any(
        lowered,
        ("return", "retrieve", "list", "show", "fetch", "search", "find", "搜索", "检索", "查找", "列出", "返回", "给出"),
    )
    mentions_posted = _contains_any(
        lowered,
        (
            "posted",
            "announcement date",
            "announced",
            "today",
            "today's",
            "new submissions",
            "today on arxiv",
            "发布",
            "公告日",
            "今天",
            "今日",
            "当日",
            "新发表",
            "新文章",
        ),
    )
    explicit_submission_date = _contains_any(
        lowered,
        ("submitteddate", "submission date", "latest submission date", "original submission date"),
    )
    wants_download = _contains_any(lowered, ARXIV_DOWNLOAD_TOKENS)
    wants_read = _contains_any(lowered, ARXIV_READ_TOKENS)
    ground_with_pdf = wants_download or (bool(paper_ids) and wants_read)
    if explicit_date:
        date_mode = "submitted" if explicit_submission_date and not mentions_posted else "announcement"
    else:
        date_mode = "none"
    if paper_ids:
        request_type = "id_lookup"
    elif explicit_date and (wants_inventory or mentions_posted):
        request_type = "structured_lookup"
    else:
        request_type = "semantic_search"
    max_results = max(1, len(paper_ids)) if paper_ids else 50 if explicit_date else 5

    return {
        "query": text,
        "request_type": request_type,
        "paper_ids": paper_ids,
        "categories": normalized_categories,
        "date": explicit_date,
        "date_field": "submittedDate" if explicit_date else None,
        "date_mode": date_mode,
        "max_results": max_results,
        "sort_by": "submittedDate" if explicit_date else "relevance",
        "sort_order": "ascending" if explicit_date else "descending",
        "download_pdfs": ground_with_pdf,
        "download_limit": _configured_arxiv_download_limit(max(2, len(paper_ids)) if paper_ids else 2) if ground_with_pdf else 0,
        "enrich_abs_page": ground_with_pdf or bool(paper_ids),
    }


def _build_arxiv_search_query(parsed: dict[str, Any]) -> str:
    categories = parsed["categories"]
    category_query = "(" + " OR ".join(f"cat:{category}" for category in categories) + ")" if categories else ""
    if parsed["date"]:
        if parsed.get("date_mode") == "announcement":
            start, end = _arxiv_month_bounds(parsed["date"])
        else:
            start, end = _arxiv_day_bounds(parsed["date"])
        if category_query:
            return f"{category_query} AND {parsed['date_field']}:[{start} TO {end}]"
        return f"{parsed['date_field']}:[{start} TO {end}]"
    query = _compact_query(parsed["query"], "")
    if category_query:
        return f'all:"{query}" AND {category_query}'
    return f'all:"{query}"'


def _arxiv_day_bounds(raw_date: str) -> tuple[str, str]:
    day = date.fromisoformat(raw_date)
    next_day = day + timedelta(days=1)
    start = day.strftime("%Y%m%d000000")
    end = next_day.strftime("%Y%m%d000000")
    return start, end


def _arxiv_month_bounds(raw_date: str) -> tuple[str, str]:
    day = date.fromisoformat(raw_date)
    month_start = day.replace(day=1)
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)
    return month_start.strftime("%Y%m%d000000"), next_month.strftime("%Y%m%d000000")


def _resolve_relative_date(text: str) -> str | None:
    today = date.today()
    relative_map = {
        "today": today,
        "today's": today,
        "今天": today,
        "今日": today,
        "本日": today,
        "yesterday": today - timedelta(days=1),
        "昨天": today - timedelta(days=1),
    }
    for token, resolved in relative_map.items():
        if token in text:
            return resolved.isoformat()
    return None


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _extract_arxiv_ids(text: str) -> list[str]:
    ids: list[str] = []
    for match in re.findall(r"(?:arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)", text, re.I):
        normalized = _normalize_arxiv_id(match)
        if normalized and normalized not in ids:
            ids.append(normalized)
    for match in re.findall(r"arxiv\.org\/(?:abs|pdf)\/([^\/\s?#]+?)(?:\.pdf)?(?=[?#\s]|$)", text, re.I):
        normalized = _normalize_arxiv_id(match)
        if normalized and normalized not in ids:
            ids.append(normalized)
    return ids


def _normalize_arxiv_id(value: str) -> str:
    candidate = value.strip()
    if candidate.lower().startswith("arxiv:"):
        candidate = candidate.split(":", 1)[1]
    if candidate.lower().endswith(".pdf"):
        candidate = candidate[:-4]
    return candidate


def _strip_arxiv_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id, flags=re.I)


def _should_use_recent_arxiv_list(parsed: dict[str, Any]) -> bool:
    query = str(parsed.get("query", "")).lower()
    if "arxiv" not in query:
        return False
    if not parsed.get("categories"):
        return False
    return _contains_any(
        query,
        (
            "url",
            "urls",
            "link",
            "links",
            "article",
            "articles",
            "paper",
            "papers",
            "search",
            "find",
            "retrieve",
            "return",
            "list",
            "\u94fe\u63a5",
            "\u6587\u7ae0",
            "\u8bba\u6587",
            "\u641c\u7d22",
            "\u68c0\u7d22",
            "\u67e5\u627e",
            "\u5217\u51fa",
            "\u8fd4\u56de",
        ),
    )


def _fetch_recent_arxiv_day_results(parsed: dict[str, Any]) -> list[dict[str, Any]] | None:
    target = date.fromisoformat(parsed["date"])
    today = date.today()
    if target < today - timedelta(days=7) or target > today:
        return None
    cached = _load_arxiv_cache(parsed)
    if cached is not None:
        return cached

    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for category in parsed["categories"]:
        url = f"https://arxiv.org/list/{category}/pastweek?show=2000"
        html_text = _fetch_url_text(url)
        for item in _extract_arxiv_day_entries_from_list_page(html_text, target.isoformat()):
            item_id = str(item.get("id") or "")
            if not item_id or item_id in seen_ids:
                continue
            item["matched_category"] = category
            results.append(item)
            seen_ids.add(item_id)
    if results:
        _store_arxiv_cache(parsed, results)
    return results


def _should_bridge_to_next_arxiv_announcement(parsed: dict[str, Any]) -> bool:
    if not parsed.get("date") or parsed.get("date_mode") != "announcement":
        return False
    query = str(parsed.get("query", "")).lower()
    if _contains_any(query, ("announcement date", "announced on", "announced exactly", "公告日", "公告日期")):
        return False
    try:
        target = date.fromisoformat(parsed["date"])
    except ValueError:
        return False
    today = date.today()
    return today - timedelta(days=7) <= target <= today


def _fetch_next_arxiv_announcement_results(parsed: dict[str, Any]) -> list[dict[str, Any]] | None:
    cached = _load_arxiv_cache(parsed)
    if cached is not None:
        return cached

    target = date.fromisoformat(parsed["date"])
    today = date.today()
    latest_allowed = min(today, target + timedelta(days=3))
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    matched_announcement_date = ""
    for category in parsed["categories"]:
        url = f"https://arxiv.org/list/{category}/pastweek?show=2000"
        html_text = _fetch_url_text(url)
        dated_entries = _extract_arxiv_entries_by_day_from_list_page(html_text)
        for announcement_date in sorted(dated_entries):
            day = date.fromisoformat(announcement_date)
            if day < target or day > latest_allowed:
                continue
            for item in dated_entries[announcement_date]:
                item_id = str(item.get("id") or "")
                if not item_id or item_id in seen_ids:
                    continue
                item["matched_category"] = category
                item["requested_date"] = parsed["date"]
                item["matched_announcement_date"] = announcement_date
                item["date_match_note"] = (
                    "Requested date has no separate arXiv announcement listing; "
                    f"matched the next available announcement date {announcement_date}."
                )
                results.append(item)
                seen_ids.add(item_id)
            if results and not matched_announcement_date:
                matched_announcement_date = announcement_date
        if results:
            break
    if results:
        _store_arxiv_cache(parsed, results)
    return results


def _fetch_recent_arxiv_results(parsed: dict[str, Any]) -> list[dict[str, Any]] | None:
    cached = _load_arxiv_cache(parsed)
    if cached is not None:
        return cached

    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for category in parsed["categories"]:
        url = f"https://arxiv.org/list/{category}/recent?show=2000"
        html_text = _fetch_url_text(url)
        for item in _extract_arxiv_entries_from_list_page(html_text):
            item_id = str(item.get("id") or "")
            if not item_id or item_id in seen_ids:
                continue
            item["matched_category"] = category
            results.append(item)
            seen_ids.add(item_id)
    if results:
        _store_arxiv_cache(parsed, results)
    return results


def _parse_arxiv_api_entries(xml_text: str) -> list[dict[str, Any]]:
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_text)
    results: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", namespace):
        title = _clean_text(entry.findtext("atom:title", default="", namespaces=namespace))
        summary = _clean_text(entry.findtext("atom:summary", default="", namespaces=namespace))
        url = entry.findtext("atom:id", default="", namespaces=namespace)
        published = entry.findtext("atom:published", default="", namespaces=namespace)
        updated = entry.findtext("atom:updated", default="", namespaces=namespace)
        primary_category = ""
        category_node = entry.find("atom:primary_category", namespace)
        if category_node is not None:
            primary_category = category_node.attrib.get("term", "")
        authors = [
            _clean_text(author.findtext("atom:name", default="", namespaces=namespace))
            for author in entry.findall("atom:author", namespace)
        ]
        arxiv_id = url.rsplit("/", 1)[-1] if url else ""
        results.append(
            {
                "id": arxiv_id,
                "title": title,
                "url": url,
                "abs_url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else url,
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else "",
                "snippet": summary[:600],
                "summary": summary,
                "published": published,
                "updated": updated,
                "primary_category": primary_category,
                "authors": authors,
            }
        )
    return results


def _fetch_arxiv_id_results(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    paper_ids = [paper_id for paper_id in parsed.get("paper_ids", []) if paper_id]
    if not paper_ids:
        return []
    params = urllib.parse.urlencode({"id_list": ",".join(paper_ids), "start": 0, "max_results": len(paper_ids)})
    url = f"https://export.arxiv.org/api/query?{params}"
    xml_text = _fetch_url_text(url)
    fetched = _parse_arxiv_api_entries(xml_text)
    indexed: dict[str, dict[str, Any]] = {}
    for item in fetched:
        item_id = str(item.get("id") or "")
        if not item_id:
            continue
        indexed.setdefault(item_id, item)
        indexed.setdefault(_strip_arxiv_version(item_id), item)

    ordered: list[dict[str, Any]] = []
    for requested_id in paper_ids:
        item = indexed.get(requested_id) or indexed.get(_strip_arxiv_version(requested_id))
        if item is not None:
            ordered.append(dict(item))
            continue
        abs_url = f"https://arxiv.org/abs/{requested_id}"
        ordered.append(
            {
                "id": requested_id,
                "title": requested_id,
                "url": abs_url,
                "abs_url": abs_url,
                "pdf_url": f"https://arxiv.org/pdf/{_strip_arxiv_version(requested_id)}.pdf",
                "snippet": "",
                "summary": "",
                "published": "",
                "updated": "",
                "primary_category": "",
                "authors": [],
            }
        )
    return ordered


def _arxiv_id_lookup_url(paper_ids: list[str]) -> str:
    params = urllib.parse.urlencode({"id_list": ",".join(paper_ids), "start": 0, "max_results": len(paper_ids)})
    return f"https://export.arxiv.org/api/query?{params}"


def _postprocess_arxiv_results(results: list[dict[str, Any]], parsed: dict[str, Any]) -> list[dict[str, Any]]:
    materialized = [dict(item) for item in results if isinstance(item, dict)]
    if not materialized:
        return materialized

    enrich_limit = len(materialized) if parsed.get("paper_ids") else min(len(materialized), max(1, parsed.get("download_limit", 1)))
    if parsed.get("enrich_abs_page"):
        _enrich_arxiv_abs_pages(materialized, enrich_limit)
    if parsed.get("download_pdfs"):
        _download_arxiv_pdfs(materialized, parsed)
    return materialized


def _enrich_arxiv_abs_pages(results: list[dict[str, Any]], limit: int) -> None:
    for item in results[:limit]:
        abs_url = str(item.get("abs_url") or item.get("url") or "")
        if not abs_url:
            continue
        try:
            metadata = _fetch_arxiv_abs_page_metadata(abs_url)
        except Exception as exc:  # noqa: BLE001 - enrichment should never break search.
            item.setdefault("abs_page_error", str(exc))
            continue
        for key in ("title", "published", "pdf_url", "primary_category"):
            if metadata.get(key) and not item.get(key):
                item[key] = metadata[key]
        if metadata.get("authors"):
            item["authors"] = metadata["authors"]
        summary = str(metadata.get("summary") or "")
        if len(summary) > len(str(item.get("summary") or "")):
            item["summary"] = summary
            item["snippet"] = summary[:600]
        if metadata.get("source") and not item.get("metadata_source"):
            item["metadata_source"] = metadata["source"]


def _fetch_arxiv_abs_page_metadata(abs_url: str) -> dict[str, Any]:
    html_text = _fetch_url_text(abs_url, timeout=10)
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html_text, "html.parser")
        title = ""
        title_meta = soup.find("meta", attrs={"name": "citation_title"})
        if title_meta and title_meta.get("content"):
            title = _clean_text(str(title_meta["content"]))
        if not title:
            title_node = soup.select_one("h1.title")
            title = _clean_arxiv_abstract_text(title_node.get_text(" ", strip=True) if title_node else "")

        summary = ""
        abstract_node = soup.select_one("blockquote.abstract")
        if abstract_node:
            summary = _clean_arxiv_abstract_text(abstract_node.get_text(" ", strip=True))

        authors = []
        for author_meta in soup.find_all("meta", attrs={"name": "citation_author"}):
            content = _clean_text(str(author_meta.get("content", "")))
            if content:
                authors.append(content)
        if not authors:
            authors = [_clean_text(node.get_text(" ", strip=True)) for node in soup.select(".authors a")]

        pdf_url = ""
        pdf_meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
        if pdf_meta and pdf_meta.get("content"):
            pdf_url = _clean_text(str(pdf_meta["content"]))

        published = ""
        published_meta = soup.find("meta", attrs={"name": "citation_date"})
        if published_meta and published_meta.get("content"):
            published = _clean_text(str(published_meta["content"]))

        primary_category = ""
        subject_meta = soup.find("meta", attrs={"name": "citation_keywords"})
        if subject_meta and subject_meta.get("content"):
            primary_category = _clean_text(str(subject_meta["content"]))

        return {
            "title": title,
            "summary": summary,
            "authors": authors,
            "pdf_url": pdf_url,
            "published": published,
            "primary_category": primary_category,
            "source": "arxiv_abs_page",
        }

    title_match = re.search(r'<meta name="citation_title" content="([^"]+)"', html_text, re.I)
    pdf_match = re.search(r'<meta name="citation_pdf_url" content="([^"]+)"', html_text, re.I)
    date_match = re.search(r'<meta name="citation_date" content="([^"]+)"', html_text, re.I)
    author_matches = re.findall(r'<meta name="citation_author" content="([^"]+)"', html_text, re.I)
    summary_match = re.search(r"<blockquote class=['\"]abstract[^>]*>(.*?)</blockquote>", html_text, re.S | re.I)
    return {
        "title": _clean_text(unescape(title_match.group(1))) if title_match else "",
        "summary": _clean_arxiv_abstract_text(_clean_html_fragment(summary_match.group(1))) if summary_match else "",
        "authors": [_clean_text(unescape(item)) for item in author_matches],
        "pdf_url": _clean_text(unescape(pdf_match.group(1))) if pdf_match else "",
        "published": _clean_text(unescape(date_match.group(1))) if date_match else "",
        "primary_category": "",
        "source": "arxiv_abs_page",
    }


def _clean_arxiv_abstract_text(text: str) -> str:
    cleaned = _clean_text(text)
    return re.sub(r"^(title|abstract)\s*:\s*", "", cleaned, flags=re.I)


def _configured_arxiv_download_limit(default_value: int) -> int:
    raw_value = os.getenv("GT_ARXIV_MAX_DOWNLOADS")
    if not raw_value:
        return max(1, default_value)
    try:
        parsed = int(raw_value)
    except ValueError:
        return max(1, default_value)
    return max(1, min(parsed, 10))


def _preferred_http_downloader() -> str | None:
    return shutil.which("curl.exe") or shutil.which("curl") or shutil.which("wget")


def _arxiv_download_dir() -> Path:
    configured = os.getenv("GT_ARXIV_DOWNLOAD_DIR")
    if configured:
        return Path(configured)
    return Path.home() / ".cache" / "gt_agent" / "arxiv_papers"


def _download_arxiv_pdfs(results: list[dict[str, Any]], parsed: dict[str, Any]) -> None:
    limit = min(len(results), max(0, int(parsed.get("download_limit") or 0)))
    for item in results[:limit]:
        arxiv_id = str(item.get("id") or "")
        pdf_url = str(item.get("pdf_url") or "")
        if not arxiv_id or not pdf_url:
            continue
        try:
            pdf_path, method = _download_arxiv_pdf(pdf_url, arxiv_id)
            item["local_pdf_path"] = str(pdf_path)
            item["pdf_download_status"] = "ok"
            item["pdf_download_method"] = method
            item["pdf_size_bytes"] = pdf_path.stat().st_size
            preview = _extract_pdf_text_preview(pdf_path)
            if preview:
                item["full_text_preview"] = preview
                item["snippet"] = preview[:600]
                item["grounding_source"] = "local_pdf"
            else:
                item.setdefault("grounding_source", "local_pdf")
        except Exception as exc:  # noqa: BLE001 - download failure should not mask search results.
            item["pdf_download_status"] = "error"
            item["pdf_download_error"] = str(exc)


def _download_arxiv_pdf(pdf_url: str, arxiv_id: str) -> tuple[Path, str]:
    target_dir = _arxiv_download_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", _strip_arxiv_version(arxiv_id))
    destination = target_dir / f"{safe_stem}.pdf"
    if destination.exists() and destination.stat().st_size > 0:
        return destination, "cache"

    temp_path = destination.with_suffix(".pdf.part")
    if temp_path.exists():
        temp_path.unlink()

    downloader = _preferred_http_downloader()
    if downloader:
        downloader_name = Path(downloader).name.lower()
        if "curl" in downloader_name:
            command = [
                downloader,
                "-L",
                "--fail",
                "--retry",
                "2",
                "--retry-delay",
                "1",
                "-A",
                "gt-agent/0.1; local research assistant",
                "-o",
                str(temp_path),
                pdf_url,
            ]
        else:
            command = [
                downloader,
                "-q",
                "--tries=3",
                "--waitretry=1",
                "-U",
                "gt-agent/0.1; local research assistant",
                "-O",
                str(temp_path),
                pdf_url,
            ]
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
        method = downloader_name
    else:
        request = urllib.request.Request(pdf_url, headers={"User-Agent": "gt-agent/0.1; local research assistant"})
        with urllib.request.urlopen(request, timeout=30) as response:
            temp_path.write_bytes(response.read())
        method = "urllib"

    temp_path.replace(destination)
    return destination, method


def _extract_pdf_text_preview(pdf_path: Path, *, max_pages: int = 3, max_chars: int = 4000) -> str:
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(str(pdf_path))
    except Exception:  # noqa: BLE001 - malformed PDF should not break the retrieval path.
        return ""
    chunks: list[str] = []
    total_chars = 0
    for page in reader.pages[:max_pages]:
        try:
            page_text = _clean_text(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - individual page extraction may fail on scanned PDFs.
            continue
        if not page_text:
            continue
        remaining = max_chars - total_chars
        if remaining <= 0:
            break
        snippet = page_text[:remaining]
        chunks.append(snippet)
        total_chars += len(snippet)
    return " ".join(chunks)


def _fetch_url_text(url: str, *, timeout: int = 8, retries: int = 1) -> str:
    headers = {
        "User-Agent": "gt-agent/0.1; local research assistant",
        "Accept": "application/atom+xml,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise
        except Exception as exc:  # noqa: BLE001 - retry transient transport failures once.
            last_error = exc
            if attempt < retries:
                time.sleep(1.2 * (attempt + 1))
                continue
            raise
    raise last_error or RuntimeError("arXiv request failed")


def _arxiv_retrieval_fallback(parsed: dict[str, Any], *, list_error: str = "", api_error: str = "") -> dict[str, Any] | None:
    if parsed.get("date_mode") not in {"announcement", "none"}:
        return None
    cached = _load_arxiv_cache(parsed, allow_stale=True)
    if cached is not None:
        return {
            "status": "ok",
            "query": parsed["query"],
            "request_type": parsed["request_type"],
            "source": "arxiv_cache",
            "source_url": _arxiv_listing_url(parsed),
            "reason": _join_reasons(list_error, api_error),
            "filters": _arxiv_filters(parsed),
            "results": _postprocess_arxiv_results(cached[: parsed["max_results"]], parsed),
        }
    return {
        "status": "rate_limited",
        "query": parsed["query"],
        "request_type": parsed["request_type"],
        "source": "arxiv_list",
        "source_url": _arxiv_listing_url(parsed),
        "reason": _join_reasons(list_error, api_error) or "arXiv temporarily rate-limited live retrieval.",
        "filters": _arxiv_filters(parsed),
        "results": [],
    }


def _arxiv_filters(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_ids": parsed.get("paper_ids", []),
        "categories": parsed["categories"],
        "date": parsed["date"],
        "date_field": parsed["date_field"],
        "date_mode": parsed["date_mode"],
        "download_pdfs": parsed.get("download_pdfs", False),
    }


def _join_reasons(*values: str) -> str:
    parts = [value for value in values if value]
    return " | ".join(parts)


def _arxiv_listing_url(parsed: dict[str, Any]) -> str:
    category = parsed["categories"][0] if parsed.get("categories") else "math.AT"
    raw_date = parsed.get("date")
    if not raw_date:
        return f"https://arxiv.org/list/{category}/recent?show=2000"
    target = date.fromisoformat(raw_date)
    today = date.today()
    if today - timedelta(days=7) <= target <= today:
        return f"https://arxiv.org/list/{category}/pastweek?show=2000"
    return f"https://arxiv.org/list/{category}/{target:%Y-%m}?show=2000"


def _arxiv_cache_path() -> Path:
    configured = os.getenv("GT_ARXIV_CACHE")
    if configured:
        return Path(configured)
    return Path.home() / ".cache" / "gt_agent" / "arxiv_cache.json"


def _arxiv_cache_key(parsed: dict[str, Any]) -> str:
    paper_ids = ",".join(parsed.get("paper_ids") or [])
    categories = ",".join(parsed.get("categories") or [])
    if paper_ids:
        return f"{paper_ids}|{parsed.get('date', '')}|{parsed.get('date_mode', '')}|{categories}"
    return f"{parsed.get('date', '')}|{parsed.get('date_mode', '')}|{categories}"


def _legacy_arxiv_cache_key(parsed: dict[str, Any]) -> str:
    categories = ",".join(parsed.get("categories") or [])
    return f"{parsed.get('date', '')}|{parsed.get('date_mode', '')}|{categories}"


def _load_arxiv_cache(parsed: dict[str, Any], *, allow_stale: bool = False) -> list[dict[str, Any]] | None:
    path = _arxiv_cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    item = None
    if isinstance(data, dict):
        item = data.get(_arxiv_cache_key(parsed))
        if not isinstance(item, dict):
            item = data.get(_legacy_arxiv_cache_key(parsed))
    if not isinstance(item, dict):
        return None
    results = item.get("results")
    if not isinstance(results, list):
        return None
    if allow_stale:
        return [result for result in results if isinstance(result, dict)]
    fetched_at = item.get("fetched_at")
    try:
        fetched = datetime.fromisoformat(str(fetched_at))
    except ValueError:
        return None
    if datetime.now() - fetched > timedelta(minutes=30):
        return None
    return [result for result in results if isinstance(result, dict)]


def _store_arxiv_cache(parsed: dict[str, Any], results: list[dict[str, Any]]) -> None:
    if not results:
        return
    path = _arxiv_cache_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        else:
            data = {}
        data[_arxiv_cache_key(parsed)] = {
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "source_url": _arxiv_listing_url(parsed),
            "results": results,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _extract_arxiv_day_entries_from_list_page(html_text: str, target_date: str) -> list[dict[str, Any]]:
    return _extract_arxiv_entries_by_day_from_list_page(html_text).get(target_date, [])


def _extract_arxiv_entries_by_day_from_list_page(html_text: str) -> dict[str, list[dict[str, Any]]]:
    tokens = re.findall(r"<h3>.*?</h3>|<dt\b.*?</dt>|<dd\b.*?</dd>", html_text, re.S | re.I)
    entries_by_day: dict[str, list[dict[str, Any]]] = {}
    current_date = ""
    pending_dt = ""
    for token in tokens:
        if token.lower().startswith("<h3"):
            heading = _clean_html_fragment(token)
            heading_date = _parse_arxiv_heading_date(heading)
            if heading_date:
                current_date = heading_date
            continue
        if token.lower().startswith("<dt"):
            pending_dt = token
            continue
        if token.lower().startswith("<dd") and pending_dt and current_date:
            entry = _parse_arxiv_html_entry(pending_dt, token, current_date)
            if entry:
                entries_by_day.setdefault(current_date, []).append(entry)
            pending_dt = ""
    return entries_by_day


def _extract_arxiv_entries_from_list_page(html_text: str) -> list[dict[str, Any]]:
    tokens = re.findall(r"<h3>.*?</h3>|<dt\b.*?</dt>|<dd\b.*?</dd>", html_text, re.S | re.I)
    entries: list[dict[str, Any]] = []
    current_date = ""
    pending_dt = ""
    for token in tokens:
        if token.lower().startswith("<h3"):
            heading = _clean_html_fragment(token)
            heading_date = _parse_arxiv_heading_date(heading)
            if heading_date:
                current_date = heading_date
            continue
        if token.lower().startswith("<dt"):
            pending_dt = token
            continue
        if token.lower().startswith("<dd") and pending_dt:
            entry = _parse_arxiv_html_entry(pending_dt, token, current_date)
            if entry:
                entries.append(entry)
            pending_dt = ""
    return entries


def _parse_arxiv_heading_date(text: str) -> str | None:
    match = re.search(
        r"(?:for\s+)?(?:Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)"
        r",?\s+(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})",
        text,
        re.I,
    )
    if not match:
        return None
    day_number = int(match.group(1))
    month_name = match.group(2).lower()
    year = int(match.group(3))
    month_map = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    month = month_map.get(month_name)
    if not month:
        return None
    return date(year, month, day_number).isoformat()


def _parse_arxiv_html_entry(dt_html: str, dd_html: str, published_date: str) -> dict[str, Any] | None:
    id_match = re.search(r'href\s*=\s*"\/abs\/([^"]+)"', dt_html, re.I)
    if not id_match:
        return None
    arxiv_id = id_match.group(1).strip()
    pdf_match = re.search(r'href\s*=\s*"\/pdf\/([^"]+)"', dt_html, re.I)
    cross_match = re.search(r"\((cross-list from [^)]+)\)", dt_html, re.I)
    authors = [_clean_html_fragment(name) for name in re.findall(r"<a [^>]*>(.*?)</a>", _extract_div(dd_html, "list-authors"), re.S | re.I)]
    primary_subject_match = re.search(r'<span class="primary-subject">(.*?)</span>', dd_html, re.S | re.I)
    title = _extract_descriptor_value(_extract_div(dd_html, "list-title"))
    summary = _clean_html_fragment(_extract_paragraph(dd_html))
    subjects = _extract_descriptor_value(_extract_div(dd_html, "list-subjects"))
    return {
        "id": arxiv_id,
        "title": title,
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
        "pdf_url": f"https://arxiv.org/pdf/{pdf_match.group(1).strip()}.pdf" if pdf_match else f"https://arxiv.org/pdf/{arxiv_id}.pdf",
        "snippet": summary[:600],
        "summary": summary,
        "published": published_date,
        "updated": "",
        "primary_category": _clean_html_fragment(primary_subject_match.group(1)) if primary_subject_match else "",
        "authors": authors,
        "subjects": subjects,
        "cross_list_note": _clean_html_fragment(cross_match.group(1)) if cross_match else "",
    }


def _extract_div(html_text: str, class_name: str) -> str:
    match = re.search(rf"<div class=['\"]{re.escape(class_name)}[^>]*>(.*?)</div>", html_text, re.S | re.I)
    return match.group(1) if match else ""


def _extract_paragraph(html_text: str) -> str:
    match = re.search(r"<p class=['\"]mathjax['\"]>(.*?)</p>", html_text, re.S | re.I)
    return match.group(1) if match else ""


def _extract_descriptor_value(html_text: str) -> str:
    cleaned = re.sub(r"<span class=['\"]descriptor['\"]>.*?</span>", "", html_text, flags=re.S | re.I)
    return _clean_html_fragment(cleaned)


def _clean_html_fragment(text: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", text)
    return " ".join(unescape(without_tags).split())


def _iso_prefix(value: str) -> str:
    return value[:10] if len(value) >= 10 else value
