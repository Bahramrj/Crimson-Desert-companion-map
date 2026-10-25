"""Read-only importer for the user's own Crimson Desert install (map source A).

Reads the game's archives, never writes to the install folder, and only feeds the local
asset store (mapstore). Nothing it produces is committed or shipped.
"""

from gamedata.archive import Archive, ArchiveError
from gamedata.install import find_install, resolve_install

__all__ = ["Archive", "ArchiveError", "find_install", "resolve_install"]
