"""Main window: a navigation rail with the pages Connect, Maps, Settings, Activity and About; a status
strip that is always in view; the tray icon. Layout follows the Windows 11 pattern: rail, page title,
cards, one primary button per card.

The pages' own code is in launcher/page_connect.py, page_settings.py and page_maps.py (mixins of
MainWindow), small widgets in launcher/widgets.py, colours and the style sheet in launcher/theme.py."""

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QGuiApplication, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from engine.models import AOB_NOT_FOUND, ATTACHED, ERROR, WAITING_FOR_GAME
from launcher import support
from launcher.page_connect import ConnectPage
from launcher.page_maps import MapsPage
from launcher.page_settings import SettingsPage
from launcher.theme import ACCENT, STYLE, is_dark, style_sheet
from launcher.widgets import ImportCancelled, ImportDialog, NavButton, StatusCard, app_icon, panel, time_left
from mapstore.markers import MarkerStore
from server import APP_NAME, SHORT_NAME, __version__

# also reached through this module by the tests and scripts (they patch dialogs and read the theme here)
__all__ = ["MainWindow", "ACCENT", "STYLE", "ImportCancelled", "ImportDialog", "QFileDialog", "QMessageBox", "is_dark", "style_sheet",
           "support", "time_left"]

log = logging.getLogger("cdlivemap.launcher")

GAME_TEXT = {WAITING_FOR_GAME: ("Waiting for Crimson Desert", "amber"), ATTACHED: ("Connected", "green"),
             AOB_NOT_FOUND: ("This game version is not supported yet", "red"), ERROR: ("Error", "red")}
GAME_HELP = {
    WAITING_FOR_GAME: "Start Crimson Desert; the live position appears as soon as you are in the game world.",
    AOB_NOT_FOUND: ("The game was updated and its live position can't be read until this app is updated. "
                    "Maps and markers keep working."),
}



class MainWindow(QMainWindow, ConnectPage, SettingsPage, MapsPage):
    def __init__(self, backend, config, config_path, data_dir, log_handler):
        super().__init__()
        self.backend, self.config, self.config_path, self.data_dir = backend, config, config_path, data_dir
        self.log_handler = log_handler
        self._quitting = False
        self._tray_hint_shown = False
        self._ticks = 0
        self._raw_urls = None
        self._qr_text = None
        self._import = None
        self._import_started = 0.0
        self._import_game = False
        self._cancel = threading.Event()
        self._game = None          # (install dir or None,) once looked up
        self._adapters = None      # windows_adapters(): hardware or not, network category; None until looked up
        self._adapters_busy = False
        self._adapters_new = False
        self._devices_shown = None
        self._had_device = False
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(app_icon())
        self.resize(1040, 720)
        self.setMinimumSize(880, 600)
        self.apply_theme()
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):          # Windows switched between light and dark
            hints.colorSchemeChanged.connect(lambda *_: self.apply_theme())

        central = QWidget()
        central.setObjectName("root")
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        # pages; their order in the stack is fixed (Connect 0, Settings 1, Maps 2, Log 3, About 4)
        status = self._status_strip()             # first: the Connect page shows three of its tiles
        self.tabs = QStackedWidget()
        self.connect_tab = self._connect_tab()
        self.settings_tab = self._settings_tab()
        self.maps_tab = self._maps_tab()
        self.log_tab = self._log_tab()
        self.about_tab = self._about_tab()
        for page in (self.connect_tab, self.settings_tab, self.maps_tab, self.log_tab, self.about_tab):
            self.tabs.addWidget(page)

        shell.addWidget(self._nav_rail())
        main = QVBoxLayout()
        main.setContentsMargins(24, 20, 24, 16)
        main.setSpacing(12)
        main.addLayout(status)
        # game version vs. the version the map files were made from (green when they match)
        self.sync_note = QLabel(visible=False)
        self.sync_note.setWordWrap(True)
        self.sync_note.linkActivated.connect(lambda _: self.update_map_files())
        main.addWidget(self.sync_note)
        main.addWidget(self.tabs, 1)
        shell.addLayout(main, 1)
        self.setCentralWidget(central)

        self.tabs.currentChanged.connect(self._page_changed)
        self._page_changed()

        self.tray = self._tray() if QSystemTrayIcon.isSystemTrayAvailable() else None
        self.timer = QTimer(self, interval=250, timeout=self.refresh)
        self.timer.start()
        self.refresh()
        self.refresh_sync()
        self._refresh_guide()

    def apply_theme(self, dark=None):
        """Light or dark, as Windows is set (or as asked): the style sheet, and the colour of links in texts."""
        dark = is_dark() if dark is None else dark
        self.setStyleSheet(style_sheet(dark))
        for owner in (QGuiApplication, self):             # labels with a style of their own take the application's palette
            palette = owner.palette()
            palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT[dark]))
            owner.setPalette(palette)

    def _nav_rail(self):
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(208)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(10, 18, 10, 14)
        layout.setSpacing(4)
        brand = QLabel(SHORT_NAME)
        brand.setObjectName("brand")
        layout.addWidget(brand)
        sub = QLabel("for Crimson Desert")
        sub.setObjectName("brandSub")
        layout.addWidget(sub)
        layout.addSpacing(14)
        self.nav = {}
        # the order people need them in; Ctrl+1..5 follow it
        entries = ((self.connect_tab, "", "Connect"), (self.maps_tab, "", "Maps"), (self.settings_tab, "", "Settings"),
                   (self.log_tab, "", "Activity"), (self.about_tab, "", "About"))
        for i, (page, glyph, label) in enumerate(entries, 1):
            button = NavButton(glyph, label)
            button.setToolTip(f"{label} (Ctrl+{i})")
            button.clicked.connect(lambda _=False, page=page: self.tabs.setCurrentWidget(page))
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, activated=lambda page=page: self.tabs.setCurrentWidget(page))
            self.nav[page] = button
            if page is self.log_tab:
                layout.addStretch()
            layout.addWidget(button)
        version = QLabel(f"Version {__version__}")
        version.setObjectName("brandSub")
        layout.addSpacing(6)
        layout.addWidget(version)
        return rail

    def _page_changed(self, _index=None):
        page = self.tabs.currentWidget()
        if page in self.nav:
            self.nav[page].setChecked(True)
        self.refresh_maps()
        if page is self.settings_tab:
            self.refresh_firewall()

    @staticmethod
    def _page(title, intro=None):
        """A scrolling page with a title: (the page for the stack, the layout to fill)."""
        body = QWidget()
        body.setObjectName("pageBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 4, 6, 8)
        layout.setSpacing(14)
        head = QLabel(title)
        head.setObjectName("pageTitle")
        layout.addWidget(head)
        if intro:
            text = QLabel(intro)
            text.setObjectName("muted")
            text.setWordWrap(True)
            layout.addWidget(text)
        scroll = QScrollArea()
        scroll.setObjectName("page")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)       # pages fit the width; they only scroll down
        scroll.setWidget(body)
        return scroll, layout

    def _status_strip(self):
        """Game, server and devices are always in view; position, realm and rate sit on the Connect page."""
        self.cards = {key: StatusCard(title) for key, title in (
            ("game", "Game"), ("server", "Server"), ("clients", "Devices"),
            ("pos", "Position  X / Y / Z"), ("realm", "Realm"), ("rate", "Updates"))}
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self.cards["game"], 3)
        row.addWidget(self.cards["server"], 2)
        row.addWidget(self.cards["clients"], 1)
        return row

    def _log_tab(self):
        tab, layout = self._page("Activity", "What the app has been doing. Attach the diagnostics to a bug report.")
        frame, box = panel()
        self.log_view = QPlainTextEdit(readOnly=True)
        self.log_view.setObjectName("log")
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setFont(QFont("Cascadia Mono, Consolas", 9))
        self.log_view.setPlainText("\n".join(self.log_handler.lines))
        self.log_view.setAccessibleName("Activity log")
        self.log_handler.signal.line.connect(self.log_view.appendPlainText)
        box.addWidget(self.log_view, 1)
        row = QHBoxLayout()
        row.addWidget(QPushButton("Copy diagnostics", clicked=self.copy_diagnostics))
        row.addWidget(QPushButton("Save diagnostics…", clicked=lambda: self.save_diagnostics()))
        row.addStretch()
        row.addWidget(QPushButton("Open log folder", clicked=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.data_dir / "logs")))))
        box.addLayout(row)
        layout.addWidget(frame, 1)
        return tab

    def _about_tab(self):
        tab, layout = self._page("About")
        frame, box = panel()
        text = QLabel(ABOUT.format(app=APP_NAME, version=__version__))
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setOpenExternalLinks(False)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        box.addWidget(text)
        row = QHBoxLayout()
        row.addWidget(QPushButton("Open data folder", clicked=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.data_dir)))))
        row.addStretch()
        box.addLayout(row)
        layout.addWidget(frame)
        layout.addStretch()
        return tab

    def _tray(self):
        tray = QSystemTrayIcon(app_icon(), self)
        menu = QMenu()
        menu.addAction(QAction(f"Open {SHORT_NAME}", self, triggered=self.bring_to_front))
        menu.addAction(QAction("Copy the map address", self, triggered=lambda: QGuiApplication.clipboard().setText(self.current_url())))
        menu.addSeparator()
        menu.addAction(QAction("Quit", self, triggered=self.quit_app))
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: reason in (QSystemTrayIcon.ActivationReason.Trigger,
                                                         QSystemTrayIcon.ActivationReason.DoubleClick) and self.bring_to_front())
        tray.show()
        return tray

    def refresh(self):
        snap = self.backend.snapshot()
        state = snap["engine"]
        if state is None:
            self.cards["game"].set("Starting…", "grey")
        else:
            text, color = GAME_TEXT.get(state.status, (state.status, "grey"))
            if state.status == ERROR and state.message:
                text = state.message
            elif state.status == ATTACHED and state.x is None:
                text, color = "Connected – waiting for the game world (loading or paused)", "amber"
            self.cards["game"].setToolTip(GAME_HELP.get(state.status, state.message or ""))
            version = snap["diagnostics"].get("game_version")
            if snap["simulated"]:
                text += " (simulator)"
            elif version and state.status == ATTACHED:
                text += f" · {version}"
            self.cards["game"].set(text, color)
        if snap["running"]:
            https = f", HTTPS {snap['https_port']}" if snap["https_port"] else ""
            self.cards["server"].set(f"Running on port {snap['port']}{https}", "green")
        else:
            self.cards["server"].set(snap["error"] or "Stopped", "red")
        self.cards["clients"].set(str(snap["clients"]), "green" if snap["clients"] else None)
        self._show_devices(snap.get("devices", []))
        if state is not None and state.x is not None:
            self.cards["pos"].set(f"{state.x:,.1f} / {state.y:,.1f} / {state.z:,.1f}")
            self.cards["realm"].set("Abyss" if state.realm == "abyss" else "Pywel")
        else:
            self.cards["pos"].set("–")
            self.cards["realm"].set("–")
        self.cards["rate"].set(f"{snap['rate']:.0f} / s")

        self._fill_urls(force=self._adapters_new)
        self.no_lan.setVisible(not snap["urls"])
        self._update_qr()
        self._ticks += 1
        if self._ticks % 20 == 0:         # every 5 s: another Wi-Fi, a VPN on or off
            self.refresh_network(auto=True)
        if self._ticks % 8 == 0:          # calibration done on a device shows up here too
            self.refresh_maps()
            self._refresh_guide()
        if self._ticks % 240 == 0:        # every minute: the game may have been patched meanwhile
            self.refresh_sync()
        if self.tray:
            self.tray.setToolTip(f"{SHORT_NAME} – {self.cards['game'].value.text().split('</span> ')[-1]}")





    def diagnostics(self):
        return support.diagnostics_text(self.backend.snapshot(), self.config, self.data_dir, self.backend.maps.list(),
                                        [MarkerStore.summary(s) for s in self.backend.markers.list()])

    def copy_diagnostics(self):
        QGuiApplication.clipboard().setText(self.diagnostics())
        log.info("Diagnostics copied to the clipboard")

    def save_diagnostics(self, path=None):
        """Diagnostics plus the recent log, as a text file to attach to a bug report."""
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Save diagnostics", str(Path.home() / "companionmap-diagnostics.txt"),
                                                  "Text files (*.txt)")
        if not path:
            return None
        text = self.diagnostics() + "\n\nRecent log:\n" + "\n".join(self.log_handler.lines)
        Path(path).write_text(text, encoding="utf-8")
        log.info("Diagnostics saved to %s", path)
        return path

    def _notify(self, text):
        """A Windows notification, when the window is not the one in front (a long import finished)."""
        if self.tray and not self.isActiveWindow():
            self.tray.showMessage(SHORT_NAME, text, QSystemTrayIcon.MessageIcon.Information, 5000)

    def bring_to_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self._quitting = True
        if self.tray:
            self.tray.hide()
        QGuiApplication.quit()

    def closeEvent(self, event):
        if self.tray and not self._quitting:
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage(SHORT_NAME, "Still running in the notification area. Right-click the icon to quit.",
                                      QSystemTrayIcon.MessageIcon.Information, 4000)
            return
        self._quitting = True
        event.accept()
        QGuiApplication.quit()


ABOUT = """<h2>{app} <span style="font-weight:normal">{version}</span></h2>
<p>Shows where you are in Crimson Desert on a live map on your tablet or phone, next to the game.
The map, markers and live position come from this PC; no internet connection is used.</p>
<p><b>How it works.</b> The app reads the player position from the game's memory, read-only. It never
writes player data or changes how the game behaves. The map, markers and marker icons are made from
your own game files and stay on this PC.</p>
<p><b>Privacy.</b> No accounts, no telemetry, no online services. Devices connect to this PC over your
local network only.</p>
<p><b>Unofficial.</b> A fan-made tool, not affiliated with or endorsed by Pearl Abyss.
Crimson Desert is a trademark of Pearl Abyss Corp. Use at your own risk.</p>
<p><b>Built with</b> Qt for Python (PySide6, LGPLv3), aiohttp (Apache 2.0), Pillow (MIT-CMU),
cryptography (Apache 2.0 / BSD), segno (BSD), pymem (MIT) and OpenLayers (BSD 2-Clause). The game-archive
reader follows formats documented by CrimsonDesertModdingTools and CDMW Archive Lite (MIT).</p>
"""
