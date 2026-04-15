import pytest
from pydantic import ValidationError

from mc_helper.config import (
    RootConfig,
    _interpolate_env,
    _interpolate_obj,
    load_config,
)

# ── _interpolate_env ──────────────────────────────────────────────────────────


def test_interpolate_env_substitutes(monkeypatch):
    monkeypatch.setenv("MY_VAR", "hello")
    assert _interpolate_env("prefix_${MY_VAR}_suffix") == "prefix_hello_suffix"


def test_interpolate_env_multiple(monkeypatch):
    monkeypatch.setenv("A", "foo")
    monkeypatch.setenv("B", "bar")
    assert _interpolate_env("${A}-${B}") == "foo-bar"


def test_interpolate_env_missing_raises(monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    with pytest.raises(ValueError, match="MISSING_VAR"):
        _interpolate_env("${MISSING_VAR}")


def test_interpolate_env_no_vars():
    assert _interpolate_env("no vars here") == "no vars here"


def test_interpolate_obj_nested(monkeypatch):
    monkeypatch.setenv("KEY", "secret")
    data = {"a": "${KEY}", "b": ["${KEY}", 1], "c": {"d": "${KEY}"}}
    result = _interpolate_obj(data)
    assert result == {"a": "secret", "b": ["secret", 1], "c": {"d": "secret"}}


# ── ServerConfig defaults ─────────────────────────────────────────────────────


def _minimal_data(**overrides):
    data = {"server": {"type": "vanilla"}}
    data.update(overrides)
    return data


def test_server_defaults():
    cfg = RootConfig.model_validate(_minimal_data())
    assert cfg.server.minecraft_version == "LATEST"
    assert cfg.server.loader_version == "LATEST"
    assert cfg.server.eula is False
    assert cfg.server.memory == "1G"
    assert cfg.server.properties == {}


def test_server_invalid_type():
    with pytest.raises(ValidationError):
        RootConfig.model_validate({"server": {"type": "invalid"}})


def test_server_properties():
    data = _minimal_data()
    data["server"]["properties"] = {"max_players": 10, "online_mode": False}
    cfg = RootConfig.model_validate(data)
    assert cfg.server.properties["max_players"] == 10


# ── Mutual exclusion ──────────────────────────────────────────────────────────


def test_no_content_sections_ok():
    cfg = RootConfig.model_validate(_minimal_data())
    assert cfg.modpack is None
    assert cfg.mods is None
    assert cfg.server_pack is None


def test_modpack_and_mods_raises():
    data = _minimal_data(
        modpack={"platform": "modrinth", "project": "fabric-api"},
        mods={"modrinth": ["fabric-api"]},
    )
    with pytest.raises(ValidationError, match="modpack"):
        RootConfig.model_validate(data)


def test_modpack_and_server_pack_raises():
    data = _minimal_data(
        modpack={"platform": "modrinth", "project": "fabric-api"},
        server_pack={"url": "https://example.com/pack.zip"},
    )
    with pytest.raises(ValidationError, match="modpack"):
        RootConfig.model_validate(data)


def test_mods_and_server_pack_raises():
    data = _minimal_data(
        mods={"modrinth": ["fabric-api"]},
        server_pack={"url": "https://example.com/pack.zip"},
    )
    with pytest.raises(ValidationError, match="mods"):
        RootConfig.model_validate(data)


# ── ModpackConfig ─────────────────────────────────────────────────────────────


def test_modrinth_modpack_valid():
    data = _minimal_data(modpack={"platform": "modrinth", "project": "better-mc-fabric"})
    cfg = RootConfig.model_validate(data)
    assert cfg.modpack.platform == "modrinth"
    assert cfg.modpack.project == "better-mc-fabric"
    assert cfg.modpack.version == "LATEST"
    assert cfg.modpack.version_type == "release"


def test_modrinth_modpack_missing_project():
    data = _minimal_data(modpack={"platform": "modrinth"})
    with pytest.raises(ValidationError, match="project"):
        RootConfig.model_validate(data)


def test_curseforge_modpack_valid():
    data = _minimal_data(
        modpack={"platform": "curseforge", "api_key": "abc123", "slug": "all-the-mods-9"}
    )
    cfg = RootConfig.model_validate(data)
    assert cfg.modpack.slug == "all-the-mods-9"


def test_curseforge_modpack_missing_api_key():
    data = _minimal_data(modpack={"platform": "curseforge", "slug": "atm9"})
    with pytest.raises(ValidationError, match="api_key"):
        RootConfig.model_validate(data)


def test_curseforge_modpack_missing_slug_and_file_id():
    data = _minimal_data(modpack={"platform": "curseforge", "api_key": "abc"})
    with pytest.raises(ValidationError, match="slug"):
        RootConfig.model_validate(data)


# ── ModsConfig ────────────────────────────────────────────────────────────────


def test_mods_modrinth_only():
    data = _minimal_data(mods={"modrinth": ["fabric-api", "sodium"]})
    cfg = RootConfig.model_validate(data)
    assert cfg.mods.modrinth == ["fabric-api", "sodium"]


def test_mods_urls_only():
    data = _minimal_data(mods={"urls": ["https://example.com/mod.jar"]})
    cfg = RootConfig.model_validate(data)
    assert cfg.mods.urls == ["https://example.com/mod.jar"]


def test_mods_empty_raises():
    data = _minimal_data(mods={})
    with pytest.raises(ValidationError, match="at least one"):
        RootConfig.model_validate(data)


def test_mods_curseforge():
    data = _minimal_data(mods={"curseforge": {"api_key": "key", "files": ["jei"]}})
    cfg = RootConfig.model_validate(data)
    assert cfg.mods.curseforge.files == ["jei"]


# ── ServerPackConfig ──────────────────────────────────────────────────────────


def test_server_pack_direct_url():
    data = _minimal_data(server_pack={"url": "https://example.com/pack.zip"})
    cfg = RootConfig.model_validate(data)
    assert cfg.server_pack.url == "https://example.com/pack.zip"
    assert cfg.server_pack.strip_components == 0
    assert cfg.server_pack.force_update is False


def test_server_pack_github():
    data = _minimal_data(server_pack={"github": "ATM-Team/ATM-10", "tag": "v10.0"})
    cfg = RootConfig.model_validate(data)
    assert cfg.server_pack.github == "ATM-Team/ATM-10"
    assert cfg.server_pack.tag == "v10.0"


def test_server_pack_both_url_and_github_raises():
    data = _minimal_data(
        server_pack={"url": "https://example.com/pack.zip", "github": "owner/repo"}
    )
    with pytest.raises(ValidationError, match="only one"):
        RootConfig.model_validate(data)


def test_server_pack_neither_raises():
    data = _minimal_data(server_pack={"tag": "LATEST"})
    with pytest.raises(ValidationError, match="one of"):
        RootConfig.model_validate(data)


# ── load_config ───────────────────────────────────────────────────────────────


def test_load_config_vanilla(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("server:\n  type: vanilla\n  minecraft_version: '1.21.1'\n")
    cfg = load_config(cfg_file)
    assert cfg.server.type == "vanilla"
    assert cfg.server.minecraft_version == "1.21.1"


def test_load_config_env_interpolation(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_API_KEY", "test-key-123")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "server:\n  type: vanilla\n"
        "modpack:\n  platform: curseforge\n  api_key: ${CF_API_KEY}\n  slug: atm9\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.modpack.api_key == "test-key-123"


def test_load_config_missing_env_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("CF_API_KEY", raising=False)
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "server:\n  type: vanilla\n"
        "modpack:\n  platform: curseforge\n  api_key: ${CF_API_KEY}\n  slug: atm9\n"
    )
    with pytest.raises(ValueError, match="CF_API_KEY"):
        load_config(cfg_file)
