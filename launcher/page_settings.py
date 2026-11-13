"""The Settings page: ports, HTTPS, the name on the network, the firewall rule, startup."""

import logging
import dataclasses

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox
from launcher import support
from launcher.widgets import RESTART_FIELDS, panel
from server import EXE_NAME
from server.netinfo import MDNS_NAME

log = logging.getLogger("cdlivemap.launcher")


class SettingsPage:
    """Part of MainWindow (launcher/window.py): its methods use the window's own state."""

    def _settings_tab(self):
        tab, outer = self._page("Settings")
        c = self.config

        network, box = panel("Network", "How tablets and phones reach this PC.")
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        box.addLayout(form)
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

        live, box = panel("Live position")
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        box.addLayout(form)
        self.f_rate = QSpinBox(minimum=10, maximum=60, value=c.rate_hz, suffix=" updates / s")
        for field in (self.f_port, self.f_https_port, self.f_rate):
            field.setMaximumWidth(190)
        self.f_rate.setToolTip("How often the player position is sent to devices. Lower it on a slow network.")
        form.addRow("Update rate", self.f_rate)
        outer.addWidget(live)

        startup, box = panel("Startup")
        self.f_autostart = QCheckBox("Start with Windows", checked=support.autostart_enabled(),
                                     enabled=support.autostart_supported())
        if not support.autostart_supported():
            self.f_autostart.setToolTip(f"Available in the installed {EXE_NAME}.exe")
        self.f_minimized = QCheckBox("Start minimised to the tray", checked=c.start_minimized)
        box.addWidget(self.f_autostart)
        box.addWidget(self.f_minimized)
        outer.addWidget(startup)

        apply = QPushButton("Apply", clicked=self.apply_settings)
        apply.setObjectName("primary")
        apply.setDefault(True)
        revert = QPushButton("Revert", clicked=self._load_settings)
        row = QHBoxLayout()
        row.addWidget(apply)
        row.addWidget(revert)
        self.settings_note = QLabel()
        self.settings_note.setWordWrap(True)
        row.addWidget(self.settings_note, 1)
        outer.addLayout(row)
        outer.addStretch()
        return tab

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
