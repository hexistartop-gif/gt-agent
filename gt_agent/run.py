from __future__ import annotations

import argparse
import json
from pathlib import Path

from .controller import GTAgent
from .schemas import GTProblem


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run GT Agent on a Lean sketch or GT context file.")
    parser.add_argument("--problem", required=True, help="Path to a .lean, .md, or .txt problem file.")
    parser.add_argument("--mode", choices=["basic", "evolution"], default="basic")
    parser.add_argument("--context", help="Optional gt_context.md path.")
    parser.add_argument("--output-root", default="gt_agent_runs")
    args = parser.parse_args(argv)

    problem_path = Path(args.problem)
    if not problem_path.exists():
        parser.error(f"problem file does not exist: {problem_path}")

    problem = GTProblem.from_path(problem_path, mode=args.mode, context_path=args.context)
    agent = GTAgent(output_root=args.output_root)
    result = agent.run(problem)
    print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
