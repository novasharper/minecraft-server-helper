"""Unit tests for src/mc_helper/launch.py."""

import stat

from mc_helper.config import JvmConfig, ServerConfig
from mc_helper.launch import (
    LaunchPlan,
    _merge_user_jvm_args,
    _patch_cf_settings_cfg,
    _patch_cf_settings_local,
    _patch_cf_variables,
    apply_launch_plan,
    detect_launch_plan,
)


def _server(memory: str = "2G", java_bin: str = "java", **jvm_extra) -> ServerConfig:
    """Build a minimal ServerConfig for launch tests."""
    return ServerConfig(
        type="vanilla",
        jvm=JvmConfig(memory=memory, java_bin=java_bin, **jvm_extra),
    )


# ── detect_launch_plan ────────────────────────────────────────────────────────


class TestDetectLaunchPlan:
    def test_jar_artifact(self, tmp_path):
        jar = tmp_path / "server.jar"
        jar.touch()
        plan = detect_launch_plan(tmp_path, jar)
        assert plan.kind == "jar"
        assert plan.start_artifact == jar

    def test_run_sh_is_run_sh_kind(self, tmp_path):
        run = tmp_path / "run.sh"
        run.write_text("#!/bin/sh\n")
        plan = detect_launch_plan(tmp_path, run)
        assert plan.kind == "run_sh"

    def test_bare_script_no_settings_files(self, tmp_path):
        start = tmp_path / "ServerStart.sh"
        start.write_text("#!/bin/sh\n")
        plan = detect_launch_plan(tmp_path, start)
        assert plan.kind == "bare_script"
        assert plan.settings_files == []

    def test_cf_script_with_settings_local(self, tmp_path):
        start = tmp_path / "ServerStart.sh"
        start.write_text("#!/bin/sh\n")
        (tmp_path / "settings-local.sh").write_text("MAX_RAM=4096M\n")
        plan = detect_launch_plan(tmp_path, start)
        assert plan.kind == "cf_script"
        assert any(sf.name == "settings-local.sh" for sf in plan.settings_files)

    def test_cf_script_with_settings_cfg(self, tmp_path):
        start = tmp_path / "start.sh"
        start.write_text("#!/bin/sh\n")
        (tmp_path / "settings.cfg").write_text("MAX_RAM=2048M\n")
        plan = detect_launch_plan(tmp_path, start)
        assert plan.kind == "cf_script"

    def test_cf_script_with_variables_txt(self, tmp_path):
        start = tmp_path / "startserver.sh"
        start.write_text("#!/bin/sh\n")
        (tmp_path / "variables.txt").write_text('JAVA_ARGS=""\n')
        plan = detect_launch_plan(tmp_path, start)
        assert plan.kind == "cf_script"

    def test_cf_script_collects_all_settings_files(self, tmp_path):
        start = tmp_path / "start.sh"
        start.write_text("#!/bin/sh\n")
        (tmp_path / "settings-local.sh").write_text("")
        (tmp_path / "settings.cfg").write_text("")
        (tmp_path / "variables.txt").write_text("")
        plan = detect_launch_plan(tmp_path, start)
        assert len(plan.settings_files) == 3


# ── apply_launch_plan — jar ───────────────────────────────────────────────────


class TestApplyJar:
    def _plan(self, tmp_path, name="server.jar"):
        artifact = tmp_path / name
        artifact.touch()
        return LaunchPlan(kind="jar", start_artifact=artifact)

    def test_launch_sh_content(self, tmp_path):
        plan = self._plan(tmp_path)
        apply_launch_plan(plan, _server("2G"), tmp_path, dry_run=False)
        content = (tmp_path / "launch.sh").read_text()
        assert "java -Xmx2G -Xms2G -jar server.jar nogui" in content

    def test_launch_sh_with_jvm_args(self, tmp_path):
        plan = self._plan(tmp_path)
        apply_launch_plan(
            plan, _server("4G", args=["-Dfoo=bar", "-XX:+UseG1GC"]), tmp_path, dry_run=False
        )
        content = (tmp_path / "launch.sh").read_text()
        assert "-Dfoo=bar" in content
        assert "-XX:+UseG1GC" in content
        assert content.index("-Dfoo=bar") < content.index("-Xmx4G")

    def test_launch_sh_custom_server_args(self, tmp_path):
        plan = self._plan(tmp_path)
        server = ServerConfig(type="vanilla", server_args=["--noconsole"])
        apply_launch_plan(plan, server, tmp_path, dry_run=False)
        content = (tmp_path / "launch.sh").read_text()
        assert "--noconsole" in content
        assert "nogui" not in content
        assert content.index("-jar") < content.index("--noconsole")

    def test_launch_sh_custom_java_bin(self, tmp_path):
        plan = self._plan(tmp_path)
        apply_launch_plan(
            plan, _server("2G", java_bin="/opt/java21/bin/java"), tmp_path, dry_run=False
        )
        content = (tmp_path / "launch.sh").read_text()
        assert content.startswith("#!/bin/sh\nexec /opt/java21/bin/java")

    def test_launch_sh_is_executable(self, tmp_path):
        plan = self._plan(tmp_path)
        apply_launch_plan(plan, _server(), tmp_path, dry_run=False)
        mode = (tmp_path / "launch.sh").stat().st_mode
        assert mode & stat.S_IXUSR

    def test_dry_run_prints_no_files_written(self, tmp_path, capsys):
        plan = self._plan(tmp_path)
        apply_launch_plan(plan, _server(), tmp_path, dry_run=True)
        assert not (tmp_path / "launch.sh").exists()
        assert "[dry-run]" in capsys.readouterr().out


# ── apply_launch_plan — run_sh ────────────────────────────────────────────────


class TestApplyRunSh:
    def _plan(self, tmp_path):
        run_sh = tmp_path / "run.sh"
        run_sh.write_text("#!/bin/sh\n")
        return LaunchPlan(kind="run_sh", start_artifact=run_sh)

    def test_launch_sh_execs_run_sh(self, tmp_path):
        plan = self._plan(tmp_path)
        apply_launch_plan(plan, _server("4G"), tmp_path, dry_run=False)
        content = (tmp_path / "launch.sh").read_text()
        assert "./run.sh" in content
        assert "java" not in content

    def test_user_jvm_args_created_with_memory(self, tmp_path):
        plan = self._plan(tmp_path)
        apply_launch_plan(plan, _server("4G"), tmp_path, dry_run=False)
        lines = (tmp_path / "user_jvm_args.txt").read_text().splitlines()
        assert "-Xmx4G" in lines
        assert "-Xms4G" in lines

    def test_user_jvm_args_includes_extra_flags(self, tmp_path):
        plan = self._plan(tmp_path)
        apply_launch_plan(plan, _server("4G", args=["-Dfoo=bar"]), tmp_path, dry_run=False)
        lines = (tmp_path / "user_jvm_args.txt").read_text().splitlines()
        assert "-Dfoo=bar" in lines

    def test_dry_run_no_files(self, tmp_path, capsys):
        plan = self._plan(tmp_path)
        apply_launch_plan(plan, _server("2G"), tmp_path, dry_run=True)
        assert not (tmp_path / "launch.sh").exists()
        assert not (tmp_path / "user_jvm_args.txt").exists()


# ── apply_launch_plan — cf_script ─────────────────────────────────────────────


class TestApplyCfScript:
    def _plan(self, tmp_path, settings_files):
        start = tmp_path / "ServerStart.sh"
        start.write_text("#!/bin/sh\n")
        return LaunchPlan(kind="cf_script", start_artifact=start, settings_files=settings_files)

    def test_patches_settings_local(self, tmp_path):
        sl = tmp_path / "settings-local.sh"
        sl.write_text("MIN_RAM=2048M\nMAX_RAM=2048M\nJAVA_PARAMETERS=\n")
        plan = self._plan(tmp_path, [sl])
        apply_launch_plan(plan, _server("8G", args=["-Dfoo=bar"]), tmp_path, dry_run=False)
        content = sl.read_text()
        assert "MIN_RAM=8192M" in content
        assert "MAX_RAM=8192M" in content
        assert "JAVA_PARAMETERS=-Dfoo=bar" in content

    def test_patches_settings_cfg(self, tmp_path):
        sc = tmp_path / "settings.cfg"
        sc.write_text("MAX_RAM=2048M\n")
        plan = self._plan(tmp_path, [sc])
        apply_launch_plan(plan, _server("4G"), tmp_path, dry_run=False)
        assert "MAX_RAM=4096M" in sc.read_text()

    def test_patches_variables_txt(self, tmp_path):
        vt = tmp_path / "variables.txt"
        vt.write_text('JAVA_ARGS=""\n')
        plan = self._plan(tmp_path, [vt])
        apply_launch_plan(plan, _server("2G", args=["-Dfoo=bar"]), tmp_path, dry_run=False)
        assert 'JAVA_ARGS="-Dfoo=bar"' in vt.read_text()

    def test_launch_sh_execs_start_script(self, tmp_path):
        sl = tmp_path / "settings-local.sh"
        sl.write_text("")
        plan = self._plan(tmp_path, [sl])
        apply_launch_plan(plan, _server("2G"), tmp_path, dry_run=False)
        content = (tmp_path / "launch.sh").read_text()
        assert "./ServerStart.sh" in content


# ── _merge_user_jvm_args ──────────────────────────────────────────────────────


class TestMergeUserJvmArgs:
    def test_creates_file_when_absent(self, tmp_path):
        path = tmp_path / "user_jvm_args.txt"
        _merge_user_jvm_args(path, "4G", [], dry_run=False)
        lines = path.read_text().splitlines()
        assert "-Xmx4G" in lines
        assert "-Xms4G" in lines

    def test_prepends_memory_before_existing_lines(self, tmp_path):
        path = tmp_path / "user_jvm_args.txt"
        path.write_text("-XX:+UseG1GC\n")
        _merge_user_jvm_args(path, "4G", [], dry_run=False)
        lines = path.read_text().splitlines()
        assert lines[0] == "-Xmx4G"
        assert lines[1] == "-Xms4G"
        assert "-XX:+UseG1GC" in lines

    def test_replaces_prior_xmx_xms(self, tmp_path):
        path = tmp_path / "user_jvm_args.txt"
        path.write_text("-Xmx2G\n-Xms2G\n-XX:+UseG1GC\n")
        _merge_user_jvm_args(path, "8G", [], dry_run=False)
        lines = path.read_text().splitlines()
        assert "-Xmx8G" in lines
        assert "-Xms8G" in lines
        assert "-Xmx2G" not in lines
        assert "-Xms2G" not in lines

    def test_idempotent_on_repeat_run(self, tmp_path):
        path = tmp_path / "user_jvm_args.txt"
        _merge_user_jvm_args(path, "4G", ["-Dfoo=bar"], dry_run=False)
        _merge_user_jvm_args(path, "4G", ["-Dfoo=bar"], dry_run=False)
        lines = path.read_text().splitlines()
        assert lines.count("-Xmx4G") == 1
        assert lines.count("-Dfoo=bar") == 1

    def test_appends_extra_args(self, tmp_path):
        path = tmp_path / "user_jvm_args.txt"
        _merge_user_jvm_args(path, "2G", ["-Dfoo=bar", "-XX:+UseZGC"], dry_run=False)
        content = path.read_text()
        assert "-Dfoo=bar" in content
        assert "-XX:+UseZGC" in content


# ── CF settings patchers ──────────────────────────────────────────────────────


class TestPatchCfSettingsLocal:
    def test_updates_existing_keys_in_place(self, tmp_path):
        path = tmp_path / "settings-local.sh"
        path.write_text("# comment\nMIN_RAM=1024M\nMAX_RAM=2048M\nJAVA_PARAMETERS=\n")
        _patch_cf_settings_local(path, "8G", ["-Dfoo=bar"], dry_run=False)
        lines = path.read_text().splitlines()
        assert "# comment" in lines
        assert "MIN_RAM=8192M" in lines
        assert "MAX_RAM=8192M" in lines
        assert "JAVA_PARAMETERS=-Dfoo=bar" in lines

    def test_appends_missing_keys(self, tmp_path):
        path = tmp_path / "settings-local.sh"
        path.write_text("OTHER=foo\n")
        _patch_cf_settings_local(path, "4G", [], dry_run=False)
        content = path.read_text()
        assert "MIN_RAM=4096M" in content
        assert "MAX_RAM=4096M" in content


class TestPatchCfSettingsCfg:
    def test_updates_max_ram(self, tmp_path):
        path = tmp_path / "settings.cfg"
        path.write_text("MAX_RAM=2048M\nMIN_RAM=1024M\n")
        _patch_cf_settings_cfg(path, "6G", dry_run=False)
        content = path.read_text()
        assert "MAX_RAM=6144M" in content
        assert "MIN_RAM=1024M" in content  # untouched

    def test_appends_when_absent(self, tmp_path):
        path = tmp_path / "settings.cfg"
        path.write_text("SOMETHING=else\n")
        _patch_cf_settings_cfg(path, "4G", dry_run=False)
        assert "MAX_RAM=4096M" in path.read_text()


class TestPatchCfVariables:
    def test_updates_java_args(self, tmp_path):
        path = tmp_path / "variables.txt"
        path.write_text('JAVA_ARGS=""\nOTHER=val\n')
        _patch_cf_variables(path, ["-Dfoo=bar"], dry_run=False)
        content = path.read_text()
        assert 'JAVA_ARGS="-Dfoo=bar"' in content
        assert "OTHER=val" in content

    def test_appends_when_absent(self, tmp_path):
        path = tmp_path / "variables.txt"
        path.write_text("OTHER=val\n")
        _patch_cf_variables(path, ["-Dfoo=bar"], dry_run=False)
        assert 'JAVA_ARGS="-Dfoo=bar"' in path.read_text()
