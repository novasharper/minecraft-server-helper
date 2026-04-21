"""Shared exclude/include filter utilities for modpack installers."""

import fnmatch
import json
from pathlib import Path
from typing import Literal

_DATA_DIR = Path(__file__).parent.parent / "data"


def load_exclude_include(kind: Literal["cf", "mr"]) -> dict:
    """Load the bundled exclude/include filter file for CurseForge or Modrinth."""
    filename = "cf-exclude-include.json" if kind == "cf" else "modrinth-exclude-include.json"
    path = _DATA_DIR / filename
    if path.exists():
        return json.loads(path.read_text())
    return {"globalExcludes": [], "globalForceIncludes": [], "modpacks": {}}


def matches_any(patterns: list[str], name: str) -> bool:
    """Return True if *name* matches any of the given fnmatch *patterns*."""
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)
