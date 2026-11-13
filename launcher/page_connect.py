"""The Connect page: the address and its QR code, the first steps, connected devices, the network."""

import dataclasses
import threading
import time

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from launcher import support
from launcher.theme import COLORS
from launcher.widgets import panel
from server.netinfo import MDNS_NAME, default_route_ip


class ConnectPage:
    """Part of MainWindow (launcher/window.py): its methods use the window's own state."""

    def _connect_tab(self):
        tab, page = self._page("Connect")

        # first steps, until they are done or hidden
        self.guide, guide = panel("Get started")
        self.guide.setObjectName("guide")
        self.guide_steps = []
        for _ in range(3):
            line = QLabel()
            line.setWordWrap(True)
            line.setTextFormat(Qt.TextFormat.RichText)
            self.guide_steps.append(line)
            guide.addWidget(line)
        row = QHBoxLayout()
        self.guide_folder = QPushButton("Choose the game folder…", clicked=lambda: self.choose_game_dir())
        self.guide_import = QPushButton("Make the map", clicked=lambda: self.update_map_files())
        self.guide_import.setObjectName("primary")
        hide = QPushButton("Hide these steps", clicked=lambda: self.finish_guide())
        hide.setObjectName("link")
        row.addWidget(self.guide_folder)
        row.addWidget(self.guide_import)
        row.addStretch()
        row.addWidget(hide)
        guide.addLayout(row)
        page.addWidget(self.guide)

        hero, layout = panel()
        hero_row = QHBoxLayout()
        hero_row.setSpacing(24)
        layout.addLayout(hero_row)
        self.qr = QLabel()
        self.qr.setFixedSize(300, 300)
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setObjectName("qr")
        self.qr.setAccessibleName("QR code of the map address")
        hero_row.addWidget(self.qr, 0, Qt.AlignmentFlag.AlignTop)

        side = QVBoxLayout()
        side.setSpacing(8)
        heading = QLabel("Open the map on your tablet or phone")
        heading.setObjectName("heading")
        side.addWidget(heading)
        intro = QLabel("Scan the code with its camera, or type the address in its browser. "
                       "It must be on the same Wi-Fi or network as this PC.")
        intro.setWordWrap(True)
        side.addWidget(intro)
        self.url_label = QLabel()
        self.url_label.setObjectName("bigUrl")
        self.url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.url_label.setWordWrap(True)
        side.addWidget(self.url_label)
        buttons = QHBoxLayout()
        copy = QPushButton("Copy link", clicked=lambda: QGuiApplication.clipboard().setText(self.current_url()))
        copy.setObjectName("primary")
        copy.setToolTip("Copy the address to paste it into a message or another device")
        open_ = QPushButton("Open in browser",
                            clicked=lambda: QDesktopServices.openUrl(QUrl(self.current_url() or self.backend.local_url())))
        refresh = QPushButton("Refresh network", clicked=lambda: self.refresh_network())
        refresh.setToolTip("Look again for this PC's network addresses, after changing Wi-Fi or turning a VPN on or off. "
                           "This also happens by itself every few seconds.")
        buttons.addWidget(copy)
        buttons.addWidget(open_)
        buttons.addWidget(refresh)
        buttons.addStretch()
        side.addLayout(buttons)
        self.scheme = QComboBox()
        self.scheme.addItem("Standard connection (HTTP)", "http")
        self.scheme.addItem("Secure connection (HTTPS)", "https")
        self.scheme.setToolTip("HTTPS lets the device keep its screen awake. Each device has to trust this PC's "
                               "certificate once: see the setup page.")
        self.scheme.setAccessibleName("Connection type")
        self.scheme.currentIndexChanged.connect(lambda _: self._fill_urls(force=True))
        side.addWidget(self.scheme)
        self.url_combo = QComboBox()
        self.url_combo.setAccessibleName("Network address")
        self.url_combo.currentIndexChanged.connect(lambda _: self._update_qr())
        side.addWidget(self.url_combo)
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
        self.net_note = QLabel(visible=False)
        self.net_note.setObjectName("muted")
        self.net_note.setWordWrap(True)
        side.addWidget(self.net_note)
        tip = QLabel("Tip: add the page to the home screen for a full-screen app "
                     "(Safari: Share → Add to Home Screen; Chrome: menu → Add to Home screen).")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        side.addWidget(tip)
        side.addStretch()
        hero_row.addLayout(side, 1)
        page.addWidget(hero)

        lower = QHBoxLayout()
        lower.setSpacing(14)
        devices, layout = panel("Connected devices")
        self.devices = QLabel()
        self.devices.setObjectName("deviceList")
        self.devices.setWordWrap(True)
        self.devices.setTextFormat(Qt.TextFormat.RichText)
        self.devices.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.devices)
        layout.addStretch()
        lower.addWidget(devices, 1)
        live, layout = panel("Live position")
        for key in ("pos", "realm", "rate"):
            self.cards[key].setObjectName("stat")
            layout.addWidget(self.cards[key])
        layout.addStretch()
        lower.addWidget(live, 1)
        page.addLayout(lower)
        page.addStretch()
        return tab

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

    def _show_devices(self, devices):
        """Who is connected: a word for the device, its address, since when."""
        if devices:
            self._had_device = True
        key = tuple((d["ip"], d["agent"], int(d["since"])) for d in devices)
        if key == self._devices_shown:
            return
        self._devices_shown = key
        if not devices:
            self.devices.setText('<span style="color:gray">No device connected yet. Scan the code above with your tablet or phone.</span>')
            return
        self.devices.setText("<br>".join(
            f"<b>{d['agent']}</b> &nbsp;·&nbsp; {d['ip']} &nbsp;·&nbsp; since {time.strftime('%H:%M', time.localtime(d['since']))}"
            for d in devices))

    def _refresh_guide(self):
        """The "Get started" card on the Connect page: find the game, make the map, connect a device.
        It ticks the steps off by itself and goes away when all three are done (or when it is hidden)."""
        if self.config.setup_done:
            self.guide.setVisible(False)
            return
        game = self._game_dir() is not None
        has_map = any(m["source"] == "A" and m.get("fixed") for m in self.backend.maps.list())
        importing = bool(self._import and self._import.is_alive())
        steps = ((game, "Crimson Desert was found on this PC.", "Find Crimson Desert: choose the folder it is installed in."),
                 (has_map, "The map is made from your game files.",
                  "Making the map from your game files …" if importing else "Make the map from your game files (about a minute)."),
                 (self._had_device, "A tablet or phone is connected.", "Scan the code below with your tablet or phone."))
        for i, (label, (done, yes, todo)) in enumerate(zip(self.guide_steps, steps), 1):
            label.setText(f'<span style="color:{COLORS["green"]}">✓</span>&nbsp;&nbsp;{yes}' if done else f"<b>{i}.</b>&nbsp;&nbsp;{todo}")
        self.guide_folder.setVisible(not game)
        self.guide_import.setVisible(game and not has_map)
        self.guide_import.setEnabled(not importing)
        if game and has_map and self._had_device:
            self.finish_guide()
        else:
            self.guide.setVisible(True)

    def finish_guide(self):
        self.config = dataclasses.replace(self.config, setup_done=True)
        self.config.save(self.config_path)
        self.guide.setVisible(False)

    def _fill_urls(self, force=False):
        """The address list for the chosen connection; adapters are looked up only when addresses change."""
        self.scheme.setVisible(self.config.https)
        secure = self.secure()
        urls = self.backend.urls(secure)
        key = (tuple(urls), secure)
        if key == self._raw_urls and not force:
            return
        self._raw_urls = key
        self._adapters_new = False
        if self._adapters is None and not self._adapters_busy:
            self._lookup_adapters()
        adapters = support.adapter_names(self._adapters or {})
        shown, hidden = support.device_urls(urls, adapters, recommended_ip=default_route_ip())
        self.url_combo.blockSignals(True)
        self.url_combo.clear()
        for text, url in shown:
            self.url_combo.addItem(text, url)
        self.url_combo.blockSignals(False)
        self.url_combo.setVisible(self.url_combo.count() > 1)
        self.url_hint.setText(f"{hidden} address{'es' if hidden != 1 else ''} of virtual adapters and VPNs (VMware, "
                              "WSL, Hyper-V, VPN, …) hidden: other devices can't reach them. With a VPN on, allow "
                              "local network access in the VPN app if devices can't connect." if hidden else "")
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

    def _lookup_adapters(self):
        """Ask Windows which adapters are real hardware and which networks are Public (about 1 s, in the
        background); the address list is redrawn when the answer arrives."""
        self._adapters_busy = True

        def work():
            try:
                self._adapters = support.windows_adapters()
            except Exception:              # no adapter details: names alone decide
                self._adapters = self._adapters or {}
            finally:
                self._adapters_busy = False
                self._adapters_new = True
        threading.Thread(target=work, name="net-adapters", daemon=True).start()

    def refresh_network(self, auto=False):
        """Pick up a changed network: listen on the current addresses and look at the adapters again."""
        changed = self.backend.refresh_network()
        if changed or not auto:
            if not self._adapters_busy:
                self._lookup_adapters()
            self._raw_urls = None
        if changed:
            urls = ", ".join(u.split("//", 1)[-1].rstrip("/") for u in self.backend.urls()) or "no network address"
            self.net_note.setText(f"Network changed: now listening on {urls}. Connected devices reconnect by themselves.")
        elif not auto:
            self.net_note.setText("Network checked: no change.")
        if changed or not auto:
            self.net_note.setVisible(True)
            QTimer.singleShot(8000, lambda: self.net_note.setVisible(False))
        return changed

    def _check_network(self, adapters):
        """Warn when the recommended network is a Windows "Public" network (the firewall rule covers Private ones)."""
        names = {name for name, kind in adapters.values() if kind != "virtual"}
        public = sorted(n for n in names if (self._adapters or {}).get(n, {}).get("category") == "Public")
        self.net_warn.setText(
            f"Windows treats “{', '.join(public)}” as a <b>public</b> network, so it may block other devices. On your "
            "home network, set it to Private: <a href='ms-settings:network-status'>Network settings</a> → the network → "
            "Network profile type → Private." if public else "")
        self.net_warn.setVisible(bool(public))
