# Server Types

The `server.type` field controls which server software is downloaded and how it is installed. Each type has its own version resolution strategy and installation method.

---

## `vanilla`

Plain Mojang server JAR with no mod loader.

**API:** [Mojang launcher manifest](https://launchermeta.mojang.com/mc/game/version_manifest.json)

**Version resolution:**

| Value | Resolves to |
|---|---|
| `LATEST` | The latest stable release. |
| `SNAPSHOT` | The latest snapshot build. |
| `1.21.1` | That exact version. Fails if not found in the manifest. |

**Installed files:**

- `minecraft_server.<version>.jar` — SHA-1 verified.

**`loader_version`:** Ignored.

---

## `fabric`

Fabric mod loader. Downloads the Fabric unified server launcher JAR (which embeds the loader, mappings, and a vanilla JAR fetcher).

**API:** [Fabric Meta](https://meta.fabricmc.net)

**Version resolution:**

- `minecraft_version` is resolved the same way as vanilla (`LATEST`, `SNAPSHOT`, or a specific version).
- `loader_version: LATEST` picks the newest stable Fabric loader version.
- `installer_version` is always resolved to the latest available installer.

**Installed files:**

- `fabric-server-launch.jar` — the unified launcher.
- `server.properties` is read by Fabric to launch the underlying Minecraft server on first run.

**Launch:** `java -jar fabric-server-launch.jar nogui`

---

## `forge`

Minecraft Forge mod loader. Downloads the Forge installer JAR and runs it with `--installServer`.

**API:** [Forge Maven](https://maven.minecraftforge.net)

**Version resolution:**

| `loader_version` | Resolves to |
|---|---|
| `LATEST` | The newest Forge version for the given `minecraft_version`. |
| `RECOMMENDED` | The recommended Forge version (may fall back to latest if unavailable). |
| `47.3.0` | That exact Forge version. |

**Installation:**

1. Download `forge-<mc>-<forge>-installer.jar`.
2. Run `java -jar forge-<mc>-<forge>-installer.jar --installServer` in `output_dir`.
3. The installer creates `run.sh` (Linux/macOS) and `run.bat` (Windows).

**`launch.sh`:** Delegates to the Forge-generated `./run.sh`.

**Note:** Java must be on `PATH` at setup time.

---

## `neoforge`

NeoForge mod loader (the Forge fork maintained post-1.20.1). Same installation pattern as Forge.

**API:** [NeoForge Maven](https://maven.neoforged.net)

**Version resolution:**

- For Minecraft 1.20.1 and earlier (the "forge-like" branch): resolves via the Forge-compatible Maven path.
- For Minecraft 1.20.2+: resolves the latest `<mc_major>.<mc_minor>.*` NeoForge build.
- `loader_version: LATEST` always selects the newest matching version.

**Installation:** Same subprocess pattern as Forge — runs `--installServer` and produces `run.sh`.

**`launch.sh`:** Delegates to `./run.sh`.

---

## `paper`

[PaperMC](https://papermc.io) — a high-performance Bukkit/Spigot fork with plugin support.

**API:** [PaperMC Fill API v3](https://fill.papermc.io)

**Version resolution:**

- The newest build for the given `minecraft_version` is selected automatically.
- `loader_version` is ignored.

**Installed files:**

- `paper-<mc>-<build>.jar` — SHA-256 verified.

**Launch:** `java -jar paper-<mc>-<build>.jar nogui`

---

## `purpur`

[Purpur](https://purpurmc.org) — a Paper fork with additional gameplay and configuration options.

**API:** [Purpur API](https://api.purpurmc.org)

**Version resolution:**

- The newest build for the given `minecraft_version` is selected automatically.
- `loader_version` is ignored.

**Installed files:**

- `purpur-<mc>-<build>.jar`

**Launch:** `java -jar purpur-<mc>-<build>.jar nogui`

---

## Version string summary

| `minecraft_version` | Meaning |
|---|---|
| `LATEST` | Latest stable release (all types). |
| `SNAPSHOT` | Latest snapshot (vanilla only). |
| `1.21.1` | Exact version; error if not available. |

| `loader_version` | Applicable types | Meaning |
|---|---|---|
| `LATEST` | fabric, forge, neoforge | Newest available loader for the given Minecraft version. |
| `RECOMMENDED` | forge | Forge-recommended version; falls back to latest. |
| `<specific>` | fabric, forge, neoforge | Pin to an exact loader version. |
| *(any)* | vanilla, paper, purpur | Ignored. |

---

## Modpack-embedded server JARs

When `modpack` is used, the modpack installer resolves the server type and loader version from the modpack metadata (e.g. `modrinth.index.json` or CurseForge `manifest.json`) and installs the loader automatically. The `server.type` field is used only as a hint for mod compatibility filtering in that case.
