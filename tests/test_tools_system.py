from __future__ import annotations

import json
import urllib.error
import urllib.parse
from datetime import date
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gt_agent.research_service import GTResearchService, ResearchRequest
from gt_agent.tool_config import (
    ToolConfig,
    ToolsConfig,
    default_tools_config,
    load_tools_config,
    save_tools_config,
)
from gt_agent.tools.builtin import ArxivSearchTool, _extract_arxiv_day_entries_from_list_page
from gt_agent.tools.registry import ToolRegistry, run_enabled_tools


class FakeModelClient:
    def __init__(self) -> None:
        self.last_user = ""

    def complete(self, *, system: str, user: str, **kwargs):
        self.last_user = user

        class Response:
            text = "Status: PARTIAL\nTool context consumed."
            finish_reason = "stop"

        return Response()


def test_tools_config_round_trip() -> None:
    with TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "tools_config.yaml"
        config = default_tools_config().with_updates({"web_search": False, "arxiv_search": True})

        save_tools_config(config, path)
        loaded = load_tools_config(path)

        assert loaded.tools["web_search"].enabled is False
        assert loaded.tools["arxiv_search"].enabled is True
        assert loaded.tools["theorem_lookup"].display_name == "Theorem Lookup"


def test_tool_registry_orders_enabled_tools() -> None:
    config = default_tools_config().with_updates(
        {
            "web_search": False,
            "theorem_lookup": True,
            "proof_chain": True,
        }
    )
    registry = ToolRegistry(config)

    active_names = [tool.name for tool in registry.get_active_tools()]

    assert active_names[:2] == ["theorem_lookup", "proof_chain"]
    assert all(item["id"] for item in registry.list_metadata())


def test_enabled_tools_return_promptable_results() -> None:
    config = default_tools_config().with_updates({"web_search": False, "theorem_lookup": True})

    results = run_enabled_tools("Compute pi_3(SO(4)) using Spin(4).", config=config)

    theorem_result = next(item for item in results if item["id"] == "theorem_lookup")
    assert theorem_result["result"]["status"] == "ok"
    assert theorem_result["result"]["matches"]


def test_research_service_injects_tool_context() -> None:
    fake = FakeModelClient()
    config = default_tools_config().with_updates({"web_search": False, "theorem_lookup": True, "arxiv_search": False})
    original_runner = run_enabled_tools

    def fake_runner(problem: str, domain_context: str = "", config_override=None):  # noqa: ANN001
        return original_runner(problem, domain_context, config_override or config)

    service = GTResearchService(client=fake)  # type: ignore[arg-type]

    with patch("gt_agent.research_service.run_enabled_tools", fake_runner):
        response = service.research(
            ResearchRequest(
                problem="Compute pi_3(SO(4)) using Spin(4).",
                domain_context="algebraic topology",
                api_key="test-key",
            )
        )

    assert response.tool_results
    assert "# Tool Context" in fake.last_user
    assert "Spin(4) decomposition" in fake.last_user


def test_arxiv_tool_builds_structured_category_date_query() -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    def fake_urlopen(request, timeout=0):  # noqa: ANN001
        captured["url"] = request.full_url
        return FakeResponse()

    tool = ArxivSearchTool(ToolConfig(enabled=True, display_name="arXiv Search", category="literature"))

    with patch("urllib.request.urlopen", fake_urlopen):
        result = tool.run(
            problem="Retrieve the list of URLs for all articles posted on arXiv under category math.AT with announcement date exactly 2024-06-01.",
        )

    parsed = urllib.parse.urlparse(captured["url"])
    query = urllib.parse.parse_qs(parsed.query)["search_query"][0]
    assert "cat:math.AT" in query
    assert "submittedDate:[20240601000000 TO 20240701000000]" in query
    assert result["status"] == "ok"
    assert result["filters"]["date"] == "2024-06-01"
    assert result["filters"]["date_mode"] == "announcement"


def test_research_service_prefers_direct_arxiv_tool_answer() -> None:
    class FakeClient:
        def complete(self, *, system: str, user: str, **kwargs):  # noqa: ARG002
            raise AssertionError("LLM should not be called for direct arXiv inventory requests")

    class FakeArxivResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'''<?xml version="1.0"?>
            <feed xmlns="http://www.w3.org/2005/Atom">
              <entry>
                <id>http://arxiv.org/abs/2406.00001v1</id>
                <updated>2024-06-01T12:00:00Z</updated>
                <published>2024-06-01T12:00:00Z</published>
                <title>Sample Topology Paper</title>
                <summary>Sample summary.</summary>
                <author><name>Alice</name></author>
                <primary_category term="math.AT" />
              </entry>
            </feed>'''

    def fake_urlopen(request, timeout=0):  # noqa: ANN001, ARG001
        return FakeArxivResponse()

    service = GTResearchService(client=FakeClient())  # type: ignore[arg-type]

    with patch("urllib.request.urlopen", fake_urlopen):
        response = service.research(
            ResearchRequest(
                problem="Return full metadata for all arXiv articles in math.AT on 2024-06-01, including URLs.",
                domain_context="",
                api_key="test-key",
            )
        )

    assert "Sample Topology Paper" in response.answer
    assert "https://arxiv.org/abs/2406.00001v1" in response.answer
    assert response.tool_results


def test_extract_arxiv_day_entries_from_list_page() -> None:
    html = """
    <h3>Mon, 1 Jun 2026 (showing 2 of 2 entries )</h3>
    <dt>
      <a href="/abs/2605.30835" title="Abstract" id="2605.30835">arXiv:2605.30835</a>
      [<a href="/pdf/2605.30835" title="Download PDF">pdf</a>]
    </dt>
    <dd>
      <div class='meta'>
        <div class='list-title mathjax'><span class='descriptor'>Title:</span> The group of homotopy self-equivalences is a Lax functor</div>
        <div class='list-authors'><a href="https://arxiv.org/search/math?searchtype=author&amp;query=Yamaguchi,+T">Toshihiro Yamaguchi</a></div>
        <div class='list-subjects'><span class='descriptor'>Subjects:</span> <span class="primary-subject">Algebraic Topology (math.AT)</span>; Category Theory (math.CT)</div>
        <p class='mathjax'>Sample summary.</p>
      </div>
    </dd>
    <dt>
      <a href="/abs/2605.30558" title="Abstract" id="2605.30558">arXiv:2605.30558</a>
      (cross-list from math-ph)
      [<a href="/pdf/2605.30558" title="Download PDF">pdf</a>]
    </dt>
    <dd>
      <div class='meta'>
        <div class='list-title mathjax'><span class='descriptor'>Title:</span> BV pushforward as a quasi-isomorphism</div>
        <div class='list-authors'><a href="https://arxiv.org/search/math-ph?searchtype=author&amp;query=Cattaneo,+A+S">Alberto S. Cattaneo</a></div>
        <div class='list-subjects'><span class='descriptor'>Subjects:</span> <span class="primary-subject">Mathematical Physics (math-ph)</span>; Algebraic Topology (math.AT)</div>
        <p class='mathjax'>Another summary.</p>
      </div>
    </dd>
    """

    entries = _extract_arxiv_day_entries_from_list_page(html, "2026-06-01")

    assert len(entries) == 2
    assert entries[0]["id"] == "2605.30835"
    assert entries[0]["abs_url"] == "https://arxiv.org/abs/2605.30835"
    assert entries[0]["primary_category"] == "Algebraic Topology (math.AT)"
    assert entries[1]["cross_list_note"] == "cross-list from math-ph"


def test_arxiv_tool_resolves_today_to_announcement_date() -> None:
    class FakeResponse:
        def __init__(self, body: str) -> None:
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return self.body.encode("utf-8")

    html = """
    <h3>Mon, 1 Jun 2026 (showing 1 of 1 entries )</h3>
    <dt>
      <a href="/abs/2605.30835" title="Abstract" id="2605.30835">arXiv:2605.30835</a>
      [<a href="/pdf/2605.30835" title="Download PDF">pdf</a>]
    </dt>
    <dd>
      <div class='meta'>
        <div class='list-title mathjax'><span class='descriptor'>Title:</span> The group of homotopy self-equivalences is a Lax functor</div>
        <div class='list-authors'><a href="#">Toshihiro Yamaguchi</a></div>
        <div class='list-subjects'><span class='descriptor'>Subjects:</span> <span class="primary-subject">Algebraic Topology (math.AT)</span></div>
        <p class='mathjax'>Sample summary.</p>
      </div>
    </dd>
    """

    def fake_urlopen(request, timeout=0):  # noqa: ANN001, ARG001
        return FakeResponse(html)

    tool = ArxivSearchTool(ToolConfig(enabled=True, display_name="arXiv Search", category="literature"))

    with patch("gt_agent.tools.builtin.date") as fake_date:
        fake_date.today.return_value = date(2026, 6, 1)
        fake_date.fromisoformat.side_effect = lambda raw: date.fromisoformat(raw)
        fake_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
        with patch("urllib.request.urlopen", fake_urlopen):
            result = tool.run(problem="Search arXiv for articles in math.AT announced today and return the links.")

    assert result["source"] == "arxiv_list"
    assert result["filters"]["date"] == "2026-06-01"
    assert result["results"][0]["abs_url"] == "https://arxiv.org/abs/2605.30835"


def test_arxiv_tool_bridges_weekend_request_to_next_announcement_date() -> None:
    class FakeResponse:
        def __init__(self, body: str) -> None:
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return self.body.encode("utf-8")

    html = """
    <h3>Mon, 1 Jun 2026 (showing 3 of 3 entries )</h3>
    <dt>
      <a href="/abs/2605.30835" title="Abstract" id="2605.30835">arXiv:2605.30835</a>
      [<a href="/pdf/2605.30835" title="Download PDF">pdf</a>]
    </dt>
    <dd>
      <div class='meta'>
        <div class='list-title mathjax'><span class='descriptor'>Title:</span> The group of homotopy self-equivalences is a Lax functor</div>
        <div class='list-authors'><a href="#">Toshihiro Yamaguchi</a></div>
        <div class='list-subjects'><span class='descriptor'>Subjects:</span> <span class="primary-subject">Algebraic Topology (math.AT)</span></div>
        <p class='mathjax'>Sample summary.</p>
      </div>
    </dd>
    <dt>
      <a href="/abs/2605.31128" title="Abstract" id="2605.31128">arXiv:2605.31128</a>
      (cross-list from math.RT)
      [<a href="/pdf/2605.31128" title="Download PDF">pdf</a>]
    </dt>
    <dd>
      <div class='meta'>
        <div class='list-title mathjax'><span class='descriptor'>Title:</span> The classification of integral endotrivial complexes</div>
        <div class='list-authors'><a href="#">Juan Omar Gomez</a></div>
        <div class='list-subjects'><span class='descriptor'>Subjects:</span> Algebraic Topology (math.AT)</div>
        <p class='mathjax'>Another summary.</p>
      </div>
    </dd>
    """

    def fake_urlopen(request, timeout=0):  # noqa: ANN001, ARG001
        return FakeResponse(html)

    tool = ArxivSearchTool(ToolConfig(enabled=True, display_name="arXiv Search", category="literature"))

    with TemporaryDirectory() as temp_dir:
        with patch.dict("os.environ", {"GT_ARXIV_CACHE": str(Path(temp_dir) / "arxiv_cache.json")}):
            with patch("gt_agent.tools.builtin.date") as fake_date:
                fake_date.today.return_value = date(2026, 6, 1)
                fake_date.fromisoformat.side_effect = lambda raw: date.fromisoformat(raw)
                fake_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                with patch("urllib.request.urlopen", fake_urlopen):
                    result = tool.run(problem="search for the arxiv paper of math.AT of 2026-05-31 and return links")

    assert result["source"] == "arxiv_list"
    assert result["filters"]["date"] == "2026-05-31"
    assert len(result["results"]) == 2
    assert result["results"][0]["matched_announcement_date"] == "2026-06-01"
    assert result["results"][0]["abs_url"] == "https://arxiv.org/abs/2605.30835"


def test_arxiv_tool_uses_cache_when_rate_limited() -> None:
    tool = ArxivSearchTool(ToolConfig(enabled=True, display_name="arXiv Search", category="literature"))

    with TemporaryDirectory() as temp_dir:
        cache_path = Path(temp_dir) / "arxiv_cache.json"
        cache_path.write_text(
            json.dumps(
                {
                    "2026-06-01|announcement|math.AT": {
                        "fetched_at": "2026-06-01T12:00:00",
                        "source_url": "https://arxiv.org/list/math.AT/pastweek?show=2000",
                        "results": [
                            {
                                "id": "2605.30835",
                                "title": "Cached paper",
                                "abs_url": "https://arxiv.org/abs/2605.30835",
                                "url": "https://arxiv.org/abs/2605.30835",
                            }
                        ],
                    }
                }
            ),
            encoding="utf-8",
        )

        with patch.dict("os.environ", {"GT_ARXIV_CACHE": str(cache_path)}):
            with patch("gt_agent.tools.builtin.datetime") as fake_datetime:
                fake_datetime.now.return_value = date(2026, 6, 1)
                fake_datetime.fromisoformat.return_value = date(2026, 6, 1)
                with patch("gt_agent.tools.builtin.date") as fake_date:
                    fake_date.today.return_value = date(2026, 6, 1)
                    fake_date.fromisoformat.side_effect = lambda raw: date.fromisoformat(raw)
                    fake_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                    result = tool.run(problem="Search arXiv for articles in math.AT announced today and return links.")

    assert result["status"] == "ok"
    assert result["source"] == "arxiv_list"
    assert result["results"][0]["abs_url"] == "https://arxiv.org/abs/2605.30835"


def test_arxiv_rate_limit_returns_source_url_not_tool_error() -> None:
    def fake_urlopen(request, timeout=0):  # noqa: ANN001, ARG001
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "Unknown Error",
            {},
            BytesIO(b"rate limited"),
        )

    tool = ArxivSearchTool(ToolConfig(enabled=True, display_name="arXiv Search", category="literature"))

    with TemporaryDirectory() as temp_dir:
        with patch.dict("os.environ", {"GT_ARXIV_CACHE": str(Path(temp_dir) / "missing.json")}):
            with patch("gt_agent.tools.builtin.date") as fake_date:
                fake_date.today.return_value = date(2026, 6, 1)
                fake_date.fromisoformat.side_effect = lambda raw: date.fromisoformat(raw)
                fake_date.side_effect = lambda *args, **kwargs: date(*args, **kwargs)
                with patch("urllib.request.urlopen", fake_urlopen):
                    result = tool.run(problem="Search arXiv for articles in math.AT announced today and return links.")

    assert result["status"] == "rate_limited"
    assert result["source_url"] == "https://arxiv.org/list/math.AT/pastweek?show=2000"
    assert result["results"] == []
