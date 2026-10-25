"""Small launcher helpers: Qt log handler, QR pixmaps, Windows autostart, diagnostics."""

import collections
import io
import logging
import platform
import re
import subprocess
import sys

import segno
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap

from server import APP_NAME, SHORT_NAME, __version__

TASK_NAME = SHORT_NAME   # the online app's logon task is "CD Live Map"
OLD_TASK_NAMES = ("CD Live Map Standalone",)


class _LogSignal(QObject):
    line = Signal(str)


class QtLogHandler(logging.Handler):
    """Keeps the last 500 lines and re-emits each one on the Qt thread."""

    def __init__(self, keep=500):
        super().__init__()
        self.lines = collections.deque(maxlen=keep)
        self.signal = _LogSignal()

    def emit(self, record):
        try:
            text = self.format(record)
        except Exception:
            return
        self.lines.append(text)
        self.signal.line.emit(text)


# Adapters a tablet on the Wi-Fi cannot reach: VMs, WSL/Hyper-V switches, VPNs, Bluetooth.
VIRTUAL_ADAPTER = re.compile(r"vEthernet|VMware|VirtualBox|Hyper-V|WSL|Docker|Default Switch|TAP|VPN|Tailscale|"
                             r"ZeroTier|Npcap|Bluetooth|Loopback|Pseudo", re.I)
KIND_LABEL = {"wifi": "Wi-Fi", "ethernet": "Ethernet", "other": "Network", "virtual": "Virtual adapter"}


def adapter_names():
    """{ipv4: (adapter name, kind)} from the OS (Qt), kind wifi / ethernet / virtual / other."""
    from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface
    out = {}
    for iface in QNetworkInterface.allInterfaces():
        name, kind = iface.humanReadableName(), iface.type()
        if VIRTUAL_ADAPTER.search(name) or kind in (QNetworkInterface.InterfaceType.Virtual,
                                                     QNetworkInterface.InterfaceType.Loopback):
            label = "virtual"
        elif kind == QNetworkInterface.InterfaceType.Wifi:
            label = "wifi"
        elif kind == QNetworkInterface.InterfaceType.Ethernet:
            label = "ethernet"
        else:
            label = "other"
        for entry in iface.addressEntries():
            if entry.ip().protocol() == QAbstractSocket.NetworkLayerProtocol.IPv4Protocol:
                out[entry.ip().toString()] = (name, label)
    return out


def device_urls(urls, adapters=None, recommended_ip=None):
    """The URLs another device can use, best first, as (text, url); plus how many were left out.
    Virtual adapters are hidden unless nothing else is left."""
    adapters = adapter_names() if adapters is None else adapters
    rows = []
    for url in urls:
        ip = url.split("//", 1)[-1].split(":", 1)[0]
        name, kind = adapters.get(ip, ("", "other"))
        best = ip == recommended_ip and kind != "virtual"
        rank = (not best, {"wifi": 0, "ethernet": 1, "other": 2, "virtual": 3}[kind])
        text = f"{url}  –  {name or KIND_LABEL[kind]}" + ("  (recommended)" if best else "")
        rows.append((rank, kind, text, url))
    rows.sort()
    usable = [r for r in rows if r[1] != "virtual"] or rows
    return [(text, url) for _, _, text, url in usable], len(rows) - len(usable)


def qr_pixmap(text, size):
    qr = segno.make(text, error="m")
    modules = qr.symbol_size(border=2)[0]
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=max(1, size // modules), border=2, dark="#000000", light="#ffffff")
    pixmap = QPixmap()
    pixmap.loadFromData(buf.getvalue(), "PNG")
    return pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)


def _schtasks(*args):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, creationflags=flags)


def autostart_supported():
    """Only the built exe can register itself; it runs elevated, so a logon task is used
    (the Run key cannot start an app that requires administrator rights)."""
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def autostart_enabled():
    return autostart_supported() and _schtasks("/query", "/tn", TASK_NAME).returncode == 0


def set_autostart(on):
    if on:
        result = _schtasks("/create", "/f", "/tn", TASK_NAME, "/sc", "onlogon", "/rl", "highest",
                           "/tr", f'"{sys.executable}" --minimized')
    else:
        result = _schtasks("/delete", "/f", "/tn", TASK_NAME)
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or result.stdout.strip() or "schtasks failed")


FIREWALL_RULE = APP_NAME


def _netsh(*args):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(["netsh", "advfirewall", "firewall", *args], capture_output=True, text=True, creationflags=flags)


def firewall_ports(config):
    """(TCP ports, UDP ports) other devices need: the HTTP/HTTPS ports and mDNS."""
    tcp = [config.port] + ([config.https_port] if config.https else [])
    return tcp, ([5353] if config.mdns else [])


def network_categories():
    """{adapter name: "Public" | "Private" | "DomainAuthenticated"} of the connected networks (Windows)."""
    if sys.platform != "win32":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                 "Get-NetConnectionProfile | ForEach-Object { $_.InterfaceAlias + '|' + $_.NetworkCategory }"],
                                capture_output=True, text=True, timeout=10, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return dict(line.split("|", 1) for line in result.stdout.splitlines() if "|" in line)


def firewall_rule_ports():
    """The local ports our inbound rules allow now (empty if the rule exists but its ports can't
    be read, e.g. a translated netsh), or None without a rule (Windows only)."""
    if sys.platform != "win32":
        return None
    result = _netsh("show", "rule", f"name={FIREWALL_RULE}", "verbose")
    if result.returncode != 0:
        return None
    ports = set()
    for line in result.stdout.splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "LocalPort":
            ports.update(int(p) for p in re.findall(r"\d+", value))
    return ports


def set_firewall(config):
    """Allow the app's ports on private (home) networks only; replaces our earlier rules.
    Needs administrator rights (the app runs elevated)."""
    _netsh("delete", "rule", f"name={FIREWALL_RULE}")
    tcp, udp = firewall_ports(config)
    for protocol, ports in (("TCP", tcp), ("UDP", udp)):
        if not ports:
            continue
        result = _netsh("add", "rule", f"name={FIREWALL_RULE}", "dir=in", "action=allow", f"protocol={protocol}",
                        f"localport={','.join(map(str, ports))}", "profile=private",
                        f"description=Lets devices on your home network open the {APP_NAME} map.")
        if result.returncode != 0:
            raise OSError(result.stdout.strip() or result.stderr.strip() or "netsh failed (run the app as administrator)")


def remove_firewall():
    result = _netsh("delete", "rule", f"name={FIREWALL_RULE}")
    if result.returncode != 0 and "No rules match" not in result.stdout:
        raise OSError(result.stdout.strip() or result.stderr.strip() or "netsh failed")


def migrate_autostart():
    """Re-register a logon task made under this app's earlier name."""
    if not autostart_supported():
        return
    for old in OLD_TASK_NAMES:
        if _schtasks("/query", "/tn", old).returncode == 0:
            _schtasks("/delete", "/f", "/tn", old)
            try:
                set_autostart(True)
            except OSError:
                pass


def diagnostics_text(snapshot, config, data_dir, maps=None, marker_sets=None):
    engine = snapshot["engine"]
    lines = [
        f"{APP_NAME} {__version__}",
        f"Python {platform.python_version()} · {platform.platform()}",
        f"Engine: {'simulator' if snapshot['simulated'] else 'memory'}",
        f"Engine status: {engine.status if engine else '-'} {engine.message if engine else ''}".rstrip(),
        f"Server: {'running' if snapshot['running'] else 'stopped'} on port {snapshot['port']} {snapshot['error']}".rstrip(),
        f"Clients: {snapshot['clients']}",
        f"URLs: {', '.join(snapshot['urls']) or '-'}",
        f"Config: port={config.port} https={config.https_port if config.https else 'off'} mdns={config.mdns} rate={config.rate_hz}Hz "
        f"quality={config.map_quality} game={config.game_dir or 'auto'}",
        f"Data: {data_dir}",
    ]
    for key, value in sorted(snapshot["diagnostics"].items()):
        lines.append(f"{key}: {value}")
    for m in maps or []:
        lines.append(f"Map {m['id']}: {m['realm']} source {m['source']} {m['image'][0]}x{m['image'][1]} "
                     f"rev {m['rev']} points {len(m['calibration'])}")
    if maps is not None and not maps:
        lines.append("Maps: none imported")
    for s in marker_sets or []:
        lines.append(f"Markers {s['id']}: {s['count']} source {s['source']} game {s.get('gameVersion') or '-'}")
    return "\n".join(lines)
