"""
Tests for CodecMapping — transparent encode/decode wrapper over MutableMapping.

Covers:
- Basic get/set with identity codecs
- Custom encode/decode functions (json, pickle-like)
- __delitem__, __iter__, __len__, __contains__
- clear()
- raw property
- Edge cases: None encode/decode treated as identity
- Falsy key/value guard in __setitem__
"""

import json
import pytest

from Caching.CodecMapping import CodecMapping


class _SimpleDict(dict):
    """Plain dict that satisfies MutableMapping for testing."""
    pass


# ---------------------------------------------------------------------------
# Basic operations
# ---------------------------------------------------------------------------

class TestBasicOps:
    def test_set_and_get_identity(self):
        backing = _SimpleDict()
        cm = CodecMapping(backing, enc=None, dec=None)
        cm["k"] = "v"
        assert cm["k"] == "v"

    def test_len(self):
        backing = _SimpleDict(a=1, b=2)
        cm = CodecMapping(backing, enc=None, dec=None)
        assert len(cm) == 2

    def test_iter(self):
        backing = _SimpleDict(x=1, y=2)
        cm = CodecMapping(backing, enc=None, dec=None)
        assert set(cm) == {"x", "y"}

    def test_contains(self):
        backing = _SimpleDict(present=1)
        cm = CodecMapping(backing, enc=None, dec=None)
        assert "present" in cm
        assert "absent" not in cm

    def test_delitem(self):
        backing = _SimpleDict(k=1)
        cm = CodecMapping(backing, enc=None, dec=None)
        del cm["k"]
        assert "k" not in cm

    def test_delitem_missing_raises(self):
        backing = _SimpleDict()
        cm = CodecMapping(backing, enc=None, dec=None)
        with pytest.raises(KeyError):
            del cm["nope"]

    def test_clear(self):
        backing = _SimpleDict(a=1, b=2, c=3)
        cm = CodecMapping(backing, enc=None, dec=None)
        cm.clear()
        assert len(cm) == 0
        assert len(backing) == 0


# ---------------------------------------------------------------------------
# Encode / Decode
# ---------------------------------------------------------------------------

class TestEncodeDecode:
    def test_json_roundtrip(self):
        backing = _SimpleDict()
        cm = CodecMapping(backing, enc=json.dumps, dec=json.loads)
        cm["data"] = {"list": [1, 2, 3]}
        # Stored encoded
        assert isinstance(backing["data"], str)
        # Retrieved decoded
        assert cm["data"] == {"list": [1, 2, 3]}

    def test_custom_encode_decode(self):
        backing = _SimpleDict()
        cm = CodecMapping(backing, enc=lambda x: x * 2, dec=lambda x: x // 2)
        cm["n"] = 21
        assert backing["n"] == 42
        assert cm["n"] == 21

    def test_encode_only(self):
        backing = _SimpleDict()
        cm = CodecMapping(backing, enc=str, dec=None)
        cm["n"] = 123
        assert backing["n"] == "123"
        # Decode is identity, returns the raw encoded value
        assert cm["n"] == "123"

    def test_decode_only(self):
        backing = _SimpleDict()
        cm = CodecMapping(backing, enc=None, dec=int)
        cm["n"] = "456"
        assert backing["n"] == "456"
        assert cm["n"] == 456


# ---------------------------------------------------------------------------
# raw property
# ---------------------------------------------------------------------------

class TestRawProperty:
    def test_raw_returns_backing(self):
        backing = _SimpleDict()
        cm = CodecMapping(backing, enc=None, dec=None)
        assert cm.raw is backing


# ---------------------------------------------------------------------------
# Falsy guard in __setitem__
# ---------------------------------------------------------------------------

class TestSetItemGuard:
    def test_falsy_key_skips_write(self):
        backing = _SimpleDict()
        cm = CodecMapping(backing, enc=None, dec=None)
        cm[""] = "value"
        assert "" not in backing

    def test_falsy_value_skips_write(self):
        backing = _SimpleDict()
        cm = CodecMapping(backing, enc=None, dec=None)
        cm["key"] = ""
        assert "key" not in backing

    def test_none_key_skips_write(self):
        backing = _SimpleDict()
        cm = CodecMapping(backing, enc=None, dec=None)
        cm[None] = "value"
        assert None not in backing

    def test_none_value_skips_write(self):
        backing = _SimpleDict()
        cm = CodecMapping(backing, enc=None, dec=None)
        cm["key"] = None
        assert "key" not in backing

    def test_zero_value_skips_write(self):
        backing = _SimpleDict()
        cm = CodecMapping(backing, enc=None, dec=None)
        cm["key"] = 0
        assert "key" not in backing

    def test_truthy_key_and_value_writes(self):
        backing = _SimpleDict()
        cm = CodecMapping(backing, enc=None, dec=None)
        cm["key"] = "value"
        assert backing["key"] == "value"
