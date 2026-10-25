"""Image -> tile pyramid tiles/{z}/{x}/{y}.webp (512 px, z = max_zoom is native size)."""

import math
from pathlib import Path

from PIL import Image

TILE = 512
MAX_PIXELS = 32768 * 32768   # local files the user picked; Pillow's bomb guard is far lower


def max_zoom(width, height, tile=TILE):
    return max(0, math.ceil(math.log2(max(width, height) / tile)))


def tile_count(width, height, tile=TILE):
    total, w, h = 0, width, height
    for _ in range(max_zoom(width, height, tile) + 1):
        total += math.ceil(w / tile) * math.ceil(h / tile)
        w, h = math.ceil(w / 2), math.ceil(h / 2)
    return total


def open_image(path):
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    img = Image.open(path)
    img.load()
    return img.convert("RGBA" if img.mode in ("RGBA", "LA", "P", "PA") else "RGB")


def build_from(render, width, height, out_dir, tile=TILE, quality=85, progress=None):
    """Pyramid from a tile renderer: render(tx, ty) -> 512x512 image for the full-size level.
    Lower levels are made from their four children, so the full image never sits in memory."""
    out_dir = Path(out_dir)
    top = max_zoom(width, height, tile)
    total, done = tile_count(width, height, tile), 0

    def tick():
        nonlocal done
        done += 1
        if progress:
            progress(done, total)

    w, h = width, height
    for tx in range(math.ceil(w / tile)):
        (out_dir / str(top) / str(tx)).mkdir(parents=True, exist_ok=True)
        for ty in range(math.ceil(h / tile)):
            render(tx, ty).save(out_dir / str(top) / str(tx) / f"{ty}.webp", "WEBP", quality=quality, method=4)
            tick()
    for z in range(top - 1, -1, -1):
        w, h = math.ceil(w / 2), math.ceil(h / 2)
        for tx in range(math.ceil(w / tile)):
            (out_dir / str(z) / str(tx)).mkdir(parents=True, exist_ok=True)
            for ty in range(math.ceil(h / tile)):
                canvas = Image.new("RGBA", (2 * tile, 2 * tile), (0, 0, 0, 0))
                for dx in (0, 1):
                    for dy in (0, 1):
                        child = out_dir / str(z + 1) / str(2 * tx + dx) / f"{2 * ty + dy}.webp"
                        if child.is_file():
                            with Image.open(child) as c:
                                canvas.paste(c.convert("RGBA"), (dx * tile, dy * tile))
                canvas.reduce(2).save(out_dir / str(z) / str(tx) / f"{ty}.webp", "WEBP", quality=quality, method=4)
                tick()
    return top


def build(img, out_dir, tile=TILE, quality=85, progress=None):
    """Write the pyramid for a PIL image; returns max_zoom. progress(done, total) is optional."""
    out_dir = Path(out_dir)
    width, height = img.size
    top = max_zoom(width, height, tile)
    total, done = tile_count(width, height, tile), 0
    level = img
    for z in range(top, -1, -1):
        w, h = level.size
        for tx in range(math.ceil(w / tile)):
            col = out_dir / str(z) / str(tx)
            col.mkdir(parents=True, exist_ok=True)
            for ty in range(math.ceil(h / tile)):
                box = (tx * tile, ty * tile, min(w, (tx + 1) * tile), min(h, (ty + 1) * tile))
                part = level.crop(box)
                if part.size != (tile, tile):          # edge tile: pad with transparency
                    padded = Image.new("RGBA", (tile, tile), (0, 0, 0, 0))
                    padded.paste(part, (0, 0))
                    part = padded
                part.save(col / f"{ty}.webp", "WEBP", quality=quality, method=4)
                done += 1
                if progress:
                    progress(done, total)
        if z:
            level = level.reduce(2) if min(level.size) > 1 else level
    return top
