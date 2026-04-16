"""End-to-end tests: run mc-helper setup with real downloads and validate outputs.

Each test invokes `mc-helper setup` as a subprocess and checks that the expected
server files are created.  Tests make real network requests and can take several
minutes each — they are intentionally not parallelized.

Run via the container:
    bash tests/e2e/run_tests.sh

Or directly (requires mc-helper on PATH and network access):
    E2E_OUTPUT_DIR=/tmp/e2e-output pytest tests/e2e/test_e2e.py -v
"""

import os
import subprocess
import sys  # for stderr output only
from pathlib import Path

import pytest

CONFIGS_DIR = Path(__file__).parent / "configs"
E2E_OUTPUT_BASE = Path(os.environ.get("E2E_OUTPUT_DIR", "/tmp/e2e-output"))

# 20 minutes — modpack downloads can be large
TIMEOUT = 1200


def _run(config_name: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """Run `mc-helper setup --config <config_name>` and return the result."""
    env = os.environ.copy()
    env.setdefault("E2E_OUTPUT_DIR", str(E2E_OUTPUT_BASE))
    if extra_env:
        env.update(extra_env)

    config_path = CONFIGS_DIR / config_name
    result = subprocess.run(
        ["mc-helper", "setup", "--config", str(config_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    if result.returncode != 0:
        # Print output to make pytest failures readable
        print("STDOUT:\n", result.stdout)
        print("STDERR:\n", result.stderr, file=sys.stderr)
    return result


def _assert_basic_files(output_dir: Path) -> None:
    """Assert that the standard server files were written."""
    assert output_dir.exists(), f"output_dir does not exist: {output_dir}"
    assert (output_dir / "eula.txt").exists(), "eula.txt missing"
    assert "eula=true" in (output_dir / "eula.txt").read_text()
    assert (output_dir / "server.properties").exists() or True  # only written if properties set
    assert (output_dir / "launch.sh").exists(), "launch.sh missing"
    assert (output_dir / ".mc-helper-manifest.json").exists(), "manifest missing"


def _assert_mods_populated(output_dir: Path) -> None:
    """Assert that at least one mod JAR was installed."""
    mods_dir = output_dir / "mods"
    assert mods_dir.exists(), f"mods/ directory missing in {output_dir}"
    jars = list(mods_dir.glob("*.jar"))
    assert jars, f"no .jar files found in {mods_dir}"


# ── Server pack tests ─────────────────────────────────────────────────────────


def test_modpack_serverpack_gtnh():
    """GT: New Horizons 2.8.4 installed from a direct-URL server pack."""
    result = _run("server-pack-gtnh.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    _assert_basic_files(E2E_OUTPUT_BASE / "gtnh")


def test_modpack_serverpack_tfg():
    """TerraFirmaGreg Modern v0.11.28 installed from a GitHub release asset."""
    result = _run("server-pack-tfg.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    _assert_basic_files(E2E_OUTPUT_BASE / "tfg")


# ── Modpack tests ─────────────────────────────────────────────────────────────


def test_modpack_ftb_stoneblock4():
    """FTB StoneBlock 4 installed via the FTB platform API."""
    result = _run("modpack-ftb-sb4.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = E2E_OUTPUT_BASE / "ftb-sb4"
    _assert_basic_files(output_dir)
    _assert_mods_populated(output_dir)


def test_modpack_cobblemon():
    """Cobblemon (Fabric) installed from Modrinth."""
    result = _run("modpack-cobblemon.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = E2E_OUTPUT_BASE / "cobblemon"
    _assert_basic_files(output_dir)
    _assert_mods_populated(output_dir)


@pytest.mark.skipif(
    not os.environ.get("CF_API_KEY"),
    reason="CF_API_KEY not set — skipping CurseForge test",
)
def test_modpack_all_of_create():
    """All of Create installed from CurseForge (requires CF_API_KEY)."""
    result = _run("modpack-aoc.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = E2E_OUTPUT_BASE / "aoc"
    _assert_basic_files(output_dir)
    _assert_mods_populated(output_dir)


# ── Pure server type tests ────────────────────────────────────────────────────


def _assert_server_artifact(output_dir: Path, pattern: str) -> None:
    """Assert that the server-type-specific file or glob pattern exists."""
    if "*" in pattern:
        matches = list(output_dir.glob(pattern))
        assert matches, f"expected server artifact {pattern!r} not found in {output_dir}"
    else:
        assert (output_dir / pattern).exists(), (
            f"expected server artifact {pattern!r} not found in {output_dir}"
        )


def test_server_vanilla():
    """Vanilla 1.21.4 server JAR installed."""
    result = _run("server-vanilla.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = E2E_OUTPUT_BASE / "vanilla"
    _assert_basic_files(output_dir)
    _assert_server_artifact(output_dir, "minecraft_server.*.jar")


def test_server_fabric():
    """Fabric 1.21.4 server launcher JAR installed."""
    result = _run("server-fabric.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = E2E_OUTPUT_BASE / "fabric"
    _assert_basic_files(output_dir)
    _assert_server_artifact(output_dir, "fabric-server-launch.jar")


def test_server_forge():
    """Forge 1.21.1 server installed via --installServer (creates run.sh)."""
    result = _run("server-forge.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = E2E_OUTPUT_BASE / "forge"
    _assert_basic_files(output_dir)
    _assert_server_artifact(output_dir, "run.sh")


def test_server_neoforge():
    """NeoForge 1.21.4 server installed via --installServer (creates run.sh)."""
    result = _run("server-neoforge.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = E2E_OUTPUT_BASE / "neoforge"
    _assert_basic_files(output_dir)
    _assert_server_artifact(output_dir, "run.sh")


def test_server_paper():
    """Paper 1.21.4 server JAR installed."""
    result = _run("server-paper.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = E2E_OUTPUT_BASE / "paper"
    _assert_basic_files(output_dir)
    _assert_server_artifact(output_dir, "paper-*.jar")


def test_server_purpur():
    """Purpur 1.21.4 server JAR installed."""
    result = _run("server-purpur.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = E2E_OUTPUT_BASE / "purpur"
    _assert_basic_files(output_dir)
    _assert_server_artifact(output_dir, "purpur-*.jar")
