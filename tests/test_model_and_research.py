from __future__ import annotations

import io
import json
import urllib.error

from gt_agent.model_client import ModelClientError, ModelConfig, OpenAICompatibleClient
from gt_agent.research_service import GTResearchService, ResearchRequest


class FakeModelClient:
    def __init__(self) -> None:
        self.last_user = ""

    def complete(self, *, system: str, user: str, **kwargs):
        self.last_user = user

        class Response:
            text = "Status: PARTIAL\nGap ledger recorded.\nNext executable steps: formalize a local lemma."

        return Response()


class TruncatingFakeModelClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(self, *, system: str, user: str, **kwargs):
        self.calls.append(user)

        class Response:
            def __init__(self, text: str, finish_reason: str) -> None:
                self.text = text
                self.finish_reason = finish_reason

        if len(self.calls) == 1:
            return Response("Status: PARTIAL\nProof starts for all \\(n \\", "length")
        return Response("\\ge 2\\).\nNext executable steps: done.", "stop")


def test_model_client_requires_api_key() -> None:
    client = OpenAICompatibleClient(ModelConfig(api_key=None))

    try:
        client.complete(system="s", user="u")
    except ModelClientError as exc:
        assert "missing API key" in str(exc)
    else:
        raise AssertionError("expected missing API key failure")


def test_model_client_retries_without_deprecated_temperature() -> None:
    class Client(OpenAICompatibleClient):
        def __init__(self) -> None:
            super().__init__(ModelConfig(api_key="test-key"))
            self.payloads: list[dict] = []

        def _post_chat_completion(self, *, url: str, key: str, payload: dict):
            self.payloads.append(payload)
            if len(self.payloads) == 1:
                body = json.dumps({"error": {"message": "`temperature` is deprecated for this model."}}).encode()
                raise urllib.error.HTTPError(url, 400, "Bad Request", {}, io.BytesIO(body))
            return {"choices": [{"message": {"content": "ok"}}]}

    client = Client()
    response = client.complete(system="s", user="u", temperature=0.2)

    assert response.text == "ok"
    assert "temperature" in client.payloads[0]
    assert "temperature" not in client.payloads[1]


def test_model_client_records_finish_reason() -> None:
    class Client(OpenAICompatibleClient):
        def __init__(self) -> None:
            super().__init__(ModelConfig(api_key="test-key"))

        def _post_chat_completion(self, *, url: str, key: str, payload: dict):
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "length"}]}

    client = Client()
    response = client.complete(system="s", user="u")

    assert response.text == "ok"
    assert response.finish_reason == "length"


def test_model_client_accepts_full_chat_completions_url() -> None:
    class Client(OpenAICompatibleClient):
        def __init__(self) -> None:
            super().__init__(ModelConfig(api_key="test-key"))
            self.url = ""

        def _post_chat_completion(self, *, url: str, key: str, payload: dict):
            self.url = url
            return {"choices": [{"message": {"content": "ok"}}]}

    client = Client()
    response = client.complete(
        system="s",
        user="u",
        base_url="https://example.test/v1/chat/completions",
    )

    assert response.text == "ok"
    assert client.url == "https://example.test/v1/chat/completions"


def test_model_client_reports_localhost_connection_hint() -> None:
    class Client(OpenAICompatibleClient):
        def _post_chat_completion(self, *, url: str, key: str, payload: dict):
            raise urllib.error.URLError(ConnectionRefusedError(10061, "actively refused"))

    client = Client(ModelConfig(api_key="test-key", base_url="http://127.0.0.1:1234/v1"))

    try:
        client.complete(system="s", user="u")
    except ModelClientError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected connection failure")

    assert "127.0.0.1:1234" in message
    assert "localhost/127.0.0.1 means this computer" in message


def test_research_service_wraps_problem_with_gt_audit() -> None:
    fake = FakeModelClient()
    service = GTResearchService(client=fake)  # type: ignore[arg-type]

    response = service.research(
        ResearchRequest(
            problem="Prove a statement about compact oriented smooth manifolds.",
            domain_context="differential topology",
            api_key="test-key",
        )
    )

    assert response.status == "PARTIAL"
    assert "Gap ledger recorded" in response.answer
    assert "# GT Gap Ledger" in fake.last_user
    assert "Geometry/topology assumption audit" in fake.last_user


def test_research_service_continues_truncated_model_output() -> None:
    fake = TruncatingFakeModelClient()
    service = GTResearchService(client=fake)  # type: ignore[arg-type]

    response = service.research(
        ResearchRequest(
            problem="Compute a homotopy group.",
            domain_context="algebraic topology",
            api_key="test-key",
            max_tokens=1024,
        )
    )

    assert len(fake.calls) == 2
    assert response.answer.endswith("\\ge 2\\).\nNext executable steps: done.")
    assert response.continuation_count == 1
    assert response.finish_reason == "stop"
    assert response.truncated is False
    assert any("automatic continuation" in warning for warning in response.warnings)


def test_research_service_uses_search_mode_for_bibliographic_request() -> None:
    fake = FakeModelClient()
    service = GTResearchService(client=fake)  # type: ignore[arg-type]

    response = service.research(
        ResearchRequest(
            problem="Search arXiv for papers in math.AT and return the links.",
            domain_context="",
            api_key="test-key",
        )
    )

    assert response.status in {"COMPLETED", "PARTIAL"}
    assert "Retrieval assumption audit" in response.assumption_audit
    assert "proof-audit task" in response.assumption_audit
    assert "No proof-gap analysis is required" in response.gap_ledger
