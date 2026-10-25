"""A tiny mDNS responder: answers "companionmap.local" with this PC's LAN address (RFC 6762).

Only A queries for that one name are answered; nothing is browsed or registered elsewhere.
It listens on UDP 5353 (shared with Windows' own mDNS) on the LAN interfaces and only ever
sends to the mDNS multicast group or back to the asking device, never off the local network.
"""

import asyncio
import ipaddress
import logging
import socket
import struct

from server.netinfo import MDNS_NAME

log = logging.getLogger("cdlivemap.server")

GROUP, PORT = "224.0.0.251", 5353
TYPE_A, TYPE_ANY, CLASS_IN = 1, 255, 1
CACHE_FLUSH, UNICAST_RESPONSE = 0x8000, 0x8000
TTL = 120


class ParseError(ValueError):
    pass


def _name(data, offset, depth=0):
    """A (possibly compressed) DNS name at offset -> (lower-case name, offset after it)."""
    labels, end = [], None
    while True:
        if offset >= len(data) or depth > 16:
            raise ParseError("bad name")
        length = data[offset]
        if length & 0xC0 == 0xC0:                       # pointer
            if offset + 1 >= len(data):
                raise ParseError("bad pointer")
            target = ((length & 0x3F) << 8) | data[offset + 1]
            rest, _ = _name(data, target, depth + 1)
            labels.append(rest)
            return ".".join(x for x in labels if x).lower(), (end if end is not None else offset + 2)
        offset += 1
        if length == 0:
            return ".".join(labels).lower(), (end if end is not None else offset)
        labels.append(data[offset:offset + length].decode("utf-8", "replace"))
        offset += length


def questions(data):
    """[(name, qtype, unicast_response)] of a query; [] for responses."""
    if len(data) < 12:
        raise ParseError("short packet")
    _, flags, qd = struct.unpack_from("!HHH", data, 0)
    if flags & 0x8000:                                  # a response, not a query
        return []
    out, offset = [], 12
    for _ in range(qd):
        name, offset = _name(data, offset)
        if offset + 4 > len(data):
            raise ParseError("short question")
        qtype, qclass = struct.unpack_from("!HH", data, offset)
        offset += 4
        out.append((name, qtype, bool(qclass & UNICAST_RESPONSE)))
    return out


def _encode(name):
    return b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0"


def response(ips, query_id=0, question=None, ttl=TTL):
    """An answer with one A record per address. Legacy unicast queries (question given) get
    their id and question back and no cache-flush bit (RFC 6762 section 6.7)."""
    name = _encode(MDNS_NAME)
    head = struct.pack("!HHHHHH", query_id, 0x8400, 1 if question else 0, len(ips), 0, 0)
    body = (name + struct.pack("!HH", TYPE_A, CLASS_IN)) if question else b""
    rclass = CLASS_IN if question else CLASS_IN | CACHE_FLUSH
    for ip in ips:
        body += name + struct.pack("!HHIH", TYPE_A, rclass, ttl, 4) + socket.inet_aton(ip)
    return head + body


def addresses_for(sender, ips):
    """The addresses on the asking device's network (same /24, else /16), else all of them."""
    if sender:
        a = ipaddress.ip_address(sender)
        for prefix in (24, 16):
            net = ipaddress.ip_network(f"{a}/{prefix}", strict=False)
            near = [ip for ip in ips if ipaddress.ip_address(ip) in net]
            if near:
                return near
    return list(ips)


class Responder(asyncio.DatagramProtocol):
    def __init__(self, ips):
        self.ips = list(ips)
        self.transport = None
        self.answered = 0

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        try:
            asked = questions(data)
        except ParseError:
            return
        wanted = [q for q in asked if q[0] == MDNS_NAME and q[1] in (TYPE_A, TYPE_ANY)]
        if not wanted or not self.ips:
            return
        sender, port = addr[0], addr[1]
        ips = addresses_for(sender, self.ips)
        if port != PORT:                                # legacy unicast resolver: answer it directly
            query_id = struct.unpack_from("!H", data, 0)[0]
            self.transport.sendto(response(ips, query_id, question=True, ttl=10), addr)
        elif any(q[2] for q in wanted):                 # QU question: unicast reply to the asker
            self.transport.sendto(response(ips), addr)
        else:
            self._multicast(response(ips), ips)
        self.answered += 1

    def _multicast(self, packet, ips):
        sock = self.transport.get_extra_info("socket")
        for ip in ips:
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                self.transport.sendto(packet, (GROUP, PORT))
            except OSError as e:
                log.debug("mDNS send on %s failed: %s", ip, e)

    def announce(self):
        self._multicast(response(self.ips), self.ips)


def _socket(ips):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", PORT))                               # multicast receive needs the wildcard address
    for ip in ips:
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(GROUP) + socket.inet_aton(ip))
        except OSError as e:
            log.warning("mDNS: cannot join the multicast group on %s: %s", ip, e)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    sock.setblocking(False)
    return sock


async def start(ips):
    """Answer for MDNS_NAME with these addresses; returns the transport (close() to stop) or None."""
    if not ips:
        return None
    try:
        sock = _socket(ips)
    except OSError as e:
        log.warning("mDNS name %s unavailable: %s", MDNS_NAME, e)
        return None
    transport, responder = await asyncio.get_running_loop().create_datagram_endpoint(lambda: Responder(ips), sock=sock)
    responder.announce()
    log.info("mDNS: answering for %s (%s)", MDNS_NAME, ", ".join(ips))
    return transport
