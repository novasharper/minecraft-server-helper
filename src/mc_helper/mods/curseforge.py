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

from mc_helper.curseforge_api import CurseForgeClient
from mc_helper.http_client import build_session, download_file


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
        self.minecraft_version = minecraft_version
        self.loader = loader
        self.show_progress = show_progress

        if session is None:
            self.session = build_session(extra_headers={"X-Api-Key": api_key})
        else:
            self.session = session
            self.session.headers["X-Api-Key"] = api_key

        self.cf = CurseForgeClient(api_key, session=self.session)

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

    def install(self, output_dir: Path) -> str:
        """Download the mod JAR to ``output_dir/mods/``.

        Returns the relative path written (e.g. ``"mods/jei-1.21.1-18.0.0.1.jar"``).
        """
        project, file_id = self.parse_mod_spec(self.spec)

        if isinstance(project, int):
            project_id = project
        else:
            mod_obj = self.cf.search_by_slug(project, class_id=6)
            if mod_obj is None:
                raise ValueError(f"CurseForge mod not found for slug '{project}'")
            project_id = mod_obj["id"]

        if file_id is not None:
            file_obj = self.cf.get_mod_file(project_id, file_id)
        else:
            file_obj = self.cf.get_latest_file(
                project_id,
                minecraft_version=self.minecraft_version,
                loader=self.loader,
            )

        url = CurseForgeClient.download_url_for(file_obj)
        filename = file_obj["fileName"]
        dest = output_dir / "mods" / filename
        sha1 = CurseForgeClient.sha1_of(file_obj)
        download_file(
            url, dest, session=self.session, expected_sha1=sha1, show_progress=self.show_progress
        )
        return str(Path("mods") / filename)


# Module-level alias so parse_mod_spec can be imported directly
parse_mod_spec = CurseForgeModInstaller.parse_mod_spec
