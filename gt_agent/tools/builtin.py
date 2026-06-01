from __future__ import annotations

import json
import os
import re
import shutil
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

    def run(self, *, problem: str, domain_context: str = "") -> dict[str, Any]:
        parsed = _parse_arxiv_request(problem, domain_context)
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
                    "results": day_results[: parsed["max_results"]],
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
                        "results": bridged_results[: parsed["max_results"]],
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
                    "results": recent_results[: parsed["max_results"]],
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

        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml_text)
        results = []
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
        if parsed["date"] and parsed["date_mode"] == "announcement":
            results = [item for item in results if _iso_prefix(item.get("published", "")) == parsed["date"]]
            if results:
                _store_arxiv_cache(parsed, results)
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
            "results": results[: parsed["max_results"]],
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
    categories = sorted(set(re.findall(r"\b[a-z]+\.[A-Z]{2}\b", text)))
    if not categories:
        categories = sorted(set(re.findall(r"\b[a-z]+\.[a-z]{2}\b", lowered)))
    normalized_categories = [
        category.replace("math.at", "math.AT").replace("math.gt", "math.GT").replace("math.dg", "math.DG")
        for category in categories
    ]
    if not normalized_categories:
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
    if explicit_date:
        date_mode = "submitted" if explicit_submission_date and not mentions_posted else "announcement"
    else:
        date_mode = "none"
    request_type = "structured_lookup" if explicit_date and (wants_inventory or mentions_posted) else "semantic_search"

    return {
        "query": text,
        "request_type": request_type,
        "categories": normalized_categories,
        "date": explicit_date,
        "date_field": "submittedDate" if explicit_date else None,
        "date_mode": date_mode,
        "max_results": 50 if explicit_date else 5,
        "sort_by": "submittedDate" if explicit_date else "relevance",
        "sort_order": "ascending" if explicit_date else "descending",
    }


def _build_arxiv_search_query(parsed: dict[str, Any]) -> str:
    categories = parsed["categories"]
    category_query = "(" + " OR ".join(f"cat:{category}" for category in categories) + ")"
    if parsed["date"]:
        if parsed.get("date_mode") == "announcement":
            start, end = _arxiv_month_bounds(parsed["date"])
        else:
            start, end = _arxiv_day_bounds(parsed["date"])
        return f"{category_query} AND {parsed['date_field']}:[{start} TO {end}]"
    query = _compact_query(parsed["query"], "")
    return f'all:"{query}" AND {category_query}'


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
            "results": cached[: parsed["max_results"]],
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
        "categories": parsed["categories"],
        "date": parsed["date"],
        "date_field": parsed["date_field"],
        "date_mode": parsed["date_mode"],
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
    item = data.get(_arxiv_cache_key(parsed)) if isinstance(data, dict) else None
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
