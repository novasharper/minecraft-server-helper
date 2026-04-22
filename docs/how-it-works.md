# How It Works

This document describes the internal mechanics of `mc-helper`: manifest tracking, HTTP behaviour, archive extraction, and idempotency.

---

## Manifest

Every `setup` run reads and writes `.mc-helper-manifest.json` in `output_dir`. This file is the source of truth for what has been installed.

```json
{
  "timestamp": "2026-04-14T12:00:00+00:00",
  "mc_version": "1.21.1",
  "loader_type": "fabric",
  "loader_version": "0.16.9",
  "files": [
    "mods/fabric-api-0.119.2+1.21.4.jar",
    "mods/sodium-mc1.21.1-0.6.0.jar"
  ]
}
```

On each run the installer:

1. Loads the existing manifest (or starts fresh).
2. Builds the new desired file list.
3. Downloads only files that are not already present.
4. Deletes files that are in the old manifest but absent from the new list (stale cleanup).
5. Saves the updated manifest.

This makes re-runs safe and fast.

### GitHub/URL pack idempotency

For GitHub and URL modpack platforms, re-extraction is skipped when the SHA-1 of the downloaded archive matches `pack_sha1` in the manifest and `force_update` is `false`. The SHA-1 is written to the manifest after the first successful extraction.

---

## HTTP client

All downloads share a single `requests.Session` configured with:

- **User-Agent:** `mc-helper/0.1.0`
- **Retry policy:** 5 attempts, exponential backoff (1 s, 2 s, 4 s, 8 s, 16 s), retries on HTTP 429/500/502/503/504.
- **Progress bar:** `tqdm` is shown for each file download (suppressed in parallel mod downloads to avoid interleaved output).

File downloads optionally verify SHA-1 or SHA-256 after writing. If a checksum fails the partial file is deleted and an error is raised.

CurseForge requests use a separate session with the `X-Api-Key` header injected.

---

## Parallel mod downloads

In `mods` mode (standalone or as an overlay on top of a modpack), all Modrinth and CurseForge mod downloads are submitted to a `ThreadPoolExecutor` with a maximum of 10 concurrent workers. URL-based mods are downloaded sequentially after the pool finishes. Errors from individual mods are collected and reported at the end; a non-zero exit code is returned if any download failed.

When `mods` is combined with a modpack, the extra mod paths are appended to the manifest after the base installer saves it. This ensures that on the next run, the base pack's stale-file cleanup correctly removes them before they are re-installed.

---

## Archive extraction (GitHub/URL packs)

Archive format is detected from the filename:

| Extension | Handler |
|---|---|
| `.zip` | Python `zipfile` |
| `.tar.gz`, `.tgz`, `.tar.bz2` | Python `tarfile` |

### `strip_components`

When `strip_components: N` is set (for GitHub/URL platforms), the first N path segments of every archive entry are removed during extraction. This mirrors the behaviour of `tar --strip-components=N` and is useful when the archive wraps everything in a single top-level directory.

### Content-root detection

After extraction, the tool searches for the shallowest directory that contains a subdirectory named `mods`, `plugins`, or `config`. If the content is nested one or more levels deep, the content root is promoted to `output_dir` directly.

### `exclude_mods` (as `disable_mods`)

For GitHub/URL packs, any file inside `mods/` whose name matches a glob pattern in `exclude_mods` is renamed to `<name>.disabled` after extraction. This is useful for disabling client-only mods that are bundled in server packs.

---

## Config loading pipeline

```
YAML file on disk
      ↓
yaml.safe_load()
      ↓
${VAR} interpolation  ← environment variables substituted here
      ↓
Pydantic v2 model_validate()
      ↓
RootConfig (validated)
```

Interpolation runs before validation, so Pydantic sees fully resolved values. If any `${VAR}` reference names an unset environment variable, the tool exits immediately before making any network requests.

## Launch plans and JVM flags

`mc-helper` detects the appropriate delivery channel for JVM and server arguments based on the installed artifact.

### Launch kinds

| Kind | Trigger | Writes |
|---|---|---|
| `jar` | `.jar` artifact (Vanilla / Fabric / Paper / Purpur) | `launch.sh` with full `java … -jar …` line. |
| `run_sh` | `run.sh` (Forge 1.17+ / NeoForge) | Merges `-Xms/-Xmx` and JVM args into `user_jvm_args.txt` (idempotent); `launch.sh` execs `./run.sh`. |
| `cf_script` | `.sh` + CurseForge settings files present | Patches `settings-local.sh`, `settings.cfg`, or `variables.txt` in place. |
| `bare_script` | Generic `.sh` fallback | Thin `launch.sh`; warns if JVM args are configured (nowhere to put them). |

### Auto JVM flags

The tool automatically applies certain flags based on the Minecraft version and server state:

- **Log4j CVE shim:** Applied automatically for MC 1.7 to <1.18.1 (except for `cf_script` which handles its own).
- **GTNH args:** `-Dfml.readTimeout=180` and version-specific memory flags are applied when `loader_type` is `gtnh`.

### Opt-in flag bundles

Users can enable pre-configured flag bundles in the `server.jvm` section:

- `use_aikar_flags`: Optimized G1GC flags for Minecraft.
- `use_meowice_flags`: Aggressive optimization flags (requires Java 17+, falls back to Aikar if older).
- `use_meowice_graalvm_flags`: Experimental optimization flags for GraalVM.
- `use_flare_flags`: Enables profiling support for Flare.
- `use_simd_flags`: Enables the Vector API (`jdk.incubator.vector`).

Java version is auto-detected by running `java -version` to ensure compatibility with specific flag bundles.

---

## Generated files

### `eula.txt`

```
eula=true
```

Written unconditionally. Reflects `server.eula` from the config.

### `server.properties`

If `properties` is empty, the file is not written at all — any existing `server.properties` in `output_dir` is left untouched.

When `properties` is non-empty and no `server.properties` exists yet, the file is created with one `key=value` line per entry:

```
difficulty=normal
max-players=20
motd=A Minecraft Server
```

When `server.properties` already exists (e.g. on a re-run or from the server pack), the file is merged in-place: keys that appear in the config map are updated to their new values, keys not in the config map are preserved verbatim (including comments and blank lines), and any config keys not already in the file are appended at the end.

### `launch.sh`

A minimal POSIX shell script that starts the server. The script is created with executable permissions (`chmod +x`). `"$@"` passes any extra arguments through, so you can add JVM flags at launch time without editing the script. The exact content of the script depends on the [Launch kind](#launch-kinds) detected during setup.
