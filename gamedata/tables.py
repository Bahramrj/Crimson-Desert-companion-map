"""Static game-data tables (gamedata/binarystaticinfo__/bin/<name>.staticinfoheader|body, group 0008).

Header: u16 or u32 row count, then (key, u32 body offset) per row; the key width follows from
the header length. Body row from 2.04: u32 name length, name, u32 key, payload. Up to 2.03:
u32|u16|u8 id, u32 name length, name, NUL, payload.
"""

import re
import struct
from dataclasses import dataclass

from gamedata.archive import ArchiveError
from mapstore.georef import WORLD

TABLE_DIR = "gamedata/binarystaticinfo__/bin/"
Y_RANGE = (-500.0, 3500.0)


@dataclass(frozen=True)
class Row:
    key: int
    name: str
    payload: bytes


def parse(header, body):
    if len(header) in (2, 4) and not int.from_bytes(header, "little"):
        return []                                     # an empty table
    for count_size in (2, 4):
        count = int.from_bytes(header[:count_size], "little")
        rest = len(header) - count_size - 4 * count
        if count and rest > 0 and rest % count == 0:
            key_size = rest // count
            break
    else:
        raise ArchiveError("cannot read table header")
    index, pos = [], count_size
    for _ in range(count):
        key = int.from_bytes(header[pos:pos + key_size], "little")
        index.append((struct.unpack_from("<I", header, pos + key_size)[0], key))
        pos += key_size + 4
    index.sort()
    ends = [o for o, _ in index[1:]] + [len(body)]
    rows = []
    for (start, key), end in zip(index, ends):
        raw = body[start:end]
        name, payload = "", raw
        n = struct.unpack_from("<I", raw)[0] if len(raw) >= 4 else 0
        if n <= 500 and 8 + n <= len(raw) and struct.unpack_from("<I", raw, 4 + n)[0] == key:   # 2.04 layout
            try:
                rows.append(Row(key, raw[4:4 + n].decode("utf-8"), raw[8 + n:]))
                continue
            except UnicodeDecodeError:
                pass
        for id_size in (4, 2, 1):
            if len(raw) < id_size + 4:
                continue
            n = struct.unpack_from("<I", raw, id_size)[0]
            if n <= 500 and id_size + 4 + n < len(raw) and raw[id_size + 4 + n] == 0:
                try:
                    name = raw[id_size + 4:id_size + 4 + n].decode("utf-8")
                except UnicodeDecodeError:
                    continue
                payload = raw[id_size + 5 + n:]
                break
        rows.append(Row(key, name, payload))
    return rows


def read_table(archive, name):
    found = {e.path.rsplit("/", 1)[1]: e for e in archive.entries("0008") if e.path.startswith(TABLE_DIR)}
    try:
        header, body = found[f"{name}.staticinfoheader"], found[f"{name}.staticinfobody"]
    except KeyError:
        raise ArchiveError(f"table {name} not found") from None
    return parse(archive.read(header), archive.read(body))


MISC_DIR = TABLE_DIR + "misc/"
PLACEMENT_NAME = re.compile(rb"[A-Za-z][A-Za-z0-9_]{2,120}")


def read_misc(archive, name):
    """Raw bytes of <name>.base.staticinfomisc (in misc/, or next to the tables)."""
    paths = (f"{MISC_DIR}{name}.base.staticinfomisc", f"{TABLE_DIR}{name}.base.staticinfomisc")
    for e in archive.entries("0008"):
        if e.path in paths:
            return archive.read(e)
    raise ArchiveError(f"misc table {name} not found")


def grouped_points(data):
    """{type key: [(x, y, z)]} from a grouped misc table (fieldreviveinfo_misc, 2.04):
    [u32 groups] then per group [u32 type key][u32 n][n x (x y z, rotation, u32, u32)]."""
    out, off = {}, 4
    for _ in range(struct.unpack_from("<I", data)[0]):
        key, n = struct.unpack_from("<2I", data, off)
        off += 8
        out[key] = [struct.unpack_from("<3f", data, off + 24 * i) for i in range(n)]
        off += 24 * n
    if off != len(data):
        raise ArchiveError("unexpected grouped misc table layout")
    return out


def placements(data):
    """Named objects placed in the levels (levelgimmicksceneobjectinfo_misc):
    [u32 len][name][x y z][quaternion x y z w][scale x y z], all float32 -> [(name, x, y, z)].
    Unnamed placements (props) follow a different layout and are skipped."""
    out, i, n = [], 0, len(data)
    while i < n - 48:
        size = struct.unpack_from("<I", data, i)[0]
        end = i + 4 + size
        if 3 <= size <= 120 and end + 40 <= n and PLACEMENT_NAME.fullmatch(data[i + 4:end]):
            x, y, z, qx, qy, qz, qw, sx = struct.unpack_from("<8f", data, end)
            if (WORLD[0] < x < WORLD[2] and WORLD[1] < z < WORLD[3] and Y_RANGE[0] < y < Y_RANGE[1]
                    and abs(qx * qx + qy * qy + qz * qz + qw * qw - 1) < 0.01 and 0 < sx < 100):
                out.append((data[i + 4:end].decode("ascii"), x, y, z))
                i = end + 40
                continue
        i += 1
    return out


# Typed placements in the same table (ore, plants, campfires, chests, ...): a transform block
#   +0 x y z, +12 quaternion, +28 scale, +40 offset position, +52 offset quaternion, +68 offset scale (1 1 1).
# From 2.04 the type comes before it: [u32 gimmickinfo key][8 bytes][u32 n][level name, n bytes], then
# TYPED_GAP bytes, then the placement's own [u32 n][name] (n = 0 for most), then the transform.
# Up to 2.03 the key sat at +105 (TYPED_KEY).
TYPED_SCALE = re.compile(rb"(?=(?:\x00\x00\x80\x3f){3})")      # the offset scale, three float32 1.0
TYPED_KEY = 105
TYPED_GAP = 44
TYPED_NAME_END = TYPED_GAP + 4   # level name end -> transform, for an unnamed placement
LEVEL_NAME = re.compile(rb"[ -~]+")


def _level_key(data, end):
    """The key 16 bytes before a [u32 n][level name] that ends at `end`, or None."""
    for size in range(1, 121):
        s = end - size
        if s < 16:
            break
        if struct.unpack_from("<I", data, s - 4)[0] == size and LEVEL_NAME.fullmatch(data, s, end):
            return struct.unpack_from("<I", data, s - 16)[0]
    return None


def _typed_key(data, p):
    """The gimmickinfo key of the transform at p: before the level name (2.04), else at +105 (2.03)."""
    key = _level_key(data, p - TYPED_NAME_END)
    if key is None:                  # a named placement: its [u32 n][name] sits right before the transform
        for size in range(3, 121):
            s = p - size
            if s < 4:
                break
            if struct.unpack_from("<I", data, s - 4)[0] == size and PLACEMENT_NAME.fullmatch(data, s, p):
                key = _level_key(data, s - 4 - TYPED_GAP)
                break
    if key is None and p + TYPED_KEY + 4 <= len(data):
        key = struct.unpack_from("<I", data, p + TYPED_KEY)[0]
    return key


def typed_placements(data):
    """[(gimmickinfo key, x, y, z)] of the objects placed by type in levelgimmicksceneobjectinfo_misc."""
    out, n = [], len(data)
    for m in TYPED_SCALE.finditer(data):
        p = m.start() - 68
        if p < 0 or p + 80 > n:
            continue
        x, y, z, qx, qy, qz, qw, sx = struct.unpack_from("<8f", data, p)
        ox, oy, oz, ow = struct.unpack_from("<4f", data, p + 52)
        if (WORLD[0] < x < WORLD[2] and WORLD[1] < z < WORLD[3] and Y_RANGE[0] < y < Y_RANGE[1] and 0 < sx < 100
                and abs(qx * qx + qy * qy + qz * qz + qw * qw - 1) < 0.01 and abs(ox * ox + oy * oy + oz * oz + ow * ow - 1) < 0.01):
            key = _typed_key(data, p)
            if key is not None:
                out.append((key, x, y, z))
    return out


def positions(payload):
    """All float32 (x, y, z) triples inside the game world, in payload order (any alignment)."""
    found = []
    for phase in range(4):
        n = (len(payload) - phase) // 4
        if n < 3:
            continue
        values = struct.unpack_from(f"<{n}f", payload, phase)
        for i in range(n - 2):
            x, y, z = values[i], values[i + 1], values[i + 2]
            if (WORLD[0] < x < WORLD[2] and WORLD[1] < z < WORLD[3] and Y_RANGE[0] < y < Y_RANGE[1]
                    and min(abs(x), abs(z)) > 1 and abs(y) > 0.5):
                found.append((phase + 4 * i, (x, y, z)))
    return [p for _, p in sorted(found)]


def first_position(payload, *checks):
    """The earliest position the first check agrees with, else the second, ... (any, without checks).
    Rows also hold counters and sizes that look like coordinates; the checks (on land, for
    example) tell the real position apart."""
    found = positions(payload)
    for check in checks or (None,):
        hit = next((p for p in found if check is None or check(*p)), None)
        if hit:
            return hit
    return None
