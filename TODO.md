# minecraft-server-helper — TODO

## Phase 1: Project Scaffold ✓
- [x] Create `pyproject.toml` (Poetry) with dependencies (pydantic, PyYAML, requests, tqdm) and `mc-helper` entry point
- [x] Create `src/mc_helper/__init__.py`, `cli.py` (stub), `config.py` (stub)
- [x] Create `tests/` directory with empty `conftest.py`
- [x] Create annotated `example-config.yaml` covering all three scenarios (vanilla, modpack, mods)

## Phase 2: Configuration Layer
- [ ] Implement Pydantic v2 models in `config.py`: `ServerConfig`, `ModpackConfig`, `ModsConfig`, `RootConfig`
- [ ] Add `${VAR}` env-var interpolation in YAML loader (runs before Pydantic validation)
- [ ] Add model validator: enforce only one of `modpack` / `mods` is set
- [ ] Implement `mc-helper validate` subcommand
- [ ] Write `tests/test_config.py` (valid configs, mutual exclusion, env interpolation)

## Phase 3: Shared Infrastructure
- [ ] Implement `http_client.py`: `requests.Session` with Retry (5 attempts, exponential backoff), User-Agent header, `download_file()` with tqdm progress
- [ ] Implement `manifest.py`: load/save `.mc-helper-manifest.json`; `files_changed()`, `cleanup_stale()` helpers
- [ ] Implement `utils.py`: `compare_versions()`, `cleanup_stale()`, glob-based file deletion
- [ ] Write `tests/test_manifest.py`

## Phase 4: Server JAR Installers
- [ ] `server/vanilla.py` — Mojang launcher manifest → version resolution → JAR download + SHA-1 verify
  - API: `https://launchermeta.mojang.com/mc/game/version_manifest.json`
  - Reference: `docker-minecraft-server/scripts/start-deployVanilla`
- [ ] `server/fabric.py` — Fabric Meta API → launcher JAR download
  - API: `https://meta.fabricmc.net`
  - Reference: `mc-image-helper/.../fabric/FabricMetaClient.java`, `FabricLauncherInstaller.java`
- [ ] `server/forge.py` — Forge installer JAR download + `java -jar ... --installServer` subprocess
  - Reference: `mc-image-helper/.../forge/ForgeLikeInstaller.java`, `ForgeInstallerResolver.java`
  - Reference: `docker-minecraft-server/scripts/start-deployForge`
- [ ] `server/neoforge.py` — same pattern as forge.py
  - Reference: `mc-image-helper/.../forge/NeoForgeInstallerResolver.java`
  - Reference: `docker-minecraft-server/scripts/start-deployNeoForge`
- [ ] `server/paper.py` — PaperMC Downloads API → JAR + SHA-256 verify
  - API: `https://fill.papermc.io`
  - Reference: `mc-image-helper/.../paper/PaperDownloadsClient.java`, `InstallPaperCommand.java`
- [ ] `server/purpur.py` — Purpur API → JAR download
  - API: `https://api.purpurmc.org`
  - Reference: `mc-image-helper/.../purpur/PurpurDownloadsClient.java`
- [ ] Write `tests/test_vanilla.py` (mock HTTP responses)

## Phase 5: Modpack Installers
- [ ] `modpack/curseforge.py` — full install workflow
  - Slug/file-ID resolution via CurseForge API (`/v1/mods/search`, `/v1/mods/{id}/files`)
  - ZIP download → `manifest.json` parse → per-file API lookup + download
  - Exclude/force-include lists (mirrors `cf-exclude-include.json` schema in `docker-minecraft-server/files/`)
  - Overrides extraction, mod loader auto-install, stale cleanup
  - Reference: `mc-image-helper/.../curseforge/CurseForgeInstaller.java`, `CurseForgeApiClient.java`
  - Reference: `docker-minecraft-server/scripts/start-deployAutoCF`
- [ ] `modpack/modrinth.py` — full install workflow
  - Project/version resolution via Modrinth API (`/v2/project/{id}`, `/v2/project/{id}/versions`)
  - `.mrpack` ZIP → `modrinth.index.json` parse → file download (skip `env.server == "unsupported"`)
  - `overrides/` + `server-overrides/` extraction, loader auto-install, stale cleanup
  - Reference: `mc-image-helper/.../modrinth/ModrinthPackInstaller.java`, `ModpackIndex.java`
  - Reference: `docker-minecraft-server/scripts/start-deployModrinth`
- [ ] Write `tests/test_curseforge.py` (mock API + ZIP)
- [ ] Write `tests/test_modrinth.py` (mock API + ZIP)

## Phase 5.5: Server Pack Installer
- [ ] Add `ServerPackConfig` Pydantic model to `config.py` (`url` XOR `github`+`tag`+`asset`+`token`, plus `strip_components`, `disable_mods`, `force_update`)
- [ ] Extend `RootConfig` validator: enforce mutual exclusivity of `modpack`, `mods`, `server_pack`
- [ ] `pack/server_pack.py`:
  - GitHub release resolution: GET `https://api.github.com/repos/{owner}/{repo}/releases/latest` (or `/releases/tags/{tag}`) → glob-match `assets[].name` → download `browser_download_url`
    - Reference: `mc-image-helper` `github` subcommand family in `McImageHelper.java`
  - Direct URL: pass to `http_client.download_file()`
  - Format detection from filename: `.zip` → `zipfile`, `.tar.gz`/`.tgz` → `tarfile`
  - `strip_components`: skip N leading path segments per entry during extraction
    - Reference: `easy-add/main.go` `processTarGz` / `processZip`
  - Content-root auto-detection: find shallowest extracted dir containing `mods/`, `plugins/`, `config/`, or `*.jar`
    - Reference: `docker-minecraft-server/scripts/start-setupModpack` lines 213–220 (`mc-image-helper find --only-shallowest`)
  - SHA-1 checksum of archive stored in manifest; skip re-extraction if unchanged and `force_update` is false
    - Reference: `docker-minecraft-server/scripts/start-setupModpack` lines 189–243 (`checkSum` / `sha1sum`)
  - `disable_mods`: rename matched filenames to `*.disabled` post-extraction
    - Reference: `docker-minecraft-server/scripts/start-setupModpack` lines 204–207 (`GENERIC_PACKS_DISABLE_MODS`)
- [ ] Update `mc-helper setup` dispatch in `cli.py` to handle `server_pack` config
- [x] Update `example-config.yaml` with `server_pack` examples (direct URL and GitHub) — done in Phase 1
- [ ] Write `tests/test_server_pack.py` (mock HTTP, mock GitHub API, mock ZIP + tar.gz extraction)

## Phase 6: Individual Mod Installers
- [ ] `mods/modrinth.py` — resolve slug/ID/version → download JAR
  - Formats: `fabric-api`, `fabric-api:0.119.2+1.21.4`, `P7dR8mSH`
  - Reference: `mc-image-helper/.../modrinth/` (project version resolution)
  - Reference: `docker-minecraft-server/docs/variables.md` (`MODRINTH_PROJECTS` formats)
- [ ] `mods/curseforge.py` — resolve slug/project-ID/file-ID → download JAR
  - Formats: `jei`, `jei:4593548`, `238222`, full page URL
  - Reference: `mc-image-helper/.../curseforge/CurseForgeApiClient.java`
  - Reference: `docker-minecraft-server/docs/variables.md` (`CURSEFORGE_FILES` formats)
- [ ] Parallel download in `setup` command (ThreadPoolExecutor, max 10 workers)

## Phase 7: CLI & Output
- [ ] Implement `mc-helper setup` — dispatch to correct installer, write `server.properties`, `eula.txt`, `launch.sh`
  - `server.properties` key mapping from `docker-minecraft-server/files/property-definitions.json`
- [ ] Implement `mc-helper status` — read manifest, display installed versions
- [ ] Add `--dry-run` flag to `setup` (log actions without downloading)
- [ ] Add `--output-dir` flag to override `server.output_dir` from config

## Phase 8: Polish
- [ ] Update `CLAUDE.md` at repo root with mc-helper build/test/lint commands
- [ ] End-to-end smoke test: vanilla 1.21.1 setup (no API key required)
- [ ] End-to-end smoke test: Modrinth modpack (small pack, e.g. `adrenaline`)
