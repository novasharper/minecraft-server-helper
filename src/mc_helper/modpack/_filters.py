"""Shared exclude/include filter utilities for modpack installers."""

import fnmatch
import json
from pathlib import Path
from typing import Literal

from importlib import resources

def load_exclude_include(kind: Literal["cf", "mr"]) -> dict:
    """Load the bundled exclude/include filter file for CurseForge or Modrinth."""
    filename = "cf-exclude-include.json" if kind == "cf" else "modrinth-exclude-include.json"
    try:
        traversable = resources.files("mc_helper.data").joinpath(filename)
        with traversable.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (ImportError, FileNotFoundError):
        return {"globalExcludes": [], "globalForceIncludes": [], "modpacks": {}}


def matches_any(patterns: list[str], name: str) -> bool:
    """Return True if *name* matches any of the given fnmatch *patterns*."""
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)
