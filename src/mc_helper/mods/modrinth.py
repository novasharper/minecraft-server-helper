"""Modrinth individual mod installer.

Reference: mc-image-helper/.../modrinth/ (version resolution)
Reference: docker-minecraft-server/docs/variables.md (MODRINTH_PROJECTS formats)

Spec formats:
  fabric-api                → latest release for mc/loader
  fabric-api:0.119.2+1.21.4 → specific version number
  P7dR8mSH                  → project ID (latest release)
  P7dR8mSH:abc123           → project ID + version ID
"""

from pathlib import Path

import requests

from mc_helper.http_client import build_session, download_file
from mc_helper.modrinth_api import pick_primary_file, resolve_version


class ModrinthModInstaller:
    """Downloads a single Modrinth mod JAR, including required dependencies."""

    def __init__(
        self,
        spec: str,
        minecraft_version: str | None = None,
        loader: str | None = None,
        version_type: str = "release",
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.spec = spec
        self.minecraft_version = minecraft_version
        self.loader = loader
        self.version_type = version_type
        self.session = session or build_session()
        self.show_progress = show_progress

    @staticmethod
    def parse_mod_spec(spec: str) -> tuple[str, str]:
        """Return (project_slug_or_id, version_or_LATEST).

        Splits on the first colon: ``fabric-api:0.119.2+1.21.4``
        → ``("fabric-api", "0.119.2+1.21.4")``.
        Bare specs return ``"LATEST"`` as the version.
        """
        if ":" in spec:
            slug, version = spec.split(":", 1)
            return slug, version
        return spec, "LATEST"

    def install(self, output_dir: Path) -> str:
        """Download the mod JAR to ``output_dir/mods/``.

        Returns the relative path written (e.g. ``"mods/fabric-api-0.x.x.jar"``).
        Required dependencies are fetched recursively.
        """
        return self._install(output_dir, set())

    def _install(self, output_dir: Path, installed_projects: set[str]) -> str:
        project, requested_version = self.parse_mod_spec(self.spec)
        version = resolve_version(
            self.session,
            project,
            self.minecraft_version,
            self.loader,
            self.version_type,
            requested_version,
        )

        project_id = version.get("project_id", project)
        if project_id in installed_projects:
            return str(Path("mods") / pick_primary_file(version)[1])
        installed_projects.add(project_id)

        url, filename, sha1, sha512 = pick_primary_file(version)
        dest = output_dir / "mods" / filename
        effective_sha1 = sha1 if not sha512 else None
        download_file(
            url,
            dest,
            session=self.session,
            expected_sha512=sha512,
            expected_sha1=effective_sha1,
            show_progress=self.show_progress,
        )

        for dep in version.get("dependencies", []):
            if dep.get("dependency_type") != "required":
                continue
            dep_project_id = dep.get("project_id")
            if not dep_project_id or dep_project_id in installed_projects:
                continue
            dep_version_id = dep.get("version_id")
            dep_spec = f"{dep_project_id}:{dep_version_id}" if dep_version_id else dep_project_id
            dep_installer = ModrinthModInstaller(
                dep_spec,
                minecraft_version=self.minecraft_version,
                loader=self.loader,
                version_type=self.version_type,
                session=self.session,
                show_progress=self.show_progress,
            )
            dep_installer._install(output_dir, installed_projects)

        return str(Path("mods") / filename)


# Module-level alias so parse_mod_spec can be imported directly
parse_mod_spec = ModrinthModInstaller.parse_mod_spec
