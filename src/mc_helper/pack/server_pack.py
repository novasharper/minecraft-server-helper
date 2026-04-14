"""Pre-assembled server pack installer.

Reference: docker-minecraft-server/scripts/start-setupModpack
Reference: easy-add/main.go (processTarGz / processZip)
Reference: mc-image-helper github subcommand family

Supports:
  - Direct URL (ZIP or tar.gz)
  - GitHub release asset (by glob on asset name)

Workflow:
  1. Resolve download URL (GitHub or direct)
  2. Download archive, compute SHA-1
  3. Skip re-extraction if SHA-1 matches manifest and force_update is False
  4. Extract with strip_components support
  5. Auto-detect content root (shallowest dir containing mods/, plugins/, config/, *.jar)
  6. Copy content root into output_dir
  7. Rename disable_mods matches to *.disabled
  8. Save SHA-1 in manifest
"""

import fnmatch
import hashlib
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file
from mc_helper.manifest import Manifest
from mc_helper.utils import disable_mods, find_content_root

_GITHUB_API = "https://api.github.com"


# ── GitHub resolution ─────────────────────────────────────────────────────────


def _resolve_github_url(
    session: requests.Session,
    repo: str,
    tag: str,
    asset_glob: str | None,
) -> str:
    """Return the browser_download_url for the matching release asset."""
    if tag.upper() == "LATEST":
        url = f"{_GITHUB_API}/repos/{repo}/releases/latest"
    else:
        url = f"{_GITHUB_API}/repos/{repo}/releases/tags/{tag}"

    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    release = resp.json()

    assets: list[dict] = release.get("assets", [])
    if not assets:
        raise ValueError(f"No assets found in GitHub release {repo}@{tag}")

    if asset_glob:
        matched = [a for a in assets if fnmatch.fnmatch(a["name"], asset_glob)]
        if not matched:
            names = [a["name"] for a in assets]
            raise ValueError(
                f"No asset matching '{asset_glob}' in {repo}@{tag}. Available: {names}"
            )
        return matched[0]["browser_download_url"]

    return assets[0]["browser_download_url"]


# ── Archive extraction ────────────────────────────────────────────────────────


def _extract_zip(archive: Path, dest: Path, strip_components: int) -> None:
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


def _extract_tar(archive: Path, dest: Path, strip_components: int) -> None:
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


def _extract(archive: Path, dest: Path, strip_components: int, original_name: str = "") -> None:
    name = (original_name or archive.name).lower()
    if name.endswith(".zip"):
        _extract_zip(archive, dest, strip_components)
    elif name.endswith(".tar.gz") or name.endswith(".tgz") or name.endswith(".tar.bz2"):
        _extract_tar(archive, dest, strip_components)
    else:
        raise ValueError(f"Unsupported archive format: {name}")


def _sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Public install ────────────────────────────────────────────────────────────


def install(
    output_dir: Path,
    url: str | None = None,
    github: str | None = None,
    tag: str = "LATEST",
    asset: str | None = None,
    token: str | None = None,
    strip_components: int = 0,
    disable_mods_patterns: list[str] | None = None,
    force_update: bool = False,
    session: requests.Session | None = None,
    show_progress: bool = True,
) -> None:
    """Download and extract a pre-assembled server pack into output_dir."""
    if session is None:
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        session = build_session(extra_headers=headers or None)
    elif token:
        session.headers["Authorization"] = f"Bearer {token}"

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(output_dir)
    manifest.load()

    # 1. Resolve download URL
    if github:
        download_url = _resolve_github_url(session, github, tag, asset)
    elif url:
        download_url = url
    else:
        raise ValueError("Either url or github must be provided")

    # Derive archive filename from URL
    archive_name = download_url.split("?")[0].rstrip("/").split("/")[-1]
    tmp_archive = output_dir / f".mc-helper-{archive_name}.tmp"

    # 2. Download archive
    download_file(download_url, tmp_archive, session=session, show_progress=show_progress)

    try:
        # 3. Check SHA-1 for idempotency
        sha1 = _sha1_file(tmp_archive)
        if not force_update and manifest.pack_sha1 == sha1:
            return

        # 4. Extract into temp dir
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp_dir = Path(tmp_str)
            _extract(tmp_archive, tmp_dir, strip_components, original_name=archive_name)

            # 5. Find content root
            content_root = find_content_root(tmp_dir)

            # 7. Rename disable_mods entries
            if disable_mods_patterns:
                mods_dir = content_root / "mods"
                if mods_dir.is_dir():
                    disable_mods(mods_dir, disable_mods_patterns)

            # 6. Copy content root into output_dir
            for item in content_root.iterdir():
                dest = output_dir / item.name
                if item.is_dir():
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

        # 8. Save SHA-1 in manifest
        manifest.pack_sha1 = sha1
        manifest.save()

    finally:
        tmp_archive.unlink(missing_ok=True)
