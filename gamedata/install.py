"""Find the Crimson Desert install folder (read-only)."""

import os
import re
import sys
from pathlib import Path

GAME_FOLDER = "Crimson Desert"
DEFAULT_STEAM = Path(r"C:\Program Files (x86)\Steam")


def _steam_root():
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                return Path(winreg.QueryValueEx(key, "SteamPath")[0])
        except OSError:
            pass
    return DEFAULT_STEAM


def steam_libraries(steam_root=None):
    """Steam library folders from steamapps/libraryfolders.vdf (the Steam folder itself first)."""
    root = Path(steam_root or _steam_root())
    libs = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libs
    for path in re.findall(r'"path"\s+"([^"]+)"', text):
        p = Path(path.replace("\\\\", "\\"))
        if p not in libs:
            libs.append(p)
    return libs


def is_install(path):
    path = Path(path)
    return (path / "meta" / "0.paver").is_file() and (path / "0012" / "0.pamt").is_file()


def resolve_install(path):
    """The install folder for a folder the user picked: the game folder itself, the folder that
    holds it, or a Steam library; None when none of them is an install."""
    path = Path(path)
    for candidate in (path, path / GAME_FOLDER, path / "steamapps" / "common" / GAME_FOLDER):
        if is_install(candidate):
            return candidate
    return None


def find_install(explicit=None, steam_root=None):
    """The install folder, or None. CDLM_GAME_DIR or an explicit path wins over Steam."""
    for candidate in (explicit, os.environ.get("CDLM_GAME_DIR")):
        if candidate:
            return Path(candidate) if is_install(candidate) else None
    for lib in steam_libraries(steam_root):
        path = lib / "steamapps" / "common" / GAME_FOLDER
        if is_install(path):
            return path
    return None
