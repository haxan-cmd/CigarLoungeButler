"""Signed, expiring URL tokens for the read-only web Stats Lab.

The Discord panel mints a short-lived token and puts it in the deep link; the
web route verifies it before serving anything. HMAC-SHA256 over a compact
base64url payload, timing-safe compare. No secrets in the URL beyond the token
itself. Pure — unit-tested in tests/test_lab_auth.py.
"""
import base64
import hashlib
import hmac
import json
import time


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip('=')


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def _sign(body: str, secret: str) -> str:
    return _b64e(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def make_token(secret: str, ttl_seconds: int = 86400, extra: dict = None, now=None) -> str:
    """Mint `body.sig`, where body is a base64url JSON payload carrying an
    expiry (and any `extra` fields), signed with `secret`."""
    now = int(time.time() if now is None else now)
    payload = {'exp': now + int(ttl_seconds)}
    if extra:
        payload.update(extra)
    body = _b64e(json.dumps(payload, separators=(',', ':'), sort_keys=True).encode())
    return f"{body}.{_sign(body, secret)}"


def verify_token(token: str, secret: str, now=None):
    """Return the payload dict if the token is well-formed, correctly signed,
    and unexpired; else None. Timing-safe on the signature check."""
    if not token or not secret or '.' not in token:
        return None
    body, _, sig = token.partition('.')
    if not hmac.compare_digest(sig, _sign(body, secret)):
        return None
    try:
        payload = json.loads(_b64d(body))
    except Exception:
        return None
    now = int(time.time() if now is None else now)
    try:
        if int(payload.get('exp', 0)) < now:
            return None
    except (TypeError, ValueError):
        return None
    return payload
