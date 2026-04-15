import fnmatch
import zipfile
from pathlib import Path


def extract_zip_overrides(
    zf: zipfile.ZipFile,
    output_dir: Path,
    prefixes: list[str],
    exclusions: list[str],
) -> list[str]:
    """Extract one or more override directories from *zf* into *output_dir*.

    Each entry in *prefixes* is a directory name (e.g. ``"overrides"``).
    Files whose relative path matches any *exclusions* glob are skipped.
    Returns the list of extracted relative paths.
    """
    resolved_root = output_dir.resolve()
    extracted: list[str] = []
    for prefix_name in prefixes:
        prefix = prefix_name.rstrip("/") + "/"
        for name in zf.namelist():
            if not name.startswith(prefix) or name == prefix:
                continue
            rel = name[len(prefix) :]
            if not rel:
                continue
            if any(fnmatch.fnmatch(rel, pat) for pat in exclusions):
                continue
            dest = output_dir / rel
            # Guard against path-traversal entries (e.g. "overrides/../../evil")
            try:
                dest.resolve().relative_to(resolved_root)
            except ValueError:
                raise ValueError(f"Path traversal detected in ZIP entry: {name!r}")
            if name.endswith("/"):
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(name))
                extracted.append(rel)
    return extracted


def compare_versions(a: str, b: str) -> int:
    """Compare two dot-separated version strings.

    Returns -1 if a < b, 0 if a == b, 1 if a > b.
    Non-numeric segments are compared lexicographically.
    """

    def _parts(v: str) -> list[int | str]:
        parts: list[int | str] = []
        for seg in v.split("."):
            try:
                parts.append(int(seg))
            except ValueError:
                parts.append(seg)
        return parts

    pa, pb = _parts(a), _parts(b)
    # Pad to equal length
    max_len = max(len(pa), len(pb))
    pa += [0] * (max_len - len(pa))
    pb += [0] * (max_len - len(pb))

    for x, y in zip(pa, pb):
        # If types differ, convert both to str for comparison
        if type(x) is not type(y):
            x, y = str(x), str(y)
        if x < y:
            return -1
        if x > y:
            return 1
    return 0


def glob_delete(directory: Path, patterns: list[str]) -> list[Path]:
    """Delete files in *directory* matching any of the given glob *patterns*.

    Returns the list of deleted paths.
    """
    deleted: list[Path] = []
    for pattern in patterns:
        for match in directory.glob(pattern):
            if match.is_file():
                match.unlink()
                deleted.append(match)
    return deleted


def find_content_root(base: Path, markers: list[str] | None = None, max_depth: int = 3) -> Path:
    """Find the shallowest directory under *base* that looks like a server root.

    Mirrors the reference behaviour of ``mc-image-helper find --only-shallowest
    --max-depth=3`` which finds directories named ``mods``, ``plugins``, or
    ``config`` and returns their *parent* as the content root.

    *markers* is a list of subdirectory names whose presence indicates a server
    root. Defaults to ``["mods", "plugins", "config"]``.

    Returns *base* itself if no qualifying subdirectory is found.
    """
    if markers is None:
        markers = ["mods", "plugins", "config"]

    base_depth = len(base.parts)

    # Collect the parent of every marker directory found within max_depth, then
    # pick the shallowest.
    parents: list[Path] = []
    for marker in markers:
        for match in base.rglob(marker):
            if match.is_dir() and len(match.parts) - base_depth <= max_depth:
                parents.append(match.parent)

    if parents:
        parents.sort(key=lambda p: len(p.parts))
        return parents[0]

    return base


def disable_mods(mods_dir: Path, patterns: list[str]) -> list[Path]:
    """Rename files in *mods_dir* matching any pattern to ``<name>.disabled``.

    Returns the list of renamed paths (the new .disabled paths).
    """
    renamed: list[Path] = []
    for f in mods_dir.iterdir():
        if not f.is_file():
            continue
        if any(fnmatch.fnmatch(f.name, p) for p in patterns):
            new_path = f.with_suffix(f.suffix + ".disabled")
            f.rename(new_path)
            renamed.append(new_path)
    return renamed
