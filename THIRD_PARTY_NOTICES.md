# Third-party notices

Offline Companion Map for Crimson Desert uses the following components. Their licences apply to
those components only.

| Component | Version | Licence | Where |
| --- | --- | --- | --- |
| Qt for Python (PySide6, shiboken6) and Qt 6 | 6.12 | LGPL-3.0-only (or GPL-2.0/3.0) | The Windows app's user interface. Shipped as separate, unmodified libraries in the release's `PySide6` folder; texts in [licenses/](licenses/) |
| CPython | 3.15 | PSF License | Runtime bundled in the release |
| aiohttp | 3.14 | Apache-2.0 AND MIT | Local web server |
| Pillow | 13 | MIT-CMU | Map tiles |
| cryptography | 50 | Apache-2.0 OR BSD-3-Clause | Game-archive decryption, local HTTPS certificates |
| segno | 1.6 | BSD-3-Clause | QR codes |
| pymem | 1.14 | MIT | Reading the game's memory (read-only) |
| OpenLayers (`ol`) | 10.11 | BSD-2-Clause | Map view in the browser (bundled in `web/dist`) |

Knowledge and code this app builds on:

- **CD_Companion** by andreikapica-dot, https://github.com/andreikapica-dot/CD_Companion. The live
  position engine (`engine/`) is based on its memory signatures and position capture hook, with
  every write and teleport path removed.
- **CrimsonDesertModdingTools** (NattKh) and **CDMW Archive Lite** (CDMW), both MIT: the archive
  formats read by `gamedata/`. See [gamedata/NOTICE.md](gamedata/NOTICE.md) for the notices.
- Bob Jenkins' lookup3 hash (public domain).

## Qt / PySide6 (LGPLv3)

The release ships Qt and PySide6 as separate files in the `PySide6` folder next to
`CompanionMap.exe`. They are not modified. You may replace them with your own builds of the same
major version (PySide6 6.12 / Qt 6.12). The sources are available from https://download.qt.io/
and https://code.qt.io/. The LGPLv3 is in [licenses/LGPL-3.0.txt](licenses/LGPL-3.0.txt); it
builds on the GPLv3 in [licenses/GPL-3.0.txt](licenses/GPL-3.0.txt).
