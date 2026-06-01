from __future__ import annotations

from typing import Any

from gt_agent.tool_config import ToolsConfig, load_tools_config

from .base import BaseTool
from .builtin import (
    ArxivSearchTool,
    HomologyHomotopyTool,
    ProofChainTool,
    ProofVerificationTool,
    SympyPointsetTool,
    TheoremLookupTool,
    TopologicalInvariantsTool,
    TopologyDatabaseTool,
    WebSearchTool,
)


TOOL_CLASSES: dict[str, type[BaseTool]] = {
    "web_search": WebSearchTool,
    "theorem_lookup": TheoremLookupTool,
    "arxiv_search": ArxivSearchTool,
    "homology_homotopy": HomologyHomotopyTool,
    "topological_invariants": TopologicalInvariantsTool,
    "sympy_pointset": SympyPointsetTool,
    "topology_database": TopologyDatabaseTool,
    "proof_chain": ProofChainTool,
    "proof_verification": ProofVerificationTool,
}


class ToolRegistry:
    def __init__(self, config: ToolsConfig | None = None) -> None:
        self.config = config or load_tools_config()

    def get_all_tools(self) -> list[BaseTool]:
        tools = []
        for tool_id, cfg in self.config.tools.items():
            tool_cls = TOOL_CLASSES.get(tool_id)
            if tool_cls:
                tools.append(tool_cls(cfg))
        return sorted(tools, key=lambda tool: (tool.config.priority, tool.name))

    def get_active_tools(self) -> list[BaseTool]:
        return [tool for tool in self.get_all_tools() if tool.config.enabled]

    def get_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_schema() for tool in self.get_active_tools()]

    def list_metadata(self) -> list[dict[str, Any]]:
        return [tool.metadata() for tool in self.get_all_tools()]


def run_enabled_tools(problem: str, domain_context: str = "", config: ToolsConfig | None = None) -> list[dict[str, Any]]:
    registry = ToolRegistry(config)
    results = []
    for tool in registry.get_active_tools():
        try:
            result = tool.run(problem=problem, domain_context=domain_context)
        except Exception as exc:  # noqa: BLE001 - tool failures should never block the main answer.
            result = {"status": "error", "reason": str(exc)}
        results.append(
            {
                "id": tool.name,
                "display_name": tool.config.display_name,
                "category": tool.config.category,
                "result": result,
            }
        )
    return results
