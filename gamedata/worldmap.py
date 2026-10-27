"""World-map basemaps rendered from the game's own SDF map layers.

Each layer is 16 x 16 tiles of 512 x 512 8-bit DDS (`..._<col>_<row>.dds`), 8192 px per side,
covering the world square in mapstore.georef.WORLD (the "32768" in the names is shader space; the
tiles hold no finer mip). The game draws its map from these in a shader; we do the same once, at
import, and store ordinary tiles. SDFs stay sharp when upsampled: each tile is upsampled in float
precision and every edge (coast, river, road) gets an anti-aliasing ramp about one output pixel
wide, so rendering at 2x (16384 px, ~1.2 m/px, "default") or 4x (32768 px, ~0.6 m/px, "high")
gives crisp coasts and roads.

The Abyss has no island layer: its map art is a set of small stage icons with no placement data.
Its islands are drawn from the game's Abyss level files instead: every object placed above
Pywel becomes a disc, near neighbours are joined (bridges are chains of pieces), and the
blurred mask is rendered like an SDF layer over the hex background.
"""

import io
import logging
import math
import struct

from collections import defaultdict

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from gamedata import levels, regions
from gamedata.archive import ArchiveError
from mapstore import georef as geo
from mapstore.tiler import TILE

log = logging.getLogger("cdlivemap.gamedata")

LAYER_DIR = "ui/texture/image/worldmap/"
GRID, SRC_TILE = 16, 512
SRC_SIZE = GRID * SRC_TILE

LAYERS = {
    "land": "cd_worldmap_land_sdf_32768x32768",
    "height": "cd_worldmap_blur_height",
    "road": "cd_worldmap_road_sdf_32768x32768",
    "wagon": "cd_worldmap_road_wagon_sdf_32768x32768",
    "mountain": "cd_worldmap_mountain_sdf_32768x32768",
    "abyss": "cd_worldmap_abyss_hex_sdf_32768x32768",
}
REALM_LAYERS = {"pywel": ("land", "height", "road", "wagon", "mountain"), "abyss": ("abyss",)}

PAPER, SEA = (233, 223, 198), (150, 178, 190)
CONTOUR, RIDGE, WAGON, ROAD = (150, 120, 90), (110, 95, 80), (170, 120, 70), (90, 60, 40)
ISLAND, ISLAND_RIM = (214, 204, 178), (150, 125, 95)
BORDER = (150, 60, 60)

ABYSS_Y = 1400.0                 # same rule as the engine: higher is the Abyss
ISLAND_LEVELS = "abyss"          # abyssisland_*, abyssbridge_*, abyss_bossrush_*, ...: the Abyss's level files
ISLAND_R, LINK_M, ISLAND_BLUR = 10.0, 90.0, 5.0   # m: disc per object, join neighbours this close, softening


def _lut(lo, hi, strength=1.0):
    """Smoothstep from lo to hi (8-bit SDF values) as a 0..255 alpha lookup table."""
    out = []
    for v in range(256):
        t = min(1.0, max(0.0, (v - lo) / (hi - lo)))
        out.append(round(t * t * (3 - 2 * t) * 255 * strength))
    return out


# Soft layers keep a lookup table: the height tint and the province border band.
LUT = {
    "height": _lut(90, 180, 0.3),
    "border": _lut(40, 255, 0.4),
    "island": _lut(104, 124),
    "island_core": _lut(124, 150),
}


# Edges (S3 measurements): the SDF values fall ~3.7 per source pixel at the iso line. Each edge is
# drawn at the same iso value as before, with a ramp `px` output pixels wide at the render scale.
SDF_GRADIENT = 3.7
EDGES = {                     # layer: [(iso value, strength, ramp width in output px)]
    "land": [(128, 1.0, 1.0)],
    "mountain": [(102, 0.18, 1.2), (116, 0.22, 6.0)],    # a light tint with a crisp rim, then a softer core
    "wagon": [(123.5, 0.85, 1.0)],
    "road": [(121.5, 0.95, 1.0)],
}
WEBP_QUALITY = 92             # crisp lines stay clean (q85 shows blocks along them); ~40 KB per Pywel tile


def edge(t, iso, scale, strength=1.0, px=1.0):
    """Alpha (L) of the area above `iso` in a float SDF tile, with an anti-aliasing ramp `px` output pixels wide."""
    width = max(0.5, px * SDF_GRADIENT / scale)
    k = 255 / width
    alpha = t.point(lambda v: v * k - (iso - width / 2) * k).convert("L")     # converting clamps to 0..255
    return alpha if strength >= 1 else alpha.point(lambda v: round(v * strength))


def decode_l8(dds):
    """An 8-bit layer tile as a 512 x 512 'L' image (the 8 x 8 placeholder tiles are uniform)."""
    if dds[:4] != b"DDS ":
        raise ArchiveError("not a DDS file")
    height, width = struct.unpack_from("<2I", dds, 12)
    fourcc, bits = dds[84:88], struct.unpack_from("<I", dds, 88)[0]
    offset = 148 if fourcc == b"DX10" else 128
    if bits == 8 and fourcc in (b"\0\0\0\0", b"DX10"):
        if (width, height) != (SRC_TILE, SRC_TILE):
            return Image.new("L", (SRC_TILE, SRC_TILE), dds[offset] if len(dds) > offset else 0)
        return Image.frombytes("L", (SRC_TILE, SRC_TILE), dds[offset:offset + SRC_TILE * SRC_TILE])
    with Image.open(io.BytesIO(dds)) as img:          # block-compressed variant, if a patch changes it
        return img.convert("L").resize((SRC_TILE, SRC_TILE))


def load_layer(archive, key, failures=None):
    """Stitch one 8192 x 8192 layer. Missing or broken tiles are logged and left at 0."""
    prefix = LAYER_DIR + LAYERS[key] + "_"
    found = {e.path[len(prefix):-4]: e for e in archive.entries("0012") if e.path.startswith(prefix) and e.path.endswith(".dds")}
    img = Image.new("L", (SRC_SIZE, SRC_SIZE), 0)
    for col in range(GRID):
        for row in range(GRID):
            entry = found.get(f"{col}_{row}")
            if entry is None:
                log.warning("map layer %s: tile %d_%d missing", key, col, row)
                if failures is not None:
                    failures.append(f"{key} {col}_{row}: missing")
                continue
            try:
                img.paste(decode_l8(archive.read(entry)), (col * SRC_TILE, row * SRC_TILE))
            except (ArchiveError, OSError, ValueError, struct.error) as e:
                log.warning("map layer %s: tile %d_%d unreadable: %s", key, col, row, e)
                if failures is not None:
                    failures.append(f"{key} {col}_{row}: {e}")
    return img


def island_points(archive, failures=None):
    """{level name: [(x, z)]} of the objects placed in the Abyss level files above Pywel."""
    out = {}
    for name, entry in sorted(levels.levels(archive, ISLAND_LEVELS).items()):
        try:
            pts = [(x, z) for x, _, z in levels.transforms(archive.read(entry), ABYSS_Y)]
        except (ArchiveError, OSError, ValueError, struct.error) as e:
            log.warning("Abyss level %s unreadable: %s", name, e)
            if failures is not None:
                failures.append(f"level {name}: {e}")
            continue
        if pts:
            out[name] = pts
    return out


def _links(pts, reach, count=2):
    """Each point joined to its `count` nearest neighbours within `reach`, so the pieces of a
    bridge form a chain (a grid keeps this linear)."""
    grid = defaultdict(list)
    for i, (x, z) in enumerate(pts):
        grid[(int(x // reach), int(z // reach))].append(i)
    for i, (x, z) in enumerate(pts):
        cx, cz = int(x // reach), int(z // reach)
        near = sorted(((pts[j][0] - x) ** 2 + (pts[j][1] - z) ** 2, j)
                      for gx in (cx - 1, cx, cx + 1) for gz in (cz - 1, cz, cz + 1) for j in grid.get((gx, gz), ()))
        for d, j in [n for n in near if 0 < n[0] < reach * reach][:count]:
            yield pts[i], pts[j]


def island_layer(archive, failures=None):
    """An 8-bit mask of the Abyss islands over the world square, SDF-like (128 = the edge)."""
    size = SRC_SIZE
    mpp = geo.WORLD_SIZE / size
    img = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(img)

    def px(x, z):
        return (x - geo.WORLD[0]) / mpp, (geo.WORLD[3] - z) / mpp
    r, width = ISLAND_R / mpp, max(1, round(ISLAND_R * 0.8 / mpp))
    count = 0
    for pts in island_points(archive, failures).values():
        for a, b in _links(pts, LINK_M):
            draw.line((px(*a), px(*b)), fill=255, width=width)
        for x, z in pts:
            u, v = px(x, z)
            draw.ellipse((u - r, v - r, u + r, v + r), fill=255)
        count += len(pts)
    log.info("Abyss islands: %d placed objects", count)
    if not count:
        return None
    return img.filter(ImageFilter.GaussianBlur(ISLAND_BLUR / mpp))


def _crop(layer, tx, ty, scale, precise=False):
    """The source region of output tile (tx, ty), upsampled by `scale` with bilinear filtering;
    `precise` upsamples in float (mode F), so narrow edge ramps don't step on 8-bit values."""
    src = TILE / scale
    x0, y0 = tx * src, ty * src
    pad = 2
    box = (math.floor(x0) - pad, math.floor(y0) - pad, math.ceil(x0 + src) + pad, math.ceil(y0 + src) + pad)
    part = layer.crop(box)                           # outside the layer reads as 0 (sea / empty)
    if precise:
        part = part.convert("F")
    big = part.resize((round(part.width * scale), round(part.height * scale)), Image.BILINEAR)
    ox, oy = round((x0 - box[0]) * scale), round((y0 - box[1]) * scale)
    return big.crop((ox, oy, ox + TILE, oy + TILE))


def _ink(base, color, alpha):
    base.paste(color, (0, 0, TILE, TILE), alpha)


def pywel_renderer(layers, scale):
    def edges(key, tx, ty):
        t = _crop(layers[key], tx, ty, scale, precise=True)
        return [edge(t, iso, scale, strength, px) for iso, strength, px in EDGES[key]]

    def render(tx, ty):
        land = edges("land", tx, ty)[0]
        out = Image.new("RGB", (TILE, TILE), SEA)
        _ink(out, PAPER, land)
        _ink(out, CONTOUR, ImageChops.multiply(_crop(layers["height"], tx, ty, scale).point(LUT["height"]), land))
        for alpha in edges("mountain", tx, ty):
            _ink(out, RIDGE, alpha)
        _ink(out, WAGON, edges("wagon", tx, ty)[0])
        _ink(out, ROAD, edges("road", tx, ty)[0])
        if "border" in layers:
            _ink(out, BORDER, ImageChops.multiply(_crop(layers["border"], tx, ty, scale).point(LUT["border"]), land))
        return out
    return render


def abyss_renderer(layers, scale):
    # a faint hex grid on deep blue (the dark mask areas stay darker), so the islands stand out
    r = [round(14 + v * 0.08) for v in range(256)]
    g = [round(18 + v * 0.11) for v in range(256)]
    b = [round(30 + v * 0.20) for v in range(256)]
    islands = layers.get("islands")

    def render(tx, ty):
        t = _crop(layers["abyss"], tx, ty, scale)
        out = Image.merge("RGB", (t.point(r), t.point(g), t.point(b)))
        if islands is not None:
            mask = _crop(islands, tx, ty, scale)
            rim, core = mask.point(LUT["island"]), mask.point(LUT["island_core"])
            _ink(out, ISLAND_RIM, rim)                      # a light rim, then the island body inside it
            _ink(out, ISLAND, core)
        return out
    return render


RENDERERS = {"pywel": pywel_renderer, "abyss": abyss_renderer}
NAMES = {"pywel": "Pywel (game map)", "abyss": "Abyss (game map)"}


def game_maps(store, realm):
    """Maps an earlier game import made for this realm (replaced by the next import)."""
    return [m for m in store.list() if m["realm"] == realm and m["source"] == "A" and m.get("fixed")]


# Map quality: render scale per realm. "high" only sharpens Pywel; the Abyss hex background has no finer detail.
QUALITY = {"default": {"pywel": 2, "abyss": 2}, "high": {"pywel": 4, "abyss": 2}}
SCALES = (1, 2, 4)


def scale_for(quality, realm):
    if quality not in QUALITY:
        raise ValueError(f"quality must be one of {', '.join(QUALITY)}")
    return QUALITY[quality][realm]


def import_basemap(archive, store, realm, scale=2, progress=None):
    """Render one realm's basemap into the asset store, replacing the previous game import.
    Returns (summary, failures); failures lists tiles that could not be read."""
    if scale not in SCALES:
        raise ValueError(f"scale must be one of {SCALES}")
    failures = []
    layers = {k: load_layer(archive, k, failures) for k in REALM_LAYERS[realm]}
    if realm == "pywel":
        try:
            bitmap = regions.load(archive)
            if bitmap is not None:
                layers["border"] = regions.border_layer(bitmap, SRC_SIZE)
        except (ArchiveError, OSError, ValueError) as e:   # borders are a nicety
            log.warning("province borders unavailable: %s", e)
            failures.append(f"borders: {e}")
    if realm == "abyss":
        try:
            layers["islands"] = island_layer(archive, failures)
        except (ArchiveError, OSError, ValueError) as e:   # the hex background still makes a map
            log.warning("Abyss islands unavailable: %s", e)
            failures.append(f"islands: {e}")
    previous = game_maps(store, realm)
    size = SRC_SIZE * scale
    summary = store.import_rendered(
        RENDERERS[realm](layers, scale), (size, size), realm, NAMES[realm], source="A",
        licence="rendered from your own Crimson Desert install; personal use, do not share",
        game_version=archive.version(), fixed_georef=geo.world_georef(size), progress=progress, quality=WEBP_QUALITY)
    for old in previous:
        store.delete(old["id"])
    log.info("Imported %s basemap %s (game %s, %d unreadable tiles)", realm, summary["id"], summary["gameVersion"], len(failures))
    return summary, failures
