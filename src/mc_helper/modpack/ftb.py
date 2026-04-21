"""FTB (Feed The Beast) modpack installer.

Reference: https://github.com/FTBTeam/FTB-Server-Installer
API base: https://api.feed-the-beast.com/v1/modpacks

Workflow:
  1. GET /modpack/{pack_id} → version list
  2. Resolve version ID (explicit, or first with matching version_type)
  3. GET /modpack/{pack_id}/{version_id} → file list + targets
  4. Parse targets: mc_version, loader_type, loader_version
  5. Filter files: drop clientonly=True; apply exclude_mods fnmatch patterns
  6. Download files in parallel to output_dir/{file.path}/{file.name}
  7. Cleanup stale, save manifest
"""

import fnmatch
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from mc_helper.config import FTBSource, ModpackConfig
from mc_helper.http_client import build_session, download_with_mirrors
from mc_helper.manifest import Manifest

log = logging.getLogger(__name__)

_API_BASE = "https://api.feed-the-beast.com/v1/modpacks"
_MAX_WORKERS = 10


def _ftb_get(url: str, api_key: str, session: requests.Session) -> dict:
    """GET *url* with optional FTB Bearer auth. Raises on HTTP error or non-success status."""
    headers: dict[str, str] = {}
    if api_key != "public":
        headers["Authorization"] = f"Bearer {api_key}"
    resp = session.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    data: dict = resp.json()
    if data.get("status") != "success":
        raise ValueError(f"FTB API error for pack: {data.get('message', 'unknown error')}")
    return data


def _should_include(file_entry: dict, exclude_mods: list[str]) -> bool:
    if file_entry.get("clientonly"):
        return False
    name = file_entry.get("name", "")
    return not any(fnmatch.fnmatch(name, pattern) for pattern in exclude_mods)


class FTBPackInstaller:
    """Installs an FTB modpack by downloading files directly from the FTB API."""

    def __init__(
        self,
        source: FTBSource,
        modpack: ModpackConfig,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.source = source
        self.modpack = modpack
        self.session = session or build_session()
        self.show_progress = show_progress
        self.recommended_memory_mb: int | None = None

    def _api_key(self) -> str:
        return self.source.api_key or "public"

    def _resolve_version_id(self) -> int:
        if self.source.version_id is not None:
            return self.source.version_id
        data = _ftb_get(f"{_API_BASE}/modpack/{self.source.pack_id}", self._api_key(), self.session)
        versions = sorted(data.get("versions", []), key=lambda v: v["id"], reverse=True)
        for v in versions:
            if v.get("type") == self.source.version_type:
                return int(v["id"])
        if versions:
            return int(versions[0]["id"])
        raise ValueError(
            f"No versions found for FTB pack {self.source.pack_id} "
            f"with type {self.source.version_type!r}"
        )

    def install(self, output_dir: Path) -> None:
        """Install the FTB modpack into *output_dir*."""
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = Manifest(output_dir)
        manifest.load()

        version_id = self._resolve_version_id()
        log.info("Resolved FTB pack %d version_id: %d", self.source.pack_id, version_id)

        detail = _ftb_get(
            f"{_API_BASE}/modpack/{self.source.pack_id}/{version_id}", self._api_key(), self.session
        )

        specs = detail.get("specs", {})
        if specs.get("recommended"):
            self.recommended_memory_mb = int(specs["recommended"])

        mc_version: str | None = None
        loader_type: str | None = None
        loader_version: str | None = None
        for target in detail.get("targets", []):
            if target.get("type") == "game" and target.get("name") == "minecraft":
                mc_version = target.get("version")
            elif target.get("type") == "modloader":
                loader_type = target.get("name")
                loader_version = target.get("version")

        exclude_mods = self.modpack.exclude_mods or []
        all_files = detail.get("files", [])
        files_to_download = [f for f in all_files if _should_include(f, exclude_mods)]
        log.info(
            "Downloading %d file(s) (%d skipped as client-only/excluded)...",
            len(files_to_download),
            len(all_files) - len(files_to_download),
        )

        new_files: list[str] = []
        errors: list[str] = []
        session = self.session

        def _download_entry(entry: dict) -> str:
            dest = output_dir / entry["path"] / entry["name"]
            download_with_mirrors(
                entry["url"],
                entry.get("mirrors", []),
                dest,
                session,
                entry.get("sha1") or None,
            )
            return str(Path(entry["path"]) / entry["name"])

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {pool.submit(_download_entry, f): f for f in files_to_download}
            for fut in as_completed(futures):
                entry = futures[fut]
                try:
                    new_files.append(fut.result())
                except Exception as exc:
                    errors.append(f"{entry.get('name', '?')}: {exc}")

        if errors:
            raise RuntimeError(f"{len(errors)} file(s) failed to download:\n" + "\n".join(errors))

        manifest.cleanup_stale(new_files)
        manifest.files = new_files
        if mc_version:
            manifest.mc_version = mc_version
        if loader_type:
            manifest.loader_type = loader_type
        if loader_version:
            manifest.loader_version = loader_version
        manifest.save()
