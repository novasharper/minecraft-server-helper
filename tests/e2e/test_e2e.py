"""End-to-end tests: run mc-helper setup with real downloads and validate outputs.

Each test builds the mc-helper-e2e image once (session fixture), then spawns a
fresh container per test with src/ bind-mounted.  Tests make real network
requests and can take several minutes each — they are intentionally not
parallelized.

Run via the helper script (recommended):
    bash tests/e2e/run_tests.sh

Or directly with poetry (requires podman or docker):
    poetry run pytest tests/e2e/test_e2e.py -v
    E2E_OUTPUT_DIR=/tmp/e2e-output poetry run pytest tests/e2e/test_e2e.py -v  # keep output
"""

import os
import shutil
import subprocess
import sys  # for stderr output only
import tempfile
import time
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).parent
REPO_ROOT = E2E_DIR.parent.parent  # minecraft-server-helper/
SRC_DIR = REPO_ROOT / "src"
CONFIGS_DIR = E2E_DIR / "configs"
IMAGE = "mc-helper-e2e"

# 20 minutes — modpack downloads can be large
TIMEOUT = 1200

# 10 minutes — server startup (Forge/NeoForge can be slow on first boot)
SERVER_START_TIMEOUT = 600

# 20 minutes — heavy modpacks (GTNH, large Forge packs) load hundreds of mods
HEAVY_START_TIMEOUT = 1200


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def container_runtime():
    """Detect and return the available container runtime (podman or docker)."""
    override = os.environ.get("CONTAINER_RUNTIME", "")
    if override:
        return override
    for rt in ("podman", "docker"):
        if shutil.which(rt):
            return rt
    pytest.skip("neither podman nor docker found on PATH")


@pytest.fixture(scope="session")
def e2e_image(container_runtime):
    """Build the mc-helper-e2e image once for the entire test session."""
    subprocess.run(
        [
            container_runtime,
            "build",
            "-t",
            IMAGE,
            "-f",
            str(E2E_DIR / "Containerfile"),
            str(E2E_DIR),
        ],
        check=True,
    )
    return IMAGE


@pytest.fixture(scope="session")
def output_base():
    """Return the base directory for server output.

    Uses E2E_OUTPUT_DIR if set; otherwise creates a temporary directory that is
    automatically removed at the end of the session.
    """
    explicit = os.environ.get("E2E_OUTPUT_DIR", "")
    if explicit:
        p = Path(explicit)
        p.mkdir(parents=True, exist_ok=True)
        yield p
    else:
        with tempfile.TemporaryDirectory(prefix="mc-helper-e2e-") as tmp:
            yield Path(tmp)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _run(
    container_runtime: str,
    e2e_image: str,
    output_base: Path,
    config_name: str,
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run `mc-helper setup --config <config_name>` in a fresh container."""
    # VirtioFS (Podman/macOS) presents bind-mounts as root:nobody regardless of
    # the host uid.  Making the directory world-writable on the host is the
    # only reliable way to let the container user create subdirectories inside.
    output_base.chmod(0o777)

    env_flags = ["-e", "E2E_OUTPUT_DIR=/output"]
    cf_key = os.environ.get("CF_API_KEY", "")
    if cf_key:
        env_flags += ["-e", f"CF_API_KEY={cf_key}"]
    if extra_env:
        for k, v in extra_env.items():
            env_flags += ["-e", f"{k}={v}"]

    cmd = [
        container_runtime,
        "run",
        "--rm",
        "-v",
        f"{SRC_DIR}:/app/src:ro",
        "-v",
        f"{CONFIGS_DIR}:/configs:ro",
        "-v",
        f"{output_base}:/output",
        *env_flags,
        e2e_image,
        "mc-helper",
        "setup",
        "--config",
        f"/configs/{config_name}",
    ]

    live = os.environ.get("E2E_LIVE_OUTPUT", "").lower() in ("1", "true", "yes")
    if live:
        # Stream output directly to the terminal as the container runs.
        result = subprocess.run(cmd, timeout=TIMEOUT)
    else:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
        if result.returncode != 0:
            print("STDOUT:\n", result.stdout)
            print("STDERR:\n", result.stderr, file=sys.stderr)
    return result


def _assert_basic_files(output_dir: Path) -> None:
    """Assert that the standard server files were written."""
    assert output_dir.exists(), f"output_dir does not exist: {output_dir}"
    assert (output_dir / "eula.txt").exists(), "eula.txt missing"
    assert "eula=true" in (output_dir / "eula.txt").read_text()
    assert (output_dir / "launch.sh").exists(), "launch.sh missing"
    assert (output_dir / ".mc-helper-manifest.json").exists(), "manifest missing"


def _assert_mods_populated(output_dir: Path) -> None:
    """Assert that at least one mod JAR was installed."""
    mods_dir = output_dir / "mods"
    assert mods_dir.exists(), f"mods/ directory missing in {output_dir}"
    jars = list(mods_dir.glob("*.jar"))
    assert jars, f"no .jar files found in {mods_dir}"


def _check_server_starts(
    container_runtime: str,
    output_dir: Path,
    e2e_image: str,
    *,
    timeout: int = SERVER_START_TIMEOUT,
) -> None:
    """Start the installed server in a container and verify port 25565 opens."""
    # Make the server directory world-writable so the container user can write
    # world data, logs, etc. (VirtioFS on macOS presents bind-mounts as root:nobody)
    output_dir.chmod(0o777)

    container_name = f"mc-helper-e2e-srv-{output_dir.name}"
    cmd = [
        container_runtime,
        "run",
        # No --rm: keep the container after exit so its logs remain accessible
        # even if the server crashes immediately before the first `logs` poll.
        "--name", container_name,
        "-v", f"{output_dir}:/server",
        "-w", "/server",
        e2e_image,
        "/server/launch.sh",
    ]

    # Use DEVNULL — container output is still captured by the runtime's log
    # buffer and retrieved below via `logs` subcommand.
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            logs = subprocess.run(
                [container_runtime, "logs", container_name],
                capture_output=True,
                text=True,
            )
            combined = logs.stdout + logs.stderr
            # "Done (Xs)! For help, type "help"" is emitted by all server
            # types after port bind AND spawn chunk generation are complete.
            if "Done (" in combined:
                return
            if proc.poll() is not None:
                # Re-fetch logs now that the container has fully flushed output
                logs = subprocess.run(
                    [container_runtime, "logs", container_name],
                    capture_output=True,
                    text=True,
                )
                pytest.fail(
                    f"Server process exited early (rc={proc.returncode}).\n"
                    f"Server output:\n{logs.stdout + logs.stderr}"
                )
            time.sleep(3)
        logs = subprocess.run(
            [container_runtime, "logs", container_name],
            capture_output=True,
            text=True,
        )
        pytest.fail(
            f"Server did not finish starting within {timeout}s.\n"
            f"Server output:\n{logs.stdout + logs.stderr}"
        )
    finally:
        # rm -f stops (if still running) and removes the container in one step
        subprocess.run(
            [container_runtime, "rm", "-f", container_name],
            capture_output=True,
            timeout=30,
        )
        proc.wait()


def _assert_server_artifact(output_dir: Path, pattern: str) -> None:
    """Assert that the server-type-specific file or glob pattern exists."""
    if "*" in pattern:
        matches = list(output_dir.glob(pattern))
        assert matches, f"expected server artifact {pattern!r} not found in {output_dir}"
    else:
        assert (output_dir / pattern).exists(), (
            f"expected server artifact {pattern!r} not found in {output_dir}"
        )


# ── Server pack tests ─────────────────────────────────────────────────────────


def test_modpack_serverpack_gtnh(container_runtime, e2e_image, output_base):
    """GT: New Horizons 2.8.4 installed from a direct-URL server pack."""
    result = _run(container_runtime, e2e_image, output_base, "serverpack-gtnh.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = output_base / "gtnh"
    _assert_basic_files(output_dir)
    _check_server_starts(container_runtime, output_dir, e2e_image, timeout=HEAVY_START_TIMEOUT)


def test_modpack_serverpack_tfg(container_runtime, e2e_image, output_base):
    """TerraFirmaGreg Modern v0.11.28 installed from a GitHub release asset."""
    result = _run(container_runtime, e2e_image, output_base, "serverpack-tfg.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = output_base / "tfg"
    _assert_basic_files(output_dir)
    _check_server_starts(container_runtime, output_dir, e2e_image, timeout=HEAVY_START_TIMEOUT)


# ── Modpack tests ─────────────────────────────────────────────────────────────


def test_modpack_ftb_stoneblock4(container_runtime, e2e_image, output_base):
    """FTB StoneBlock 4 installed via the FTB platform API."""
    result = _run(container_runtime, e2e_image, output_base, "modpack-ftb-sb4.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = output_base / "ftb-sb4"
    _assert_basic_files(output_dir)
    _assert_mods_populated(output_dir)
    _check_server_starts(container_runtime, output_dir, e2e_image, timeout=HEAVY_START_TIMEOUT)


def test_modpack_cobblemon(container_runtime, e2e_image, output_base):
    """Cobblemon (Fabric) installed from Modrinth."""
    result = _run(container_runtime, e2e_image, output_base, "modpack-cobblemon.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = output_base / "cobblemon"
    _assert_basic_files(output_dir)
    _assert_mods_populated(output_dir)
    _check_server_starts(container_runtime, output_dir, e2e_image, timeout=HEAVY_START_TIMEOUT)


@pytest.mark.skipif(
    not os.environ.get("CF_API_KEY"),
    reason="CF_API_KEY not set — skipping CurseForge test",
)
def test_modpack_all_of_create(container_runtime, e2e_image, output_base):
    """All of Create installed from CurseForge (requires CF_API_KEY)."""
    result = _run(container_runtime, e2e_image, output_base, "modpack-aoc.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = output_base / "aoc"
    _assert_basic_files(output_dir)
    _assert_mods_populated(output_dir)
    _check_server_starts(container_runtime, output_dir, e2e_image, timeout=HEAVY_START_TIMEOUT)


# ── Pure server type tests ────────────────────────────────────────────────────


def test_server_vanilla(container_runtime, e2e_image, output_base):
    """Vanilla 1.21.4 server JAR installed and starts."""
    result = _run(container_runtime, e2e_image, output_base, "server-vanilla.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = output_base / "vanilla"
    _assert_basic_files(output_dir)
    _assert_server_artifact(output_dir, "minecraft_server.*.jar")
    _check_server_starts(container_runtime, output_dir, e2e_image)


def test_server_fabric(container_runtime, e2e_image, output_base):
    """Fabric 1.21.4 server launcher JAR installed and starts."""
    result = _run(container_runtime, e2e_image, output_base, "server-fabric.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = output_base / "fabric"
    _assert_basic_files(output_dir)
    _assert_server_artifact(output_dir, "fabric-server-launch.jar")
    _check_server_starts(container_runtime, output_dir, e2e_image)


def test_server_forge(container_runtime, e2e_image, output_base):
    """Forge 1.21.1 server installed via --installServer (creates run.sh) and starts."""
    result = _run(container_runtime, e2e_image, output_base, "server-forge.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = output_base / "forge"
    _assert_basic_files(output_dir)
    _assert_server_artifact(output_dir, "run.sh")
    _check_server_starts(container_runtime, output_dir, e2e_image)


def test_server_neoforge(container_runtime, e2e_image, output_base):
    """NeoForge 1.21.4 server installed via --installServer (creates run.sh) and starts."""
    result = _run(container_runtime, e2e_image, output_base, "server-neoforge.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = output_base / "neoforge"
    _assert_basic_files(output_dir)
    _assert_server_artifact(output_dir, "run.sh")
    _check_server_starts(container_runtime, output_dir, e2e_image)


def test_server_paper(container_runtime, e2e_image, output_base):
    """Paper 1.21.4 server JAR installed and starts."""
    result = _run(container_runtime, e2e_image, output_base, "server-paper.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = output_base / "paper"
    _assert_basic_files(output_dir)
    _assert_server_artifact(output_dir, "paper-*.jar")
    _check_server_starts(container_runtime, output_dir, e2e_image)


def test_server_purpur(container_runtime, e2e_image, output_base):
    """Purpur 1.21.4 server JAR installed and starts."""
    result = _run(container_runtime, e2e_image, output_base, "server-purpur.yaml")
    assert result.returncode == 0, "mc-helper exited non-zero"
    output_dir = output_base / "purpur"
    _assert_basic_files(output_dir)
    _assert_server_artifact(output_dir, "purpur-*.jar")
    _check_server_starts(container_runtime, output_dir, e2e_image)
