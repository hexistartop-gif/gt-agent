from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchReplacePatch:
    search: str
    replace: str


def apply_search_replace(code: str, patch: SearchReplacePatch) -> str:
    if patch.search not in code:
        raise ValueError("search text not found")
    return code.replace(patch.search, patch.replace, 1)
