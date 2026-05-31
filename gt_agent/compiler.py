from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LeanFeedback:
    compiles: bool
    output: str = ""
    checked: bool = True
    command: tuple[str, ...] = ()


class LeanCompiler:
    """Thin Lean compiler adapter.

    The adapter is intentionally small: it calls a local ``lean`` executable when
    present and reports ``checked=False`` when Lean is unavailable. Callers can
    inject a fake compiler in tests or a richer Lake-backed adapter in projects.
    """

    def __init__(self, executable: str | None = None, timeout_seconds: int = 30) -> None:
        self.executable = executable or shutil.which("lean")
        self.timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return self.executable is not None

    def check_file(self, path: str | Path) -> LeanFeedback:
        if not self.executable:
            return LeanFeedback(
                compiles=False,
                output="Lean executable not found; compile check was not run.",
                checked=False,
            )
        command = (self.executable, str(path))
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + (exc.stderr or "")
            return LeanFeedback(False, output or "Lean check timed out.", True, command)
        output = (completed.stdout or "") + (completed.stderr or "")
        return LeanFeedback(completed.returncode == 0, output.strip(), True, command)

    def check_code(self, code: str, suffix: str = ".lean") -> LeanFeedback:
        with tempfile.TemporaryDirectory(prefix="gt_agent_lean_") as tmp:
            path = Path(tmp) / f"check{suffix}"
            path.write_text(code, encoding="utf-8")
            return self.check_file(path)
