"""md_safe: neutralize markdown-link injection via user-controlled names."""
from utils.parsing import md_safe


def test_injection_payload_is_defanged():
    # A name crafted to break out of [text](url) and inject its own link. The ']' that
    # would close the link text early is gone, so it renders as a literal label instead.
    assert md_safe("Bob](https://evil.io)") == "Bob(https://evil.io)"
    # No ']' survives, so it can't close the link-text early.
    assert "]" not in md_safe("x]evil")
    assert "[" not in md_safe("[x")


def test_legit_names_untouched():
    assert md_safe("Brittany (OF)") == "Brittany (OF)"
    assert md_safe("C10H15N (Meth)") == "C10H15N (Meth)"
    assert md_safe("Massive Σggplant") == "Massive Σggplant"


def test_empty_and_none():
    assert md_safe("") == ""
    assert md_safe(None) is None
