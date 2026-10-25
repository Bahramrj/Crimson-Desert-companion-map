"""Where a map image sits in game space: image pixel <-> game (x, z).

A map is north-up and orthographic, so one uniform scale plus an offset is enough:

    game_x = origin_x + u * mpp        (u: pixels to the right)
    game_z = origin_z - v * mpp        (v: pixels down; screen up = +z)

`origin` is the game position of the image's top-left corner, `mpp` metres per pixel.
This matches a square-pixel tile grid, needs only 2 calibration points, and from 2
points on the least-squares fit leaves a real residual (error) in metres.
"""

import math

# Extent of the game's world-map layers: x -16384..3076, z -11267..8193.
WORLD = (-16384.0, -11267.0, 3076.0, 8193.0)   # xmin, zmin, xmax, zmax
WORLD_SIZE = WORLD[2] - WORLD[0]
MIN_MPP, MAX_MPP = 0.01, 1000.0


class GeorefError(ValueError):
    pass


def default_georef(width, height):
    """Stretch the image over the world square: a starting guess before calibration."""
    return {"origin": [WORLD[0], WORLD[3]], "mpp": WORLD_SIZE / max(width, height)}


def world_georef(width):
    """Exact placement for an image rendered from the game's own world-map layers."""
    return {"origin": [WORLD[0], WORLD[3]], "mpp": WORLD_SIZE / width}


def px_to_game(georef, u, v):
    (x0, z0), r = georef["origin"], georef["mpp"]
    return x0 + u * r, z0 - v * r


def game_to_px(georef, x, z):
    (x0, z0), r = georef["origin"], georef["mpp"]
    return (x - x0) / r, (z0 - z) / r


def bounds(georef, width, height):
    """[xmin, zmin, xmax, zmax] covered by the image."""
    (x0, z0), r = georef["origin"], georef["mpp"]
    return [x0, z0 - height * r, x0 + width * r, z0]


def fit(points):
    """Least-squares origin + mpp from >= 2 points {"game": [x, z], "px": [u, v]}."""
    if len(points) < 2:
        raise GeorefError("need at least 2 points")
    n = len(points)
    xs = [p["game"][0] for p in points]
    zs = [p["game"][1] for p in points]
    us = [p["px"][0] for p in points]
    vs = [p["px"][1] for p in points]
    mx, mz, mu, mv = sum(xs) / n, sum(zs) / n, sum(us) / n, sum(vs) / n
    num = sum((u - mu) * (x - mx) - (v - mv) * (z - mz) for x, z, u, v in zip(xs, zs, us, vs))
    den = sum((u - mu) ** 2 + (v - mv) ** 2 for u, v in zip(us, vs))
    if den < 1e-9:
        raise GeorefError("points must be at different places on the image")
    r = num / den
    if not MIN_MPP <= r <= MAX_MPP:
        raise GeorefError("points do not give a sensible scale; check that each tap matches its position")
    return {"origin": [mx - r * mu, mz + r * mv], "mpp": r}


def residuals(georef, points):
    """Distance in game metres between each point and where the georef puts its pixel."""
    out = []
    for p in points:
        x, z = px_to_game(georef, *p["px"])
        out.append(math.hypot(x - p["game"][0], z - p["game"][1]))
    return out


def rms(values):
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else None
