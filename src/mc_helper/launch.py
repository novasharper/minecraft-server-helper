"""Launch configuration for Minecraft servers.

Detects the appropriate delivery channel for JVM/server args based on what
the installer produced, then writes launch.sh and any sibling config files.
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .config import ServerConfig

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
    mc_version: str | None = None
    loader_type: str | None = None


def detect_launch_plan(output_dir: Path, start_artifact: Path) -> LaunchPlan:
    """Determine how this server should be launched based on the installed artifact."""
    if start_artifact.suffix == ".jar":
        plan = LaunchPlan(kind="jar", start_artifact=start_artifact)
    elif start_artifact.suffix == ".sh":
        if start_artifact.name == "run.sh":
            plan = LaunchPlan(kind="run_sh", start_artifact=start_artifact)
        else:
            settings_files = [
                output_dir / name
                for name in (_CF_SETTINGS_LOCAL, _CF_SETTINGS_CFG, _CF_VARIABLES)
                if (output_dir / name).exists()
            ]
            if settings_files:
                plan = LaunchPlan(
                    kind="cf_script", start_artifact=start_artifact, settings_files=settings_files
                )
            else:
                plan = LaunchPlan(kind="bare_script", start_artifact=start_artifact)
    else:
        # Unexpected suffix — treat as JAR and let java complain if needed
        plan = LaunchPlan(kind="jar", start_artifact=start_artifact)

    # Populate mc_version and loader_type from the installed manifest
    try:
        from mc_helper.manifest import Manifest

        manifest = Manifest(output_dir)
        manifest.load()
        plan.mc_version = manifest.mc_version
        plan.loader_type = manifest.loader_type
    except Exception:
        pass  # manifest missing on dry-run or first-run; fields stay None

    return plan


def apply_launch_plan(
    plan: LaunchPlan,
    server_config: ServerConfig,
    output_dir: Path,
    dry_run: bool,
) -> None:
    """Write/patch launch configuration files according to *plan*."""
    auto = _build_auto_jvm_args(
        plan,
        server.memory,
        server.java_bin,
        server.use_aikar_flags,
        server.use_meowice_flags,
        server.use_meowice_graalvm_flags,
        server.use_flare_flags,
        server.use_simd_flags,
    )
    expanded_dd = [f"-D{k}={v}" for k, v in (server.jvm_dd_opts or {}).items()]
    # Assembly order mirrors Docker: auto → user jvm_xx_opts → user jvm_opts → DD opts → jvm_args
    effective_jvm_args = (
        auto
        + list(server.jvm_xx_opts)
        + list(server.jvm_opts)
        + expanded_dd
        + list(server.jvm_args)
    )

    if plan.kind == "run_sh":
        _apply_run_sh(plan, output_dir, server.memory, effective_jvm_args, dry_run)
    elif plan.kind == "cf_script":
        _apply_cf_script(plan, output_dir, server.memory, effective_jvm_args, dry_run)
    elif plan.kind == "bare_script":
        if effective_jvm_args:
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
            server.memory,
            effective_jvm_args,
            server.server_args,
            server.java_bin,
            dry_run,
        )


# ── Auto JVM arg detection ─────────────────────────────────────────────────────


def _detect_java_major_version(java_bin: str) -> int | None:
    """Run java_bin -version and return the major version integer, or None on failure."""
    try:
        result = subprocess.run([java_bin, "-version"], capture_output=True, text=True, timeout=5)
        # Java 8:  java version "1.8.0_xxx"  → major=1, minor=8
        # Java 9+: openjdk version "21.0.3"  → major=21
        m = re.search(r'version "(\d+)(?:\.(\d+))?', result.stderr)
        if m:
            major = int(m.group(1))
            if major == 1:  # old "1.X" scheme
                return int(m.group(2) or 8)
            return major
    except Exception:
        pass
    return None


def _parse_memory_mb(memory: str) -> int:
    """Parse '4G' / '4096M' / '4096' to integer MiB."""
    s = memory.strip().upper()
    if s.endswith("G"):
        return int(s[:-1]) * 1024
    if s.endswith("M"):
        return int(s[:-1])
    return int(s)


def _mc_version_tuple(version: str) -> tuple[int, ...]:
    """'1.18.1' → (1, 18, 1).  Non-numeric segments become 0."""
    parts = []
    for p in version.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _build_auto_jvm_args(
    plan: LaunchPlan,
    memory: str,
    java_bin: str,
    use_aikar_flags: bool,
    use_meowice_flags: bool,
    use_meowice_graalvm_flags: bool,
    use_flare_flags: bool,
    use_simd_flags: bool,
) -> list[str]:
    """Build JVM args inferred from the installed server state and opt-in flag bundles."""
    args: list[str] = []
    gtnh = plan.loader_type == "gtnh"

    # ── Log4j CVE shim (automatic, MC 1.7 – <1.18.1) ─────────────────────────
    # CF scripts patch their own JAVA_PARAMETERS; skip to avoid duplication.
    if plan.mc_version and plan.kind != "cf_script":
        ver = _mc_version_tuple(plan.mc_version)
        if (1, 7) <= ver < (1, 18, 1):
            args.append("-Dlog4j2.formatMsgNoLookups=true")

    # ── Java version detection (shared by bundles that need it) ───────────────
    java_ver: int | None = None
    if use_meowice_flags or use_meowice_graalvm_flags or gtnh:
        java_ver = _detect_java_major_version(java_bin)

    # ── Aikar / MeowIce G1GC flag bundles ─────────────────────────────────────
    if use_meowice_flags and java_ver is not None and java_ver < 17:
        log.warning(
            "use_meowice_flags requires Java 17+; detected Java %d — falling back to Aikar's flags",
            java_ver,
        )
        use_meowice_flags = False
        use_aikar_flags = True

    if use_aikar_flags or use_meowice_flags:
        mb = _parse_memory_mb(memory)
        if use_meowice_flags:
            g1_new, g1_max, region, reserve, ihop, mixed_target, rset = 28, 50, "16M", 15, 20, 3, 0
        elif mb >= 12 * 1024:
            g1_new, g1_max, region, reserve, ihop, mixed_target, rset = 40, 50, "16M", 15, 20, 4, 5
        else:
            g1_new, g1_max, region, reserve, ihop, mixed_target, rset = 30, 40, "8M", 20, 15, 4, 5
        args += [
            "-XX:+UseG1GC",
            "-XX:+ParallelRefProcEnabled",
            "-XX:MaxGCPauseMillis=200",
            "-XX:+UnlockExperimentalVMOptions",
            "-XX:+DisableExplicitGC",
            "-XX:+AlwaysPreTouch",
            f"-XX:G1NewSizePercent={g1_new}",
            f"-XX:G1MaxNewSizePercent={g1_max}",
            f"-XX:G1HeapRegionSize={region}",
            f"-XX:G1ReservePercent={reserve}",
            "-XX:G1HeapWastePercent=5",
            f"-XX:G1MixedGCCountTarget={mixed_target}",
            f"-XX:InitiatingHeapOccupancyPercent={ihop}",
            "-XX:G1MixedGCLiveThresholdPercent=90",
            f"-XX:G1RSetUpdatingPauseTimePercent={rset}",
            "-XX:SurvivorRatio=32",
            "-XX:+PerfDisableSharedMem",
            "-XX:MaxTenuringThreshold=1",
        ]
        if use_aikar_flags and not use_meowice_flags:
            args += ["-Dusing.aikars.flags=https://mcflags.emc.gs", "-Daikars.new.flags=true"]

    if use_meowice_flags:
        args += [
            "-XX:+UnlockDiagnosticVMOptions",
            "-XX:+UnlockExperimentalVMOptions",
            "-XX:G1SATBBufferEnqueueingThresholdPercent=30",
            "-XX:G1ConcMarkStepDurationMillis=5",
            "-XX:+UseNUMA",
            "-XX:-DontCompileHugeMethods",
            "-XX:MaxNodeLimit=240000",
            "-XX:NodeLimitFudgeFactor=8000",
            "-XX:ReservedCodeCacheSize=400M",
            "-XX:NonNMethodCodeHeapSize=12M",
            "-XX:ProfiledCodeHeapSize=194M",
            "-XX:NonProfiledCodeHeapSize=194M",
            "-XX:NmethodSweepActivity=1",
            "-XX:+UseFastUnorderedTimeStamps",
            "-XX:+UseCriticalJavaThreadPriority",
            "-XX:AllocatePrefetchStyle=3",
            "-XX:+AlwaysActAsServerClassMachine",
            "-XX:+UseTransparentHugePages",
            "-XX:LargePageSizeInBytes=2M",
            "-XX:+UseLargePages",
            "-XX:+EagerJVMCI",
            "-XX:+UseStringDeduplication",
            "-XX:+UseAES",
            "-XX:+UseAESIntrinsics",
            "-XX:+UseFMA",
            "-XX:+UseLoopPredicate",
            "-XX:+RangeCheckElimination",
            "-XX:+OptimizeStringConcat",
            "-XX:+UseCompressedOops",
            "-XX:+UseThreadPriorities",
            "-XX:+OmitStackTraceInFastThrow",
            "-XX:+RewriteBytecodes",
            "-XX:+RewriteFrequentPairs",
            "-XX:+UseFPUForSpilling",
            "-XX:+UseVectorCmov",
            "-XX:+UseXMMForArrayCopy",
            "-XX:+EliminateLocks",
            "-XX:+DoEscapeAnalysis",
            "-XX:+AlignVector",
            "-XX:+OptimizeFill",
            "-XX:+EnableVectorSupport",
            "-XX:+UseCharacterCompareIntrinsics",
            "-XX:+UseCopySignIntrinsic",
            "-XX:+UseVectorStubs",
        ]
        if platform.machine() == "x86_64":
            args += [
                "-XX:+UseFastStosb",
                "-XX:+UseNewLongLShift",
                "-XX:+UseXmmI2D",
                "-XX:+UseXmmI2F",
                "-XX:+UseXmmLoadAndClearUpper",
                "-XX:+UseXmmRegToRegMoveAll",
                "-XX:UseAVX=2",
                "-XX:UseSSE=4",
            ]

    # ── MeowIce GraalVM flags ─────────────────────────────────────────────────
    if use_meowice_graalvm_flags:
        common = [
            "-XX:+UseFastJNIAccessors",
            "-XX:+UseInlineCaches",
            "-XX:+SegmentedCodeCache",
            "-Djdk.nio.maxCachedBufferSize=262144",
        ]
        if java_ver is not None and java_ver >= 24:
            args += common + [
                "-Djdk.graal.UsePriorityInlining=true",
                "-Djdk.graal.Vectorization=true",
                "-Djdk.graal.OptDuplication=true",
                "-Djdk.graal.DetectInvertedLoopsAsCounted=true",
                "-Djdk.graal.LoopInversion=true",
                "-Djdk.graal.VectorizeHashes=true",
                "-Djdk.graal.EnterprisePartialUnroll=true",
                "-Djdk.graal.VectorizeSIMD=true",
                "-Djdk.graal.StripMineNonCountedLoops=true",
                "-Djdk.graal.SpeculativeGuardMovement=true",
                "-Djdk.graal.TuneInlinerExploration=1",
                "-Djdk.graal.LoopRotation=true",
                "-Djdk.graal.CompilerConfiguration=enterprise",
                "--enable-native-access=ALL-UNNAMED",
            ]
        else:
            args += common + [
                "-Dgraal.UsePriorityInlining=true",
                "-Dgraal.Vectorization=true",
                "-Dgraal.OptDuplication=true",
                "-Dgraal.DetectInvertedLoopsAsCounted=true",
                "-Dgraal.LoopInversion=true",
                "-Dgraal.VectorizeHashes=true",
                "-Dgraal.EnterprisePartialUnroll=true",
                "-Dgraal.VectorizeSIMD=true",
                "-Dgraal.StripMineNonCountedLoops=true",
                "-Dgraal.SpeculativeGuardMovement=true",
                "-Dgraal.TuneInlinerExploration=1",
                "-Dgraal.LoopRotation=true",
                "-Dgraal.OptWriteMotion=true",
                "-Dgraal.CompilerConfiguration=enterprise",
            ]

    # ── Flare profiling ───────────────────────────────────────────────────────
    if use_flare_flags:
        args += ["-XX:+UnlockDiagnosticVMOptions", "-XX:+DebugNonSafepoints"]

    # ── SIMD ──────────────────────────────────────────────────────────────────
    if use_simd_flags:
        args.append("--add-modules=jdk.incubator.vector")

    # ── GTNH (auto-detected from manifest loader_type == "gtnh") ──────────────
    if gtnh:
        args.append("-Dfml.readTimeout=180")
        if java_ver is not None:
            if java_ver == 8:
                args += [
                    "-XX:+UseStringDeduplication",
                    "-XX:+UseCompressedOops",
                    "-XX:+UseCodeCacheFlushing",
                ]
            elif java_ver >= 17:
                args.append("@java9args.txt")

    return args


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
    _write_script(launch_path, f'#!/bin/sh\nexec {cmd} "$@"\n', dry_run)


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
    _patch_key_value_file(path, {"JAVA_ARGS": " ".join(jvm_args)}, dry_run, quote_values=True)
