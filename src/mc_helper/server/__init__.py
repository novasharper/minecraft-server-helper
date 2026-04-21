from __future__ import annotations

import requests

from mc_helper.config import ServerConfig

from . import fabric as _fabric_mod
from . import forge as _forge_mod
from . import neoforge as _neoforge_mod
from . import paper as _paper_mod
from . import purpur as _purpur_mod
from . import vanilla as _vanilla_mod
from .base import ServerInstaller
from .vanilla import resolve_version

_INSTALLER_MODULE_ATTR: dict[str, tuple[object, str]] = {
    "vanilla": (_vanilla_mod, "VanillaInstaller"),
    "fabric": (_fabric_mod, "FabricInstaller"),
    "forge": (_forge_mod, "ForgeInstaller"),
    "neoforge": (_neoforge_mod, "NeoForgeInstaller"),
    "paper": (_paper_mod, "PaperInstaller"),
    "purpur": (_purpur_mod, "PurpurInstaller"),
}


def installer_for(config: ServerConfig, session: requests.Session | None = None) -> ServerInstaller:
    """Return the appropriate installer instance for *config.type*."""
    server_type = config.type or "vanilla"
    entry = _INSTALLER_MODULE_ATTR.get(server_type)
    if entry is None:
        raise ValueError(f"Unknown server type: {server_type!r}")
    mod, attr = entry
    cls = getattr(mod, attr)
    return cls(config, session=session)


def resolve_minecraft_version(session: requests.Session, version: str | None) -> str | None:
    """Resolve 'LATEST'/'SNAPSHOT' to a concrete version; pass through everything else."""
    if not version or version.upper() not in ("LATEST", "SNAPSHOT"):
        return version
    return resolve_version(session, version)
