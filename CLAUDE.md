# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

`minecraft-server-helper` is a Python CLI (`mc-helper`) that prepares a Minecraft server directory without Docker. It downloads server JARs, installs mod loaders, and fetches modpacks/mods from CurseForge, Modrinth, FTB, GTNH, or custom GitHub/URL server packs — driven by a single YAML config file.

See `docs/` for user-facing reference documentation.

## Setup

```bash
poetry install
```

## Common Commands

```bash
# Run all unit tests (real network blocked by autouse fixture in conftest.py)
poetry run pytest

# Run a single test file
poetry run pytest tests/test_vanilla.py

# Run a single test
poetry run pytest tests/test_curseforge.py::test_resolve_by_slug

# Run e2e tests (requires podman or docker; makes real network calls, ~minutes each)
bash tests/e2e/run_tests.sh
# or directly:
poetry run pytest tests/e2e/test_e2e.py -v
# set E2E_OUTPUT_DIR=/some/path to preserve downloaded output after tests

# Lint + format (line length: 100)
poetry run ruff check src/ tests/
poetry run ruff format src/ tests/

# Validate a config file
poetry run mc-helper validate --config example-config.yaml

# Dry-run setup (no downloads)
poetry run mc-helper setup --config example-config.yaml --dry-run

# Show installed state (reads .mc-helper-manifest.json)
poetry run mc-helper status --config example-config.yaml
```

## Architecture

### CLI dispatch (`cli.py`)

The entry point uses `argparse` (not Click). Subcommands: `setup`, `validate`, `status`. `_cmd_setup` runs the base install mode first, then optionally installs extra mods:

1. `modpack` → `_setup_modpack()`, which dispatches on `modpack.platform` (`modrinth | curseforge | ftb | gtnh | github | url`) into the `modpack/` package (`curseforge.py`, `modrinth.py`, `ftb.py`, `gtnh.py`, `custom.py`)
2. `mods` only → `_setup_mods()` → `_download_mods()` (parallel), then `_install_server_jar()`
3. *(none)* → `_install_server_jar()` only
4. If `mods` is set alongside `modpack` → `_install_extra_mods()` runs after the base step

`_download_mods()` is a shared helper used by both `_setup_mods()` and `_install_extra_mods()`. After install, `_write_server_files()` writes `eula.txt` + `server.properties`, then hands off to `launch.py` to produce the launch configuration (see below). Modpack installers handle server JAR installation themselves (embedded in pack metadata); `_install_server_jar()` is only called explicitly for the `mods` and bare-server cases.

The `github` and `url` platforms share `modpack/custom.py` (`ServerPackInstaller`) for pre-assembled server-pack archives. After extraction, `modpack/_detect.py::detect_pack_versions()` is called to populate `mc_version`, `loader_type`, and `loader_version` in the manifest. Detection order: `forge-auto-install.txt` sidecar (covers Forge + NeoForge via `loaderType` field) → filename heuristics (Fabric, Paper, Purpur, Vanilla, legacy Forge jar) → installer-jar inspection (`version.json` / `install_profile.json`). Config-level overrides (`source.mc_version`, `source.loader_type`, `source.loader_version`) take precedence over auto-detection.

### Config (`config.py`)

Pydantic v2 models. YAML is loaded → `${VAR}` env interpolation runs on all string values → `model_validate()`. `ModpackConfig.source` discriminates on `platform` to select the right source model (`ModrinthSource`, `CurseForgeSource`, `FTBSource`, `GTNHSource`, `GithubSource`, `UrlSource`). `mods` may be combined with any modpack. The `server.properties` map keys are written verbatim as `server.properties` entries.

### Manifest (`manifest.py`)

`.mc-helper-manifest.json` in `output_dir` tracks `mc_version`, `loader_type`, `loader_version`, `pack_sha1`, and `files: list[str]`. On re-run: stale files (in manifest but not in new list) are deleted; the manifest is rewritten. For custom server packs, the SHA-1 of the archive is stored; extraction is skipped if it matches and `force_update` is false. The manifest's `loader_type` (e.g. `"gtnh"`) is also read by `launch.py` to auto-apply loader-specific JVM args.

### HTTP (`http_client.py`)

`build_session()` returns a `requests.Session` with 5-attempt exponential backoff (retries on 429/500/502/503/504). `download_file()` streams to disk with a tqdm progress bar and optional SHA-1/SHA-256 verification; the partial file is deleted if verification fails.

### Server installers (`server/`)

Each module exposes an installer class (`VanillaInstaller`, `FabricInstaller`, `ForgeInstaller`, `NeoForgeInstaller`, `PaperInstaller`, `PurpurInstaller`). The constructor takes version and session params; `install(output_dir)` downloads and installs the server. Vanilla, Fabric, Paper, Purpur return the installed JAR `Path`. Forge and NeoForge run `java -jar <installer>.jar --installServer` as a subprocess and return `None` (the installer creates its own `run.sh`).

### Mod resolution (`mods/`)

`mods/curseforge.py` and `mods/modrinth.py` resolve individual mods (by slug/ID) to a download URL and checksum, then delegate the actual download to `http_client.download_file()`. This package is distinct from `modpack/` — it handles the `mods:` list in config, not full modpack installs.

### Launch configuration (`launch.py`)

`_write_server_files()` calls `detect_launch_plan()` → `apply_launch_plan()`. The `LaunchPlan` dataclass classifies the installed artifact into one of four delivery channels and decides where JVM/server args get written:

| `kind`        | Trigger                                             | Writes                                                                                       |
|---------------|-----------------------------------------------------|----------------------------------------------------------------------------------------------|
| `jar`         | `.jar` artifact (Vanilla / Fabric / Paper / Purpur) | `launch.sh` with full `java … -jar …` line                                                   |
| `run_sh`      | `run.sh` (Forge 1.17+ / NeoForge)                   | merges `-Xms/-Xmx` + JVM args into `user_jvm_args.txt` (idempotent); thin `launch.sh` execs `./run.sh` |
| `cf_script`   | `.sh` + CF settings files present                   | patches `settings-local.sh` / `settings.cfg` / `variables.txt` in place                      |
| `bare_script` | `.sh` fallback                                      | thin `launch.sh`; warns if `jvm_args` are configured (nowhere to put them)                   |

`_build_auto_jvm_args()` composes args in the same order as `docker-minecraft-server`: auto flags → `jvm_xx_opts` → `jvm_opts` → `jvm_dd_opts` → `jvm_args`. Auto flags include:
- Log4j CVE shim for MC 1.7–<1.18.1 (skipped for `cf_script`, which patches its own `JAVA_PARAMETERS`)
- Aikar / MeowIce G1GC / MeowIce GraalVM / Flare / SIMD flag bundles (opt-in via `use_*_flags` in `ServerConfig`)
- GTNH-specific args (auto-applied when manifest `loader_type == "gtnh"`)

Java major version is probed via `java -version` when a bundle needs it. `use_meowice_flags` falls back to Aikar if Java <17 is detected.

### Data files (`data/`)

`cf-exclude-include.json` and `modrinth-exclude-include.json` are mirrored from `docker-minecraft-server/files/` and drive mod filtering during modpack installs.

### Shared utilities (`utils.py`)

`extract_zip_overrides()` — ZIP extraction with path-traversal guard and glob exclusions.  
`find_content_root()` — mirrors `mc-image-helper find --only-shallowest` to locate the server root inside an extracted archive.  
`compare_versions()`, `glob_delete()`, `disable_mods()` — version comparison and file management helpers.

### Parallelism

`_download_mods()` submits all Modrinth and CurseForge mod downloads to a `ThreadPoolExecutor(max_workers=10)`. Errors are collected per-mod; all are reported before exiting non-zero if any failed. This helper is called by both `_setup_mods()` (mods-only path) and `_install_extra_mods()` (overlay path).

### Testing conventions

Unit tests block all real network I/O via an `autouse` fixture in `conftest.py` (patches `socket.create_connection` and `socket.getaddrinfo`). Use `@responses.activate` to mock HTTP calls — tests decorated with it are unaffected by the socket block.

## Knowledge persistence during long tasks

During multi-phase work (planning, large refactors), save durable learnings to memory incrementally as they're discovered — don't wait until task end. Context compaction can silently drop mid-session work.

- Group memories by topic into separate files (`reference_*.md`, `project_*.md`, `feedback_*.md`) — not one large file.
- Always update `MEMORY.md` (index) when adding a new memory file.
- Trigger: any task expected to span more than ~5 tool calls, or any explicit planning phase.

## Reference Sources

Clone these repositories locally when you need to read reference implementations. Do not assume a specific directory layout relative to this repo.

| Topic | Repository | Path |
|---|---|---|
| Vanilla install | [itzg/docker-minecraft-server](https://github.com/itzg/docker-minecraft-server) | `scripts/start-deployVanilla` |
| Fabric install | [itzg/mc-image-helper](https://github.com/itzg/mc-image-helper) | `src/main/java/me/itzg/helpers/fabric/` |
| Forge install | [itzg/mc-image-helper](https://github.com/itzg/mc-image-helper) | `src/main/java/me/itzg/helpers/forge/` |
| Paper install | [itzg/mc-image-helper](https://github.com/itzg/mc-image-helper) | `src/main/java/me/itzg/helpers/paper/` |
| CurseForge modpack | [itzg/mc-image-helper](https://github.com/itzg/mc-image-helper) | `src/main/java/me/itzg/helpers/curseforge/` |
| Modrinth modpack | [itzg/mc-image-helper](https://github.com/itzg/mc-image-helper) | `src/main/java/me/itzg/helpers/modrinth/` |
| FTB modpack | [FTBTeam/FTB-Server-Installer](https://github.com/FTBTeam/FTB-Server-Installer) | *(root)* |
| Server pack extract | [itzg/docker-minecraft-server](https://github.com/itzg/docker-minecraft-server) | `scripts/start-setupModpack` |
| Server properties | [itzg/docker-minecraft-server](https://github.com/itzg/docker-minecraft-server) | `files/property-definitions.json` |
| Mod filter rules | [itzg/docker-minecraft-server](https://github.com/itzg/docker-minecraft-server) | `files/cf-exclude-include.json` |
