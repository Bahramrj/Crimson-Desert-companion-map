"""Localised string tables (gamedata/stringtable/binary__/<lang>/<name>.paloc).

Each .paloc is ChaCha20-encrypted in the archive. Inside: a 512-byte header ("paloc", u32
compressed size at offset 9, u32 decompressed size), then an LZ4 block of entries
[u64 tag][u32 len] key [u32 len] text. Keys are numeric strings, (sequence << 32) | table id,
in most tables. Rows of other tables refer to them as plain u64 values.
"""

import struct

from gamedata.archive import ArchiveError, lz4_block

STRING_DIR = "gamedata/stringtable/binary__/"
HEADER = 512


def parse_paloc(raw):
    if raw[:5] != b"paloc":
        raise ArchiveError("not a paloc string table")
    csize, usize = struct.unpack_from("<2I", raw, 9)
    data = lz4_block(raw[HEADER:HEADER + csize], usize)
    out, pos = {}, 0
    while pos + 12 <= len(data):
        pos += 8
        n = struct.unpack_from("<I", data, pos)[0]
        key = data[pos + 4:pos + 4 + n].decode("utf-8", "replace")
        pos += 4 + n
        n = struct.unpack_from("<I", data, pos)[0]
        out[key] = data[pos + 4:pos + 4 + n].decode("utf-8", "replace")
        pos += 4 + n
    return out


def _string_groups(archive):
    """String tables sit in small groups of their own; skip the big asset groups."""
    small = [g for g in archive.groups() if (archive.root / g / "0.pamt").stat().st_size < 256 * 1024]
    return small or archive.groups()


def load_strings(archive, table="knowledge", lang="eng"):
    """{numeric key: text} for one table in one language ({} if it is missing)."""
    path = f"{STRING_DIR}{lang}/{table}.paloc"
    for group in _string_groups(archive):
        for e in archive.entries(group):
            if e.path == path:
                return parse_paloc(archive.read(e))
    return {}


def texts_in(payload, strings, limit=2):
    """The first distinct texts a table row refers to (u64 keys at any byte offset)."""
    found = []
    for off in range(len(payload) - 7):
        text = strings.get(str(struct.unpack_from("<Q", payload, off)[0]))
        if text and text not in found:
            found.append(text)
            if len(found) == limit:
                break
    return found
