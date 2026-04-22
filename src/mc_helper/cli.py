import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mc_helper import launch as launcher
from mc_helper import server as server_pkg
from mc_helper.config import JvmConfig, ServerConfig, load_config
from mc_helper.http_client import build_session, download_file
from mc_helper.manifest import Manifest
from mc_helper.modpack import curseforge as modpack_cf
from mc_helper.modpack import custom as modpack_custom
from mc_helper.modpack import ftb as modpack_ftb
from mc_helper.modpack import gtnh as modpack_gtnh
from mc_helper.modpack import modrinth as modpack_mr
from mc_helper.mods import curseforge as cf_mods
from mc_helper.mods import modrinth as mr_mods
from mc_helper.server import resolve_minecraft_version
from mc_helper.server_properties import merge_server_properties

log = logging.getLogger(__name__)


def main() -> None:
    _config_parent = argparse.ArgumentParser(add_help=False)
    _config_parent.add_argument(
        "--config",
        metavar="FILE",
        default=argparse.SUPPRESS,
        help="Path to the YAML configuration file.",
    )

    parser = argparse.ArgumentParser(
        prog="mc-helper",
        description="Download and configure a Minecraft server from a YAML config file.",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        default=None,
        help="Path to the YAML configuration file.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser(
        "setup", parents=[_config_parent], help="Download and install the server."
    )
    setup_parser.add_argument("--output-dir", metavar="DIR", help="Override server.output_dir.")
    setup_parser.add_argument(
        "--dry-run", action="store_true", help="Log actions without downloading."
    )

    subparsers.add_parser(
        "validate", parents=[_config_parent], help="Validate the configuration file."
    )

    subparsers.add_parser(
        "status", parents=[_config_parent], help="Show installed server state from the manifest."
    )

    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug-level logging.")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[mc-helper] %(message)s",
        stream=sys.stderr,
    )

    if not args.config:
        parser.error("argument --config is required")

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
        log.error("Invalid config: %s", exc)
        sys.exit(1)

    log.info("OK — server type=%s, mc=%s", config.server.type, config.server.minecraft_version)


def _cmd_setup(args: argparse.Namespace) -> None:
    try:
        config = load_config(args.config)
    except Exception as exc:
        log.error("Invalid config: %s", exc)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else config.server.output_dir
    dry_run: bool = args.dry_run

    if dry_run:
        log.info("[dry-run] No files will be downloaded or written.")

    if config.modpack:
        _setup_modpack(config, output_dir, dry_run)
    elif config.mods:
        _setup_mods(config, output_dir, dry_run)
        return
    else:
        start_artifact = _install_server_jar(config, output_dir, dry_run)
        _write_server_files(config, output_dir, start_artifact, dry_run)
        if not dry_run:
            log.info("Server installed to %s", output_dir)
        return

    if config.mods:
        _install_extra_mods(config, output_dir, dry_run)


def _install_server_jar(config, output_dir: Path, dry_run: bool) -> Path | None:
    """Install the appropriate server JAR and return the start artifact path.

    Returns None for Forge/NeoForge (they create their own run.sh).
    """
    server = config.server

    if server.type is None:
        raise ValueError("server.type must be set for this installation mode")

    if dry_run:
        log.info(
            "[dry-run] Would install %s %s server to %s",
            server.type,
            server.minecraft_version,
            output_dir,
        )
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()
    mc_version = resolve_minecraft_version(session, server.minecraft_version)
    log.info("Installing %s %s server...", server.type, mc_version)

    server_with_resolved = server.model_copy(update={"minecraft_version": mc_version})
    installer = server_pkg.installer_for(server_with_resolved, session=session)
    start_artifact = installer.install(output_dir)

    manifest = Manifest(output_dir)
    manifest.load()
    manifest.mc_version = mc_version
    manifest.loader_type = server.type
    if server.type not in ("vanilla", "paper", "purpur"):
        manifest.loader_version = server.loader_version
    if start_artifact is not None:
        manifest.add_file(start_artifact.relative_to(output_dir))
    manifest.save()

    return start_artifact


def _write_server_files(
    config, output_dir: Path, start_artifact: Path | None, dry_run: bool
) -> None:
    """Write eula.txt, server.properties, and launch.sh into output_dir."""
    log.info("Writing server files to %s...", output_dir)
    server = config.server

    eula_value = str(server.eula).lower()
    eula_path = output_dir / "eula.txt"
    if dry_run:
        print(f"[dry-run] Would write {eula_path}: eula={eula_value}")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        eula_path.write_text(f"eula={eula_value}\n")

    if server.properties:
        props_path = output_dir / "server.properties"
        if dry_run:
            print(f"[dry-run] Would write/merge {props_path}:")
            for k, v in server.properties.items():
                print(f"  {k}={v}")
        else:
            merge_server_properties(props_path, server.properties)

    if dry_run:
        start_artifact = output_dir / "dry-run.jar"
    elif start_artifact is None:
        raise ValueError(
            "start_artifact is None; the server installer must return the start artifact path"
        )

    plan = launcher.detect_launch_plan(output_dir, start_artifact)
    launcher.apply_launch_plan(plan, server, output_dir, dry_run=dry_run)


def _setup_modpack(config, output_dir: Path, dry_run: bool) -> None:
    mp = config.modpack
    src = mp.source

    if dry_run:
        log.info("[dry-run] Would install %s modpack to %s", mp.platform, output_dir)
        _write_server_files(config, output_dir, None, dry_run)
        return

    log.info("Installing %s modpack to %s...", mp.platform, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()

    if mp.platform in ("github", "url"):
        start_artifact = modpack_custom.ServerPackInstaller(
            source=src,
            modpack=mp,
            session=session,
        ).install(output_dir)
        _write_server_files(config, output_dir, start_artifact, dry_run)
        log.info("Server pack installed to %s", output_dir)
        return

    if mp.platform == "gtnh":
        start_artifact = modpack_gtnh.GTNHPackInstaller(
            source=src,
            server=config.server,
            session=session,
        ).install(output_dir)
        _write_server_files(config, output_dir, start_artifact, dry_run)
        log.info("GTNH pack installed to %s", output_dir)
        return

    if mp.platform == "modrinth":
        modpack_mr.ModrinthPackInstaller(
            source=src,
            server=config.server,
            modpack=mp,
            session=session,
        ).install(output_dir)
    elif mp.platform == "curseforge":
        modpack_cf.CurseForgePackInstaller(
            source=src,
            modpack=mp,
            session=session,
        ).install(output_dir)
    elif mp.platform == "ftb":
        ftb_installer = modpack_ftb.FTBPackInstaller(
            source=src,
            modpack=mp,
            session=session,
        )
        ftb_installer.install(output_dir)
        # Use pack's memory recommendation when user left memory at the default
        if (
            ftb_installer.recommended_memory_mb is not None
            and config.server.jvm.memory == JvmConfig().memory
        ):
            recommended = f"{ftb_installer.recommended_memory_mb}M"
            log.info("FTB pack recommends %s RAM; using as server.jvm.memory default", recommended)
            config.server.jvm.memory = recommended

    # Install server JAR using loader info saved to manifest by the pack installer
    manifest = Manifest(output_dir)
    manifest.load()
    loader_type = manifest.loader_type
    mc_version = manifest.mc_version
    loader_version = manifest.loader_version

    if loader_type == "gtnh":
        raise RuntimeError("GTNH packs install their own server JAR; use 'platform: gtnh' directly")
    if loader_type == "quilt":
        raise NotImplementedError("Quilt server installation is not supported")

    log.info("Installing %s %s server JAR...", loader_type or "vanilla", mc_version)
    pack_server_cfg = ServerConfig(
        type=loader_type or "vanilla",
        minecraft_version=mc_version,
        loader_version=loader_version or "LATEST",
    )
    start_artifact = server_pkg.installer_for(pack_server_cfg, session=session).install(output_dir)

    _write_server_files(config, output_dir, start_artifact, dry_run)
    log.info("Modpack installed to %s", output_dir)


def _download_mods(
    mods_cfg, mc_ver: str, loader: str | None, output_dir: Path, session
) -> list[str]:
    """Download all configured mods. Returns list of relative paths installed."""
    installed: list[str] = []
    errors: list[str] = []
    tasks: list[tuple] = []

    for spec in mods_cfg.modrinth or []:
        tasks.append(("modrinth", spec))

    cf = mods_cfg.curseforge
    cf_session = build_session(extra_headers={"X-Api-Key": cf.api_key}) if cf else None
    for spec in cf.files if cf else []:
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
                log.info("  installed %s → %s", spec, path)
            except Exception as exc:
                errors.append(f"{spec}: {exc}")
                log.error("  ERROR %s: %s", spec, exc)

    for spec in mods_cfg.urls or []:
        filename = spec.split("/")[-1].split("?")[0]
        dest = output_dir / "mods" / filename
        download_file(spec, dest, session=session, show_progress=True)
        installed.append(str(Path("mods") / filename))
        log.info("  installed %s → mods/%s", spec, filename)

    if errors:
        log.error("%d mod(s) failed to install.", len(errors))
        sys.exit(1)

    return installed


def _setup_mods(config, output_dir: Path, dry_run: bool) -> None:
    mods_cfg = config.mods
    if dry_run:
        mr_count = len(mods_cfg.modrinth or [])
        cf_count = len(mods_cfg.curseforge.files) if mods_cfg.curseforge else 0
        url_count = len(mods_cfg.urls or [])
        log.info(
            "[dry-run] Would install %d Modrinth + %d CurseForge + %d URL mod(s) to %s/mods/",
            mr_count,
            cf_count,
            url_count,
            output_dir,
        )
        start_artifact = _install_server_jar(config, output_dir, dry_run)
        _write_server_files(config, output_dir, start_artifact, dry_run)
        return

    loader = (
        config.server.type
        if config.server.type not in (None, "vanilla", "paper", "purpur")
        else None
    )
    session = build_session()
    mc_ver = resolve_minecraft_version(session, config.server.minecraft_version)

    total = (
        len(mods_cfg.modrinth or [])
        + (len(mods_cfg.curseforge.files) if mods_cfg.curseforge else 0)
        + len(mods_cfg.urls or [])
    )
    log.info("Downloading %d mod(s) to %s/mods/...", total, output_dir)
    installed = _download_mods(mods_cfg, mc_ver, loader, output_dir, session)
    log.info("%d mod(s) installed to %s/mods/", len(installed), output_dir)

    start_artifact = _install_server_jar(config, output_dir, dry_run)
    _write_server_files(config, output_dir, start_artifact, dry_run)


def _install_extra_mods(config, output_dir: Path, dry_run: bool) -> None:
    """Install extra mods on top of an already-installed modpack or server pack."""
    mods_cfg = config.mods
    if dry_run:
        mr_count = len(mods_cfg.modrinth or [])
        cf_count = len(mods_cfg.curseforge.files) if mods_cfg.curseforge else 0
        url_count = len(mods_cfg.urls or [])
        log.info(
            "[dry-run] Would install %d Modrinth + %d CurseForge + %d extra mod(s) to %s/mods/",
            mr_count,
            cf_count,
            url_count,
            output_dir,
        )
        return

    manifest = Manifest(output_dir)
    manifest.load()
    if not manifest.mc_version:
        raise RuntimeError(
            "Cannot install extra mods: Minecraft version is not recorded in the manifest. "
            "Re-run setup to reinstall the base pack."
        )
    loader = manifest.loader_type or (
        config.server.type
        if config.server.type not in (None, "vanilla", "paper", "purpur")
        else None
    )

    session = build_session()
    mc_ver = resolve_minecraft_version(session, manifest.mc_version)

    total = (
        len(mods_cfg.modrinth or [])
        + (len(mods_cfg.curseforge.files) if mods_cfg.curseforge else 0)
        + len(mods_cfg.urls or [])
    )
    log.info("Downloading %d extra mod(s) to %s/mods/...", total, output_dir)
    installed = _download_mods(mods_cfg, mc_ver, loader, output_dir, session)

    manifest.files = sorted(set(manifest.files) | set(installed))
    manifest.save()

    log.info("%d extra mod(s) installed to %s/mods/", len(installed), output_dir)


def _cmd_status(args: argparse.Namespace) -> None:
    try:
        config = load_config(args.config)
    except Exception as exc:
        log.error("Invalid config: %s", exc)
        sys.exit(1)

    output_dir = config.server.output_dir
    manifest = Manifest(output_dir)
    manifest.load()

    data = manifest.snapshot()
    if not data:
        log.info("No manifest found in %s — server has not been set up yet.", output_dir)
        return

    log.info("Manifest: %s", manifest.path)
    if manifest.mc_version:
        log.info("  Minecraft version : %s", manifest.mc_version)
    if manifest.loader_type:
        log.info("  Loader            : %s", manifest.loader_type)
    if manifest.loader_version:
        log.info("  Loader version    : %s", manifest.loader_version)
    if manifest.pack_sha1:
        log.info("  Pack SHA-1        : %s", manifest.pack_sha1)
    files = manifest.files
    if files:
        log.info("  Tracked files     : %d", len(files))
        for f in files:
            log.info("    %s", f)


if __name__ == "__main__":
    main()
