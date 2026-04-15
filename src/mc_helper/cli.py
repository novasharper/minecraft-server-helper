import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mc_helper.config import load_config
from mc_helper.http_client import build_session, download_file
from mc_helper.manifest import Manifest
from mc_helper.modpack import curseforge as modpack_cf
from mc_helper.modpack import modrinth as modpack_mr
from mc_helper.mods import curseforge as cf_mods
from mc_helper.mods import modrinth as mr_mods
from mc_helper.pack import server_pack
from mc_helper.server import fabric, forge, neoforge, paper, purpur, vanilla
from mc_helper.server.vanilla import resolve_version


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mc-helper",
        description="Download and configure a Minecraft server from a YAML config file.",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        required=True,
        help="Path to the YAML configuration file.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # setup
    setup_parser = subparsers.add_parser("setup", help="Download and install the server.")
    setup_parser.add_argument("--output-dir", metavar="DIR", help="Override server.output_dir.")
    setup_parser.add_argument(
        "--dry-run", action="store_true", help="Log actions without downloading."
    )

    # validate
    subparsers.add_parser("validate", help="Validate the configuration file.")

    # status
    subparsers.add_parser("status", help="Show installed server state from the manifest.")

    args = parser.parse_args()

    if args.command == "validate":
        _cmd_validate(args)
    elif args.command == "setup":
        _cmd_setup(args)
    elif args.command == "status":
        _cmd_status(args)


def _cmd_validate(args: argparse.Namespace) -> None:
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"Invalid config: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"OK — server type={config.server.type}, mc={config.server.minecraft_version}")


def _cmd_setup(args: argparse.Namespace) -> None:
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"Invalid config: {exc}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else config.server.output_dir
    dry_run: bool = args.dry_run

    if dry_run:
        print("[dry-run] No files will be downloaded or written.")

    if config.server_pack:
        _setup_server_pack(config, output_dir, dry_run)
    elif config.modpack:
        _setup_modpack(config, output_dir, dry_run)
    elif config.mods:
        _setup_mods(config, output_dir, dry_run)
    else:
        # Vanilla / loader-only: install server JAR, then write config files
        jar_path = _install_server_jar(config, output_dir, dry_run)
        _write_server_files(config, output_dir, jar_path, dry_run)
        if not dry_run:
            print(f"Server installed to {output_dir}")


def _resolve_mc_version(session, version: str) -> str:
    """Resolve 'LATEST' / 'SNAPSHOT' to a concrete Minecraft release version."""
    if version.upper() not in ("LATEST", "SNAPSHOT"):
        return version
    return resolve_version(session, version)


def _install_server_jar(config, output_dir: Path, dry_run: bool) -> Path | None:
    """Install the appropriate server JAR.

    Returns the path to the installed JAR, or None for Forge/NeoForge (which
    create their own run script via --installServer).
    """
    server = config.server

    if dry_run:
        print(
            f"[dry-run] Would install {server.type} {server.minecraft_version} "
            f"server to {output_dir}"
        )
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()
    mc_version = _resolve_mc_version(session, server.minecraft_version)

    if server.type == "vanilla":
        return vanilla.VanillaInstaller(mc_version, session=session).install(output_dir)

    elif server.type == "fabric":
        return fabric.FabricInstaller(
            mc_version,
            loader_version=server.loader_version,
            session=session,
        ).install(output_dir)

    elif server.type == "forge":
        forge.ForgeInstaller(
            mc_version,
            forge_version=server.loader_version,
            session=session,
        ).install(output_dir)
        return None  # forge --installServer creates its own run.sh

    elif server.type == "neoforge":
        neoforge.NeoForgeInstaller(
            mc_version,
            neoforge_version=server.loader_version,
            session=session,
        ).install(output_dir)
        return None  # neoforge --installServer creates its own run.sh

    elif server.type == "paper":
        return paper.PaperInstaller(mc_version, session=session).install(output_dir)

    elif server.type == "purpur":
        return purpur.PurpurInstaller(mc_version, session=session).install(output_dir)

    else:
        raise ValueError(f"Unknown or unsupported server type: {server.type!r}")


def _write_server_files(config, output_dir: Path, jar_path: Path | None, dry_run: bool) -> None:
    """Write eula.txt, server.properties, and launch.sh into output_dir."""
    server = config.server

    # eula.txt
    eula_value = str(server.eula).lower()
    eula_path = output_dir / "eula.txt"
    if dry_run:
        print(f"[dry-run] Would write {eula_path}: eula={eula_value}")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        eula_path.write_text(f"eula={eula_value}\n")

    # server.properties — merge: preserve existing keys, overlay config keys
    if server.properties:
        props_path = output_dir / "server.properties"
        if dry_run:
            print(f"[dry-run] Would write/merge {props_path}:")
            for k, v in server.properties.items():
                print(f"  {k}={v}")
        else:
            if props_path.exists():
                # Merge: update matching keys in-place, preserving comments and
                # blank lines; append any config keys not already in the file.
                lines: list[str] = []
                seen_keys: set[str] = set()
                for raw in props_path.read_text().splitlines():
                    if "=" in raw and not raw.lstrip().startswith("#"):
                        k, _, _ = raw.partition("=")
                        k = k.strip()
                        if k in server.properties:
                            lines.append(f"{k}={server.properties[k]}")
                            seen_keys.add(k)
                        else:
                            lines.append(raw)
                    else:
                        lines.append(raw)
                for k, v in server.properties.items():
                    if k not in seen_keys:
                        lines.append(f"{k}={v}")
                props_path.write_text("\n".join(lines) + "\n")
            else:
                props_path.write_text(
                    "\n".join(f"{k}={v}" for k, v in server.properties.items()) + "\n"
                )

    # launch.sh
    launch_path = output_dir / "launch.sh"
    mem = server.memory
    if jar_path is not None:
        jar_name = jar_path.name
        launch_content = (
            f"#!/bin/sh\n" f'exec java -Xmx{mem} -Xms{mem} -jar {jar_name} nogui "$@"\n'
        )
    elif server.type in ("forge", "neoforge"):
        launch_content = (
            "#!/bin/sh\n"
            "# The Forge/NeoForge installer created run.sh — invoke it here.\n"
            'exec ./run.sh "$@"\n'
        )
    else:
        launch_content = (
            f"#!/bin/sh\n" f'exec java -Xmx{mem} -Xms{mem} -jar server.jar nogui "$@"\n'
        )

    if dry_run:
        print(f"[dry-run] Would write {launch_path}:")
        for line in launch_content.splitlines():
            print(f"  {line}")
    else:
        launch_path.write_text(launch_content)
        launch_path.chmod(0o755)


def _setup_server_pack(config, output_dir: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] Would install server pack to {output_dir}")
        _write_server_files(config, output_dir, None, dry_run)
        return

    sp = config.server_pack
    server_pack.ServerPackInstaller(
        url=sp.url,
        github=sp.github,
        tag=sp.tag,
        asset=sp.asset,
        token=sp.token,
        strip_components=sp.strip_components,
        disable_mods_patterns=sp.disable_mods,
        force_update=sp.force_update,
    ).install(output_dir)
    _write_server_files(config, output_dir, None, dry_run)
    print(f"Server pack installed to {output_dir}")


def _setup_modpack(config, output_dir: Path, dry_run: bool) -> None:
    mp = config.modpack

    if dry_run:
        print(f"[dry-run] Would install {mp.platform} modpack to {output_dir}")
        _write_server_files(config, output_dir, None, dry_run)
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    loader = (
        config.server.type if config.server.type not in ("vanilla", "paper", "purpur") else None
    )

    session = build_session()
    mc_version = _resolve_mc_version(session, config.server.minecraft_version)

    if mp.platform == "modrinth":
        modpack_mr.ModrinthPackInstaller(
            project=mp.project,
            minecraft_version=mc_version,
            loader=loader,
            version_type=mp.version_type,
            requested_version=mp.version,
            exclude_mods=mp.exclude_mods or None,
            overrides_exclusions=mp.overrides_exclusions or None,
            session=session,
        ).install(output_dir)
    elif mp.platform == "curseforge":
        modpack_cf.CurseForgePackInstaller(
            api_key=mp.api_key,
            slug=mp.slug,
            file_id=mp.file_id,
            filename_matcher=mp.filename_matcher,
            exclude_mods=mp.exclude_mods or None,
            force_include_mods=mp.force_include_mods or None,
            overrides_exclusions=mp.overrides_exclusions or None,
        ).install(output_dir)

    # Install server JAR using loader info the modpack installer saved to manifest
    manifest = Manifest(output_dir)
    manifest.load()
    jar_path: Path | None = None
    loader_type = manifest.loader_type
    mc_version = manifest.mc_version
    loader_version = manifest.loader_version

    if loader_type == "fabric":
        jar_path = fabric.FabricInstaller(
            mc_version, loader_version=loader_version, session=session
        ).install(output_dir)
    elif loader_type == "forge":
        forge.ForgeInstaller(mc_version, forge_version=loader_version, session=session).install(
            output_dir
        )
    elif loader_type == "neoforge":
        neoforge.NeoForgeInstaller(
            mc_version, neoforge_version=loader_version, session=session
        ).install(output_dir)
    elif loader_type == "quilt":
        raise NotImplementedError("Quilt server installation is not supported")
    elif loader_type in (None, "vanilla"):
        jar_path = vanilla.VanillaInstaller(mc_version, session=session).install(output_dir)
    elif loader_type == "paper":
        jar_path = paper.PaperInstaller(mc_version, session=session).install(output_dir)
    elif loader_type == "purpur":
        jar_path = purpur.PurpurInstaller(mc_version, session=session).install(output_dir)
    else:
        raise ValueError(f"Unknown loader type from modpack manifest: {loader_type!r}")

    _write_server_files(config, output_dir, jar_path, dry_run)
    print(f"Modpack installed to {output_dir}")


def _setup_mods(config, output_dir: Path, dry_run: bool) -> None:
    if dry_run:
        mods_cfg = config.mods
        mr_count = len(mods_cfg.modrinth or [])
        cf_count = len(mods_cfg.curseforge.files) if mods_cfg.curseforge else 0
        url_count = len(mods_cfg.urls or [])
        print(
            f"[dry-run] Would install {mr_count} Modrinth + {cf_count} CurseForge "
            f"+ {url_count} URL mod(s) to {output_dir}/mods/"
        )
        jar_path = _install_server_jar(config, output_dir, dry_run)
        _write_server_files(config, output_dir, jar_path, dry_run)
        return

    mods_cfg = config.mods
    loader = (
        config.server.type if config.server.type not in ("vanilla", "paper", "purpur") else None
    )

    session = build_session()
    mc_ver = _resolve_mc_version(session, config.server.minecraft_version)
    installed: list[str] = []
    errors: list[str] = []

    tasks: list[tuple] = []

    for spec in mods_cfg.modrinth or []:
        tasks.append(("modrinth", spec))

    cf = mods_cfg.curseforge
    if cf:
        cf_session = build_session(extra_headers={"X-Api-Key": cf.api_key})
        for spec in cf.files:
            tasks.append(("curseforge", spec))

    def _run(kind: str, spec: str) -> str:
        if kind == "modrinth":
            return mr_mods.ModrinthModInstaller(
                spec,
                minecraft_version=mc_ver,
                loader=loader,
                session=session,
                show_progress=False,
            ).install(output_dir)
        else:
            return cf_mods.CurseForgeModInstaller(
                spec,
                api_key=cf.api_key,
                minecraft_version=mc_ver,
                loader=loader,
                session=cf_session,
                show_progress=False,
            ).install(output_dir)

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_run, kind, spec): (kind, spec) for kind, spec in tasks}
        for fut in as_completed(futures):
            kind, spec = futures[fut]
            try:
                path = fut.result()
                installed.append(path)
                print(f"  installed {spec} → {path}")
            except Exception as exc:
                errors.append(f"{spec}: {exc}")
                print(f"  ERROR {spec}: {exc}", file=sys.stderr)

    for spec in mods_cfg.urls or []:
        filename = spec.split("/")[-1].split("?")[0]
        dest = output_dir / "mods" / filename
        download_file(spec, dest, session=session, show_progress=True)
        installed.append(str(Path("mods") / filename))
        print(f"  installed {spec} → mods/{filename}")

    if errors:
        print(f"\n{len(errors)} mod(s) failed to install.", file=sys.stderr)
        sys.exit(1)

    print(f"\n{len(installed)} mod(s) installed to {output_dir}/mods/")

    # Install server JAR and write config files
    jar_path = _install_server_jar(config, output_dir, dry_run)
    _write_server_files(config, output_dir, jar_path, dry_run)


def _cmd_status(args: argparse.Namespace) -> None:
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"Invalid config: {exc}", file=sys.stderr)
        sys.exit(1)

    output_dir = config.server.output_dir
    manifest = Manifest(output_dir)
    manifest.load()

    if not manifest._data:
        print(f"No manifest found in {output_dir} — server has not been set up yet.")
        return

    print(f"Manifest: {manifest.path}")
    if manifest.mc_version:
        print(f"  Minecraft version : {manifest.mc_version}")
    if manifest.loader_type:
        print(f"  Loader            : {manifest.loader_type}")
    if manifest.loader_version:
        print(f"  Loader version    : {manifest.loader_version}")
    if manifest.pack_sha1:
        print(f"  Pack SHA-1        : {manifest.pack_sha1}")
    files = manifest.files
    if files:
        print(f"  Tracked files     : {len(files)}")
        for f in files:
            print(f"    {f}")
