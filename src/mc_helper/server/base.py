import subprocess
from pathlib import Path

import requests

from mc_helper.config import ServerConfig
from mc_helper.http_client import build_session


class ServerInstaller:
    """Base class for all server-type installers."""

    def __init__(
        self,
        config: ServerConfig,
        session: requests.Session | None = None,
        show_progress: bool = True,
    ) -> None:
        self.config = config
        self.session = session or build_session()
        self.show_progress = show_progress

    def install(self, output_dir: Path) -> Path | None:
        raise NotImplementedError


def run_java_installer(installer_jar: Path, cwd: Path) -> Path:
    """Run `java -jar <installer_jar> --installServer` in *cwd*.

    Cleans up the installer JAR and its log file afterwards.
    Returns ``cwd / "run.sh"``.
    """
    try:
        subprocess.run(
            ["java", "-jar", str(installer_jar), "--installServer"],
            cwd=cwd,
            check=True,
        )
    finally:
        installer_jar.unlink(missing_ok=True)
        installer_jar.with_suffix(installer_jar.suffix + ".log").unlink(missing_ok=True)
    return cwd / "run.sh"
