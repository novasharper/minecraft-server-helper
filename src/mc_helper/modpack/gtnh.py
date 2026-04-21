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
from enum import Enum
from pathlib import Path
from typing import NamedTuple

import requests

from mc_helper.config import GTNHSource, ServerConfig
from mc_helper.http_client import build_session, download_file
from mc_helper.launch import _detect_java_major_version
from mc_helper.manifest import Manifest

from ._archives import find_content_root

log = logging.getLogger(__name__)

_VERSIONS_URL = "https://downloads.gtnewhorizons.com/versions.json"
_MC_VERSION = "1.7.10"

_MIN_JAVA_VERSION = 17
_START_JAR = "lwjgl3ify-forgePatches.jar"


class ReleaseType(Enum):
    BETA = 0
    RC = 1
    RELEASE = 2


class ReleaseInfo(NamedTuple):
    version: tuple[int, ...]
    release_type: ReleaseType
    dev_version: int

    @staticmethod
    def from_version_str(version_str: str) -> ReleaseInfo:
        version = _parse_version(version_str)
        release_type, dev_version = _parse_release_type(version_str)
        return ReleaseInfo(version, release_type, dev_version)

    def __str__(self) -> str:
        if self.release_type == ReleaseType.BETA:
            tail = f"-beta-{self.dev_version}"
        elif self.release_type == ReleaseType.RC:
            tail = f"-rc-{self.dev_version}"
        else:
            tail = ""

        parts = [str(p) for p in self.version]
        return f"{'.'.join(parts)}{tail}"


class PackEntry(NamedTuple):
    release: ReleaseInfo
    url: str
    java_min: int
    java_max: int

    @property
    def is_beta(self):
        return self.release.release_type != ReleaseType.RELEASE


def _parse_version(version: str) -> tuple[int, ...]:
    m = re.search(r"(\d+(?:\.\d+)+)", version)
    if not m:
        return (0,)
    return tuple(int(p) for p in m.group(1).split("."))


def _parse_release_type(version: str) -> tuple[ReleaseType, int]:
    m = re.search(r"(beta|rc)(?:-(\d+))?", version.lower())
    if not m:
        return ReleaseType.RELEASE, 0

    _release_type = m.group(1)
    _release_ver = int(m.group(2) or 0)
    if _release_type.startswith("rc"):
        return ReleaseType.RC, _release_ver

    assert _release_type == "beta"
    return ReleaseType.BETA, _release_ver


def _fetch_packs(session: requests.Session) -> list[PackEntry]:
    resp = session.get(_VERSIONS_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    packs: list[PackEntry] = []
    for version, pack_data in data.get("versions", {}).items():
        packs.append(
            PackEntry(
                ReleaseInfo.from_version_str(version),
                pack_data["server"]["java17_2XUrl"],
                _MIN_JAVA_VERSION,
                pack_data["maxJavaVersion"],
            )
        )
    return packs


def _select_pack(packs: list[PackEntry], version_selector: str, java_ver: int) -> PackEntry | None:
    if not packs:
        return None

    lower = version_selector.lower()
    if lower in ("latest", "latest-dev"):
        want_dev = lower == "latest-dev"
        candidates = [p for p in packs if p.is_beta == want_dev]

    else:
        candidates = [p for p in packs if lower in str(p.release)]

    if not candidates:
        return None

    return max(candidates, key=lambda p: p.release)


class GTNHPackInstaller:
    """Download and install a GTNH server pack."""

    def __init__(
        self,
        source: GTNHSource,
        server: ServerConfig,
        session: requests.Session | None = None,
    ) -> None:
        self.source = source
        self.server = server
        self.session = session or build_session()

    def install(self, output_dir: Path) -> Path:
        """Download, extract, and manifest the GTNH server pack.

        Returns the start artifact JAR path.
        """
        java_bin = self.server.jvm.java_bin
        java_ver = _detect_java_major_version(java_bin)
        if java_ver is None:
            raise RuntimeError(
                "Could not detect Java version from java_bin=%r; "
                "ensure Java is installed and accessible" % java_bin
            )
        if java_ver < _MIN_JAVA_VERSION:
            # Technically Java8 is supported, but for simplicity only support
            # more modern java versions
            raise RuntimeError(
                f"GTNH only supports Java {_MIN_JAVA_VERSION}+; detected Java {java_ver}"
            )

        log.info("Fetching GTNH pack list from %s", _VERSIONS_URL)
        packs = _fetch_packs(self.session)
        if not packs:
            raise RuntimeError("No GTNH server packs found in versions.json")

        pack = _select_pack(packs, self.source.version, java_ver)
        if pack is None:
            raise RuntimeError(
                f"No GTNH server pack found for version={self.source.version!r} "
                f"and Java {java_ver}"
            )

        log.info("Selected GTNH pack: %s", pack.release)
        output_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp_str:
            tmp_dir = Path(tmp_str)
            filename = f"GT_New_Horizons_{str(pack.release)}.zip"
            archive_path = tmp_dir / filename
            download_file(pack.url, archive_path, session=self.session, show_progress=True)

            log.info("Extracting %s...", filename)
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(tmp_dir / "extracted")

            content_root = find_content_root(tmp_dir / "extracted")
            log.debug("GTNH content root: %s", content_root)

            for eula in content_root.rglob("eula.txt"):
                eula.unlink()

            for src in content_root.iterdir():
                dest = output_dir / src.name
                if src.is_dir():
                    if dest.exists():
                        shutil.copytree(src, dest, dirs_exist_ok=True)
                    else:
                        shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)

        start_artifact = output_dir / _START_JAR
        if not start_artifact.exists():
            raise RuntimeError(
                f"Expected start artifact {_START_JAR!r} not found after extraction; "
                "check GTNH pack contents"
            )

        manifest = Manifest(output_dir)
        manifest.load()
        manifest.mc_version = _MC_VERSION
        manifest.loader_type = "gtnh"
        manifest.loader_version = str(pack.release)
        manifest.add_file(start_artifact.relative_to(output_dir))
        manifest.save()

        log.info(
            "GTNH %s installed (Java %d → %s)",
            manifest.loader_version,
            java_ver,
            _START_JAR,
        )
        return start_artifact
