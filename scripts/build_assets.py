"""Generate build inputs for PyInstaller: the .ico (from web/public/icon-512.png) and the
Windows version resource (from server.__version__).

    python scripts/build_assets.py <out_dir>
"""

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

from server import APP_NAME, EXE_NAME, __version__  # noqa: E402

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def png_bytes(image, size):
    scaled = image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    scaled.save(buf, "PNG")
    return bytes(data)


def write_ico(source, target):
    """ICO with PNG-compressed entries (supported since Windows Vista)."""
    image = QImage(str(source))
    if image.isNull():
        raise SystemExit(f"cannot read {source}")
    entries = [(size, png_bytes(image, size)) for size in ICON_SIZES]
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    directory, blobs = b"", b""
    for size, blob in entries:
        dim = 0 if size >= 256 else size
        directory += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset + len(blobs))
        blobs += blob
    target.write_bytes(header + directory + blobs)


def write_version_file(target):
    parts = [int(p) for p in __version__.split(".")] + [0] * 4
    v = tuple(parts[:4])
    dotted = ".".join(map(str, v))
    target.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{APP_NAME}'),
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('LegalCopyright', 'Unofficial fan tool, not affiliated with Pearl Abyss'),
      StringStruct('FileVersion', '{dotted}'),
      StringStruct('InternalName', '{EXE_NAME}'),
      StringStruct('OriginalFilename', '{EXE_NAME}.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "build")
    out.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication.instance() or QGuiApplication(["build_assets", "-platform", "offscreen"])  # noqa: F841
    write_ico(ROOT / "web" / "public" / "icon-512.png", out / "companionmap.ico")
    write_version_file(out / "version_info.txt")
    print(f"icon and version {__version__} written to {out}")


if __name__ == "__main__":
    main()
