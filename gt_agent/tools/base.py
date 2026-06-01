from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from gt_agent.tool_config import ToolConfig


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    category: str = "general"

    def __init__(self, config: ToolConfig) -> None:
        self.config = config

    @abstractmethod
    def run(self, *, problem: str, domain_context: str = "") -> dict[str, Any]:
        """Run a tool and return structured data suitable for prompt injection."""

    def status(self) -> dict[str, Any]:
        return {
            "available": True,
            "status": "ready",
            "note": "",
        }

    def to_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "parameters": {
                "type": "object",
                "properties": {
                    "problem": {"type": "string"},
                    "domain_context": {"type": "string"},
                },
                "required": ["problem"],
            },
        }

    def metadata(self) -> dict[str, Any]:
        return {
            "id": self.name,
            "display_name": self.config.display_name,
            "description": self.description,
            "category": self.config.category or self.category,
            "enabled": self.config.enabled,
            "priority": self.config.priority,
            "provider": self.config.provider,
            "backend": self.config.backend,
            "sources": self.config.sources,
            "semantic": self.config.semantic,
            **self.status(),
        }
