# minecraft-server-helper — TODO

## Phase 1: Project Scaffold ✓
- [x] Create `pyproject.toml` (Poetry) with dependencies (pydantic, PyYAML, requests, tqdm) and `mc-helper` entry point
- [x] Create `src/mc_helper/__init__.py`, `cli.py` (stub), `config.py` (stub)
- [x] Create `tests/` directory with empty `conftest.py`
- [x] Create annotated `example-config.yaml` covering all three scenarios (vanilla, modpack, mods)

## Phase 2: Configuration Layer ✓
- [x] Implement Pydantic v2 models in `config.py`: `ServerConfig`, `ModpackConfig`, `ModsConfig`, `ServerPackConfig`, `RootConfig`
- [x] Add `${VAR}` env-var interpolation in YAML loader (runs before Pydantic validation)
- [x] Add model validator: enforce exactly one of `modpack` / `mods` / `server_pack` is set
- [x] Implement `mc-helper validate` subcommand
- [x] Write `tests/test_config.py` (valid configs, mutual exclusion, env interpolation) — 28 tests

## Phase 3: Shared Infrastructure ✓
- [x] Implement `http_client.py`: `requests.Session` with Retry (5 attempts, exponential backoff), User-Agent header, `download_file()` with tqdm progress + SHA-1/SHA-256 verification
- [x] Implement `manifest.py`: load/save `.mc-helper-manifest.json`; `files_changed()`, `cleanup_stale()` helpers
- [x] Implement `utils.py`: `compare_versions()`, `glob_delete()`, `find_content_root()`, `disable_mods()`
- [x] Write `tests/test_manifest.py` — 16 tests

## Phase 4: Server JAR Installers ✓
- [x] `server/vanilla.py` — Mojang launcher manifest → version resolution → JAR download + SHA-1 verify
- [x] `server/fabric.py` — Fabric Meta API → launcher JAR download
- [x] `server/forge.py` — Forge installer JAR download + `java -jar ... --installServer` subprocess
- [x] `server/neoforge.py` — Maven metadata resolution, forge-like vs neoforge artifact handling, `--installServer`
- [x] `server/paper.py` — PaperMC Fill API v3 → JAR + SHA-256 verify
- [x] `server/purpur.py` — Purpur API → JAR download
- [x] Write `tests/test_vanilla.py` — 8 tests (mock HTTP responses)

## Phase 5: Modpack Installers ✓
- [x] `modpack/curseforge.py` — slug/file-ID resolution, ZIP download, manifest.json parse, parallel mod downloads, overrides extraction, stale cleanup, manifest save
- [x] `modpack/modrinth.py` — version resolution, .mrpack download, modrinth.index.json parse, skip env.server==unsupported, parallel downloads, overrides/server-overrides extraction, stale cleanup, manifest save
- [x] Write `tests/test_curseforge.py` — 11 tests (mock API + ZIP)
- [x] Write `tests/test_modrinth.py` — 12 tests (mock API + ZIP)

## Phase 5.5: Server Pack Installer ✓
- [x] Add `ServerPackConfig` Pydantic model to `config.py` — done in Phase 2
- [x] Extend `RootConfig` validator: enforce mutual exclusivity of `modpack`, `mods`, `server_pack` — done in Phase 2
- [x] `pack/server_pack.py`: GitHub release resolution, direct URL, format detection, strip_components, content-root auto-detection, SHA-1 idempotency, disable_mods rename
- [ ] Update `mc-helper setup` dispatch in `cli.py` to handle `server_pack` config
- [x] Update `example-config.yaml` with `server_pack` examples (direct URL and GitHub) — done in Phase 1
- [x] Write `tests/test_server_pack.py` — 18 tests (mock HTTP, GitHub API, ZIP + tar.gz)

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
