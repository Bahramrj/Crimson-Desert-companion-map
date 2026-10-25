"""Main window: status strip, Connect / Settings / Maps / Log / About tabs, tray icon."""

import dataclasses
import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QSystemTrayIcon, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget,
)

from engine.models import AOB_NOT_FOUND, ATTACHED, ERROR, WAITING_FOR_GAME
from gamedata import Archive, ArchiveError, find_install, resolve_install
from gamedata import markers, worldmap
from launcher import support
from mapstore import SOURCES, MapError, NotFound
from mapstore.marker_import import read_marker_file
from mapstore.markers import MarkerStore
from mapstore.store import summary
from server import APP_NAME, EXE_NAME, SHORT_NAME, __version__
from server.app import WEB_DIR
from server.netinfo import MDNS_NAME, default_route_ip

log = logging.getLogger("cdlivemap.launcher")

COLORS = {"green": "#22c55e", "amber": "#f59e0b", "red": "#ef4444", "grey": "#6b7280"}
GAME_TEXT = {WAITING_FOR_GAME: ("Waiting for Crimson Desert", "amber"), ATTACHED: ("Connected", "green"),
             AOB_NOT_FOUND: ("This game version is not supported yet", "red"), ERROR: ("Error", "red")}
GAME_HELP = {
    WAITING_FOR_GAME: "Start Crimson Desert; the live position appears as soon as you are in the game world.",
    AOB_NOT_FOUND: ("The game was updated and its live position can't be read until this app is updated. "
                    "Maps and markers keep working."),
}
RESTART_FIELDS = ("port", "rate_hz", "https", "https_port", "mdns")
REALM_LABEL = {"pywel": "Pywel", "abyss": "Abyss"}
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp)"
MARKER_FILTER = "Marker files (*.csv *.geojson *.json)"


def app_icon():
    path = WEB_DIR / "dist" / "icon-512.png"
    return QIcon(str(path)) if path.exists() else QIcon()


class StatusCard(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("card")
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.value = QLabel("–")
        self.value.setObjectName("cardValue")
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        layout.addWidget(self.title)
        layout.addWidget(self.value)

    def set(self, text, color=None):
        dot = f'<span style="color:{COLORS[color]}">●</span> ' if color else ""
        self.value.setText(f"{dot}{text}")


class MainWindow(QMainWindow):
    def __init__(self, backend, config, config_path, data_dir, log_handler):
        super().__init__()
        self.backend, self.config, self.config_path, self.data_dir = backend, config, config_path, data_dir
        self.log_handler = log_handler
        self._quitting = False
        self._tray_hint_shown = False
        self._ticks = 0
        self._raw_urls = None
        self._qr_text = None
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(app_icon())
        self.resize(820, 620)
        self.setStyleSheet(STYLE)

        central = QWidget()
        root = QVBoxLayout(central)
        root.addLayout(self._status_strip())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._connect_tab(), "Connect")
        self.settings_tab = self._settings_tab()
        self.tabs.addTab(self.settings_tab, "Settings")
        self.maps_tab = self._maps_tab()
        self.tabs.addTab(self.maps_tab, "Maps")
        self.tabs.addTab(self._log_tab(), "Log")
        self.tabs.addTab(self._about_tab(), "About")
        self.tabs.currentChanged.connect(lambda _: self.refresh_maps())
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget() is self.settings_tab and self.refresh_firewall())
        self._import = None
        self._game = None          # (install dir or None,) once looked up
        self._categories = {}      # adapter name -> Windows network category (looked up in the background)
        self._categories_for = None
        root.addWidget(self.tabs)
        self.setCentralWidget(central)

        self.tray = self._tray() if QSystemTrayIcon.isSystemTrayAvailable() else None
        self.timer = QTimer(self, interval=250, timeout=self.refresh)
        self.timer.start()
        self.refresh()

    # ── status strip ────────────────────────────────────────────────

    def _status_strip(self):
        grid = QGridLayout()
        grid.setSpacing(8)
        self.cards = {key: StatusCard(title) for key, title in (
            ("game", "Game"), ("server", "Server"), ("clients", "Clients"),
            ("pos", "X / Y / Z"), ("realm", "Realm"), ("rate", "Update rate"))}
        for i, card in enumerate(self.cards.values()):
            grid.addWidget(card, i // 3, i % 3)
        return grid

    # ── tabs ────────────────────────────────────────────────────────

    def _connect_tab(self):
        tab = QWidget()
        layout = QHBoxLayout(tab)
        self.qr = QLabel()
        self.qr.setFixedSize(300, 300)
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setObjectName("qr")
        layout.addWidget(self.qr, 0, Qt.AlignmentFlag.AlignTop)

        side = QVBoxLayout()
        intro = QLabel("<b>Open the map on your tablet or phone</b><br>Scan the code with its camera, or type the "
                       "address in its browser. It must be on the same Wi-Fi or network as this PC.")
        intro.setWordWrap(True)
        side.addWidget(intro)
        self.scheme = QComboBox()
        self.scheme.addItem("Standard connection (HTTP)", "http")
        self.scheme.addItem("Secure connection (HTTPS)", "https")
        self.scheme.setToolTip("HTTPS lets the device keep its screen awake. Each device has to trust this PC's "
                               "certificate once: see the setup page.")
        self.scheme.currentIndexChanged.connect(lambda _: self._fill_urls(force=True))
        side.addWidget(self.scheme)
        self.url_combo = QComboBox()
        self.url_combo.currentIndexChanged.connect(lambda _: self._update_qr())
        side.addWidget(self.url_combo)
        self.url_label = QLabel()
        self.url_label.setObjectName("bigUrl")
        self.url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.url_label.setWordWrap(True)
        side.addWidget(self.url_label)
        buttons = QHBoxLayout()
        copy = QPushButton("Copy link", clicked=lambda: QGuiApplication.clipboard().setText(self.current_url()))
        open_ = QPushButton("Open in browser",
                            clicked=lambda: QDesktopServices.openUrl(QUrl(self.current_url() or self.backend.local_url())))
        buttons.addWidget(copy)
        buttons.addWidget(open_)
        buttons.addStretch()
        side.addLayout(buttons)
        self.name_hint = QLabel()
        self.name_hint.setObjectName("muted")
        self.name_hint.setWordWrap(True)
        self.name_hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        side.addWidget(self.name_hint)
        self.https_hint = QLabel()
        self.https_hint.setWordWrap(True)
        self.https_hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setup_qr = QPushButton("Show the setup code", checkable=True, toggled=lambda _: self._update_qr())
        side.addWidget(self.https_hint)
        side.addWidget(self.setup_qr, 0, Qt.AlignmentFlag.AlignLeft)
        tip = QLabel("Tip: add the page to the home screen for a full-screen app "
                     "(Safari: Share → Add to Home Screen; Chrome: menu → Add to Home screen).")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        side.addWidget(tip)
        self.net_warn = QLabel(visible=False)
        self.net_warn.setObjectName("warn")
        self.net_warn.setWordWrap(True)
        self.net_warn.setOpenExternalLinks(False)
        self.net_warn.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        side.addWidget(self.net_warn)
        self.url_hint = QLabel(visible=False)
        self.url_hint.setObjectName("muted")
        self.url_hint.setWordWrap(True)
        side.addWidget(self.url_hint)
        self.no_lan = QLabel("No Wi-Fi or network address found. Connect this PC to your network, then press "
                             "Apply in Settings.")
        self.no_lan.setObjectName("warn")
        self.no_lan.setWordWrap(True)
        side.addWidget(self.no_lan)
        side.addStretch()
        layout.addLayout(side, 1)
        return tab

    def _settings_tab(self):
        tab = QWidget()
        outer = QVBoxLayout(tab)
        c = self.config

        network = QGroupBox("Network")
        form = QFormLayout(network)
        self.f_port = QSpinBox(minimum=1024, maximum=65535, value=c.port)
        self.f_https = QCheckBox("Also serve HTTPS (secure connection)", checked=c.https)
        self.f_https.setToolTip("The standard HTTP address keeps working. HTTPS lets devices keep the screen awake.")
        self.f_https_port = QSpinBox(minimum=1024, maximum=65535, value=c.https_port)
        self.f_mdns = QCheckBox(f"Also reachable as {MDNS_NAME}", checked=c.mdns)
        self.f_mdns.setToolTip("Devices can open the map by this name instead of the PC's address (works on most "
                               "Apple devices and recent Android).")
        self.fw_status = QLabel()
        self.fw_status.setWordWrap(True)
        self.fw_button = QPushButton("Allow in Windows Firewall", clicked=lambda: self.toggle_firewall())
        fw_row = QHBoxLayout()
        fw_row.addWidget(self.fw_status, 1)
        fw_row.addWidget(self.fw_button)
        form.addRow("Port (HTTP)", self.f_port)
        form.addRow("", self.f_https)
        form.addRow("HTTPS port", self.f_https_port)
        form.addRow("Name", self.f_mdns)
        form.addRow("Firewall", fw_row)
        outer.addWidget(network)

        live = QGroupBox("Live position")
        form = QFormLayout(live)
        self.f_rate = QSpinBox(minimum=10, maximum=60, value=c.rate_hz, suffix=" updates / s")
        self.f_rate.setToolTip("How often the player position is sent to devices. Lower it on a slow network.")
        form.addRow("Update rate", self.f_rate)
        outer.addWidget(live)

        startup = QGroupBox("Startup")
        form = QFormLayout(startup)
        self.f_autostart = QCheckBox("Start with Windows", checked=support.autostart_enabled(),
                                     enabled=support.autostart_supported())
        if not support.autostart_supported():
            self.f_autostart.setToolTip(f"Available in the installed {EXE_NAME}.exe")
        self.f_minimized = QCheckBox("Start minimised to the tray", checked=c.start_minimized)
        form.addRow(self.f_autostart)
        form.addRow(self.f_minimized)
        outer.addWidget(startup)

        apply = QPushButton("Apply", clicked=self.apply_settings)
        apply.setObjectName("primary")
        revert = QPushButton("Revert", clicked=self._load_settings)
        row = QHBoxLayout()
        row.addWidget(apply)
        row.addWidget(revert)
        row.addStretch()
        outer.addLayout(row)
        self.settings_note = QLabel()
        self.settings_note.setWordWrap(True)
        outer.addWidget(self.settings_note)
        outer.addStretch()
        return tab

    def _maps_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Maps are kept on this PC only. Import the map from your "
                                "Crimson Desert install, or import an image and calibrate it on the device (Settings → Map)."))
        game_row = QHBoxLayout()
        self.m_game = QLabel()
        self.m_game.setWordWrap(True)
        self.m_game_import = QPushButton("Import from game files", clicked=lambda: self.import_game())
        self.m_game_import.setObjectName("primary")
        self.m_quality = QComboBox()
        self.m_quality.addItem("Default quality (16 384 px, ~2 min)", "default")
        self.m_quality.addItem("High resolution (Pywel 32 768 px, ~5 min, ~3x disk)", "high")
        self.m_quality.setCurrentIndex(max(0, self.m_quality.findData(self.config.map_quality)))
        self.m_quality.setToolTip("High resolution keeps roads and coasts sharp when zoomed in close. "
                                  "Re-import to switch; the previous game map is replaced.")
        self.m_quality.currentIndexChanged.connect(lambda _: self._save_quality())
        self.m_game_dir = QPushButton("Game folder…", clicked=lambda: self.choose_game_dir())
        self.m_game_dir.setToolTip("Pick the Crimson Desert folder if it is not in a Steam library this PC knows about.")
        self.m_game_auto = QPushButton("Find via Steam", clicked=lambda: self.set_game_dir(""))
        self.m_game_auto.setToolTip("Forget the chosen folder and look for the game in the Steam libraries again.")
        game_row.addWidget(self.m_game, 1)
        game_row.addWidget(self.m_game_dir)
        game_row.addWidget(self.m_game_auto)
        game_row.addWidget(self.m_quality)
        game_row.addWidget(self.m_game_import)
        layout.addLayout(game_row)
        self.m_table = QTableWidget(0, 6)
        self.m_table.setHorizontalHeaderLabels(["Name", "Realm", "Source", "Size", "Placement", "Shown"])
        self.m_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.m_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.m_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.m_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.m_table)
        self.m_progress = QProgressBar(visible=False)
        layout.addWidget(self.m_progress)
        row = QHBoxLayout()
        self.m_import = QPushButton("Import image…", clicked=self.choose_import)
        row.addWidget(self.m_import)
        row.addWidget(QPushButton("Import markers…", clicked=self.choose_marker_import))
        row.addWidget(QPushButton("Show this map", clicked=self.activate_selected_map))
        row.addWidget(QPushButton("Delete", clicked=lambda: self.delete_selected_map()))
        row.addWidget(QPushButton("Open maps folder", clicked=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.backend.maps.root)))))
        row.addStretch()
        layout.addLayout(row)
        self.m_note = QLabel()
        self.m_note.setWordWrap(True)
        layout.addWidget(self.m_note)
        return tab

    def _log_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.log_view = QPlainTextEdit(readOnly=True)
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setFont(QFont("Consolas", 9))
        self.log_view.setPlainText("\n".join(self.log_handler.lines))
        self.log_handler.signal.line.connect(self.log_view.appendPlainText)
        layout.addWidget(self.log_view)
        row = QHBoxLayout()
        row.addWidget(QPushButton("Open log folder", clicked=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.data_dir / "logs")))))
        row.addWidget(QPushButton("Copy diagnostics", clicked=self.copy_diagnostics))
        row.addWidget(QPushButton("Save diagnostics…", clicked=lambda: self.save_diagnostics()))
        row.addStretch()
        layout.addLayout(row)
        return tab

    def _about_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        text = QLabel(ABOUT.format(app=APP_NAME, version=__version__))
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setOpenExternalLinks(False)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(text)
        row = QHBoxLayout()
        row.addWidget(QPushButton("Open data folder", clicked=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.data_dir)))))
        row.addStretch()
        layout.addLayout(row)
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

    # ── behaviour ───────────────────────────────────────────────────

    def current_url(self):
        return self.url_combo.currentData() or ""

    def secure(self):
        return self.config.https and self.scheme.currentData() == "https"

    def setup_url(self):
        """The HTTPS setup page, on the plain address of the chosen network (works before the certificate is trusted)."""
        url = self.current_url()
        host = url.split("//", 1)[-1].split(":", 1)[0] if url else ""
        return self.backend.setup_url(host) if host and host != MDNS_NAME else ""

    def _update_qr(self):
        url = self.current_url()
        self.url_label.setText(url or self.backend.local_url() + "  (this PC only)")
        if self.setup_qr.isChecked() and self.setup_url():
            url = self.setup_url()
        if url != self._qr_text:
            self._qr_text = url
            if url:
                self.qr.setPixmap(support.qr_pixmap(url, 290))
            else:
                self.qr.clear()
                self.qr.setText("No LAN address")

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
        self.cards["clients"].set(str(snap["clients"]))
        if state is not None and state.x is not None:
            self.cards["pos"].set(f"{state.x:,.1f} / {state.y:,.1f} / {state.z:,.1f}")
            self.cards["realm"].set("Abyss" if state.realm == "abyss" else "Pywel")
        else:
            self.cards["pos"].set("–")
            self.cards["realm"].set("–")
        self.cards["rate"].set(f"{snap['rate']:.0f} / s")

        self._fill_urls()
        self.no_lan.setVisible(not snap["urls"])
        self._update_qr()
        self._ticks += 1
        if self._ticks % 8 == 0:          # calibration done on a device shows up here too
            self.refresh_maps()
        if self.tray:
            self.tray.setToolTip(f"{SHORT_NAME} – {self.cards['game'].value.text().split('</span> ')[-1]}")

    def _fill_urls(self, force=False):
        """The address list for the chosen connection; adapters are looked up only when addresses change."""
        self.scheme.setVisible(self.config.https)
        secure = self.secure()
        urls = self.backend.urls(secure)
        key = (tuple(urls), secure)
        if key == self._raw_urls and not force:
            return
        self._raw_urls = key
        adapters = support.adapter_names()
        shown, hidden = support.device_urls(urls, adapters, recommended_ip=default_route_ip())
        self.url_combo.blockSignals(True)
        self.url_combo.clear()
        for text, url in shown:
            self.url_combo.addItem(text, url)
        self.url_combo.blockSignals(False)
        self.url_combo.setVisible(self.url_combo.count() > 1)
        self.url_hint.setText(f"{hidden} address{'es' if hidden != 1 else ''} of virtual adapters (VMware, WSL, "
                              "Hyper-V, VPN, …) hidden: other devices can't reach them." if hidden else "")
        self.url_hint.setVisible(bool(hidden))
        name = self.backend.name_url(secure)
        self.name_hint.setText(f"Also by name on most devices: {name}" if name else "")
        self.name_hint.setVisible(bool(name))
        setup = self.setup_url()
        self.https_hint.setText(f"<b>First time on a device?</b> Open <b>{setup}</b> on it (or scan the setup code) and "
                                "follow the steps to trust this PC's certificate." if secure and setup else "")
        self.https_hint.setVisible(bool(secure and setup))
        self.setup_qr.setVisible(bool(secure and setup))
        if not (secure and setup):
            self.setup_qr.setChecked(False)
        self._check_network(adapters)

    def _check_network(self, adapters):
        """Warn when the recommended network is a Windows "Public" network (the firewall rule covers Private ones)."""
        names = {name for name, kind in adapters.values() if kind != "virtual"}
        if names != self._categories_for:
            self._categories_for = names
            threading.Thread(target=lambda: setattr(self, "_categories", support.network_categories()),
                             name="net-categories", daemon=True).start()
        public = sorted(n for n in names if self._categories.get(n) == "Public")
        self.net_warn.setText(
            f"Windows treats “{', '.join(public)}” as a <b>public</b> network, so it may block other devices. On your "
            "home network, set it to Private: <a href='ms-settings:network-status'>Network settings</a> → the network → "
            "Network profile type → Private." if public else "")
        self.net_warn.setVisible(bool(public))

    def refresh_firewall(self):
        """Show whether Windows Firewall lets devices in (only checked when the Settings tab is shown)."""
        ports = support.firewall_rule_ports()
        tcp, udp = support.firewall_ports(self.config)
        if ports is None:
            self.fw_status.setText("No rule yet. Windows may ask on first use, or block devices silently.")
            self.fw_button.setText("Allow in Windows Firewall")
        elif ports and not set(tcp + udp) <= ports:
            self.fw_status.setText("The rule is out of date (ports changed).")
            self.fw_button.setText("Update the firewall rule")
        else:
            self.fw_status.setText("Allowed on private (home) networks.")
            self.fw_button.setText("Remove the firewall rule")
        self._fw_allowed = ports is not None and (not ports or set(tcp + udp) <= ports)

    def toggle_firewall(self, remove=None):
        remove = getattr(self, "_fw_allowed", False) if remove is None else remove
        try:
            if remove:
                support.remove_firewall()
                log.info("Firewall rule removed")
            else:
                support.set_firewall(self.config)
                log.info("Firewall rule added for ports %s", support.firewall_ports(self.config))
        except OSError as e:
            QMessageBox.warning(self, "Windows Firewall", f"Could not change the firewall rule:\n{e}")
        self.refresh_firewall()

    def _load_settings(self):
        c = self.config
        self.f_port.setValue(c.port)
        self.f_https.setChecked(c.https)
        self.f_https_port.setValue(c.https_port)
        self.f_mdns.setChecked(c.mdns)
        self.f_rate.setValue(c.rate_hz)
        self.f_minimized.setChecked(c.start_minimized)
        self.f_autostart.setChecked(support.autostart_enabled())
        self.settings_note.clear()

    def apply_settings(self):
        new = dataclasses.replace(
            self.config, port=self.f_port.value(), rate_hz=self.f_rate.value(), https=self.f_https.isChecked(),
            https_port=self.f_https_port.value(), mdns=self.f_mdns.isChecked(),
            start_minimized=self.f_minimized.isChecked())
        try:
            new.validate()
        except ValueError as e:
            QMessageBox.warning(self, "Settings", str(e)[:1].upper() + str(e)[1:])
            return False
        if support.autostart_supported() and self.f_autostart.isChecked() != support.autostart_enabled():
            try:
                support.set_autostart(self.f_autostart.isChecked())
            except OSError as e:
                QMessageBox.warning(self, "Start with Windows", str(e))
        restart = any(getattr(new, f) != getattr(self.config, f) for f in RESTART_FIELDS) or not self.backend.app
        new.save(self.config_path)
        self.config = new
        if restart:
            self.settings_note.setText("Restarting the server…")
            QGuiApplication.processEvents()
            self.backend.restart(new)
            log.info("Settings applied; server restarted")
        snap = self.backend.snapshot()
        self.settings_note.setText(snap["error"] or "Saved." + (" Server restarted." if restart else ""))
        self.refresh()
        return True

    # ── maps ────────────────────────────────────────────────────────

    def refresh_maps(self):
        if self.tabs.currentWidget() is not self.maps_tab:
            return
        maps, active = self.backend.maps.list(), self.backend.maps.active()
        text, can_import = self._game_status(maps)
        self.m_game.setText(text)
        self.m_game_auto.setVisible(bool(self.config.game_dir))
        if not (self._import and self._import.is_alive()):
            self.m_game_import.setEnabled(can_import)
        self.m_table.setRowCount(len(maps))
        for row, m in enumerate(maps):
            if m.get("fixed"):
                placement = "exact (game data)"
            elif len(m["calibration"]) >= 2:
                placement = f"{len(m['calibration'])} points · error {summary(m)['errorM']:.1f} m"
            else:
                placement = f"not calibrated ({len(m['calibration'])} of 2+ points)"
            cells = (m["name"], REALM_LABEL[m["realm"]], SOURCES[m['source']].capitalize(),
                     f"{m['image'][0]} × {m['image'][1]}", placement, "yes" if active.get(m["realm"]) == m["id"] else "")
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, m["id"])
                if m["licence"]:
                    item.setToolTip(f"Source / licence note: {m['licence']}")
                self.m_table.setItem(row, col, item)
        if not maps:
            self.m_note.setText("No map imported yet: devices show a coordinate grid with the live arrow.")

    def _selected_map(self):
        row = self.m_table.currentRow()
        item = self.m_table.item(row, 0) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def choose_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import map image", "", IMAGE_FILTER)
        if not path:
            return
        dialog = ImportDialog(self, path)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.import_map(path, **dialog.values())

    def import_map(self, path, realm, name="", source="C", licence="", wait=False):
        """Tile an image on a worker thread; the table refreshes when it is done."""
        return self._start_import(f"Importing {path} …", lambda progress: [self.backend.maps.import_image(
            path, realm, name=name or None, source=source, licence=licence, progress=progress)], wait)

    def _save_quality(self):
        self.config = dataclasses.replace(self.config, map_quality=self.m_quality.currentData())
        self.config.save(self.config_path)

    def import_game(self, wait=False):
        """Render Pywel and the Abyss from the game's own map layers (read-only), replacing the last game import."""
        game = self._game_dir()
        if game is None:
            self.m_note.setText("Crimson Desert install not found.")
            return None

        quality = self.m_quality.currentData()

        def job(progress):
            archive = Archive(game)
            sets, failures = markers.import_markers(archive, self.backend.markers)
            for f in failures:
                log.warning("Marker import: %s", f)
            log.info("Imported marker sets: %s", ", ".join(f"{s['id']} ({s['count']})" for s in sets))
            self.backend.notify_markers()
            results = []
            for i, realm in enumerate(("pywel", "abyss")):
                summary, failures = worldmap.import_basemap(
                    archive, self.backend.maps, realm, worldmap.scale_for(quality, realm),
                    progress=lambda d, t, i=i: progress(i * 1000 + 1000 * d // t, 2000))
                if failures:
                    log.warning("%s: %d map tiles could not be read", realm, len(failures))
                results.append(summary)
            return results
        return self._start_import("Rendering the world map from your game files (about 2 minutes) …", job, wait)

    def _start_import(self, note, job, wait):
        if self._import and self._import.is_alive():
            self.m_note.setText("An import is already running.")
            return None
        signals = _ImportSignals(self)
        signals.progress.connect(self._import_progress)
        signals.finished.connect(self._import_finished)
        self.m_progress.setValue(0)
        self.m_progress.setVisible(True)
        self.m_import.setEnabled(False)
        self.m_game_import.setEnabled(False)
        self.m_note.setText(note)

        def work():
            try:
                signals.finished.emit(job(signals.progress.emit), "")
            except Exception as e:   # MapError, ArchiveError, OSError, and whatever Pillow raises for a bad image
                log.warning("Map import failed: %s", e)
                signals.finished.emit([], str(e) or type(e).__name__)

        self._import = threading.Thread(target=work, name="map-import", daemon=True)
        self._import.start()
        if wait:
            self._import.join()
            QGuiApplication.processEvents()
        return self._import

    def _import_progress(self, done, total):
        self.m_progress.setMaximum(total)
        self.m_progress.setValue(done)

    def _import_finished(self, results, error):
        self.m_progress.setVisible(False)
        self.m_import.setEnabled(True)
        self.m_game_import.setEnabled(self._game_dir() is not None)
        if error:
            self.m_note.setText(f"Import failed: {error}")
            return
        for result in results:
            log.info("Imported map %s (%dx%d)", result["id"], *result["image"])
            self.backend.notify_maps(result["id"], "imported")
        if len(results) == 1 and not results[0]["fixed"]:
            r = results[0]
            self.m_note.setText(f"Imported “{r['name']}”, now shown for {REALM_LABEL[r['realm']]}. "
                                "Calibrate it on your device: Settings → Map → Add point.")
        else:
            self.m_note.setText("Imported " + ", ".join(f"“{r['name']}”" for r in results)
                                + ": placed exactly from the game data, no calibration needed.")
        self.refresh_maps()

    # ── game install ────────────────────────────────────────────────

    def _game_dir(self):
        if self._game is None:
            self._game = (find_install(self.config.game_dir or None),)
        return self._game[0]

    def choose_game_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Crimson Desert folder", self.config.game_dir or "")
        if not path:
            return False
        game = resolve_install(path)
        if game is None:
            QMessageBox.warning(self, "Game folder", f"{path} is not a Crimson Desert install.\n\n"
                                "Pick the folder that holds the game's numbered data folders and “meta”, "
                                "for example …\\steamapps\\common\\Crimson Desert.")
            return False
        return self.set_game_dir(str(game))

    def set_game_dir(self, path):
        """Use this install folder for imports ("" = find it via Steam); saved in config.json."""
        self.config = dataclasses.replace(self.config, game_dir=path)
        self.config.save(self.config_path)
        self._game = None
        log.info("Game folder: %s", path or "find via Steam")
        self.refresh_maps()
        return True

    def _game_status(self, maps):
        game = self._game_dir()
        if game is None:
            if self.config.game_dir:
                return (f"No Crimson Desert install at {self.config.game_dir}. Pick another game folder, "
                        "or find it via Steam."), False
            return ("Crimson Desert install not found in the Steam libraries. Use “Game folder…” to pick it; "
                    "map images can still be imported."), False
        try:
            version = Archive(game).version()
        except (ArchiveError, OSError) as e:
            return f"Crimson Desert install unreadable: {e}", False
        self.m_game.setToolTip(f"Game folder: {game}")
        imported = {m["gameVersion"] for m in maps if m["source"] == "A" and m.get("fixed")}
        if not imported:
            return (f"Crimson Desert {version} found at {game}. Import its world map for an exact, "
                    "calibration-free map."), True
        if imported != {version}:
            return (f"<b>Game updated</b> to {version} (maps are from {', '.join(sorted(v or '?' for v in imported))}): "
                    "re-import from game files."), True
        return f"Crimson Desert {version}: game map up to date.", True

    def choose_marker_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import markers", "", MARKER_FILTER)
        if not path:
            return
        dialog = ImportDialog(self, path, title="Import markers")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.import_markers(path, **dialog.values())

    def import_markers(self, path, realm, name="", source="C", licence=""):
        """A marker set from CSV / GeoJSON / JSON (game x/z); quick, so it runs here."""
        try:
            data = read_marker_file(path, name or Path(path).stem, source, licence, realm)
            s = self.backend.markers.save(data)
        except (MapError, OSError, ValueError) as e:
            self.m_note.setText(f"Marker import failed: {e}")
            return None
        log.info("Imported marker set %s (%d markers)", s["id"], s["count"])
        self.backend.notify_markers()
        self.m_note.setText(f"Imported {s['count']} markers as “{s['name']}”; they show on connected devices now.")
        return s

    def activate_selected_map(self):
        map_id = self._selected_map()
        if not map_id:
            return
        try:
            self.backend.maps.set_active(self.backend.maps.get(map_id)["realm"], map_id)
        except (MapError, NotFound) as e:
            self.m_note.setText(str(e))
            return
        self.backend.notify_maps(map_id, "active")
        self.refresh_maps()

    def delete_selected_map(self, confirm=True):
        map_id = self._selected_map()
        if not map_id:
            return
        if confirm and QMessageBox.question(self, "Maps", f"Delete map {map_id} and its tiles?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.backend.maps.delete(map_id)
        except (NotFound, OSError) as e:
            self.m_note.setText(f"Delete failed: {e}")
            return
        log.info("Deleted map %s", map_id)
        self.backend.notify_maps(map_id, "deleted")
        self.refresh_maps()

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


class _ImportSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(object, str)


class ImportDialog(QDialog):
    """Name, realm, source and licence note for an imported image (every map records its source)."""

    def __init__(self, parent, path, title="Import map image"):
        super().__init__(parent)
        self.setWindowTitle(title)
        form = QFormLayout(self)
        form.addRow("File", QLabel(path))
        self.name = QLineEdit(placeholderText="e.g. Pywel full map", maxLength=60)
        self.realm = QComboBox()
        for key, label in REALM_LABEL.items():
            self.realm.addItem(label, key)
        self.source = QComboBox()
        self.source.addItem("Own screenshot / capture", "C")
        self.source.addItem("Downloaded (needs a licence note)", "B")
        self.licence = QLineEdit(placeholderText="where it came from and what its licence allows", maxLength=300)
        form.addRow("Name", self.name)
        form.addRow("Realm", self.realm)
        form.addRow("Source", self.source)
        form.addRow("Licence note", self.licence)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept(self):
        if self.source.currentData() == "B" and not self.licence.text().strip():
            QMessageBox.warning(self, "Import map image", "Downloaded maps need a licence note.")
            return
        self.accept()

    def values(self):
        return {"realm": self.realm.currentData(), "name": self.name.text().strip(),
                "source": self.source.currentData(), "licence": self.licence.text().strip()}


ABOUT = """<h2>{app} <span style="font-weight:normal">{version}</span></h2>
<p>Shows where you are in Crimson Desert on a live map on your tablet or phone, next to the game.
The map, markers and live position come from this PC; no internet connection is used.</p>
<p><b>How it works.</b> The app reads the player position from the game's memory, read-only. It never
writes player data or changes how the game behaves. The map and markers are made from your own game
files and stay on this PC.</p>
<p><b>Privacy.</b> No accounts, no telemetry, no online services. Devices connect to this PC over your
local network only.</p>
<p><b>Unofficial.</b> A fan-made tool, not affiliated with or endorsed by Pearl Abyss.
Crimson Desert is a trademark of Pearl Abyss Corp. Use at your own risk.</p>
<p><b>Built with</b> Qt for Python (PySide6, LGPLv3), aiohttp (Apache 2.0), Pillow (MIT-CMU),
cryptography (Apache 2.0 / BSD), segno (BSD), pymem (MIT) and OpenLayers (BSD 2-Clause). The game-archive
reader follows formats documented by CrimsonDesertModdingTools and CDMW Archive Lite (MIT).</p>
"""

STYLE = """
QMainWindow, QWidget { font-size: 10pt; }
#card { background: palette(base); border: 1px solid palette(mid); border-radius: 8px; }
#cardTitle { color: palette(placeholder-text); font-size: 8pt; text-transform: uppercase; }
#cardValue { font-size: 11pt; font-weight: 600; }
#bigUrl { font-size: 18pt; font-weight: 700; padding: 8px 0; }
#qr { background: white; border: 1px solid palette(mid); border-radius: 8px; }
#warn { color: #b45309; }
#muted { color: palette(placeholder-text); font-size: 9pt; }
QPushButton { padding: 6px 14px; }
QPushButton#primary { font-weight: 700; }
"""
