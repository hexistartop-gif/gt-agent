from __future__ import annotations

import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOOLS_CONFIG_PATH = PROJECT_ROOT / "config" / "tools_config.yaml"


@dataclass(frozen=True)
class ToolConfig:
    enabled: bool = False
    display_name: str = ""
    category: str = "general"
    priority: int = 100
    provider: str | None = None
    backend: str | None = None
    sources: list[str] | None = None
    semantic: bool | None = None


@dataclass(frozen=True)
class ToolsConfig:
    tools: dict[str, ToolConfig]

    def with_updates(self, updates: dict[str, bool]) -> "ToolsConfig":
        changed = dict(self.tools)
        for tool_id, enabled in updates.items():
            if tool_id in changed:
                changed[tool_id] = replace(changed[tool_id], enabled=bool(enabled))
        return ToolsConfig(changed)


DEFAULT_TOOL_CONFIGS: dict[str, ToolConfig] = {
    "web_search": ToolConfig(
        enabled=True,
        display_name="Web Search",
        category="general",
        provider="tavily",
        priority=0,
    ),
    "theorem_lookup": ToolConfig(
        enabled=True,
        display_name="Theorem Lookup",
        category="reference",
        priority=10,
    ),
    "arxiv_search": ToolConfig(
        enabled=False,
        display_name="arXiv Search",
        category="literature",
        semantic=False,
        priority=20,
    ),
    "homology_homotopy": ToolConfig(
        enabled=False,
        display_name="Homology / Homotopy",
        category="topology_compute",
        backend="sage",
        priority=30,
    ),
    "topological_invariants": ToolConfig(
        enabled=False,
        display_name="Topological Invariants",
        category="topology_compute",
        priority=40,
    ),
    "sympy_pointset": ToolConfig(
        enabled=False,
        display_name="SymPy Point-Set Checks",
        category="verification",
        priority=50,
    ),
    "topology_database": ToolConfig(
        enabled=False,
        display_name="Topology Databases",
        category="database",
        sources=["manifold_atlas", "nlab", "groupprops"],
        priority=60,
    ),
    "proof_chain": ToolConfig(
        enabled=False,
        display_name="Proof Chain",
        category="reasoning",
        priority=70,
    ),
    "proof_verification": ToolConfig(
        enabled=False,
        display_name="Proof Verification",
        category="verification",
        backend="lean",
        priority=80,
    ),
}


def tools_config_path() -> Path:
    configured = os.getenv("GT_TOOLS_CONFIG")
    return Path(configured) if configured else DEFAULT_TOOLS_CONFIG_PATH


def default_tools_config() -> ToolsConfig:
    return ToolsConfig(dict(DEFAULT_TOOL_CONFIGS))


def load_tools_config(path: Path | None = None) -> ToolsConfig:
    target = path or tools_config_path()
    if not target.exists():
        config = default_tools_config()
        save_tools_config(config, target)
        return config

    parsed = _parse_simple_yaml(target.read_text(encoding="utf-8"))
    raw_tools = parsed.get("tools", {})
    tools = dict(DEFAULT_TOOL_CONFIGS)
    if isinstance(raw_tools, dict):
        for tool_id, raw_cfg in raw_tools.items():
            if isinstance(raw_cfg, dict):
                base = tools.get(str(tool_id), ToolConfig())
                tools[str(tool_id)] = _merge_tool_config(base, raw_cfg)
    return ToolsConfig(tools)


def save_tools_config(config: ToolsConfig, path: Path | None = None) -> None:
    target = path or tools_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_render_simple_yaml(config), encoding="utf-8")


def reset_tools_config(path: Path | None = None) -> ToolsConfig:
    config = default_tools_config()
    save_tools_config(config, path)
    return config


def serialize_tools_config(config: ToolsConfig) -> dict[str, Any]:
    return {"tools": {tool_id: asdict(tool) for tool_id, tool in config.tools.items()}}


def _merge_tool_config(base: ToolConfig, raw: dict[str, Any]) -> ToolConfig:
    values = asdict(base)
    for key in values:
        if key in raw:
            values[key] = raw[key]
    if values.get("sources") is not None:
        values["sources"] = [str(source) for source in values["sources"]]
    return ToolConfig(**values)


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_tool: str | None = None
    current_list_key: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line == "tools:":
            data["tools"] = {}
            current_tool = None
            current_list_key = None
            continue
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            current_tool = line.strip()[:-1]
            data.setdefault("tools", {})[current_tool] = {}
            current_list_key = None
            continue
        if current_tool and line.startswith("    ") and not line.startswith("      "):
            key, _, raw_value = line.strip().partition(":")
            value = raw_value.strip()
            if not value:
                data["tools"][current_tool][key] = []
                current_list_key = key
            else:
                data["tools"][current_tool][key] = _parse_scalar(value)
                current_list_key = None
            continue
        if current_tool and current_list_key and line.startswith("      - "):
            data["tools"][current_tool][current_list_key].append(_parse_scalar(line.strip()[2:].strip()))

    return data


def _parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def _render_simple_yaml(config: ToolsConfig) -> str:
    lines = ["tools:"]
    for tool_id, cfg in sorted(config.tools.items(), key=lambda item: (item[1].priority, item[0])):
        values = asdict(cfg)
        lines.append(f"  {tool_id}:")
        for key in ("enabled", "display_name", "category", "provider", "backend", "sources", "semantic", "priority"):
            value = values[key]
            if value is None:
                continue
            if isinstance(value, list):
                lines.append(f"    {key}:")
                for item in value:
                    lines.append(f"      - {_format_scalar(item)}")
            else:
                lines.append(f"    {key}: {_format_scalar(value)}")
    return "\n".join(lines) + "\n"


def _format_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value).replace('"', '\\"')
    return f'"{text}"'
