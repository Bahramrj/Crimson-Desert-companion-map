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
from gamedata import markers, worldmap
from mapstore import MapStore
from mapstore.markers import MarkerStore
from server.config import Config, data_dir


def saved_game_dir():
    """The game folder chosen in the launcher (config.json), if any."""
    try:
        return Config.load(data_dir() / "config.json").game_dir or None
    except (OSError, ValueError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m gamedata")
    sub = ap.add_subparsers(dest="cmd", required=True)
    info = sub.add_parser("info", help="show the install and its version")
    info.add_argument("--game")
    imp = sub.add_parser("import", help="render the world map(s) into the local asset store")
    imp.add_argument("--game")
    imp.add_argument("--realm", choices=("pywel", "abyss", "all"), default="all")
    imp.add_argument("--quality", choices=tuple(worldmap.QUALITY), default="default",
                     help="default: 16384 px (~1 min per realm); high: Pywel at 32768 px (~3.5 min, ~3x disk)")
    imp.add_argument("--scale", type=int, choices=worldmap.SCALES, help="render scale for every realm (overrides --quality)")
    imp.add_argument("--what", choices=("all", "maps", "markers"), default="all")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    game = find_install(args.game or saved_game_dir())
    if game is None:
        print("error: Crimson Desert install not found; pass --game <folder>", file=sys.stderr)
        return 1
    try:
        archive = Archive(game)
        print(f"Crimson Desert {archive.version()} at {game}")
        if args.cmd == "info":
            return 0
        store = MapStore(data_dir() / "maps")
        realms = ("pywel", "abyss") if args.realm == "all" else (args.realm,)
        if args.what in ("all", "markers"):
            sets, failures = markers.import_markers(archive, MarkerStore(data_dir() / "markers"))
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
            summary, failures = worldmap.import_basemap(archive, store, realm, scale, progress)
            print(f"\n  {realm}: {summary['id']} in {time.monotonic() - started:.0f} s"
                  + (f", {len(failures)} unreadable layer tiles (see log)" if failures else ""))
    except (ArchiveError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
