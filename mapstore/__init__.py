"""Local map asset store: maps (tile pyramid + manifest) in %LOCALAPPDATA%\\CompanionMap\\maps.

Assets come from the user's own game install (source A), a download with a licence that
allows it (B), or the user's own captures (C). They never go into the repo or the exe.
"""

from mapstore.store import REALMS, SOURCES, MapError, MapStore, NotFound

__all__ = ["REALMS", "SOURCES", "MapError", "MapStore", "NotFound"]
