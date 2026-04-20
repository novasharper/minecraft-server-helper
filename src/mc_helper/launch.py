"""Launch configuration for Minecraft servers.

Detects the appropriate delivery channel for JVM/server args based on what
the installer produced, then writes launch.sh and any sibling config files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

LaunchKind = Literal["jar", "run_sh", "cf_script", "bare_script"]

_CF_SETTINGS_LOCAL = "settings-local.sh"
_CF_SETTINGS_CFG = "settings.cfg"
_CF_VARIABLES = "variables.txt"


@dataclass
class LaunchPlan:
    kind: LaunchKind
    start_artifact: Path
    settings_files: list[Path] = field(default_factory=list)


def detect_launch_plan(output_dir: Path, start_artifact: Path) -> LaunchPlan:
    """Determine how this server should be launched based on the installed artifact."""
    if start_artifact.suffix == ".jar":
        return LaunchPlan(kind="jar", start_artifact=start_artifact)

    if start_artifact.suffix == ".sh":
        if start_artifact.name == "run.sh":
            return LaunchPlan(kind="run_sh", start_artifact=start_artifact)

        settings_files = [
            output_dir / name
            for name in (_CF_SETTINGS_LOCAL, _CF_SETTINGS_CFG, _CF_VARIABLES)
            if (output_dir / name).exists()
        ]
        if settings_files:
            return LaunchPlan(
                kind="cf_script", start_artifact=start_artifact, settings_files=settings_files
            )

        return LaunchPlan(kind="bare_script", start_artifact=start_artifact)

    # Unexpected suffix — treat as JAR and let java complain if needed
    return LaunchPlan(kind="jar", start_artifact=start_artifact)


def apply_launch_plan(
    plan: LaunchPlan,
    output_dir: Path,
    memory: str,
    jvm_args: list[str],
    server_args: list[str],
    java_bin: str,
    dry_run: bool,
) -> None:
    """Write/patch launch configuration files according to *plan*."""
    if plan.kind == "run_sh":
        _apply_run_sh(plan, output_dir, memory, jvm_args, dry_run)
    elif plan.kind == "cf_script":
        _apply_cf_script(plan, output_dir, memory, jvm_args, dry_run)
    elif plan.kind == "bare_script":
        if jvm_args:
            log.warning(
                "jvm_args configured but %s has no known settings file to write them into;"
                " they will be ignored",
                plan.start_artifact.name,
            )
        _write_launch_sh(output_dir / "launch.sh", plan.start_artifact, dry_run=dry_run)
    else:  # "jar"
        _write_jar_launch_sh(
            output_dir / "launch.sh",
            plan.start_artifact,
            memory,
            jvm_args,
            server_args,
            java_bin,
            dry_run,
        )


# ── launch.sh writers ─────────────────────────────────────────────────────────


def _write_jar_launch_sh(
    launch_path: Path,
    artifact: Path,
    memory: str,
    jvm_args: list[str],
    server_args: list[str],
    java_bin: str,
    dry_run: bool,
) -> None:
    parts: list[str] = [java_bin]
    parts.extend(jvm_args)
    parts += [f"-Xmx{memory}", f"-Xms{memory}", "-jar", artifact.name]
    parts.extend(server_args)
    cmd = " ".join(parts)
    _write_script(launch_path, f"#!/bin/sh\nexec {cmd} \"$@\"\n", dry_run)


def _write_launch_sh(launch_path: Path, artifact: Path, dry_run: bool) -> None:
    _write_script(launch_path, f'#!/bin/sh\nexec ./{artifact.name} "$@"\n', dry_run)


def _write_script(path: Path, content: str, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] Would write {path}:")
        for line in content.splitlines():
            print(f"  {line}")
    else:
        path.write_text(content)
        path.chmod(0o755)


# ── run_sh (Forge 1.17+ / NeoForge) ──────────────────────────────────────────


def _apply_run_sh(
    plan: LaunchPlan, output_dir: Path, memory: str, jvm_args: list[str], dry_run: bool
) -> None:
    _merge_user_jvm_args(output_dir / "user_jvm_args.txt", memory, jvm_args, dry_run)
    _write_launch_sh(output_dir / "launch.sh", plan.start_artifact, dry_run)


def _merge_user_jvm_args(path: Path, memory: str, extra_args: list[str], dry_run: bool) -> None:
    """Merge memory and extra_args into user_jvm_args.txt idempotently.

    Preserves any lines the Forge/NeoForge installer wrote (e.g. classpath flags),
    strips our own prior -Xms/-Xmx lines, and re-adds them at the top.
    """
    if path.exists():
        existing = [
            line
            for line in path.read_text().splitlines()
            if line and not line.startswith("-Xms") and not line.startswith("-Xmx")
        ]
    else:
        existing = []

    merged = [f"-Xmx{memory}", f"-Xms{memory}", *existing, *extra_args]

    # Deduplicate while preserving first-occurrence order
    seen: set[str] = set()
    deduped: list[str] = []
    for line in merged:
        if line not in seen:
            seen.add(line)
            deduped.append(line)

    content = "\n".join(deduped) + "\n"
    if dry_run:
        print(f"[dry-run] Would write {path}:")
        for line in deduped:
            print(f"  {line}")
    else:
        path.write_text(content)


# ── CurseForge server-pack settings patchers ─────────────────────────────────


def _apply_cf_script(
    plan: LaunchPlan, output_dir: Path, memory: str, jvm_args: list[str], dry_run: bool
) -> None:
    for sf in plan.settings_files:
        if sf.name == _CF_SETTINGS_LOCAL:
            _patch_cf_settings_local(sf, memory, jvm_args, dry_run)
        elif sf.name == _CF_SETTINGS_CFG:
            _patch_cf_settings_cfg(sf, memory, dry_run)
        elif sf.name == _CF_VARIABLES:
            _patch_cf_variables(sf, jvm_args, dry_run)
    _write_launch_sh(output_dir / "launch.sh", plan.start_artifact, dry_run)


def _cf_memory_mb(memory: str) -> str:
    """Convert '4G' or '4096M' to an integer MB string for CF settings files."""
    s = memory.strip()
    if s.upper().endswith("G"):
        return str(int(s[:-1]) * 1024)
    if s.upper().endswith("M"):
        return s[:-1]
    return s


def _patch_key_value_file(
    path: Path,
    updates: dict[str, str],
    dry_run: bool,
    *,
    quote_values: bool = False,
) -> None:
    """Patch key=value (or key="value") lines in *path* in place; append missing keys."""
    lines = path.read_text().splitlines() if path.exists() else []
    seen: set[str] = set()
    result: list[str] = []

    for raw in lines:
        stripped = raw.strip()
        matched = False
        for key, val in updates.items():
            if stripped.startswith(f"{key}="):
                v = f'"{val}"' if quote_values else val
                result.append(f"{key}={v}")
                seen.add(key)
                matched = True
                break
        if not matched:
            result.append(raw)

    for key, val in updates.items():
        if key not in seen:
            v = f'"{val}"' if quote_values else val
            result.append(f"{key}={v}")

    if dry_run:
        print(f"[dry-run] Would patch {path}: {list(updates)}")
    else:
        path.write_text("\n".join(result) + "\n")


def _patch_cf_settings_local(path: Path, memory: str, jvm_args: list[str], dry_run: bool) -> None:
    mb = _cf_memory_mb(memory)
    _patch_key_value_file(
        path,
        {"MIN_RAM": f"{mb}M", "MAX_RAM": f"{mb}M", "JAVA_PARAMETERS": " ".join(jvm_args)},
        dry_run,
    )


def _patch_cf_settings_cfg(path: Path, memory: str, dry_run: bool) -> None:
    mb = _cf_memory_mb(memory)
    _patch_key_value_file(path, {"MAX_RAM": f"{mb}M"}, dry_run)


def _patch_cf_variables(path: Path, jvm_args: list[str], dry_run: bool) -> None:
    _patch_key_value_file(
        path, {"JAVA_ARGS": " ".join(jvm_args)}, dry_run, quote_values=True
    )
