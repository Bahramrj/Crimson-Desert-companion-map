"""Read-only access to Crimson Desert's PAMT/PAZ archives.

Install files are only ever opened with mode "rb".
Format knowledge from NattKh CrimsonDesertModdingTools and CDMW-Lite (both MIT, see
gamedata/NOTICE.md); this is our own implementation.
"""

import fnmatch
import os
import struct
from dataclasses import dataclass
from pathlib import Path

M32 = 0xFFFFFFFF


class ArchiveError(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    group: str
    path: str
    paz: Path
    offset: int
    stored: int
    size: int
    flags: int   # bits 0-3 compression (1 partial, 2 LZ4), bits 4-7 encryption (3 ChaCha20)

    @property
    def compression(self):
        return self.flags & 0x0F

    @property
    def encryption(self):
        return (self.flags >> 4) & 0x0F


# ── hashing (Bob Jenkins' lookup3) ────────────────────────────────

def _rot(v, k):
    return ((v << k) | (v >> (32 - k))) & M32


def _lookup3(data, a):
    """lookup3 hashlittle body with a = b = c preset; returns c."""
    b = c = a
    n, off = len(data), 0
    while n > 12:
        a = (a + int.from_bytes(data[off:off + 4], "little")) & M32
        b = (b + int.from_bytes(data[off + 4:off + 8], "little")) & M32
        c = (c + int.from_bytes(data[off + 8:off + 12], "little")) & M32
        a = (a - c) & M32; a ^= _rot(c, 4); c = (c + b) & M32
        b = (b - a) & M32; b ^= _rot(a, 6); a = (a + c) & M32
        c = (c - b) & M32; c ^= _rot(b, 8); b = (b + a) & M32
        a = (a - c) & M32; a ^= _rot(c, 16); c = (c + b) & M32
        b = (b - a) & M32; b ^= _rot(a, 19); a = (a + c) & M32
        c = (c - b) & M32; c ^= _rot(b, 4); b = (b + a) & M32
        off += 12
        n -= 12
    if n == 0:
        return c
    tail = data[off:] + b"\0" * 12           # zero padding equals lookup3's byte masks
    a = (a + int.from_bytes(tail[0:4], "little")) & M32
    b = (b + int.from_bytes(tail[4:8], "little")) & M32
    c = (c + int.from_bytes(tail[8:12], "little")) & M32
    c ^= b; c = (c - _rot(b, 14)) & M32
    a ^= c; a = (a - _rot(c, 11)) & M32
    b ^= a; b = (b - _rot(a, 25)) & M32
    c ^= b; c = (c - _rot(b, 16)) & M32
    a ^= c; a = (a - _rot(c, 4)) & M32
    b ^= a; b = (b - _rot(a, 14)) & M32
    c ^= b; c = (c - _rot(b, 24)) & M32
    return c


def hashlittle(data, initval=0):
    return _lookup3(data, (0xDEADBEEF + len(data) + initval) & M32)


def pa_checksum(text):
    """Key of meta/0.pathc entries: pa_checksum("/" + path)."""
    data = text.encode("utf-8")
    return _lookup3(data, (len(data) + 0xDEBA1DCD) & M32)


# ── codecs ────────────────────────────────────────────────────────

def lz4_block(src, size):
    """LZ4 block (no frame) decoder; the lz4 package has no wheel for every Python we use."""
    dst = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]; i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1
                lit += b
                if b != 255:
                    break
        dst += src[i:i + lit]
        i += lit
        if i >= n:
            break
        dist = src[i] | (src[i + 1] << 8); i += 2
        if not 0 < dist <= len(dst):
            raise ArchiveError("LZ4 match offset out of range")
        ml = token & 15
        if ml == 15:
            while True:
                b = src[i]; i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(dst) - dist
        if dist >= ml:
            dst += dst[start:start + ml]
        else:                                  # overlapping copy repeats the last `dist` bytes
            for k in range(ml):
                dst.append(dst[start + k])
    if len(dst) != size:
        raise ArchiveError(f"LZ4 block decoded to {len(dst)} bytes, expected {size}")
    return bytes(dst)


def chacha_key(name):
    """ChaCha20 key and IV derived from the lower-cased basename."""
    seed = hashlittle(os.path.basename(name).lower().encode("utf-8"), 0x000C5EDE)
    base = seed ^ 0x60616263
    deltas = (0, 0x0A0A0A0A, 0x0C0C0C0C, 0x06060606, 0x0E0E0E0E, 0x0A0A0A0A, 0x06060606, 0x02020202)
    return b"".join(struct.pack("<I", base ^ d) for d in deltas), struct.pack("<I", seed) * 4


def chacha20(data, name):
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    except ImportError as e:   # only string tables and UI files are encrypted
        raise ArchiveError("the 'cryptography' package is needed for encrypted entries") from e
    key, iv = chacha_key(name)
    return Cipher(algorithms.ChaCha20(key, iv), mode=None).encryptor().update(data)


# ── partial DDS: header in meta/0.pathc, mips as LZ4 chunks ───────

BLOCK8 = {71, 72, 80, 81}
BLOCK16 = {74, 75, 77, 78, 83, 84, 94, 95, 96, 98, 99}


class Pathc:
    def __init__(self, raw):
        hsize, hcount, ecount, ccount, flen = struct.unpack_from("<5I", raw, 8)
        if not 0x80 <= hsize <= 4096:
            raise ArchiveError("unsupported PATHC header size")
        off = 28
        self.hsize = hsize
        self.headers = [raw[off + i * hsize: off + (i + 1) * hsize] for i in range(hcount)]
        off += hcount * hsize
        sums = struct.unpack_from(f"<{ecount}I", raw, off)
        off += 4 * ecount
        self.entries = {}
        for i in range(ecount):
            self.entries[sums[i]] = (struct.unpack_from("<H", raw, off)[0], raw[off + 4:off + 20])
            off += 20
        rows = [(struct.unpack_from("<I", raw, off + 24 * i)[0], struct.unpack_from("<H", raw, off + 24 * i + 4)[0],
                 raw[off + 24 * i + 8:off + 24 * i + 24]) for i in range(ccount)]
        off += 24 * ccount
        names = raw[off:off + flen]
        self.collisions = {}
        for name_off, idx, info in rows:
            end = names.find(b"\0", name_off)
            self.collisions[names[name_off:end].decode("utf-8").replace("\\", "/").strip("/")] = (idx, info)

    def header(self, path):
        norm = path.replace("\\", "/").strip("/")
        found = self.entries.get(pa_checksum("/" + norm))
        if found is None:
            raise ArchiveError(f"no DDS header for {path}")
        idx, info = found
        if idx == 0xFFFF:
            idx, info = self.collisions[norm]
        header = bytearray(self.headers[idx])
        if self.hsize == 0x94 and len(info) >= 16:
            header[0x20:0x30] = info[:16]
        return bytes(header)


def _surface_size(w, h, dxgi, fourcc, pflags, bits, pitch, level):
    code = fourcc.lower()
    per_block = 8 if dxgi in BLOCK8 or code in ("dxt1", "bc4u", "bc4s", "ati1") else \
        16 if dxgi in BLOCK16 or code in ("dxt3", "dxt5", "bc5u", "bc5s", "ati2", "rxgb") else 0
    if per_block:
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * per_block
    if pflags & (0x1 | 0x2 | 0x40 | 0x20000) and bits and bits % 8 == 0:
        return w * h * bits // 8
    if pitch:
        return max(1, pitch >> level) * h
    raise ArchiveError("unsupported partial DDS pixel format")


def partial_dds(header, payload):
    if header[:4] != b"DDS " or struct.unpack_from("<I", header, 4)[0] != 124:
        raise ArchiveError("invalid DDS header in PATHC")
    height, width, pitch, depth, mips = struct.unpack_from("<5I", header, 12)
    mips = max(1, mips)
    reserved = list(struct.unpack_from("<11I", header, 32))
    pflags = struct.unpack_from("<I", header, 80)[0]
    fourcc = header[84:88].decode("latin1")
    bits = struct.unpack_from("<I", header, 88)[0]
    caps2 = struct.unpack_from("<I", header, 112)[0]
    dx10 = fourcc == "DX10"
    hsize = 0x94 if dx10 else 0x80
    dxgi = struct.unpack_from("<I", header, 0x80)[0] if dx10 else 0
    array = struct.unpack_from("<I", header, 0x8C)[0] if dx10 else 1
    single = (dx10 and array >= 2) or mips <= 5 or caps2 != 0 or depth >= 2
    if single:
        stored, sizes = [reserved[0]], [reserved[1]]
    else:
        stored, sizes, w, h = reserved[:4], [], width, height
        for level in range(min(4, mips)):
            sizes.append(_surface_size(w, h, dxgi, fourcc, pflags, bits, pitch, level))
            w, h = max(1, w >> 1), max(1, h >> 1)
    if payload[:4] == b"DDS ":          # newer entries carry their own chunk sizes
        mine = list(struct.unpack_from("<11I", payload, 32))
        own_stored, own_sizes = ([mine[0]], [mine[1]]) if single else (mine[:len(stored)], sizes)
        total, current = sum(own_stored), sum(stored)
        if 0 < total <= sum(own_sizes) and total <= len(payload) - hsize and \
                (current == 0 or current > len(payload) - hsize or total < current):
            stored = own_stored
            if single:
                sizes = own_sizes
    out = bytearray(header[:hsize])
    pos = hsize
    for s, d in zip(stored, sizes):
        if not s or not d:
            continue
        chunk = payload[pos:pos + s]
        out += lz4_block(chunk, d) if s != d else chunk
        pos += s
    out += payload[pos:]
    return bytes(out)


# ── archive ───────────────────────────────────────────────────────

def _names(block):
    cache = {}

    def full(ref):
        if ref in cache:
            return cache[ref]
        parts, cur, seen = [], ref, 0
        while cur != M32:
            if cur + 5 > len(block) or seen > 255:
                raise ArchiveError("PAMT name record out of range")
            parent, n = struct.unpack_from("<I", block, cur)[0], block[cur + 4]
            parts.append(block[cur + 5:cur + 5 + n].decode("utf-8", "replace"))
            cur, seen = parent, seen + 1
        cache[ref] = "".join(reversed(parts))
        return cache[ref]
    return full


def parse_pamt(group_dir):
    group_dir = Path(group_dir)
    with open(group_dir / "0.pamt", "rb") as f:
        data = f.read()
    paz_count = struct.unpack_from("<I", data, 4)[0]
    off = 12 + paz_count * 12
    dsize = struct.unpack_from("<I", data, off)[0]; off += 4
    dirs = _names(data[off:off + dsize]); off += dsize
    nsize = struct.unpack_from("<I", data, off)[0]; off += 4
    files = _names(data[off:off + nsize]); off += nsize
    folders = struct.unpack_from("<I", data, off)[0]; off += 4
    ranges = []
    for i in range(folders):
        _, name_off, first, count = struct.unpack_from("<4I", data, off + 16 * i)
        if count:
            ranges.append((first, first + count, dirs(name_off).replace("\\", "/").strip("/")))
    ranges.sort()
    off += 16 * folders
    count = struct.unpack_from("<I", data, off)[0]; off += 4
    out, cursor = [], 0
    for i in range(count):
        name_off, poff, stored, size, paz, flags = struct.unpack_from("<IIIIHH", data, off + 20 * i)
        path = files(name_off).replace("\\", "/").strip("/")
        while cursor < len(ranges) and i >= ranges[cursor][1]:
            cursor += 1
        if cursor < len(ranges) and ranges[cursor][0] <= i and ranges[cursor][2]:
            path = f"{ranges[cursor][2]}/{path}"
        out.append(Entry(group_dir.name, path, group_dir / f"{paz}.paz", poff, stored, size, flags))
    return out


class Archive:
    """One Crimson Desert install, opened read-only."""

    def __init__(self, game_dir):
        self.root = Path(game_dir)
        if not (self.root / "meta" / "0.paver").is_file():
            raise ArchiveError(f"not a Crimson Desert install: {self.root}")
        self._groups = {}
        self._pathc = None

    def version(self):
        with open(self.root / "meta" / "0.paver", "rb") as f:
            raw = f.read(6)
        major, minor, patch = struct.unpack("<3H", raw)
        return f"{major}.{minor:02d}.{patch:02d}"

    def groups(self):
        return sorted(d.name for d in self.root.iterdir() if d.is_dir() and d.name.isdigit() and (d / "0.pamt").is_file())

    def entries(self, group):
        if group not in self._groups:
            self._groups[group] = parse_pamt(self.root / group)
        return self._groups[group]

    def find(self, pattern, groups=None):
        """Entries whose path matches a glob (case-insensitive)."""
        pattern = pattern.lower()
        return [e for g in (groups or self.groups()) for e in self.entries(g) if fnmatch.fnmatchcase(e.path.lower(), pattern)]

    def read(self, entry):
        with open(entry.paz, "rb") as f:
            f.seek(entry.offset)
            data = f.read(entry.stored)
        if len(data) != entry.stored:
            raise ArchiveError(f"short read: {entry.path}")
        if entry.encryption:
            if entry.encryption != 3:
                raise ArchiveError(f"unsupported encryption {entry.encryption}: {entry.path}")
            data = chacha20(data, entry.path)
        if entry.stored == entry.size:
            return data
        if entry.compression == 2:
            return lz4_block(data, entry.size)
        if entry.compression == 1 and entry.path.lower().endswith(".dds"):
            return partial_dds(self.pathc().header(entry.path), data)
        raise ArchiveError(f"unsupported compression {entry.compression}: {entry.path}")

    def pathc(self):
        if self._pathc is None:
            with open(self.root / "meta" / "0.pathc", "rb") as f:
                self._pathc = Pathc(f.read())
        return self._pathc
