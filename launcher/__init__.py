"""Desktop launcher: PySide6 window and tray around the engine and LAN server."""

import concurrent.futures

import PySide6.QtCore  # noqa: F401  (must be imported before the fix below)
from concurrent.futures.process import ProcessPoolExecutor
from concurrent.futures.thread import ThreadPoolExecutor

# Python 3.15 + PySide6 6.12: after PySide6 is imported, concurrent.futures.ThreadPoolExecutor
# stays an unresolved 'lazy_import' object, so asyncio's run_in_executor and getaddrinfo
# (DNS for the TH.GL proxy) raise TypeError. Bind the real classes back onto the package.
concurrent.futures.ThreadPoolExecutor = ThreadPoolExecutor
concurrent.futures.ProcessPoolExecutor = ProcessPoolExecutor
