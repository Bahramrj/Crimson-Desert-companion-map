"""Load engine/signatures.json and scan module bytes for wildcard patterns."""

import json
import re
from functools import lru_cache
from pathlib import Path

SIGNATURES_FILE = Path(__file__).with_name("signatures.json")


def parse_hex(text):
    return bytes(int(tok, 16) for tok in text.split())


@lru_cache(maxsize=None)
def compile_pattern(pattern):
    parts = [b"." if tok == "??" else re.escape(bytes([int(tok, 16)])) for tok in pattern.split()]
    return re.compile(b"".join(parts), re.DOTALL)


def find_all(data, pattern, limit=2):
    """Offsets of up to `limit` matches of `pattern` in `data`."""
    out = []
    for m in compile_pattern(pattern).finditer(data):
        out.append(m.start())
        if len(out) >= limit:
            break
    return out


def load_signatures(path=SIGNATURES_FILE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
