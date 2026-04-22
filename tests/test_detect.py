"""Unit tests for mc_helper.modpack._detect."""

import json
import zipfile
from io import BytesIO
from pathlib import Path

from mc_helper.modpack._detect import detect_pack_versions


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _make_installer_jar(entries: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ── forge-auto-install.txt ────────────────────────────────────────────────────


def test_forge_auto_install_forge(tmp_path):
    _write(
        tmp_path / "forge-auto-install.txt",
        "minecraftVersion=1.20.1\nloaderType=forge\nloaderVersion=47.4.13\n",
    )
    assert detect_pack_versions(tmp_path) == ("1.20.1", "forge", "47.4.13")


def test_forge_auto_install_neoforge(tmp_path):
    _write(
        tmp_path / "forge-auto-install.txt",
        "minecraftVersion=1.21.1\nloaderType=NeoForge\nloaderVersion=latest\n",
    )
    mc, lt, lv = detect_pack_versions(tmp_path)
    assert mc == "1.21.1"
    assert lt == "neoforge"
    assert lv is None  # "latest" normalised to None


def test_forge_auto_install_comments_ignored(tmp_path):
    _write(
        tmp_path / "forge-auto-install.txt",
        "# Forge Auto-Install\nminecraftVersion=1.20.4\nloaderType=Forge\n"
        "loaderVersion=recommended\n",
    )
    mc, lt, lv = detect_pack_versions(tmp_path)
    assert mc == "1.20.4"
    assert lt == "forge"
    assert lv is None  # "recommended" normalised to None


def test_forge_auto_install_mc_latest_normalised(tmp_path):
    _write(
        tmp_path / "forge-auto-install.txt",
        "minecraftVersion=latest\nloaderType=forge\nloaderVersion=47.4.0\n",
    )
    mc, lt, lv = detect_pack_versions(tmp_path)
    assert mc is None
    assert lt == "forge"
    assert lv == "47.4.0"


# ── filename heuristics ───────────────────────────────────────────────────────


def test_fabric_launch_jar(tmp_path):
    (tmp_path / "fabric-server-launch.jar").write_bytes(b"")
    mc, lt, lv = detect_pack_versions(tmp_path)
    assert lt == "fabric"
    assert lv is None


def test_fabric_launcher_properties_with_mc_version(tmp_path):
    _write(
        tmp_path / "fabric-server-launcher.properties",
        "serverJar=minecraft_server.1.20.4.jar\n",
    )
    mc, lt, lv = detect_pack_versions(tmp_path)
    assert mc == "1.20.4"
    assert lt == "fabric"


def test_paper_jar(tmp_path):
    (tmp_path / "paper-1.21.1-132.jar").write_bytes(b"")
    mc, lt, lv = detect_pack_versions(tmp_path)
    assert mc == "1.21.1"
    assert lt == "paper"
    assert lv is None


def test_purpur_jar(tmp_path):
    (tmp_path / "purpur-1.20.1-2086.jar").write_bytes(b"")
    mc, lt, lv = detect_pack_versions(tmp_path)
    assert mc == "1.20.1"
    assert lt == "purpur"


def test_vanilla_jar(tmp_path):
    (tmp_path / "minecraft_server.1.20.4.jar").write_bytes(b"")
    mc, lt, lv = detect_pack_versions(tmp_path)
    assert mc == "1.20.4"
    assert lt == "vanilla"


def test_legacy_forge_universal_jar(tmp_path):
    (tmp_path / "forge-1.12.2-14.23.5.2860-universal.jar").write_bytes(b"")
    mc, lt, lv = detect_pack_versions(tmp_path)
    assert mc == "1.12.2"
    assert lt == "forge"


# ── installer-jar inspection ──────────────────────────────────────────────────


def test_installer_jar_version_json_forge(tmp_path):
    version_json = json.dumps({"id": "1.20.1-forge-47.4.13", "inheritsFrom": "1.20.1"}).encode()
    jar_bytes = _make_installer_jar({"version.json": version_json})
    (tmp_path / "forge-1.20.1-47.4.13-installer.jar").write_bytes(jar_bytes)
    mc, lt, lv = detect_pack_versions(tmp_path)
    assert mc == "1.20.1"
    assert lt == "forge"
    assert lv == "47.4.13"


def test_installer_jar_version_json_neoforge(tmp_path):
    version_json = json.dumps({"id": "neoforge-20.4.80-beta", "inheritsFrom": "1.20.4"}).encode()
    jar_bytes = _make_installer_jar({"version.json": version_json})
    (tmp_path / "neoforge-1.20.4-20.4.80-beta-installer.jar").write_bytes(jar_bytes)
    mc, lt, lv = detect_pack_versions(tmp_path)
    assert mc == "1.20.4"
    assert lt == "neoforge"
    assert lv == "20.4.80-beta"


def test_installer_jar_install_profile_json(tmp_path):
    profile = json.dumps({"versionInfo": {"id": "1.12.2-forge-14.23.5.2860"}}).encode()
    jar_bytes = _make_installer_jar({"install_profile.json": profile})
    (tmp_path / "forge-installer.jar").write_bytes(jar_bytes)
    mc, lt, lv = detect_pack_versions(tmp_path)
    assert mc == "1.12.2"
    assert lt == "forge"
    assert lv == "14.23.5.2860"


def test_installer_jar_bad_zip_does_not_raise(tmp_path):
    (tmp_path / "bad-installer.jar").write_bytes(b"not a zip")
    assert detect_pack_versions(tmp_path) == (None, None, None)


# ── precedence ────────────────────────────────────────────────────────────────


def test_forge_auto_install_beats_filename_heuristics(tmp_path):
    # Both signals present: auto-install.txt should win
    _write(
        tmp_path / "forge-auto-install.txt",
        "minecraftVersion=1.20.1\nloaderType=forge\nloaderVersion=47.4.13\n",
    )
    (tmp_path / "minecraft_server.1.20.4.jar").write_bytes(b"")
    mc, lt, lv = detect_pack_versions(tmp_path)
    assert mc == "1.20.1"
    assert lt == "forge"


# ── no metadata ───────────────────────────────────────────────────────────────


def test_no_metadata(tmp_path):
    (tmp_path / "mods").mkdir()
    (tmp_path / "mods" / "jei.jar").write_bytes(b"")
    assert detect_pack_versions(tmp_path) == (None, None, None)


def test_empty_directory(tmp_path):
    assert detect_pack_versions(tmp_path) == (None, None, None)
