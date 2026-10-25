"""HTTPS for the LAN: a local certificate authority, a server certificate signed by it, and an
iOS/iPadOS configuration profile that installs the CA on a device.

- The CA is made once per PC and kept in `<data>/tls/` (its private key never leaves this PC).
  It is name-constrained to local names (`.local`, `localhost`, this PC's name) and private
  addresses, so even a stolen key could not vouch for any internet site.
- The server certificate covers this PC's names and LAN addresses; it is made again when they
  change or a month before it expires (397 days, inside Apple's limits).
- Plain HTTP keeps working next to HTTPS; HTTPS only adds a secure context on the device (for
  example, keeping the screen awake).
"""

import datetime
import ipaddress
import logging
import os
import plistlib
import socket
import ssl
import uuid
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from server import APP_NAME, SHORT_NAME
from server.netinfo import MDNS_NAME

log = logging.getLogger("cdlivemap.server")

CA_YEARS = 10
SERVER_DAYS = 397
RENEW_DAYS = 30
PRIVATE_NETS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16")]
PROFILE_ID = "local.companionmap.ca"


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _write(path, data, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    if private:
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def local_names():
    """DNS names for this PC: localhost, its host name, <host>.local and the app's mDNS name."""
    host = socket.gethostname().split(".")[0].lower()
    return sorted({"localhost", host, f"{host}.local", MDNS_NAME})


class LocalCA:
    def __init__(self, data_dir):
        self.dir = Path(data_dir) / "tls"
        self.ca_key_path, self.ca_path = self.dir / "ca-key.pem", self.dir / "ca.pem"
        self.key_path, self.cert_path = self.dir / "server-key.pem", self.dir / "server.pem"

    # ── the CA ───────────────────────────────────────────────────────

    def ensure_ca(self):
        if self.ca_key_path.exists() and self.ca_path.exists():
            key = serialization.load_pem_private_key(self.ca_key_path.read_bytes(), None)
            cert = x509.load_pem_x509_certificate(self.ca_path.read_bytes())
            if cert.not_valid_after_utc > _now() + datetime.timedelta(days=RENEW_DAYS):
                return key, cert
        key = ec.generate_private_key(ec.SECP256R1())
        host = socket.gethostname().split(".")[0]
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{SHORT_NAME} local CA ({host[:30]})"),
                          x509.NameAttribute(NameOID.ORGANIZATION_NAME, APP_NAME)])
        dns = [x509.DNSName(n) for n in ("local", "localhost", host.lower())]
        nets = [x509.IPAddress(n) for n in PRIVATE_NETS]
        now = _now()
        cert = (x509.CertificateBuilder()
                .subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(hours=1))
                .not_valid_after(now + datetime.timedelta(days=365 * CA_YEARS))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                             data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                             crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
                .add_extension(x509.NameConstraints(permitted_subtrees=dns + nets, excluded_subtrees=None), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                .sign(key, hashes.SHA256()))
        _write(self.ca_key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()), private=True)
        _write(self.ca_path, cert.public_bytes(serialization.Encoding.PEM))
        log.info("Created the local certificate authority (%s)", self.fingerprint(cert))
        return key, cert

    def ca_der(self):
        return self.ensure_ca()[1].public_bytes(serialization.Encoding.DER)

    @staticmethod
    def fingerprint(cert):
        return cert.fingerprint(hashes.SHA256()).hex(":").upper()

    # ── the server certificate ──────────────────────────────────────

    def ensure_server_cert(self, ips, names=None):
        """A server certificate for these LAN addresses and names, made again only when needed."""
        names = sorted(set(names or local_names()))
        wanted_ips = sorted({ipaddress.ip_address(i) for i in [*ips, "127.0.0.1"]}, key=lambda a: a.packed)
        ca_key, ca_cert = self.ensure_ca()
        if self._current_ok(ca_cert, names, wanted_ips):
            return self.cert_path, self.key_path
        key = ec.generate_private_key(ec.SECP256R1())
        now = _now()
        san = [x509.DNSName(n) for n in names] + [x509.IPAddress(a) for a in wanted_ips]
        cert = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0] if MDNS_NAME not in names else MDNS_NAME)]))
                .issuer_name(ca_cert.subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(hours=1))
                .not_valid_after(now + datetime.timedelta(days=SERVER_DAYS))
                .add_extension(x509.SubjectAlternativeName(san), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                             data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                             crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                .sign(ca_key, hashes.SHA256()))
        _write(self.key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption()), private=True)
        _write(self.cert_path, cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))
        log.info("Made the HTTPS certificate for %s", ", ".join(names + [str(a) for a in wanted_ips]))
        return self.cert_path, self.key_path

    def _current_ok(self, ca_cert, names, ips):
        if not (self.cert_path.exists() and self.key_path.exists()):
            return False
        try:
            cert = x509.load_pem_x509_certificate(self.cert_path.read_bytes())
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        except (ValueError, x509.ExtensionNotFound):
            return False
        return (cert.issuer == ca_cert.subject
                and cert.not_valid_after_utc > _now() + datetime.timedelta(days=RENEW_DAYS)
                and sorted(san.get_values_for_type(x509.DNSName)) == names
                and sorted(san.get_values_for_type(x509.IPAddress), key=lambda a: a.packed) == ips)

    def ssl_context(self, ips, names=None):
        cert, key = self.ensure_server_cert(ips, names)
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key)
        return ctx

    # ── for the devices ──────────────────────────────────────────────

    def mobileconfig(self):
        """An iOS/iPadOS configuration profile that installs (only) the CA certificate."""
        _, cert = self.ensure_ca()
        der = cert.public_bytes(serialization.Encoding.DER)
        fp = cert.fingerprint(hashes.SHA256()).hex()
        payload_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"companionmap:ca:{fp}")).upper()
        profile_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"companionmap:profile:{fp}")).upper()
        profile = {
            "PayloadContent": [{
                "PayloadCertificateFileName": "companionmap-ca.cer",
                "PayloadContent": der,
                "PayloadDescription": "Lets this device open the map from your PC over HTTPS.",
                "PayloadDisplayName": cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
                "PayloadIdentifier": f"{PROFILE_ID}.{fp[:16]}",
                "PayloadType": "com.apple.security.root",
                "PayloadUUID": payload_uuid,
                "PayloadVersion": 1,
            }],
            "PayloadDescription": (f"Installs the certificate of {APP_NAME} on your PC, so this device can open the "
                                   "map over HTTPS. It is limited to local network names and addresses."),
            "PayloadDisplayName": f"{APP_NAME} (local HTTPS)",
            "PayloadIdentifier": PROFILE_ID,
            "PayloadOrganization": APP_NAME,
            "PayloadRemovalDisallowed": False,
            "PayloadType": "Configuration",
            "PayloadUUID": profile_uuid,
            "PayloadVersion": 1,
        }
        return plistlib.dumps(profile, fmt=plistlib.FMT_XML)
