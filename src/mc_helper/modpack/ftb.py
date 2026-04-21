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

from mc_helper.http_client import build_session, download_file
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
    """Return True if the file should be downloaded (not client-only, not excluded)."""
    if file_entry.get("clientonly"):
        return False
    name = file_entry.get("name", "")
    for pattern in exclude_mods:
        if fnmatch.fnmatch(name, pattern):
            return False
    return True


def _download_with_mirrors(
    primary_url: str,
    mirrors: list[str],
    dest: Path,
    session: requests.Session,
    expected_sha1: str | None,
) -> None:
    """Try primary URL, then each mirror in order. Raises RuntimeError if all fail."""
    urls = [primary_url, *mirrors]
    last_exc: Exception | None = None
    for url in urls:
        try:
            download_file(
                url, dest, session=session, expected_sha1=expected_sha1, show_progress=False
            )
            return
        except Exception as exc:
            last_exc = exc
            dest.unlink(missing_ok=True)
    raise RuntimeError(f"All download URLs failed for {dest.name}") from last_exc


class FTBPackInstaller:
    """Installs an FTB modpack by downloading files directly from the FTB API."""

    def __init__(
        self,
        pack_id: int,
        version_id: int | None = None,
        api_key: str = "public",
        version_type: str = "release",
        exclude_mods: list[str] | None = None,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.pack_id = pack_id
        self.version_id = version_id
        self.api_key = api_key
        self.version_type = version_type
        self.exclude_mods = exclude_mods or []
        self.session = session or build_session()
        self.show_progress = show_progress
        self.recommended_memory_mb: int | None = None

    def _resolve_version_id(self) -> int:
        """Return the version ID to install, fetching pack metadata if needed."""
        if self.version_id is not None:
            return self.version_id
        data = _ftb_get(f"{_API_BASE}/modpack/{self.pack_id}", self.api_key, self.session)
        versions = sorted(data.get("versions", []), key=lambda v: v["id"], reverse=True)
        for v in versions:
            if v.get("type") == self.version_type:
                return int(v["id"])
        if versions:
            return int(versions[0]["id"])
        raise ValueError(
            f"No versions found for FTB pack {self.pack_id} with type {self.version_type!r}"
        )

    def install(self, output_dir: Path) -> None:
        """Install the FTB modpack into *output_dir*."""
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = Manifest(output_dir)
        manifest.load()

        # 1+2. Resolve version ID
        version_id = self._resolve_version_id()
        log.info("Resolved FTB pack %d version_id: %d", self.pack_id, version_id)

        # 3. Fetch version detail
        detail = _ftb_get(
            f"{_API_BASE}/modpack/{self.pack_id}/{version_id}", self.api_key, self.session
        )

        # 4. Parse targets and specs
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

        # 5. Filter files
        all_files = detail.get("files", [])
        files_to_download = [f for f in all_files if _should_include(f, self.exclude_mods)]
        log.info(
            "Downloading %d file(s) (%d skipped as client-only/excluded)...",
            len(files_to_download),
            len(all_files) - len(files_to_download),
        )

        # 6. Download files in parallel (individual progress bars suppressed; too noisy)
        new_files: list[str] = []
        errors: list[str] = []
        session = self.session

        def _download_entry(entry: dict) -> str:
            dest = output_dir / entry["path"] / entry["name"]
            _download_with_mirrors(
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

        # 7. Cleanup stale + save manifest
        manifest.cleanup_stale(output_dir, new_files)
        manifest.files = new_files
        if mc_version:
            manifest.mc_version = mc_version
        if loader_type:
            manifest.loader_type = loader_type
        if loader_version:
            manifest.loader_version = loader_version
        manifest.save()
