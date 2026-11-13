"""Image -> tile pyramid tiles/{z}/{x}/{y}.webp (512 px, z = max_zoom is native size)."""

import io
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor
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


class Flat:
    """A tile of one colour (open sea, empty sky). A renderer may return it instead of an image:
    it is encoded once per colour, and a block of equal flat tiles gives a flat tile one level up."""
    __slots__ = ("color",)

    def __init__(self, color):
        self.color = tuple(color)


SUBTREE_LEVELS = 3           # a worker renders a block of up to 8 x 8 full-size tiles and the levels above it


def default_workers():
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def build_from(render, width, height, out_dir, tile=TILE, quality=85, progress=None, workers=None):
    """Pyramid from a tile renderer: render(tx, ty) -> a 512x512 image, or Flat, for the full-size level.

    The pyramid is built block by block: a tile of a lower level is made from its four children while
    they are still in memory, so nothing is read back from disk or encoded twice, and the full image
    never sits in memory. Blocks are rendered on `workers` threads (Pillow releases the lock while it
    resizes and encodes); render must be safe to call from several threads. progress(done, total) is
    called from those threads, one call at a time."""
    out_dir = Path(out_dir)
    top = max_zoom(width, height, tile)
    total = tile_count(width, height, tile)
    grid = {}                                        # level -> (tiles across, tiles down)
    w, h = width, height
    for z in range(top, -1, -1):
        grid[z] = (math.ceil(w / tile), math.ceil(h / tile))
        for tx in range(grid[z][0]):
            (out_dir / str(z) / str(tx)).mkdir(parents=True, exist_ok=True)
        w, h = math.ceil(w / 2), math.ceil(h / 2)
    lock = threading.Lock()
    done = 0
    flat_bytes = {}

    def tick():
        nonlocal done
        with lock:
            done += 1
            if progress:
                progress(done, total)

    def write(z, tx, ty, out):
        path = out_dir / str(z) / str(tx) / f"{ty}.webp"
        if isinstance(out, Flat):
            with lock:
                data = flat_bytes.get(out.color)
                if data is None:
                    buf = io.BytesIO()
                    Image.new("RGB", (tile, tile), out.color).save(buf, "WEBP", quality=quality, method=4)
                    data = flat_bytes[out.color] = buf.getvalue()
            path.write_bytes(data)
        else:
            out.save(path, "WEBP", quality=quality, method=4)
        tick()

    def merge(kids):
        """The parent of four tiles (None: outside the image), at half their size."""
        first = kids[0][2]
        if all(isinstance(k, Flat) and k.color == first.color for _, _, k in kids):
            return first
        see_through = any(k is None or (not isinstance(k, Flat) and k.mode == "RGBA") for _, _, k in kids)
        canvas = Image.new("RGBA", (2 * tile, 2 * tile), (0, 0, 0, 0)) if see_through else Image.new("RGB", (2 * tile, 2 * tile))
        for dx, dy, k in kids:
            if isinstance(k, Flat):
                canvas.paste(k.color, (dx * tile, dy * tile, (dx + 1) * tile, (dy + 1) * tile))
            elif k is not None:
                canvas.paste(k, (dx * tile, dy * tile))
        return canvas.reduce(2)

    def node(z, tx, ty, ready=None):
        """Write tile (z, tx, ty) and everything below it; returns the tile (image, Flat or None)."""
        if tx >= grid[z][0] or ty >= grid[z][1]:
            return None
        if ready is not None and z == split:
            return ready[tx, ty]
        if z == top:
            out = render(tx, ty)
        else:
            out = merge([(dx, dy, node(z + 1, 2 * tx + dx, 2 * ty + dy, ready)) for dx in (0, 1) for dy in (0, 1)])
        write(z, tx, ty, out)
        return out

    workers = default_workers() if workers is None else max(1, workers)
    split = max(0, top - SUBTREE_LEVELS)
    blocks = [(tx, ty) for tx in range(grid[split][0]) for ty in range(grid[split][1])]
    if workers == 1 or len(blocks) == 1:
        node(0, 0, 0)
        return top
    with ThreadPoolExecutor(workers, thread_name_prefix="tiles") as pool:
        futures = {block: pool.submit(node, split, *block) for block in blocks}
        try:
            ready = {block: f.result() for block, f in futures.items()}
        except BaseException:
            for f in futures.values():
                f.cancel()
            raise
    node(0, 0, 0, ready)                             # the few levels above the blocks
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
