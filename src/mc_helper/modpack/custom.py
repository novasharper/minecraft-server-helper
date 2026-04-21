"""Pre-assembled server pack installer.

Reference: docker-minecraft-server/scripts/start-setupModpack
Reference: easy-add/main.go (processTarGz / processZip)

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

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Union

import requests

from mc_helper.config import GithubSource, ModpackConfig, UrlSource
from mc_helper.github_release import resolve_github_url
from mc_helper.http_client import build_session, download_file
from mc_helper.manifest import Manifest

from ._archives import disable_mods, extract_archive, find_content_root, sha1_file

log = logging.getLogger(__name__)


class ServerPackInstaller:
    """Downloads and extracts a pre-assembled server pack."""

    def __init__(
        self,
        source: Union[GithubSource, UrlSource],
        modpack: ModpackConfig,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.source = source
        self.modpack = modpack
        self.show_progress = show_progress

        token = getattr(source, "token", None)
        if session is None:
            headers = {"Authorization": f"Bearer {token}"} if token else None
            self.session = build_session(extra_headers=headers)
        else:
            self.session = session
            if token:
                self.session.headers["Authorization"] = f"Bearer {token}"

    def _detect_start_artifact(self, output_dir: Path) -> Path | None:
        override = getattr(self.source, "start_artifact", None)
        if override:
            return output_dir / override

        for file in (
            "run.sh",
            "ServerStart.sh",
            "start.sh",
            "startserver.sh",
            "minecraft_server.jar",
        ):
            if (output_dir / file).exists():
                return output_dir / file

        forge_jars = sorted(output_dir.glob("forge-*.jar"))
        if forge_jars:
            return forge_jars[0]

        mc_jars = sorted(output_dir.glob("minecraft_server.*.jar"))
        if mc_jars:
            return mc_jars[0]

        return None

    def install(self, output_dir: Path) -> Path | None:
        """Download and extract the server pack into *output_dir*.

        Returns the detected server start artifact, or None if not found.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = Manifest(output_dir)
        manifest.load()

        if isinstance(self.source, GithubSource):
            download_url = resolve_github_url(
                self.session, self.source.repo, self.source.tag, self.source.asset
            )
        else:
            download_url = self.source.url
        log.info("Resolved server pack URL: %s", download_url)

        archive_name = download_url.split("?")[0].rstrip("/").split("/")[-1]
        tmp_archive = output_dir / f".mc-helper-{archive_name}.tmp"

        download_file(
            download_url, tmp_archive, session=self.session, show_progress=self.show_progress
        )

        force_update = getattr(self.source, "force_update", False)
        strip_components = getattr(self.source, "strip_components", 0)
        exclude_mods = self.modpack.exclude_mods or []

        try:
            sha1 = sha1_file(tmp_archive)
            if not force_update and manifest.pack_sha1 == sha1:
                log.info("Server pack SHA-1 unchanged — skipping extraction")
                return self._detect_start_artifact(output_dir)

            log.info("Extracting server pack...")
            with tempfile.TemporaryDirectory() as tmp_str:
                tmp_dir = Path(tmp_str)
                extract_archive(tmp_archive, tmp_dir, strip_components, original_name=archive_name)

                content_root = find_content_root(tmp_dir)
                log.debug("Content root: %s", content_root)

                if exclude_mods:
                    mods_dir = content_root / "mods"
                    if mods_dir.is_dir():
                        disable_mods(mods_dir, exclude_mods)

                for item in content_root.iterdir():
                    dest = output_dir / item.name
                    if item.is_dir():
                        if dest.exists():
                            shutil.rmtree(dest)
                        shutil.copytree(item, dest)
                    else:
                        shutil.copy2(item, dest)

            manifest.pack_sha1 = sha1
            manifest.save()

        finally:
            tmp_archive.unlink(missing_ok=True)

        return self._detect_start_artifact(output_dir)
