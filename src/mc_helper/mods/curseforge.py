"""CurseForge individual mod installer.

Reference: mc-image-helper/.../curseforge/CurseForgeApiClient.java
Reference: docker-minecraft-server/docs/variables.md (CURSEFORGE_FILES formats)

Spec formats:
  jei                                    → latest file for mc version (slug)
  jei:4593548                            → specific file ID by slug
  238222                                 → project ID (latest file)
  238222:4593548                         → project ID + file ID
  https://www.curseforge.com/.../jei     → page URL (slug extracted)
"""

from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file, get_json
from mc_helper.modpack.curseforge import _download_url_for_file

_API_BASE = "https://api.curseforge.com"
_MINECRAFT_GAME_ID = "432"
_MOD_CLASS_ID = 6
_LOADER_TYPE_MAP = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}


class CurseForgeModInstaller:
    """Downloads a single CurseForge mod JAR."""

    def __init__(
        self,
        spec: str,
        api_key: str,
        minecraft_version: str | None = None,
        loader: str | None = None,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.spec = spec
        self.api_key = api_key
        self.minecraft_version = minecraft_version
        self.loader = loader
        self.show_progress = show_progress

        if session is None:
            self.session = build_session(extra_headers={"X-Api-Key": api_key})
        else:
            self.session = session
            self.session.headers["X-Api-Key"] = api_key

    @staticmethod
    def parse_mod_spec(spec: str) -> tuple[str | int, int | None]:
        """Return (slug_or_project_id, file_id_or_None).

        - Full URL  → slug extracted from the last path segment
        - ``slug:file_id`` or ``project_id:file_id`` → both parts parsed
        - Numeric string → project ID
        - Plain string → slug
        """
        if spec.startswith("http"):
            slug = spec.rstrip("/").split("/")[-1]
            return slug, None
        if ":" in spec:
            left, right = spec.split(":", 1)
            project: str | int = int(left) if left.isdigit() else left
            return project, int(right)
        if spec.isdigit():
            return int(spec), None
        return spec, None

    def _resolve_project_id(self, slug: str) -> int:
        """Return the CurseForge project ID for the given mod slug."""
        resp = get_json(
            self.session,
            f"{_API_BASE}/v1/mods/search"
            f"?gameId={_MINECRAFT_GAME_ID}&slug={slug}&classId={_MOD_CLASS_ID}",
        )
        data = resp.get("data", [])  # type: ignore[union-attr]
        if not data:
            raise ValueError(f"CurseForge mod not found for slug '{slug}'")
        return data[0]["id"]

    def _get_latest_file(self, project_id: int) -> dict:
        """Return the newest compatible file object for *project_id*."""
        params: list[str] = []
        if self.minecraft_version:
            params.append(f"gameVersion={self.minecraft_version}")
        if self.loader:
            loader_type = _LOADER_TYPE_MAP.get(self.loader.lower())
            if loader_type is not None:
                params.append(f"modLoaderType={loader_type}")
        url = f"{_API_BASE}/v1/mods/{project_id}/files"
        if params:
            url += "?" + "&".join(params)
        resp = get_json(self.session, url)
        files = resp["data"]  # type: ignore[index]
        if not files:
            raise ValueError(f"No files found for CurseForge mod {project_id}")
        return files[0]

    def install(self, output_dir: Path) -> str:
        """Download the mod JAR to ``output_dir/mods/``.

        Returns the relative path written (e.g. ``"mods/jei-1.21.1-18.0.0.1.jar"``).
        """
        project, file_id = self.parse_mod_spec(self.spec)

        project_id: int = project if isinstance(project, int) else self._resolve_project_id(project)

        if file_id is not None:
            resp = get_json(self.session, f"{_API_BASE}/v1/mods/{project_id}/files/{file_id}")
            file_obj = resp["data"]  # type: ignore[index]
        else:
            file_obj = self._get_latest_file(project_id)

        url = _download_url_for_file(file_obj)
        filename = file_obj["fileName"]
        dest = output_dir / "mods" / filename
        hashes = file_obj.get("hashes", [])
        sha1 = next((h["value"] for h in hashes if h.get("algo") == 1), None)
        download_file(
            url, dest, session=self.session, expected_sha1=sha1, show_progress=self.show_progress
        )
        return str(Path("mods") / filename)


# Module-level alias so parse_mod_spec can be imported directly
parse_mod_spec = CurseForgeModInstaller.parse_mod_spec
