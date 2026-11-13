"""Pywel's provinces from the game's world-map region bitmap.

`ui/texture/image/worldmapfog/bitmap_region_worldmap_ui.dds` is an 8-bit map of province numbers
at 10 m/px over the square of the `bitmapposition` tables, centred on x -6144, z -1024:
2048 px (x -16384 ... 4096) up to 2.03, 3488 px from 2.04. A town area
inside a province is the province number + 128; values without town areas (sea, unplayable land) are
no province. The numbers carry no names: each province is named after the places
(`Node_<region>_...`) that lie inside it.
"""

import logging
from collections import Counter

from PIL import Image, ImageChops, ImageFilter

from gamedata.archive import ArchiveError
from mapstore import georef as geo

log = logging.getLogger("cdlivemap.gamedata")

BITMAP = "ui/texture/image/worldmapfog/bitmap_region_worldmap_ui.dds"
BITMAP_SIZE, BITMAP_MPP = 2048, 10.0       # the size up to 2.03; load() takes it from the file
BITMAP_CENTRE = (-6144.0, -1024.0)          # game x / z
TOWN = 128
# internal region prefix of the places -> the game's own name for the province (region.paloc)
NAMES = {"Her": "Hernand", "Kwe": "Pailune", "Dem": "Demeniss", "Del": "Delesyia", "Crim": "Crimson Desert"}
MIN_PLACES = 5                              # a province needs this many places to be named
BORDER_BLUR = 1.5                           # bitmap px


def load(archive):
    """The province bitmap as an 'L' image (town areas folded into their province), or None.
    info["provinces"] lists the numbers that have town areas."""
    entries = archive.find(BITMAP, ["0012"]) if "0012" in archive.groups() else []
    if not entries:
        return None
    dds = archive.read(entries[0])
    size = int.from_bytes(dds[16:20], "little") if len(dds) >= 128 else 0
    if dds[:4] != b"DDS " or dds[88] != 8 or not size or int.from_bytes(dds[12:16], "little") != size             or len(dds) < 128 + size * size:
        raise ArchiveError("region bitmap is not a square 8-bit DDS")
    img = Image.frombytes("L", (size, size), dds[128:128 + size * size])
    towns = img.histogram()[TOWN + 1:]
    out = img.point([v - TOWN if v >= TOWN else v for v in range(256)])
    out.info["provinces"] = [v + 1 for v, n in enumerate(towns) if n]
    return out


def origin(size):
    """Game x / z of the top-left corner of a `size` px bitmap."""
    half = size * BITMAP_MPP / 2
    return BITMAP_CENTRE[0] - half, BITMAP_CENTRE[1] + half


def pixel(x, z, size=BITMAP_SIZE):
    x0, z0 = origin(size)
    return int((x - x0) / BITMAP_MPP), int((z0 - z) / BITMAP_MPP)


def province_names(bitmap, places):
    """{province number: name} by majority of the places inside each province."""
    px, votes = bitmap.load(), {}
    for m in places:
        parts = m["id"].split("_")
        u, v = pixel(m["x"], m["z"], bitmap.width)
        if m["realm"] == "pywel" and len(parts) > 2 and parts[1] in NAMES and 0 <= u < bitmap.width and 0 <= v < bitmap.height:
            votes.setdefault(px[u, v], Counter())[parts[1]] += 1
    out = {}
    for value, counter in votes.items():
        prefix, count = counter.most_common(1)[0]
        if value and count >= MIN_PLACES and count > sum(counter.values()) / 2:
            out[value] = NAMES[prefix]
    return out


def label_point(bitmap, value):
    """Game (x, z) deep inside a province: the centre of what is left after eroding it most of the way."""
    small = bitmap.resize((bitmap.width // 4, bitmap.height // 4), Image.NEAREST)
    mask = small.point([255 if v == value else 0 for v in range(256)])
    best = mask
    while mask.getbbox():
        best, mask = mask, mask.filter(ImageFilter.MinFilter(3))
    hist_x = [sum(1 for v in col if v) for col in _columns(best)]
    hist_y = [sum(1 for v in row if v) for row in _rows(best)]
    total = sum(hist_x) or 1
    cu = sum(i * n for i, n in enumerate(hist_x)) / total + 0.5
    cv = sum(i * n for i, n in enumerate(hist_y)) / total + 0.5
    x0, z0 = origin(bitmap.width)
    return x0 + cu * 4 * BITMAP_MPP, z0 - cv * 4 * BITMAP_MPP


def _rows(img):
    w = img.width
    data = img.tobytes()
    return [data[i:i + w] for i in range(0, len(data), w)]


def _columns(img):
    return _rows(img.transpose(Image.Transpose.TRANSPOSE))


def border_layer(bitmap, size, world=geo.WORLD):
    """An 8-bit mask of the borders between provinces, over the map layers' square `world` (`size` px);
    province numbers that change between neighbouring pixels, both provinces (not sea or unplayable land)."""
    provinces = bitmap.info.get("provinces")
    if provinces:
        bitmap = bitmap.point([v if v in provinces else 0 for v in range(256)])
    edges = Image.new("L", bitmap.size, 0)
    nonzero = bitmap.point([0] + [255] * 255)
    for dx, dy in ((1, 0), (0, 1)):
        shifted = ImageChops.offset(bitmap, dx, dy)
        changed = ImageChops.difference(bitmap, shifted).point([0] + [255] * 255)
        both = ImageChops.multiply(nonzero, ImageChops.offset(nonzero, dx, dy))
        edges = ImageChops.lighter(edges, ImageChops.multiply(changed, both))
    # cut the map's square out of the bitmap's, then scale it
    x0, z0, x1, z1 = world
    bx, bz = origin(bitmap.width)
    box = ((x0 - bx) / BITMAP_MPP, (bz - z1) / BITMAP_MPP, (x1 - bx) / BITMAP_MPP, (bz - z0) / BITMAP_MPP)
    # soften the 10 m steps into a band ~40 m wide, peaking at 255 on the border
    edges = edges.filter(ImageFilter.GaussianBlur(BORDER_BLUR)).point([min(255, v * 4) for v in range(256)])
    return edges.transform((size, size), Image.Transform.EXTENT, box, Image.BICUBIC)


def province_lookup(archive, places):
    """A function (x, z) -> province name or None, for tagging markers with their province."""
    bitmap = load(archive)
    if bitmap is None:
        return lambda x, z: None
    names = province_names(bitmap, places)
    px, size = bitmap.load(), bitmap.width

    def lookup(x, z):
        u, v = pixel(x, z, size)
        return names.get(px[u, v]) if 0 <= u < size and 0 <= v < size else None
    return lookup


def province_labels(archive, places):
    """Province label markers for the "Regions" category: [(name, x, z)]."""
    bitmap = load(archive)
    if bitmap is None:
        log.warning("region bitmap not found: no province names")
        return []
    names = province_names(bitmap, places)
    out = [(name, *label_point(bitmap, value)) for value, name in sorted(names.items())]
    log.info("provinces: %s", ", ".join(n for n, _, _ in out))
    return out
