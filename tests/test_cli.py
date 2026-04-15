"""Tests for cli.py — Phase 7: setup dispatch, server file writing, status command."""

import json
import stat
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest
import yaml

# ── helpers ───────────────────────────────────────────────────────────────────


def _write_config(tmp_path: Path, data: dict) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.dump(data))
    return cfg


def _base_config(server_type: str = "vanilla", **extra) -> dict:
    cfg = {
        "server": {
            "type": server_type,
            "minecraft_version": "1.21.1",
            "output_dir": "PLACEHOLDER",  # overridden per test
            "eula": True,
            "memory": "2G",
            "properties": {
                "difficulty": "normal",
                "max-players": 20,
                "motd": "Test Server",
            },
        }
    }
    cfg["server"].update(extra)
    return cfg


# ── _write_server_files ───────────────────────────────────────────────────────


class TestWriteServerFiles:
    def _call(self, config_data: dict, tmp_path: Path, jar_path=None, dry_run=False):
        config_data["server"]["output_dir"] = str(tmp_path)
        cfg_file = _write_config(tmp_path, config_data)
        from mc_helper.cli import _write_server_files
        from mc_helper.config import load_config

        config = load_config(cfg_file)
        _write_server_files(config, tmp_path, jar_path, dry_run)
        return tmp_path

    def test_eula_true(self, tmp_path):
        self._call(_base_config(eula=True), tmp_path)
        assert (tmp_path / "eula.txt").read_text() == "eula=true\n"

    def test_eula_false(self, tmp_path):
        self._call(_base_config(eula=False), tmp_path)
        assert (tmp_path / "eula.txt").read_text() == "eula=false\n"

    def test_server_properties_written(self, tmp_path):
        self._call(_base_config(), tmp_path)
        content = (tmp_path / "server.properties").read_text()
        assert "difficulty=normal\n" in content
        assert "max-players=20\n" in content
        assert "motd=Test Server\n" in content

    def test_server_properties_skipped_when_empty(self, tmp_path):
        data = _base_config()
        data["server"]["properties"] = {}
        data["server"]["output_dir"] = str(tmp_path)
        cfg_file = _write_config(tmp_path, data)
        from mc_helper.cli import _write_server_files
        from mc_helper.config import load_config

        config = load_config(cfg_file)
        _write_server_files(config, tmp_path, None, dry_run=False)
        assert not (tmp_path / "server.properties").exists()

    def test_launch_sh_with_jar(self, tmp_path):
        jar = tmp_path / "minecraft_server.1.21.1.jar"
        jar.touch()
        self._call(_base_config(memory="4G"), tmp_path, jar_path=jar)
        content = (tmp_path / "launch.sh").read_text()
        assert "java -Xmx4G -Xms4G -jar minecraft_server.1.21.1.jar nogui" in content

    def test_launch_sh_executable(self, tmp_path):
        self._call(_base_config(), tmp_path)
        mode = (tmp_path / "launch.sh").stat().st_mode
        assert mode & stat.S_IXUSR

    def test_launch_sh_forge_no_jar(self, tmp_path):
        self._call(_base_config(server_type="forge"), tmp_path, jar_path=None)
        content = (tmp_path / "launch.sh").read_text()
        assert "run.sh" in content

    def test_launch_sh_neoforge_no_jar(self, tmp_path):
        self._call(_base_config(server_type="neoforge"), tmp_path, jar_path=None)
        content = (tmp_path / "launch.sh").read_text()
        assert "run.sh" in content

    def test_dry_run_writes_nothing(self, tmp_path, capsys):
        self._call(_base_config(), tmp_path, dry_run=True)
        assert not (tmp_path / "eula.txt").exists()
        assert not (tmp_path / "server.properties").exists()
        assert not (tmp_path / "launch.sh").exists()
        captured = capsys.readouterr()
        assert "[dry-run]" in captured.out

    def test_server_properties_merge_preserves_comments(self, tmp_path):
        """Re-running setup must preserve # comments and blank lines the server wrote."""
        props_path = tmp_path / "server.properties"
        props_path.write_text(
            "# Minecraft server properties\n"
            "\n"
            "difficulty=easy\n"
            "max-players=10\n"
            "# Another comment\n"
            "level-seed=abc123\n"
        )
        # Config overrides difficulty and max-players; level-seed and comments untouched
        self._call(_base_config(), tmp_path)
        result = props_path.read_text()
        assert "# Minecraft server properties" in result
        assert "# Another comment" in result
        assert "level-seed=abc123" in result
        assert "difficulty=normal" in result   # overwritten by config
        assert "max-players=20" in result      # overwritten by config

    def test_server_properties_merge_appends_new_keys(self, tmp_path):
        """Keys in config that are not in the existing file must be appended."""
        props_path = tmp_path / "server.properties"
        props_path.write_text("difficulty=easy\n")
        self._call(_base_config(), tmp_path)
        result = props_path.read_text()
        assert "motd=Test Server" in result


# ── _install_server_jar ───────────────────────────────────────────────────────


class TestInstallServerJar:
    def _config(self, tmp_path: Path, server_type: str):
        data = _base_config(server_type=server_type)
        data["server"]["output_dir"] = str(tmp_path)
        cfg_file = _write_config(tmp_path, data)
        from mc_helper.config import load_config

        return load_config(cfg_file)

    def test_dry_run_returns_none_and_prints(self, tmp_path, capsys):
        from mc_helper.cli import _install_server_jar

        config = self._config(tmp_path, "vanilla")
        result = _install_server_jar(config, tmp_path, dry_run=True)
        assert result is None
        assert "[dry-run]" in capsys.readouterr().out

    def test_vanilla_dispatches(self, tmp_path):
        from mc_helper.cli import _install_server_jar

        config = self._config(tmp_path, "vanilla")
        fake_jar = tmp_path / "minecraft_server.1.21.1.jar"
        with patch("mc_helper.server.vanilla.install", return_value=fake_jar) as mock_install:
            result = _install_server_jar(config, tmp_path, dry_run=False)
        mock_install.assert_called_once()
        assert result == fake_jar

    def test_fabric_dispatches(self, tmp_path):
        from mc_helper.cli import _install_server_jar

        config = self._config(tmp_path, "fabric")
        fake_jar = tmp_path / "fabric-server-launch.jar"
        with patch("mc_helper.server.fabric.install", return_value=fake_jar) as mock_install:
            result = _install_server_jar(config, tmp_path, dry_run=False)
        mock_install.assert_called_once()
        assert result == fake_jar

    def test_forge_dispatches_returns_none(self, tmp_path):
        from mc_helper.cli import _install_server_jar

        config = self._config(tmp_path, "forge")
        with patch("mc_helper.server.forge.install") as mock_install:
            result = _install_server_jar(config, tmp_path, dry_run=False)
        mock_install.assert_called_once()
        assert result is None

    def test_paper_dispatches(self, tmp_path):
        from mc_helper.cli import _install_server_jar

        config = self._config(tmp_path, "paper")
        fake_jar = tmp_path / "paper-1.21.1-123.jar"
        with patch("mc_helper.server.paper.install", return_value=fake_jar):
            result = _install_server_jar(config, tmp_path, dry_run=False)
        assert result == fake_jar

    def test_purpur_dispatches(self, tmp_path):
        from mc_helper.cli import _install_server_jar

        config = self._config(tmp_path, "purpur")
        fake_jar = tmp_path / "purpur-1.21.1-2271.jar"
        with patch("mc_helper.server.purpur.install", return_value=fake_jar):
            result = _install_server_jar(config, tmp_path, dry_run=False)
        assert result == fake_jar

    def test_latest_minecraft_version_resolved_before_installer(self, tmp_path):
        """'LATEST' must be resolved to a concrete version before calling the installer."""
        from mc_helper.cli import _install_server_jar

        data = _base_config("paper")
        data["server"]["minecraft_version"] = "LATEST"
        data["server"]["output_dir"] = str(tmp_path)
        cfg_file = _write_config(tmp_path, data)
        from mc_helper.config import load_config
        config = load_config(cfg_file)

        fake_jar = tmp_path / "paper-1.21.4-200.jar"
        with (
            patch(
                "mc_helper.cli.resolve_version", return_value="1.21.4"
            ) as mock_resolve,
            patch("mc_helper.server.paper.install", return_value=fake_jar) as mock_paper,
        ):
            result = _install_server_jar(config, tmp_path, dry_run=False)

        mock_resolve.assert_called_once_with(ANY, "LATEST")
        # Paper must be called with the resolved version, not the string "LATEST"
        call_args = mock_paper.call_args
        assert call_args.args[0] == "1.21.4"
        assert result == fake_jar


# ── status command ────────────────────────────────────────────────────────────


class TestCmdStatus:
    def _make_args(self, cfg_path: Path) -> MagicMock:
        args = MagicMock()
        args.config = str(cfg_path)
        return args

    def test_no_manifest(self, tmp_path, capsys):
        data = _base_config()
        data["server"]["output_dir"] = str(tmp_path)
        cfg_file = _write_config(tmp_path, data)
        from mc_helper.cli import _cmd_status

        _cmd_status(self._make_args(cfg_file))
        out = capsys.readouterr().out
        assert "not been set up" in out

    def test_manifest_displayed(self, tmp_path, capsys):
        data = _base_config()
        data["server"]["output_dir"] = str(tmp_path)
        cfg_file = _write_config(tmp_path, data)

        # Write a manifest
        manifest_data = {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "mc_version": "1.21.1",
            "loader_type": "fabric",
            "loader_version": "0.16.0",
            "files": ["mods/fabric-api-0.119.2.jar"],
        }
        (tmp_path / ".mc-helper-manifest.json").write_text(json.dumps(manifest_data))

        from mc_helper.cli import _cmd_status

        _cmd_status(self._make_args(cfg_file))
        out = capsys.readouterr().out
        assert "1.21.1" in out
        assert "fabric" in out
        assert "0.16.0" in out
        assert "fabric-api-0.119.2.jar" in out

    def test_invalid_config_exits(self, tmp_path, capsys):
        bad_cfg = tmp_path / "bad.yaml"
        bad_cfg.write_text("not: valid: config: at: all:\n")
        from mc_helper.cli import _cmd_status

        with pytest.raises(SystemExit):
            _cmd_status(self._make_args(bad_cfg))


# ── setup command (integration-level) ────────────────────────────────────────


class TestCmdSetupDispatch:
    """Verify setup dispatches correctly without real network calls."""

    def _make_args(self, cfg_path: Path, output_dir: Path | None = None, dry_run=False):
        args = MagicMock()
        args.config = str(cfg_path)
        args.output_dir = str(output_dir) if output_dir else None
        args.dry_run = dry_run
        return args

    def test_vanilla_setup_dry_run(self, tmp_path, capsys):
        data = _base_config("vanilla")
        data["server"]["output_dir"] = str(tmp_path)
        cfg_file = _write_config(tmp_path, data)
        from mc_helper.cli import _cmd_setup

        _cmd_setup(self._make_args(cfg_file, dry_run=True))
        out = capsys.readouterr().out
        assert "[dry-run]" in out
        # No real files created
        assert not (tmp_path / "eula.txt").exists()

    def test_output_dir_override(self, tmp_path, capsys):
        override_dir = tmp_path / "custom_output"
        data = _base_config("vanilla")
        data["server"]["output_dir"] = str(tmp_path / "default")
        cfg_file = _write_config(tmp_path, data)
        from mc_helper.cli import _cmd_setup

        fake_jar = override_dir / "minecraft_server.1.21.1.jar"
        with patch("mc_helper.server.vanilla.install", return_value=fake_jar):
            _cmd_setup(self._make_args(cfg_file, output_dir=override_dir))

        assert (override_dir / "eula.txt").exists()
        assert (override_dir / "launch.sh").exists()
