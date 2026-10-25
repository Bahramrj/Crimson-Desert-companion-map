Qt for Python (PySide6, shiboken6) and Qt 6
===========================================

This folder holds the Qt libraries that Offline Companion Map for Crimson Desert uses for its
Windows window. They are licensed under the GNU Lesser General Public License version 3
(LGPL-3.0-only; Qt is also available under GPL-2.0/3.0 and commercial terms).

- The libraries are shipped unmodified, as separate files (not packed into CompanionMap.exe).
- You may replace them with your own builds of the same major version (PySide6 6.12 / Qt 6.12);
  the app loads whatever is in this folder.
- Sources: https://download.qt.io/ and https://code.qt.io/ (Qt), https://pypi.org/project/PySide6/ (PySide6).

Licence texts: LGPL-3.0.txt (the LGPLv3) and GPL-3.0.txt (the GPLv3, which the LGPLv3 builds on).
