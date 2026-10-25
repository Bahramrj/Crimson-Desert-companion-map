"""Manage local maps from the command line.

  python -m mapstore import-image <file> --realm pywel --source C [--name N] [--licence TEXT]
  python -m mapstore import-image <render.png> --realm pywel --source A --game-extent
  python -m mapstore import-markers <file.csv|.geojson|.json> --name N [--source C|B] [--licence TEXT]
  python -m mapstore list
  python -m mapstore delete <map-id>

Uses %LOCALAPPDATA%\\CompanionMap\\maps (or CDLIVEMAP_DATA). A running server picks
the change up on the device's next reload.
"""

import argparse
import sys

from PIL import Image

from mapstore import REALMS, SOURCES, MapError, MapStore, NotFound, georef
from mapstore.marker_import import read_marker_file
from mapstore.markers import MarkerStore
from server.config import data_dir


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m mapstore")
    sub = ap.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import-image", help="tile an image into a new map")
    imp.add_argument("file")
    imp.add_argument("--realm", choices=REALMS, required=True)
    imp.add_argument("--source", choices=list(SOURCES), default="C",
                     help="A game files, B download (needs --licence), C own capture")
    imp.add_argument("--name")
    imp.add_argument("--licence", default="")
    imp.add_argument("--game-extent", action="store_true",
                     help="a square image rendered from the game's world-map layers: placed exactly, no calibration")
    mk = sub.add_parser("import-markers", help="add a marker set from CSV, GeoJSON or JSON (game x/z)")
    mk.add_argument("file")
    mk.add_argument("--name", required=True)
    mk.add_argument("--source", choices=["B", "C"], default="C", help="B download (needs --licence), C your own")
    mk.add_argument("--licence", default="")
    mk.add_argument("--realm", choices=REALMS, default="pywel", help="for rows without realm or y")
    sub.add_parser("list", help="list installed maps and marker sets")
    rm = sub.add_parser("delete", help="delete a map")
    rm.add_argument("id")
    args = ap.parse_args(argv)

    store = MapStore(data_dir() / "maps")
    try:
        if args.cmd == "import-image":
            def progress(done, total):
                if done == total or done % 50 == 0:
                    print(f"\r  tiles {done}/{total}", end="", flush=True)
            fixed = None
            if args.game_extent:
                with Image.open(args.file) as img:
                    w, h = img.size
                if w != h:
                    raise MapError(f"--game-extent needs a square image (got {w}x{h})")
                fixed = georef.world_georef(w)
            s = store.import_image(args.file, args.realm, name=args.name, source=args.source,
                                   licence=args.licence, fixed_georef=fixed, progress=progress)
            print(f"\nImported {s['id']} ({s['image'][0]}x{s['image'][1]}, zoom 0-{s['maxZoom']}); "
                  + ("placed exactly in game space." if s["fixed"] else "calibrate it on your device: Settings > Map > Add point."))
        elif args.cmd == "import-markers":
            data = read_marker_file(args.file, args.name, args.source, args.licence, args.realm)
            s = MarkerStore(data_dir() / "markers").save(data)
            print(f"Saved marker set {s['id']} ({s['count']} markers, {len(s['categories'])} categories)")
        elif args.cmd == "list":
            active = store.active()
            for m in store.list():
                mark = "*" if active.get(m["realm"]) == m["id"] else " "
                print(f"{mark} {m['id']:40s} {m['realm']:6s} {m['source']}  {m['image'][0]}x{m['image'][1]}  "
                      f"{len(m['calibration'])} points  {m['name']}")
            for s in MarkerStore(data_dir() / "markers").list():
                print(f"  markers {s['id']:32s} {s['source']}  {len(s['markers'])} markers  {s['name']}")
        elif args.cmd == "delete":
            store.delete(args.id)
            print(f"Deleted {args.id}")
    except (MapError, NotFound, OSError, ValueError) as e:   # ValueError: bad JSON/CSV
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
