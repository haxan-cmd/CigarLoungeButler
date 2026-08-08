"""Tests for utils.lab_auth — signed, expiring Stats Lab tokens."""
from utils.lab_auth import make_token, verify_token

SECRET = "test-secret-123"


def test_valid_roundtrip():
    t = make_token(SECRET, ttl_seconds=100, now=1000)
    p = verify_token(t, SECRET, now=1050)
    assert p is not None and p['exp'] == 1100


def test_extra_payload_preserved():
    t = make_token(SECRET, ttl_seconds=100, extra={'scope': 'all'}, now=1000)
    p = verify_token(t, SECRET, now=1000)
    assert p['scope'] == 'all'


def test_expired_is_rejected():
    t = make_token(SECRET, ttl_seconds=10, now=1000)
    assert verify_token(t, SECRET, now=1011) is None      # 1 second past expiry


def test_tampered_signature_rejected():
    t = make_token(SECRET, ttl_seconds=100, now=1000)
    body, _, sig = t.partition('.')
    forged = body + '.' + ('A' * len(sig))
    assert verify_token(forged, SECRET, now=1000) is None


def test_tampered_body_rejected():
    t = make_token(SECRET, ttl_seconds=100, extra={'scope': 'all'}, now=1000)
    body, _, sig = t.partition('.')
    # flip the payload but keep the old signature
    other = make_token(SECRET, ttl_seconds=999999, extra={'scope': 'admin'}, now=1000)
    forged = other.partition('.')[0] + '.' + sig
    assert verify_token(forged, SECRET, now=1000) is None


def test_wrong_secret_rejected():
    t = make_token(SECRET, ttl_seconds=100, now=1000)
    assert verify_token(t, "different-secret", now=1000) is None


def test_garbage_rejected():
    assert verify_token("", SECRET) is None
    assert verify_token("nodot", SECRET) is None
    assert verify_token(None, SECRET) is None
    assert verify_token("a.b.c", SECRET) is None
