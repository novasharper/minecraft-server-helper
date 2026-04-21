"""Archive extraction and filesystem utilities for modpack installers."""

import fnmatch
import hashlib
import tarfile
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


def extract_zip(archive: Path, dest: Path, strip_components: int) -> None:
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            parts = Path(member.filename).parts
            if len(parts) <= strip_components:
                continue
            rel = Path(*parts[strip_components:])
            target = dest / rel
            if member.filename.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))


def extract_tar(archive: Path, dest: Path, strip_components: int) -> None:
    with tarfile.open(archive) as tf:
        for member in tf.getmembers():
            parts = Path(member.name).parts
            if len(parts) <= strip_components:
                continue
            rel = Path(*parts[strip_components:])
            target = dest / rel
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                fobj = tf.extractfile(member)
                if fobj:
                    target.write_bytes(fobj.read())


def extract_archive(
    archive: Path, dest: Path, strip_components: int, original_name: str = ""
) -> None:
    """Dispatch extraction based on archive file extension."""
    name = (original_name or archive.name).lower()
    if name.endswith(".zip"):
        extract_zip(archive, dest, strip_components)
    elif name.endswith(".tar.gz") or name.endswith(".tgz") or name.endswith(".tar.bz2"):
        extract_tar(archive, dest, strip_components)
    else:
        raise ValueError(f"Unsupported archive format: {name}")


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def find_content_root(base: Path, markers: list[str] | None = None, max_depth: int = 3) -> Path:
    """Find the shallowest directory under *base* that looks like a server root.

    Mirrors ``mc-image-helper find --only-shallowest --max-depth=3``.
    Returns *base* itself if no qualifying subdirectory is found.
    """
    if markers is None:
        markers = ["mods", "plugins", "config"]

    base_depth = len(base.parts)
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
    """Rename files in *mods_dir* matching any pattern to ``<name>.disabled``."""
    renamed: list[Path] = []
    for f in mods_dir.iterdir():
        if not f.is_file():
            continue
        if any(fnmatch.fnmatch(f.name, p) for p in patterns):
            new_path = f.with_suffix(f.suffix + ".disabled")
            f.rename(new_path)
            renamed.append(new_path)
    return renamed
