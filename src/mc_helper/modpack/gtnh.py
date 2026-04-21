"""GregTech New Horizons (GTNH) server pack installer.

Downloads from https://downloads.gtnewhorizons.com/versions.json,
selects a server ZIP compatible with the current JVM, and extracts it.

Reference: docker-minecraft-server/scripts/start-deployGTNH
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import NamedTuple

import requests

from mc_helper.http_client import build_session, download_file
from mc_helper.launch import _detect_java_major_version
from mc_helper.manifest import Manifest
from mc_helper.utils import find_content_root

log = logging.getLogger(__name__)

_VERSIONS_URL = "https://downloads.gtnewhorizons.com/versions.json"
_MC_VERSION = "1.7.10"

# Server JAR names used in start-deployGTNH
_JAR_JAVA8 = "forge-1.7.10-10.13.4.1614-1.7.10-universal.jar"
_JAR_JAVA17 = "lwjgl3ify-forgePatches.jar"


class _PackEntry(NamedTuple):
    url: str
    version: tuple[int, ...]  # semver tuple for sorting
    release_type: str  # "" | "RC" | "beta" etc.
    java_min: int
    java_max: int
    filename: str


def _parse_java_range(filename: str) -> tuple[int, int]:
    """Parse 'Java_8' or 'Java_17-21' from a filename.  Returns (min, max)."""
    m = re.search(r"Java_(\d+)(?:-(\d+))?", filename)
    if not m:
        return (0, 9999)
    lo = int(m.group(1))
    hi = int(m.group(2)) if m.group(2) else lo
    return (lo, hi)


def _parse_version(filename: str) -> tuple[int, ...]:
    """Extract the version number from a filename as a sortable tuple."""
    m = re.search(r"(\d+(?:\.\d+)+)", filename)
    if not m:
        return (0,)
    return tuple(int(p) for p in m.group(1).split("."))


def _parse_release_type(filename: str) -> str:
    """Return 'beta', 'RC', 'RC-N', etc., or '' for a full release."""
    m = re.search(r"(beta|RC(?:-\d+)?)", filename, re.IGNORECASE)
    return m.group(1) if m else ""


def _is_beta(url: str) -> bool:
    return "/betas/" in url


def _pack_sort_key(p: _PackEntry) -> tuple:
    """Higher is better: full > RC > beta, then higher version number."""
    release_rank = 2 if p.release_type == "" else (1 if p.release_type.startswith("RC") else 0)
    return (p.version, release_rank)


def _fetch_packs(session: requests.Session) -> list[dict]:
    """Fetch the GTNH versions.json and return the flat list of server download URLs."""
    resp = session.get(_VERSIONS_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    urls: list[str] = []
    for version_block in data.get("versions", {}).values():
        for entry in version_block.get("server", []):
            if isinstance(entry, str) and "Server" in entry:
                urls.append(entry)
    return urls


def _select_pack(urls: list[str], version_selector: str, java_ver: int) -> _PackEntry | None:
    """Choose the best matching pack URL given a version selector and Java version."""
    entries: list[_PackEntry] = []
    for url in urls:
        filename = url.split("/")[-1]
        java_min, java_max = _parse_java_range(filename)
        if not (java_min <= java_ver <= java_max):
            continue

        ver_tuple = _parse_version(filename)
        rel_type = _parse_release_type(filename)
        entries.append(
            _PackEntry(
                url=url,
                version=ver_tuple,
                release_type=rel_type,
                java_min=java_min,
                java_max=java_max,
                filename=filename,
            )
        )

    if not entries:
        return None

    lower = version_selector.lower()
    if lower in ("latest", "latest-dev"):
        want_beta = lower == "latest-dev"
        candidates = [e for e in entries if _is_beta(e.url) == want_beta]
        if not candidates:
            candidates = entries
        return max(candidates, key=_pack_sort_key)

    # Exact version match: "2.7.0" or "2.7.0-beta-1"
    for entry in entries:
        bare = entry.filename
        ver_str = ".".join(str(v) for v in entry.version)
        full_ver = f"{ver_str}-{entry.release_type}" if entry.release_type else ver_str
        if version_selector in bare or version_selector == full_ver:
            return entry

    return None


class GTNHPackInstaller:
    """Download and install a GTNH server pack."""

    def __init__(
        self,
        version: str = "latest",
        java_bin: str = "java",
        session: requests.Session | None = None,
    ) -> None:
        self.version = version
        self.java_bin = java_bin
        self.session = session or build_session()

    def install(self, output_dir: Path) -> Path:
        """Download, extract, and manifest the GTNH server pack.

        Returns the start artifact JAR path.
        """
        java_ver = _detect_java_major_version(self.java_bin)
        if java_ver is None:
            raise RuntimeError(
                "Could not detect Java version from java_bin=%r; "
                "ensure Java is installed and accessible" % self.java_bin
            )
        if java_ver not in range(8, 9) and java_ver < 17:
            raise RuntimeError(f"GTNH only supports Java 8 or Java 17+; detected Java {java_ver}")

        log.info("Fetching GTNH pack list from %s", _VERSIONS_URL)
        urls = _fetch_packs(self.session)
        if not urls:
            raise RuntimeError("No GTNH server packs found in versions.json")

        pack = _select_pack(urls, self.version, java_ver)
        if pack is None:
            raise RuntimeError(
                f"No GTNH server pack found for version={self.version!r} and Java {java_ver}"
            )

        log.info("Selected GTNH pack: %s", pack.filename)

        output_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp_str:
            tmp_dir = Path(tmp_str)
            archive_path = tmp_dir / pack.filename
            download_file(pack.url, archive_path, session=self.session, show_progress=True)

            log.info("Extracting %s...", pack.filename)
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(tmp_dir / "extracted")

            content_root = find_content_root(tmp_dir / "extracted")
            log.debug("GTNH content root: %s", content_root)

            # Remove any eula.txt from the pack (mc-helper manages it)
            for eula in content_root.rglob("eula.txt"):
                eula.unlink()

            # Copy pack contents into output_dir
            for src in content_root.iterdir():
                dest = output_dir / src.name
                if src.is_dir():
                    if dest.exists():
                        shutil.copytree(src, dest, dirs_exist_ok=True)
                    else:
                        shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)

        # Select the start artifact based on Java version
        start_jar = _JAR_JAVA17 if java_ver >= 17 else _JAR_JAVA8
        start_artifact = output_dir / start_jar
        if not start_artifact.exists():
            raise RuntimeError(
                f"Expected start artifact {start_jar!r} not found after extraction; "
                "check GTNH pack contents"
            )

        # Save manifest
        manifest = Manifest(output_dir)
        manifest.load()
        manifest.mc_version = _MC_VERSION
        manifest.loader_type = "gtnh"
        manifest.loader_version = ".".join(str(v) for v in pack.version) + (
            f"-{pack.release_type}" if pack.release_type else ""
        )
        manifest.add_file(start_artifact.relative_to(output_dir))
        manifest.save()

        log.info(
            "GTNH %s installed (Java %d → %s)",
            manifest.loader_version,
            java_ver,
            start_jar,
        )
        return start_artifact
