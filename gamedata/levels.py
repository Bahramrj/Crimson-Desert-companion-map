"""Level files (`leveldata/bin__/rootlevel/<name>.palevel`, group 0015): reflected scene data.

Two things are read:
- the level's bounding box, `_minVerts` / `_maxVerts`: the first two float3 after the reflection schema;
- the world transform of each placed object: `[x y z][scale x y z][quaternion x y z w]`, float32.
Positions are in the engine's own space, like the static tables.
"""

import struct

from gamedata.tables import WORLD, Y_RANGE

LEVEL_GROUP = "0015"
LEVEL_DIR = "leveldata/bin__/rootlevel/"
SCHEMA_END = b"_autoTextureMultiplierForProxyLOD"     # last field name of the SceneLevelDataReflect schema


def levels(archive, prefix):
    """{name: entry} for the level files whose name starts with `prefix` (lower case); {} without the level group."""
    out = {}
    if LEVEL_GROUP not in archive.groups():
        return out
    for e in archive.entries(LEVEL_GROUP):
        if e.path.startswith(LEVEL_DIR) and e.path.endswith(".palevel") and "/" not in e.path[len(LEVEL_DIR):]:
            name = e.path[len(LEVEL_DIR):-len(".palevel")]
            if name.lower().startswith(prefix):
                out[name] = e
    return out


def _in_world(x, y, z):
    return WORLD[0] < x < WORLD[2] and WORLD[1] < z < WORLD[3] and Y_RANGE[0] < y < Y_RANGE[1]


def bounds(data):
    """(min xyz, max xyz) of the level, or None."""
    start = data.find(SCHEMA_END)
    if start < 0:
        return None
    for o in range(start, min(len(data) - 24, start + 512)):
        lo, hi = struct.unpack_from("<3f", data, o), struct.unpack_from("<3f", data, o + 12)
        if _in_world(*lo) and _in_world(*hi) and all(a <= b for a, b in zip(lo, hi)) and abs(lo[0]) > 1:
            return lo, hi
    return None


def centre(data):
    box = bounds(data)
    return tuple((a + b) / 2 for a, b in zip(*box)) if box else None


def transforms(data, y_min=Y_RANGE[0]):
    """Positions (x, y, z) of the objects placed in a level, in file order; only those above y_min."""
    found = []
    for phase in range(4):
        n = (len(data) - phase) // 4
        if n < 10:
            continue
        v = struct.unpack_from(f"<{n}f", data, phase)
        for i in range(n - 9):
            y = v[i + 1]
            if not y_min < y < Y_RANGE[1]:
                continue
            x, z = v[i], v[i + 2]
            if not (WORLD[0] < x < WORLD[2] and WORLD[1] < z < WORLD[3]):
                continue
            sx, sy, sz, qx, qy, qz, qw = v[i + 3:i + 10]
            if 0 < sx < 1000 and 0 < sy < 1000 and 0 < sz < 1000 and abs(qx * qx + qy * qy + qz * qz + qw * qw - 1) < 1e-3:
                found.append((phase + 4 * i, (x, y, z)))
    return [p for _, p in sorted(found)]
