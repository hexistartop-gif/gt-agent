from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelConfig:
    provider: str = "openai-compatible"
    model: str = "gpt-4.1"
    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    temperature: float = 0.2
    max_tokens: int = 4096

    @classmethod
    def from_env(cls) -> "ModelConfig":
        return cls(
            provider=os.getenv("GT_MODEL_PROVIDER", "openai-compatible"),
            model=os.getenv("GT_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1")),
            base_url=os.getenv("GT_MODEL_BASE_URL", os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")),
            api_key=os.getenv("GT_MODEL_API_KEY", os.getenv("OPENAI_API_KEY")),
            temperature=float(os.getenv("GT_MODEL_TEMPERATURE", "0.2")),
            max_tokens=int(os.getenv("GT_MODEL_MAX_TOKENS", "4096")),
        )


@dataclass(frozen=True)
class ModelResponse:
    text: str
    raw: dict[str, Any]


class ModelClientError(RuntimeError):
    pass


class OpenAICompatibleClient:
    """Tiny OpenAI-compatible chat-completions client.

    It works with OpenAI and many local/proxy providers exposing
    ``POST /chat/completions``.
    """

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or ModelConfig.from_env()

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> ModelResponse:
        key = api_key or self.config.api_key
        if not key:
            raise ModelClientError("missing API key; set GT_MODEL_API_KEY/OPENAI_API_KEY or submit one in the UI")

        url = _chat_completions_url(base_url or self.config.base_url)
        payload = {
            "model": model or self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_tokens if max_tokens is None else max_tokens,
        }

        try:
            raw = self._post_chat_completion(url=url, key=key, payload=payload)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 400 and "temperature" in body.lower() and "deprecated" in body.lower():
                payload_without_temperature = dict(payload)
                payload_without_temperature.pop("temperature", None)
                try:
                    raw = self._post_chat_completion(url=url, key=key, payload=payload_without_temperature)
                except urllib.error.HTTPError as retry_exc:
                    retry_body = retry_exc.read().decode("utf-8", errors="replace")
                    raise ModelClientError(f"model API HTTP {retry_exc.code}: {retry_body}") from retry_exc
                except urllib.error.URLError as retry_exc:
                    raise ModelClientError(_format_url_error(url, retry_exc)) from retry_exc
            else:
                raise ModelClientError(f"model API HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise ModelClientError(_format_url_error(url, exc)) from exc

        try:
            text = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelClientError("model API returned an unexpected response shape") from exc
        return ModelResponse(text=text, raw=raw)

    def _post_chat_completion(self, *, url: str, key: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))


def _join_url(base_url: str, suffix: str) -> str:
    return base_url.rstrip("/") + "/" + suffix.lstrip("/")


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.strip()
    if not normalized:
        raise ModelClientError("missing base URL; set GT_MODEL_BASE_URL/OPENAI_BASE_URL or submit one in the UI")

    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ModelClientError("invalid base URL; use a full http(s) URL such as https://api.openai.com/v1")

    if parsed.path.rstrip("/").endswith("/chat/completions"):
        return normalized.rstrip("/")
    return _join_url(normalized, "/chat/completions")


def _format_url_error(url: str, exc: urllib.error.URLError) -> str:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "unknown-host"
    port = f":{parsed.port}" if parsed.port else ""
    reason = exc.reason
    reason_text = str(reason)
    hints: list[str] = []

    if _is_refused(reason):
        hints.append(
            "the target refused the connection; make sure the model/API service is running on that host and port"
        )
    if host in {"127.0.0.1", "localhost", "::1"}:
        hints.append(
            "localhost/127.0.0.1 means this computer; on another device use the API server's LAN IP and allow the port through the firewall"
        )
    if parsed.scheme == "http":
        hints.append("if this is a cloud provider, confirm whether the base URL should use https")

    hint_text = f" Hint: {'; '.join(hints)}." if hints else ""
    return f"model API connection failed while connecting to {host}{port}: {reason_text}.{hint_text}"


def _is_refused(reason: object) -> bool:
    if isinstance(reason, ConnectionRefusedError):
        return True
    text = str(reason).lower()
    return "10061" in text or "connection refused" in text or "actively refused" in text
