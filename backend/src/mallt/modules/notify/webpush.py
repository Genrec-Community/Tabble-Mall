"""Web Push without a third-party push library: RFC 8291 message encryption (aes128gcm) and
RFC 8292 VAPID, on top of ``cryptography`` and ``pyjwt``. Push services (Google, Mozilla, Apple)
deliver these for free; the keys are ours (VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY)."""

import base64
import os
import time
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

RECORD_SIZE = 4096


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _hkdf(salt: bytes, info: bytes, length: int, key: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(key)


def _public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def encrypt(
    payload: bytes,
    p256dh: str,
    auth: str,
    *,
    salt: bytes | None = None,
    server_key: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """Encrypt ``payload`` for one browser subscription (RFC 8291, one record)."""
    ua_public = b64url_decode(p256dh)
    auth_secret = b64url_decode(auth)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _public_bytes(server_key.public_key())
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = server_key.exchange(ec.ECDH(), peer)
    ikm = _hkdf(auth_secret, b"WebPush: info\x00" + ua_public + as_public, 32, shared)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, b"Content-Encoding: aes128gcm\x00", 16, ikm)
    nonce = _hkdf(salt, b"Content-Encoding: nonce\x00", 12, ikm)
    body = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + body


class Vapid:
    """Signs push requests so push services know they come from us."""

    def __init__(self, private_key: str, public_key: str, subject: str) -> None:
        d = int.from_bytes(b64url_decode(private_key), "big")
        self.key = ec.derive_private_key(d, ec.SECP256R1())
        derived = b64url(_public_bytes(self.key.public_key()))
        if derived != public_key.rstrip("="):
            raise ValueError("VAPID_PUBLIC_KEY does not match VAPID_PRIVATE_KEY")
        self.public_key = derived
        self.subject = subject

    def headers(self, endpoint: str) -> dict[str, str]:
        parts = urlsplit(endpoint)
        claims = {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int(time.time()) + 12 * 3600,
            "sub": self.subject,
        }
        pem = self.key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        token = jwt.encode(claims, pem, algorithm="ES256")
        return {"Authorization": f"vapid t={token}, k={self.public_key}"}


def generate_keys() -> tuple[str, str]:
    """A fresh (private, public) VAPID pair, base64url, for .env / the host's settings."""
    key = ec.generate_private_key(ec.SECP256R1())
    d = key.private_numbers().private_value.to_bytes(32, "big")
    return b64url(d), b64url(_public_bytes(key.public_key()))
