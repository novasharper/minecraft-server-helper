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
    assert cfg.server.minecraft_version is None
    assert cfg.server.loader_version == "LATEST"
    assert cfg.server.eula is False
    assert cfg.server.memory == "1G"
    assert cfg.server.properties == {}


def test_server_invalid_type():
    with pytest.raises(ValidationError):
        RootConfig.model_validate({"server": {"type": "invalid"}})


def test_server_type_optional_with_modpack():
    data = {
        "server": {"eula": True},
        "modpack": {"platform": "modrinth", "source": {"project": "fabric-api"}},
    }
    cfg = RootConfig.model_validate(data)
    assert cfg.server.type is None


def test_server_type_optional_with_github_modpack():
    data = {
        "server": {"eula": True},
        "modpack": {"platform": "github", "source": {"repo": "owner/repo"}},
    }
    cfg = RootConfig.model_validate(data)
    assert cfg.server.type is None


def test_server_type_optional_with_url_modpack():
    data = {
        "server": {"eula": True},
        "modpack": {"platform": "url", "source": {"url": "https://example.com/pack.zip"}},
    }
    cfg = RootConfig.model_validate(data)
    assert cfg.server.type is None


def test_server_type_required_without_modpack():
    with pytest.raises(ValidationError, match="server.type is required"):
        RootConfig.model_validate({"server": {}})


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


def test_modpack_and_mods_allowed():
    data = _minimal_data(
        modpack={"platform": "modrinth", "source": {"project": "fabric-api"}},
        mods={"modrinth": ["fabric-api"]},
    )
    cfg = RootConfig.model_validate(data)
    assert cfg.modpack is not None
    assert cfg.mods is not None


# ── ModpackConfig ─────────────────────────────────────────────────────────────


def test_modrinth_modpack_valid():
    data = _minimal_data(
        modpack={"platform": "modrinth", "source": {"project": "better-mc-fabric"}}
    )
    cfg = RootConfig.model_validate(data)
    assert cfg.modpack.platform == "modrinth"
    assert cfg.modpack.source.project == "better-mc-fabric"
    assert cfg.modpack.source.version == "LATEST"
    assert cfg.modpack.source.version_type == "release"


def test_modrinth_modpack_missing_project():
    data = _minimal_data(modpack={"platform": "modrinth", "source": {}})
    with pytest.raises(ValidationError, match="project"):
        RootConfig.model_validate(data)


def test_curseforge_modpack_valid():
    data = _minimal_data(
        modpack={
            "platform": "curseforge",
            "source": {"api_key": "abc123", "slug": "all-the-mods-9"},
        }
    )
    cfg = RootConfig.model_validate(data)
    assert cfg.modpack.source.slug == "all-the-mods-9"


def test_curseforge_modpack_missing_api_key():
    data = _minimal_data(
        modpack={"platform": "curseforge", "source": {"slug": "atm9"}}
    )
    with pytest.raises(ValidationError, match="api_key"):
        RootConfig.model_validate(data)


def test_curseforge_modpack_missing_slug_and_file_id():
    data = _minimal_data(
        modpack={"platform": "curseforge", "source": {"api_key": "abc"}}
    )
    with pytest.raises(ValidationError, match="slug"):
        RootConfig.model_validate(data)


# ── GitHub / URL modpack platforms ───────────────────────────────────────────


def test_github_modpack_valid():
    data = _minimal_data(
        modpack={
            "platform": "github",
            "source": {"repo": "ATM-Team/ATM-10", "tag": "v10.0", "asset": "*server*"},
        }
    )
    cfg = RootConfig.model_validate(data)
    assert cfg.modpack.source.repo == "ATM-Team/ATM-10"
    assert cfg.modpack.source.tag == "v10.0"
    assert cfg.modpack.source.strip_components == 0
    assert cfg.modpack.source.force_update is False


def test_github_modpack_missing_repo():
    data = _minimal_data(
        modpack={"platform": "github", "source": {"tag": "v1.0"}}
    )
    with pytest.raises(ValidationError, match="repo"):
        RootConfig.model_validate(data)


def test_url_modpack_valid():
    data = _minimal_data(
        modpack={
            "platform": "url",
            "source": {"url": "https://example.com/pack.zip"},
        }
    )
    cfg = RootConfig.model_validate(data)
    assert cfg.modpack.source.url == "https://example.com/pack.zip"


def test_url_modpack_missing_url():
    data = _minimal_data(
        modpack={"platform": "url", "source": {}}
    )
    with pytest.raises(ValidationError, match="url"):
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
        "modpack:\n  platform: curseforge\n"
        "  source:\n    api_key: ${CF_API_KEY}\n    slug: atm9\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.modpack.source.api_key == "test-key-123"


def test_load_config_missing_env_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("CF_API_KEY", raising=False)
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "server:\n  type: vanilla\n"
        "modpack:\n  platform: curseforge\n"
        "  source:\n    api_key: ${CF_API_KEY}\n    slug: atm9\n"
    )
    with pytest.raises(ValueError, match="CF_API_KEY"):
        load_config(cfg_file)
