from __future__ import annotations

import argparse
import ipaddress
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def build_self_signed_cert(
    common_name: str,
    cert_path: str,
    key_path: str,
    valid_hours: int = 8,
    ip_addresses: list[str] | None = None,
    dns_names: list[str] | None = None,
) -> None:
    ip_addresses = ip_addresses or []
    dns_names = dns_names or []

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])

    now = datetime.now(timezone.utc)
    san_entries = []

    for ip_str in ip_addresses:
        san_entries.append(x509.IPAddress(ipaddress.ip_address(ip_str)))

    for dns in dns_names:
        san_entries.append(x509.DNSName(dns))

    # Build Subject Alternative Name extension
    if san_entries:
        san_ext = x509.SubjectAlternativeName(san_entries)
    else:
        san_ext = x509.SubjectAlternativeName([x509.DNSName(common_name)])

    cert_builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(hours=valid_hours))
        .add_extension(san_ext, critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
    )

    cert = cert_builder.sign(private_key=key, algorithm=hashes.SHA256())

    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print(f"Created key:  {key_path}")
    print(f"Created cert: {cert_path}")
    print(f"Valid from:   {(now - timedelta(minutes=5)).isoformat()}")
    print(f"Valid until:  {(now + timedelta(hours=valid_hours)).isoformat()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a short-lived self-signed TLS certificate.")
    parser.add_argument("--cn", default="exam-server", help="Common Name for the certificate")
    parser.add_argument("--cert", default="server.crt", help="Output certificate path")
    parser.add_argument("--key", default="server.key", help="Output private key path")
    parser.add_argument("--hours", type=int, default=8, help="Certificate lifetime in hours")
    parser.add_argument("--ip", action="append", default=[], help="Add an IP to the certificate SAN. Repeatable.")
    parser.add_argument("--dns", action="append", default=[], help="Add a DNS name to the certificate SAN. Repeatable.")

    args = parser.parse_args()

    build_self_signed_cert(
        common_name=args.cn,
        cert_path=args.cert,
        key_path=args.key,
        valid_hours=args.hours,
        ip_addresses=args.ip,
        dns_names=args.dns,
    )


if __name__ == "__main__":
    main()
