# Configuration Reference

All behavior is driven by a single YAML config file. Pass it to every command with `--config <file>`.

A config file has one required section (`server`) and optional install sections. `modpack` and `mods` are the primary install modes. `mods` may appear alone **or** alongside `modpack` to add extra mods on top of the base install.

---

## `server`

Controls the server type, Minecraft version, output location, and runtime settings.

```yaml
server:
  type: fabric
  minecraft_version: "1.21.1"
  loader_version: LATEST
  output_dir: ./server
  eula: true
  memory: 2G
  properties:
    difficulty: normal
    max-players: 20
    motd: "A Minecraft Server"
    online-mode: true
```

| Field | Type | Default | Description |
|---|---|---|---|
| `type` | string | *(required unless `modpack` is set)* | Server type. One of `vanilla`, `fabric`, `forge`, `neoforge`, `paper`, `purpur`. When `modpack` is used, this field acts as a loader hint for mod-compatibility filtering; the actual loader is read from the pack metadata. |
| `minecraft_version` | string | `LATEST` | Minecraft version, e.g. `1.21.1`, `LATEST`, or `SNAPSHOT`. Not used when `modpack` is set — the version comes from the pack. |
| `loader_version` | string | `LATEST` | Loader version for `fabric`, `forge`, or `neoforge`. Ignored for `vanilla`, `paper`, `purpur`. |
| `output_dir` | path | `./server` | Directory where server files are installed. Created if it does not exist. |
| `eula` | bool | `false` | Set to `true` to agree to the Minecraft EULA. Written to `eula.txt`. |
| `memory` | string | `1G` | JVM heap size, e.g. `2G`, `512M`. Used in the generated `launch.sh`. |
| `properties` | map | `{}` | Written verbatim to `server.properties`. Keys are the standard Minecraft property names (e.g. `difficulty`, `max-players`, `motd`). |

`properties` keys map directly to `server.properties` entries. See the [Minecraft wiki](https://minecraft.wiki/w/Server.properties) for all valid keys; the canonical machine-readable mapping is `docker-minecraft-server/files/property-definitions.json` in the parent repository.

---

## Install modes

The valid combinations are:

| Config | Behaviour |
|---|---|
| *(none)* | Server JAR only (vanilla/loader-only). |
| `modpack` | Full modpack install (mods + overrides + server JAR). |
| `mods` | Individual mods + server JAR. |
| `modpack` + `mods` | Modpack install, then extra mods layered on top. |

---

## `modpack`

Installs a modpack from Modrinth, CurseForge, FTB, or GTNH, or extracts a pre-assembled server pack from GitHub or a direct URL.

```yaml
modpack:
  platform: modrinth       # modrinth | curseforge | ftb | gtnh | github | url
  source:
    project: "better-mc-fabric"
    version: LATEST
  version_type: release
```

### Modrinth fields

| Field | Type | Default | Description |
|---|---|---|---|
| `platform` | string | *(required)* | Must be `modrinth`. |
| `source.project` | string | *(required)* | Project slug, ID, or page URL. |
| `source.version` | string | `LATEST` | Version ID or `LATEST`. |
| `source.version_type` | string | `release` | Minimum acceptable stability: `release`, `beta`, or `alpha`. |

### CurseForge fields

| Field | Type | Default | Description |
|---|---|---|---|
| `platform` | string | *(required)* | Must be `curseforge`. |
| `source.api_key` | string | *(required)* | CurseForge API key. Use `${CF_API_KEY}` to read from the environment. |
| `source.slug` | string | `null` | Project slug, e.g. `all-the-mods-9`. |
| `source.file_id` | int | `null` | Specific file ID. Null selects the newest matching file. |
| `source.filename_matcher` | string | `null` | Optional substring that the filename must contain. |

Either `source.slug` or `source.file_id` is required for CurseForge.

### FTB fields

| Field | Type | Default | Description |
|---|---|---|---|
| `platform` | string | *(required)* | Must be `ftb`. |
| `source.pack_id` | int | *(required)* | Numeric FTB pack ID. |
| `source.version_id` | int | `null` | Specific version ID. Null picks the latest version matching `version_type`. |
| `source.api_key` | string | `public` | API key for private packs. |
| `source.version_type` | string | `release` | Preferred release stability: `release`, `beta`, or `alpha`. |

To find a `pack_id`, visit the modpack's page on [feed-the-beast.com](https://www.feed-the-beast.com/modpacks). The ID is the number at the end of the URL (e.g., in `https://www.feed-the-beast.com/modpacks/130-ftb-presents-direwolf20-121`, the ID is `130`).

### GTNH fields

| Field | Type | Default | Description |
|---|---|---|---|
| `platform` | string | *(required)* | Must be `gtnh`. |
| `source.version` | string | `latest` | `latest`, `latest-dev`, or an exact version (e.g. `2.7.0`). |

GTNH installation uses a fixed Minecraft version (1.7.10) and handles its own server JAR installation.

### Server pack (GitHub/URL) fields

Extracts a pre-assembled server archive (ZIP, tar.gz, tgz, or tar.bz2) into `output_dir`.

```yaml
modpack:
  platform: github
  source:
    repo: "ATM-Team/ATM-10"
    tag: LATEST
    asset: "*server*"
    strip_components: 1
  exclude_mods:
    - "OptiFine*.jar"
```

Exactly one of `github` or `url` must be used as the platform.

#### Source: GitHub release (`platform: github`)

| Field | Type | Default | Description |
|---|---|---|---|
| `source.repo` | string | *(required)* | Repository in `owner/repo` format. |
| `source.tag` | string | `LATEST` | Release tag or `LATEST`. |
| `source.asset` | string | `null` | Glob pattern to match the asset filename. |
| `source.token` | string | `null` | GitHub personal access token. |

#### Source: Direct URL (`platform: url`)

| Field | Type | Description |
|---|---|---|
| `source.url` | string | Direct download URL for the archive. |

#### Shared server pack options

| Field | Type | Default | Description |
|---|---|---|---|
| `source.strip_components` | int | `0` | Strip N leading path segments during extraction. |
| `source.force_update` | bool | `false` | Re-extract even if the SHA-1 matches. |
| `source.mc_version` | string | `null` | Manual override for detected Minecraft version. |
| `source.loader_type` | string | `null` | Manual override for detected loader type. |
| `source.loader_version` | string | `null` | Manual override for detected loader version. |

### Shared modpack fields

| Field | Type | Default | Description |
|---|---|---|---|
| `exclude_mods` | list[string] | `[]` | Glob patterns to skip (Modrinth/CurseForge/FTB) or rename to `.disabled` (GitHub/URL). |
| `force_include_mods` | list[string] | `[]` | Slugs or IDs to always include. (CurseForge only.) |
| `overrides_exclusions` | list[string] | `[]` | Paths inside `overrides/` to skip. (Modrinth/CurseForge only.) |

---

## `mods`

Installs individual mods from Modrinth, CurseForge, or direct URLs.

```yaml
mods:
  modrinth:
    - fabric-api
    - "sodium:mc1.21-0.6.0"
  curseforge:
    api_key: ${CF_API_KEY}
    files:
      - jei
  urls:
    - https://example.com/mymod-1.0.jar
```

### Using `mods` with `modpack`

When `mods` is combined with `modpack`, the base pack installs first and then the extra mods are downloaded into `<output_dir>/mods/`.

```yaml
server:
  type: fabric
  output_dir: ./server
  eula: true

modpack:
  platform: modrinth
  source:
    project: "better-mc-fabric"

mods:
  modrinth:
    - iris
```

---

## Environment variable interpolation

Any `${VAR}` reference in the YAML is replaced with the value of the named environment variable before the config is parsed. This substitution happens on all string values, including nested ones.

```yaml
modpack:
  api_key: ${CF_API_KEY}
  token: ${GITHUB_TOKEN}
```

If a referenced variable is not set, `mc-helper` exits immediately with an error listing the missing variable name.

---

## Full example

See [`example-config.yaml`](../example-config.yaml) in the project root for an annotated file covering all three install modes.
