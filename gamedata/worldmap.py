"""World-map basemaps rendered from the game's own SDF map layers.

Each layer is a grid of 512 x 512 8-bit DDS tiles (`..._<col>_<row>.dds`) covering a world square.
From 2.04 the game draws its map from the `51200x51200` set: 25 x 25 tiles (12 800 px, 2.4 m/px)
over mapstore.georef.WORLD, which takes in the ocean. Up to 2.03 it used the `32768x32768` set:
16 x 16 tiles over WORLD_203. The number in the names is shader space; the tiles hold no finer mip.
The game draws its map from these in a shader; we do the same once, at import, and store ordinary
tiles. SDFs stay sharp when upsampled: each tile is upsampled in float precision and every edge
(coast, river, road) gets an anti-aliasing ramp about one output pixel wide, so rendering at 2x
("default", ~1.2 m/px) or 4x ("high", ~0.6 m/px) gives crisp coasts and roads.

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
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from gamedata import levels, regions
from gamedata.archive import ArchiveError
from mapstore import georef as geo
from mapstore.tiler import TILE

log = logging.getLogger("cdlivemap.gamedata")

LAYER_DIR = "ui/texture/image/worldmap/"
SRC_TILE = 512


@dataclass(frozen=True)
class LayerSet:
    suffix: str      # in the layer names, e.g. cd_worldmap_land_sdf_51200x51200
    grid: int        # tiles per side
    world: tuple     # xmin, zmin, xmax, zmax covered

    @property
    def size(self):
        return self.grid * SRC_TILE

    @property
    def mpp(self):
        return (self.world[2] - self.world[0]) / self.size


LAYER_SETS = (LayerSet("51200x51200", 25, geo.WORLD), LayerSet("32768x32768", 16, geo.WORLD_203))   # newest first
LAYERS = {
    "land": "cd_worldmap_land_sdf_{set}",
    "road": "cd_worldmap_road_sdf_{set}",
    "wagon": "cd_worldmap_road_wagon_sdf_{set}",
    "mountain": "cd_worldmap_mountain_sdf_{set}",
    "abyss": "cd_worldmap_abyss_hex_sdf_{set}",
}
HEIGHT = LayerSet("", 16, geo.WORLD_203)     # cd_worldmap_blur_height: the same 16 x 16 tiles in every version
HEIGHT_LAYER = "cd_worldmap_blur_height"
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


def layer_set(archive):
    """The newest layer set the install has (its land tiles exist), else the oldest."""
    names = {e.path for e in archive.entries("0012")} if "0012" in archive.groups() else set()
    for s in LAYER_SETS:
        if f"{LAYER_DIR}{LAYERS['land'].format(set=s.suffix)}_0_0.dds" in names:
            return s
    return LAYER_SETS[-1]


def load_layer(archive, key, failures=None, layers=None):
    """Stitch one layer of `layers` (default: layer_set(archive)). Missing or broken tiles are logged
    and left at 0. The height layer exists only over the pre-2.04 square; it is placed into the set's."""
    layers = layers or layer_set(archive)
    if key == "height":
        return _reproject(_stitch(archive, key, HEIGHT_LAYER, HEIGHT.grid, failures), HEIGHT, layers)
    return _stitch(archive, key, LAYERS[key].format(set=layers.suffix), layers.grid, failures)


HEIGHT_FEATHER_M = 1200.0    # the height lines fade out over this distance at the edge of their square


def _reproject(img, src, dst):
    """`img` covering src.world, scaled and placed onto dst's square; outside reads as 0, and the
    edge fades out over HEIGHT_FEATHER_M instead of stopping on a straight line."""
    if src.world == dst.world and img.width == dst.size:
        return img
    k = (src.world[2] - src.world[0]) / img.width / dst.mpp
    part = img.resize((round(img.width * k), round(img.height * k)), Image.BILINEAR)
    feather = max(1, round(HEIGHT_FEATHER_M / dst.mpp))
    mask = Image.new("L", part.size, 0)
    mask.paste(255, (feather, feather, part.width - feather, part.height - feather))
    mask = mask.filter(ImageFilter.BoxBlur(feather // 2))
    out = Image.new("L", (dst.size, dst.size), 0)
    out.paste(part, (round((src.world[0] - dst.world[0]) / dst.mpp), round((dst.world[3] - src.world[3]) / dst.mpp)), mask)
    return out


def _stitch(archive, key, name, grid, failures):
    prefix = LAYER_DIR + name + "_"
    found = {e.path[len(prefix):-4]: e for e in archive.entries("0012") if e.path.startswith(prefix) and e.path.endswith(".dds")}
    img = Image.new("L", (grid * SRC_TILE, grid * SRC_TILE), 0)
    for col in range(grid):
        for row in range(grid):
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


def island_layer(archive, failures=None, layers=None):
    """An 8-bit mask of the Abyss islands over the layer set's square, SDF-like (128 = the edge)."""
    layers = layers or layer_set(archive)
    size, mpp, world = layers.size, layers.mpp, layers.world
    img = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(img)

    def px(x, z):
        return (x - world[0]) / mpp, (world[3] - z) / mpp
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
    found = layer_set(archive)
    layers = {k: load_layer(archive, k, failures, found) for k in REALM_LAYERS[realm]}
    if realm == "pywel":
        try:
            bitmap = regions.load(archive)
            if bitmap is not None:
                layers["border"] = regions.border_layer(bitmap, found.size, found.world)
        except (ArchiveError, OSError, ValueError) as e:   # borders are a nicety
            log.warning("province borders unavailable: %s", e)
            failures.append(f"borders: {e}")
    if realm == "abyss":
        try:
            layers["islands"] = island_layer(archive, failures, found)
        except (ArchiveError, OSError, ValueError) as e:   # the hex background still makes a map
            log.warning("Abyss islands unavailable: %s", e)
            failures.append(f"islands: {e}")
    previous = game_maps(store, realm)
    size = found.size * scale
    summary = store.import_rendered(
        RENDERERS[realm](layers, scale), (size, size), realm, NAMES[realm], source="A",
        licence="rendered from your own Crimson Desert install; personal use, do not share",
        game_version=archive.version(), fixed_georef=geo.world_georef(size, found.world), progress=progress,
        quality=WEBP_QUALITY)
    for old in previous:
        store.delete(old["id"])
    log.info("Imported %s basemap %s (game %s, %d unreadable tiles)", realm, summary["id"], summary["gameVersion"], len(failures))
    return summary, failures
