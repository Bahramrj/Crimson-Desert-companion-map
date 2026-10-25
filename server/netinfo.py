"""LAN addresses to bind to and to show in the launcher."""

import ipaddress
import socket

MDNS_NAME = "companionmap.local"     # announced by server/mdns.py, covered by the HTTPS certificate


def default_route_ip():
    """The address of the interface the PC would use for its LAN/internet route, or None."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))   # no packet is sent; picks the default-route interface
            return s.getsockname()[0]
    except OSError:
        return None


def lan_ipv4():
    """Private, non-loopback IPv4 addresses of this PC."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    route = default_route_ip()
    if route:
        ips.add(route)
    out = []
    for ip in ips:
        addr = ipaddress.ip_address(ip)
        if addr.is_private and not addr.is_loopback and not addr.is_link_local:
            out.append(ip)
    return sorted(out, key=ipaddress.ip_address)


def bind_hosts():
    """Loopback plus every LAN interface; never 0.0.0.0."""
    return ["127.0.0.1", *lan_ipv4()]


def lan_urls(port, scheme="http"):
    return [f"{scheme}://{ip}:{port}/" for ip in lan_ipv4()]
