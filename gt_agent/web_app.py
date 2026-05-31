from __future__ import annotations

import argparse
import json
import mimetypes
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .model_client import ModelConfig
from .research_service import GTResearchService, ResearchRequest

WEB_ROOT = Path(__file__).resolve().parent / "web"


class GTWebHandler(BaseHTTPRequestHandler):
    service = GTResearchService()

    def do_GET(self) -> None:
        if self.path == "/api/config":
            config = ModelConfig.from_env()
            self._send_json(
                {
                    "provider": config.provider,
                    "model": config.model,
                    "base_url": config.base_url,
                    "temperature": config.temperature,
                    "max_tokens": config.max_tokens,
                    "has_api_key": bool(config.api_key),
                }
            )
            return
        if self.path in {"/", "/index.html"}:
            self._send_file(WEB_ROOT / "index.html")
            return
        if self.path.startswith("/static/"):
            rel = self.path.removeprefix("/static/").split("?", 1)[0]
            self._send_file(WEB_ROOT / rel)
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if self.path != "/api/research":
            self._send_json({"error": "not found"}, status=404)
            return
        try:
            payload = self._read_json()
            config = ModelConfig.from_env()
            request = ResearchRequest(
                problem=_text(payload.get("problem")),
                domain_context=_text(payload.get("domain_context")),
                mode=_text(payload.get("mode")) or "plan",
                model=_text(payload.get("model")) or config.model,
                base_url=_text(payload.get("base_url")) or config.base_url,
                api_key=_text(payload.get("api_key")) or config.api_key,
                temperature=float(payload.get("temperature", config.temperature)),
            )
            if not request.problem:
                self._send_json({"error": "problem is required"}, status=400)
                return
            response = self.service.research(request)
            self._send_json(response.to_dict())
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, status=400)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw or "{}")
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file() or WEB_ROOT not in path.resolve().parents:
            self._send_json({"error": "not found"}, status=404)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), GTWebHandler)
    for url in _display_urls(host, port):
        print(f"GT Agent UI running at {url}", flush=True)
    server.serve_forever()
    return server


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _display_urls(host: str, port: int) -> list[str]:
    if host in {"0.0.0.0", ""}:
        urls = [f"http://127.0.0.1:{port}"]
        lan_ip = _get_lan_ip()
        if lan_ip:
            urls.append(f"http://{lan_ip}:{port}")
        return urls
    return [f"http://{host}:{port}"]


def _get_lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the GT Agent web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
