"""Import maps from your own Crimson Desert install (read-only).

  python -m gamedata info [--game DIR]
  python -m gamedata import [--game DIR] [--realm pywel|abyss|all] [--quality default|high] [--what all|maps|markers]

The install is found through Steam unless --game, CDLM_GAME_DIR or the launcher's
"Game folder" setting says where it is. Maps go to
%LOCALAPPDATA%\\CompanionMap\\maps and marker sets to ...\\markers (or under
CDLIVEMAP_DATA); both replace the previous game import. Run again after a game patch.
"""

import argparse
import logging
import sys
import time

from gamedata import Archive, ArchiveError, find_install
from gamedata import markers, strings, worldmap
from mapstore import MapStore
from mapstore.markers import MarkerStore
from server.config import Config, data_dir


def saved_config():
    """The launcher's settings (config.json): the game folder and the language for names."""
    try:
        return Config.load(data_dir() / "config.json")
    except (OSError, ValueError):
        return Config()


def saved_game_dir():
    return saved_config().game_dir or None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m gamedata")
    sub = ap.add_subparsers(dest="cmd", required=True)
    info = sub.add_parser("info", help="show the install and its version")
    info.add_argument("--game")
    imp = sub.add_parser("import", help="render the world map(s) into the local asset store")
    imp.add_argument("--game")
    imp.add_argument("--realm", choices=("pywel", "abyss", "all"), default="all")
    imp.add_argument("--quality", choices=tuple(worldmap.QUALITY), default="default",
                     help="default: 25600 px (well under a minute per realm on a recent PC); high: Pywel at 51200 px (~2.5x disk)")
    imp.add_argument("--scale", type=int, choices=worldmap.SCALES, help="render scale for every realm (overrides --quality)")
    imp.add_argument("--what", choices=("all", "maps", "markers"), default="all")
    imp.add_argument("--force", action="store_true", help="render the maps even when they are up to date for this game version and quality")
    imp.add_argument("--profile", action="store_true", help="after the import, list the functions that took the most time")
    imp.add_argument("--no-night", action="store_true", help="skip the second Pywel map in night colours")
    imp.add_argument("--lang", help="game language for marker names, e.g. eng, ger, fre, jpn (default: the launcher's setting, else eng); "
                                    "`info` lists the ones the install has")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    game = find_install(args.game or saved_game_dir())
    if game is None:
        print("error: Crimson Desert install not found; pass --game <folder>", file=sys.stderr)
        return 1
    try:
        archive = Archive(game)
        print(f"Crimson Desert {archive.version()} at {game}")
        if archive.dlcs():
            print(f"  DLC: {', '.join(archive.dlcs())}")
        if args.cmd == "info":
            print(f"  languages: {', '.join(strings.languages(archive))}")
            return 0
        store = MapStore(data_dir() / "maps")
        realms = ("pywel", "abyss") if args.realm == "all" else (args.realm,)
        if args.what in ("all", "markers"):
            lang = args.lang or saved_config().game_lang
            sets, failures = markers.import_markers(archive, MarkerStore(data_dir() / "markers"), lang)
            for s in sets:
                print(f"  markers: {s['id']} ({s['count']})")
            for f in failures:
                print(f"  markers failed: {f}")
        for realm in realms if args.what in ("all", "maps") else ():
            started = time.monotonic()

            def progress(done, total):
                if done == total or done % 64 == 0:
                    print(f"\r  {realm}: tiles {done}/{total}", end="", flush=True)
            scale = args.scale or worldmap.scale_for(args.quality, realm)
            summary, failures = worldmap.import_basemap(archive, store, realm, scale, progress, night=not args.no_night, force=args.force)
            print(f"\n  {realm}: {summary['id']} in {time.monotonic() - started:.0f} s"
                  + (f", {len(failures)} unreadable layer tiles (see log)" if failures else ""))
    except (ArchiveError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def profiled(argv):
    """`--profile`: run under cProfile and print where the time went (seconds per phase are in the log anyway)."""
    import cProfile
    import pstats
    profile = cProfile.Profile()
    code = profile.runcall(main, [a for a in argv if a != "--profile"])
    print("\nSlowest functions (cumulative seconds):")
    pstats.Stats(profile).strip_dirs().sort_stats("cumulative").print_stats(25)
    return code


if __name__ == "__main__":
    sys.exit(profiled(sys.argv[1:]) if "--profile" in sys.argv[1:] else main())
