"""Auto-detect Minecraft and mod-loader versions from a pre-assembled server pack root.

Detection order (first match wins):
1. forge-auto-install.txt sidecar (covers Forge + NeoForge)
2. Filename heuristics at pack root (Fabric, Paper, Purpur, Vanilla, legacy Forge jar)
3. Installer-jar inspection (version.json / install_profile.json inside *-installer.jar)
"""

import json
import logging
import re
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

_AUTO_INSTALL_FILE = "forge-auto-install.txt"


def _parse_forge_auto_install(path: Path) -> tuple[str | None, str | None, str | None]:
    """Parse forge-auto-install.txt → (mc_version, loader_type, loader_version)."""
    props: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                props[k.strip()] = v.strip()
    except OSError:
        return None, None, None

    mc_version = props.get("minecraftVersion") or None
    if mc_version and mc_version.lower() == "latest":
        mc_version = None

    loader_type = (props.get("loaderType") or "").lower() or None
    if loader_type and loader_type not in ("forge", "neoforge"):
        log.debug("Unknown loaderType %r in forge-auto-install.txt; ignoring", loader_type)
        loader_type = None

    loader_version = props.get("loaderVersion") or None
    if loader_version and loader_version.lower() in ("latest", "recommended"):
        loader_version = None

    return mc_version, loader_type, loader_version


def _filename_heuristics(pack_root: Path) -> tuple[str | None, str | None, str | None]:
    """Detect loader type + MC version from files at *pack_root*."""
    mc_version: str | None = None
    loader_type: str | None = None
    loader_version: str | None = None

    # Fabric: launcher jar / properties file
    if (pack_root / "fabric-server-launch.jar").exists() or (
        pack_root / "fabric-server-launcher.jar"
    ).exists():
        loader_type = "fabric"

    fabric_props = pack_root / "fabric-server-launcher.properties"
    if fabric_props.exists():
        loader_type = "fabric"
        try:
            for line in fabric_props.read_text().splitlines():
                line = line.strip()
                if line.startswith("serverJar="):
                    jar_name = line.split("=", 1)[1].strip()
                    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", jar_name)
                    if m:
                        mc_version = m.group(1)
        except OSError:
            pass

    if loader_type:
        return mc_version, loader_type, loader_version

    # Paper
    for jar in sorted(pack_root.glob("paper-*.jar")):
        m = re.match(r"paper-(\d+\.\d+(?:\.\d+)?)-\d+\.jar$", jar.name)
        if m:
            return m.group(1), "paper", None

    # Purpur
    for jar in sorted(pack_root.glob("purpur-*.jar")):
        m = re.match(r"purpur-(\d+\.\d+(?:\.\d+)?)-\d+\.jar$", jar.name)
        if m:
            return m.group(1), "purpur", None

    # Vanilla
    for jar in sorted(pack_root.glob("minecraft_server.*.jar")):
        m = re.match(r"minecraft_server\.(\d+\.\d+(?:\.\d+)?)\.jar$", jar.name)
        if m:
            return m.group(1), "vanilla", None

    # Legacy Forge universal jar (pre-1.17): forge-<mc>-<ver>-universal.jar or forge-<mc>-<ver>.jar
    for jar in sorted(pack_root.glob("forge-*.jar")):
        # Skip installer jars — handled by _inspect_installer_jar
        if "installer" in jar.name:
            continue
        m = re.match(r"forge-(\d+\.\d+(?:\.\d+)?)-([^-]+(?:-\S+)?)(?:-universal)?\.jar$", jar.name)
        if m:
            return m.group(1), "forge", m.group(2).rstrip("-universal").strip("-")

    return None, None, None


def _inspect_installer_jar(jar_path: Path) -> tuple[str | None, str | None, str | None]:
    """Read version metadata from a Forge/NeoForge installer jar (opened as ZIP)."""
    try:
        with zipfile.ZipFile(jar_path) as zf:
            names = set(zf.namelist())

            if "version.json" in names:
                data = json.loads(zf.read("version.json"))
                version_id: str = data.get("id", "")
                inherits_from: str | None = data.get("inheritsFrom")

                mc_version = inherits_from
                if mc_version is None:
                    m = re.match(r"(\d+\.\d+(?:\.\d+)?)", version_id)
                    mc_version = m.group(1) if m else None

                if "neoforge" in version_id.lower():
                    m = re.search(r"neoforge-(\S+)", version_id, re.IGNORECASE)
                    return mc_version, "neoforge", m.group(1) if m else None
                if "forge" in version_id.lower():
                    m = re.search(r"forge-(\S+)", version_id, re.IGNORECASE)
                    return mc_version, "forge", m.group(1) if m else None
                return mc_version, None, None

            # Fallback: install_profile.json (older Forge)
            if "install_profile.json" in names:
                data = json.loads(zf.read("install_profile.json"))
                version_id = (data.get("versionInfo") or {}).get("id") or data.get("version", "")
                m = re.match(r"(\d+\.\d+(?:\.\d+)?)-forge-(\S+)", version_id)
                if m:
                    return m.group(1), "forge", m.group(2)

    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError):
        pass

    return None, None, None


def detect_pack_versions(pack_root: Path) -> tuple[str | None, str | None, str | None]:
    """Return (mc_version, loader_type, loader_version) detected from *pack_root*.

    Any field may be None. Never raises.
    """
    auto_install = pack_root / _AUTO_INSTALL_FILE
    if auto_install.exists():
        mc, lt, lv = _parse_forge_auto_install(auto_install)
        if mc or lt:
            log.debug("forge-auto-install.txt: mc=%s loader=%s ver=%s", mc, lt, lv)
            return mc, lt, lv

    mc, lt, lv = _filename_heuristics(pack_root)
    if mc or lt:
        log.debug("filename heuristics: mc=%s loader=%s ver=%s", mc, lt, lv)
        return mc, lt, lv

    for jar in sorted(pack_root.glob("*-installer.jar")):
        mc, lt, lv = _inspect_installer_jar(jar)
        if mc or lt:
            log.debug("installer jar %s: mc=%s loader=%s ver=%s", jar.name, mc, lt, lv)
            return mc, lt, lv

    return None, None, None
