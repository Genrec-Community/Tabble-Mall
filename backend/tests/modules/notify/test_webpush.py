"""Our encryption must be readable by a browser: decrypt it here the way RFC 8291 says one does."""

import json

import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from mallt.modules.notify.webpush import Vapid, b64url, b64url_decode, encrypt, generate_keys


def _hkdf(salt: bytes, info: bytes, n: int, key: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=n, salt=salt, info=info).derive(key)


def browser() -> tuple[ec.EllipticCurvePrivateKey, str, bytes, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    auth = b"0123456789abcdef"
    return key, b64url(public), auth, b64url(auth)


def decrypt(
    body: bytes, ua_key: ec.EllipticCurvePrivateKey, ua_public: bytes, auth: bytes
) -> bytes:
    salt, rs, idlen = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    as_public = body[21 : 21 + idlen]
    assert rs == 4096
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
    shared = ua_key.exchange(ec.ECDH(), peer)
    ikm = _hkdf(auth, b"WebPush: info\x00" + ua_public + as_public, 32, shared)
    cek = _hkdf(salt, b"Content-Encoding: aes128gcm\x00", 16, ikm)
    nonce = _hkdf(salt, b"Content-Encoding: nonce\x00", 12, ikm)
    plain = AESGCM(cek).decrypt(nonce, body[21 + idlen :], None)
    assert plain.endswith(b"\x02")  # last-record delimiter
    return plain[:-1]


def test_a_browser_can_decrypt_what_we_send() -> None:
    key, p256dh, auth, auth_b64 = browser()
    message = json.dumps({"title": "Ready"}).encode()
    body = encrypt(message, p256dh, auth_b64)
    assert decrypt(body, key, b64url_decode(p256dh), auth) == message


def test_vapid_header_is_an_es256_token_for_the_push_service_origin() -> None:
    private, public = generate_keys()
    vapid = Vapid(private, public, "https://mallt.test")
    header = vapid.headers("https://fcm.googleapis.com/fcm/send/abc")["Authorization"]
    assert header.startswith("vapid t=") and header.endswith(f", k={public}")
    token = header.split("t=")[1].split(",")[0]
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b64url_decode(public))
    claims = jwt.decode(token, pub, algorithms=["ES256"], audience="https://fcm.googleapis.com")
    assert claims["sub"] == "https://mallt.test"


def test_mismatched_vapid_keys_are_refused() -> None:
    private, _ = generate_keys()
    _, other_public = generate_keys()
    try:
        Vapid(private, other_public, "x")
    except ValueError:
        return
    raise AssertionError("expected a mismatch error")
