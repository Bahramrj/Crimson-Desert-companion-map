"""Pywel's provinces from the game's world-map region bitmap.

`ui/texture/image/worldmapfog/bitmap_region_worldmap_ui.dds` is a 2048 x 2048 8-bit map of
province numbers at 10 m/px over the larger 20 480 m square of the `bitmapposition` tables
(x -16384 ... 4096, z -11264 ... 9216). A town area inside a province is the
province number + 128. The numbers carry no names: each province is named after the places
(`Node_<region>_...`) that lie inside it.
"""

import logging
from collections import Counter

from PIL import Image, ImageChops, ImageFilter

from gamedata.archive import ArchiveError
from mapstore import georef as geo

log = logging.getLogger("cdlivemap.gamedata")

BITMAP = "ui/texture/image/worldmapfog/bitmap_region_worldmap_ui.dds"
BITMAP_SIZE, BITMAP_MPP = 2048, 10.0
BITMAP_ORIGIN = (-16384.0, 9216.0)          # game x / z of the top-left corner
TOWN = 128
# internal region prefix of the places -> the game's own name for the province (region.paloc)
NAMES = {"Her": "Hernand", "Kwe": "Pailune", "Dem": "Demeniss", "Del": "Delesyia", "Crim": "Crimson Desert"}
MIN_PLACES = 5                              # a province needs this many places to be named
BORDER_BLUR = 1.5                           # bitmap px


def load(archive):
    """The province bitmap as an 'L' image (town areas folded into their province), or None."""
    entries = archive.find(BITMAP, ["0012"]) if "0012" in archive.groups() else []
    if not entries:
        return None
    dds = archive.read(entries[0])
    if dds[:4] != b"DDS " or dds[88] != 8 or len(dds) < 128 + BITMAP_SIZE * BITMAP_SIZE:
        raise ArchiveError("region bitmap is not a 2048 x 2048 8-bit DDS")
    img = Image.frombytes("L", (BITMAP_SIZE, BITMAP_SIZE), dds[128:128 + BITMAP_SIZE * BITMAP_SIZE])
    return img.point([v - TOWN if v >= TOWN else v for v in range(256)])


def pixel(x, z):
    return int((x - BITMAP_ORIGIN[0]) / BITMAP_MPP), int((BITMAP_ORIGIN[1] - z) / BITMAP_MPP)


def province_names(bitmap, places):
    """{province number: name} by majority of the places inside each province."""
    px, votes = bitmap.load(), {}
    for m in places:
        parts = m["id"].split("_")
        u, v = pixel(m["x"], m["z"])
        if m["realm"] == "pywel" and len(parts) > 2 and parts[1] in NAMES and 0 <= u < BITMAP_SIZE and 0 <= v < BITMAP_SIZE:
            votes.setdefault(px[u, v], Counter())[parts[1]] += 1
    out = {}
    for value, counter in votes.items():
        prefix, count = counter.most_common(1)[0]
        if value and count >= MIN_PLACES and count > sum(counter.values()) / 2:
            out[value] = NAMES[prefix]
    return out


def label_point(bitmap, value):
    """Game (x, z) deep inside a province: the centre of what is left after eroding it most of the way."""
    small = bitmap.resize((BITMAP_SIZE // 4, BITMAP_SIZE // 4), Image.NEAREST)
    mask = small.point([255 if v == value else 0 for v in range(256)])
    best = mask
    while mask.getbbox():
        best, mask = mask, mask.filter(ImageFilter.MinFilter(3))
    hist_x = [sum(1 for v in col if v) for col in _columns(best)]
    hist_y = [sum(1 for v in row if v) for row in _rows(best)]
    total = sum(hist_x) or 1
    cu = sum(i * n for i, n in enumerate(hist_x)) / total + 0.5
    cv = sum(i * n for i, n in enumerate(hist_y)) / total + 0.5
    return BITMAP_ORIGIN[0] + cu * 4 * BITMAP_MPP, BITMAP_ORIGIN[1] - cv * 4 * BITMAP_MPP


def _rows(img):
    w = img.width
    data = img.tobytes()
    return [data[i:i + w] for i in range(0, len(data), w)]


def _columns(img):
    return _rows(img.transpose(Image.Transpose.TRANSPOSE))


def border_layer(bitmap, size):
    """An 8-bit mask of the borders between provinces, over the world square of the map layers
    (`size` px); province numbers that change between neighbouring pixels, both not 0."""
    edges = Image.new("L", bitmap.size, 0)
    nonzero = bitmap.point([0] + [255] * 255)
    for dx, dy in ((1, 0), (0, 1)):
        shifted = ImageChops.offset(bitmap, dx, dy)
        changed = ImageChops.difference(bitmap, shifted).point([0] + [255] * 255)
        both = ImageChops.multiply(nonzero, ImageChops.offset(nonzero, dx, dy))
        edges = ImageChops.lighter(edges, ImageChops.multiply(changed, both))
    # the bitmap's square is larger than the world square: cut the world out, then scale it
    x0, z0, x1, z1 = geo.WORLD
    box = ((x0 - BITMAP_ORIGIN[0]) / BITMAP_MPP, (BITMAP_ORIGIN[1] - z1) / BITMAP_MPP,
           (x1 - BITMAP_ORIGIN[0]) / BITMAP_MPP, (BITMAP_ORIGIN[1] - z0) / BITMAP_MPP)
    # soften the 10 m steps into a band ~40 m wide, peaking at 255 on the border
    edges = edges.filter(ImageFilter.GaussianBlur(BORDER_BLUR)).point([min(255, v * 4) for v in range(256)])
    return edges.transform((size, size), Image.Transform.EXTENT, box, Image.BICUBIC)


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
