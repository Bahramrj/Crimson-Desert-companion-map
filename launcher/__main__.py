"""Offline Companion Map for Crimson Desert: the Windows app (also the entry point of CompanionMap.exe).

  python -m launcher [--simulate] [--minimized] [--host 127.0.0.1]
"""

import argparse
import logging
import sys

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from launcher.backend import Backend
from launcher import support
from launcher.support import QtLogHandler
from launcher.window import MainWindow, app_icon
from server import APP_NAME, EXE_NAME, __version__
from server.config import Config, data_dir
from server.logs import setup_logging

log = logging.getLogger("cdlivemap.launcher")
INSTANCE_KEY = "CompanionMap-launcher"   # the online app uses "CDLiveMap-launcher"


def already_running():
    """Ask a running launcher to show itself; True if there was one."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(prog=EXE_NAME)
    ap.add_argument("--simulate", action="store_true", help="use the path simulator instead of the game")
    ap.add_argument("--minimized", action="store_true", help="start in the tray")
    ap.add_argument("--host", action="append", help="bind address (repeatable); default: loopback + LAN")
    args = ap.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)
    if already_running():
        return 0
    instance = QLocalServer()
    QLocalServer.removeServer(INSTANCE_KEY)
    instance.listen(INSTANCE_KEY)

    root = data_dir()
    handler = QtLogHandler()
    extra = [handler] if getattr(sys, "frozen", False) else [handler, logging.StreamHandler(sys.stderr)]
    setup_logging(root, *extra)
    log.info("%s %s starting (data: %s)", APP_NAME, __version__, root)

    config_path = root / "config.json"
    try:
        config = Config.load(config_path)
    except (ValueError, TypeError) as e:
        log.warning("config.json ignored (%s); using defaults", e)
        config = Config()

    support.migrate_autostart()
    backend = Backend(root, simulate=args.simulate, hosts=args.host)
    backend.start(config)
    window = MainWindow(backend, config, config_path, root, handler)
    instance.newConnection.connect(lambda: (instance.nextPendingConnection(), window.bring_to_front()))

    def excepthook(kind, value, tb):
        log.error("Unhandled error", exc_info=(kind, value, tb))
        QMessageBox.critical(window, APP_NAME, f"{kind.__name__}: {value}\n\nSee the Log tab for details.")
    sys.excepthook = excepthook

    if not ((args.minimized or config.start_minimized) and QSystemTrayIcon.isSystemTrayAvailable()):
        window.show()
    try:
        return app.exec()
    finally:
        log.info("Shutting down")
        backend.stop()


if __name__ == "__main__":
    sys.exit(main())
