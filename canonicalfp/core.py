"""Type-exact canonical encoding and fingerprints for Python values.

The encoding is deterministic across processes, dict insertion order, set
iteration order and ``PYTHONHASHSEED``.  It is *not* a pickle replacement: it
never reconstructs the value, it only decides equality classes.

Contract (the part that matters):

* scalars are compared by exact builtin type: ``1``, ``1.0``, ``True``,
  ``Decimal("1")`` and ``Fraction(1, 1)`` all encode differently;
* containers are compared by kind: a ``dict`` subclass still hashes as a
  mapping, a ``list`` subclass still hashes as a sequence;
* every ``float('nan')`` canonicalises to one payload, while ``0.0`` and
  ``-0.0`` stay distinct;
* cycles raise :class:`CycleError` instead of hanging.
"""

from __future__ import annotations

import hashlib
import struct
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from fractions import Fraction

__all__ = [
    "CycleError",
    "Divergence",
    "encode",
    "fingerprint",
    "explain",
    "feed",
]

_INT = 0x01
_BOOL = 0x02
_FLOAT = 0x03
_COMPLEX = 0x04
_DECIMAL = 0x05
_FRACTION = 0x06
_STR = 0x07
_BYTES = 0x08
_LIST = 0x09
_TUPLE = 0x0A
_SET = 0x0B
_FROZENSET = 0x0C
_DICT = 0x0D
_DATETIME = 0x0E
_DATE = 0x0F
_TIME = 0x10
_TIMEDELTA = 0x11
_NONE = 0x12
_ENUM = 0x13
_BYTEARRAY = 0x14
_MEMORYVIEW = 0x15


class CycleError(ValueError):
    """Raised when the value contains a reference cycle."""


class Divergence:
    """First structural difference between two values."""

    __slots__ = ("path", "left", "right")

    def __init__(self, path: str, left: str, right: str) -> None:
        self.path = path
        self.left = left
        self.right = right

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Divergence({self.path!r}, {self.left!r}, {self.right!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Divergence):
            return NotImplemented
        return (self.path, self.left, self.right) == (
            other.path,
            other.left,
            other.right,
        )


def _pack_len(n: int) -> bytes:
    return struct.pack(">Q", n)


def _scalar(value: object) -> bytes:
    """Encode a non-container value.  Returns bytes including the type tag."""
    if value is None:
        return bytes([_NONE])
    if isinstance(value, Enum):
        cls = type(value)
        name = cls.__module__ + "." + cls.__qualname__
        return (
            bytes([_ENUM])
            + _pack_len(len(name))
            + name.encode("utf-8")
            + _pack_len(len(value.name))
            + value.name.encode("utf-8")
        )
    if isinstance(value, bool):
        return bytes([_BOOL, 1 if value else 0])
    if isinstance(value, int):
        body = str(value).encode("ascii")
        return bytes([_INT]) + _pack_len(len(body)) + body
    if isinstance(value, float):
        # All NaNs collapse to one payload; 0.0 and -0.0 stay distinct.
        if value != value:
            body = b"\x7f\xf8\x00\x00\x00\x00\x00\x00"
        else:
            body = struct.pack(">d", value)
        return bytes([_FLOAT]) + body
    if isinstance(value, complex):
        return (
            bytes([_COMPLEX])
            + _float_body(value.real)
            + _float_body(value.imag)
        )
    if isinstance(value, Decimal):
        body = _decimal_text(value).encode("ascii")
        return bytes([_DECIMAL]) + _pack_len(len(body)) + body
    if isinstance(value, Fraction):
        body = f"{value.numerator}/{value.denominator}".encode("ascii")
        return bytes([_FRACTION]) + _pack_len(len(body)) + body
    if isinstance(value, str):
        body = value.encode("utf-8")
        return bytes([_STR]) + _pack_len(len(body)) + body
    if isinstance(value, bytes):
        return bytes([_BYTES]) + _pack_len(len(value)) + value
    if isinstance(value, bytearray):
        body = bytes(value)
        return bytes([_BYTEARRAY]) + _pack_len(len(body)) + body
    if isinstance(value, memoryview):
        body = value.tobytes()
        return bytes([_MEMORYVIEW]) + _pack_len(len(body)) + body
    if isinstance(value, datetime):
        # Aware datetimes are normalised to UTC so two representations of the
        # same instant agree; naive and aware values stay distinct.
        if value.utcoffset() is not None:
            value = value.astimezone(tz=__import__("datetime").timezone.utc)
        body = value.isoformat().encode("ascii")
        return bytes([_DATETIME]) + _pack_len(len(body)) + body
    if isinstance(value, date):
        body = value.isoformat().encode("ascii")
        return bytes([_DATE]) + _pack_len(len(body)) + body
    if isinstance(value, time):
        body = value.isoformat().encode("ascii")
        return bytes([_TIME]) + _pack_len(len(body)) + body
    if isinstance(value, timedelta):
        body = f"{value.days}/{value.seconds}/{value.microseconds}".encode("ascii")
        return bytes([_TIMEDELTA]) + _pack_len(len(body)) + body
    raise TypeError(
        "canonicalfp cannot encode value of type "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def _float_body(value: float) -> bytes:
    if value != value:
        return b"\x7f\xf8\x00\x00\x00\x00\x00\x00"
    return struct.pack(">d", value)


def _decimal_text(value: Decimal) -> str:
    if value.is_nan():
        return "NaN"
    sign, digits, exponent = value.as_tuple()
    if not digits:
        digits = (0,)
    # Normalise trailing zeros in the coefficient so 1.0 and 1.00 agree.
    digits = list(digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    text = "".join(str(d) for d in digits)
    if sign:
        text = "-" + text
    return f"{text}e{exponent}"


_MAX_DEPTH = 500


def _encode(value: object, seen: set[int], depth: int) -> bytes:
    if depth > _MAX_DEPTH:
        raise CycleError("maximum nesting depth exceeded")
    if isinstance(value, dict):
        ident = id(value)
        if ident in seen:
            raise CycleError("cycle detected in dict")
        seen.add(ident)
        try:
            items = []
            for key, item in value.items():
                kb = _encode(key, seen, depth + 1)
                vb = _encode(item, seen, depth + 1)
                items.append(_pack_len(len(kb)) + kb + vb)
            items.sort()
            return (
                bytes([_DICT])
                + _pack_len(len(items))
                + b"".join(items)
            )
        finally:
            seen.discard(ident)
    if isinstance(value, (list, tuple)):
        ident = id(value)
        if ident in seen:
            raise CycleError("cycle detected in sequence")
        seen.add(ident)
        try:
            tag = _LIST if isinstance(value, list) else _TUPLE
            parts = [_encode(item, seen, depth + 1) for item in value]
            return (
                bytes([tag])
                + _pack_len(len(parts))
                + b"".join(_pack_len(len(p)) + p for p in parts)
            )
        finally:
            seen.discard(ident)
    if isinstance(value, (set, frozenset)):
        ident = id(value)
        if ident in seen:
            raise CycleError("cycle detected in set")
        seen.add(ident)
        try:
            tag = _SET if isinstance(value, set) else _FROZENSET
            parts = sorted(_encode(item, seen, depth + 1) for item in value)
            return (
                bytes([tag])
                + _pack_len(len(parts))
                + b"".join(_pack_len(len(p)) + p for p in parts)
            )
        finally:
            seen.discard(ident)
    return _scalar(value)


def encode(value: object) -> bytes:
    """Return the canonical, self-delimiting encoding of *value*."""
    return _encode(value, set(), 0)


def feed(hasher, value: object) -> None:
    """Feed the canonical encoding of *value* into an existing hash object."""
    hasher.update(encode(value))


def fingerprint(value: object, algorithm: str = "sha256") -> str:
    """Return a hex digest of the canonical encoding of *value*."""
    digest = hashlib.new(algorithm)
    digest.update(encode(value))
    return digest.hexdigest()


def _kind(value: object) -> str:
    """Human-readable kind used in divergence reports."""
    if isinstance(value, Enum):
        return f"enum {type(value).__module__}.{type(value).__qualname__}"
    return type(value).__name__


def _short(value: object, limit: int = 60) -> str:
    try:
        text = repr(value)
    except Exception:  # pragma: no cover - defensive
        text = f"<{_kind(value)}>"
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return f"{_kind(value)} {text}"


def _as_mapping(value: object) -> dict | None:
    return value if isinstance(value, dict) else None


def _diff(left: object, right: object, path: str) -> Divergence | None:
    if encode(left) == encode(right):
        return None
    lmap, rmap = _as_mapping(left), _as_mapping(right)
    if lmap is not None and rmap is not None:
        left_keys = {encode(k): (k, v) for k, v in lmap.items()}
        right_keys = {encode(k): (k, v) for k, v in rmap.items()}
        for key_bytes, (key, lval) in left_keys.items():
            if key_bytes not in right_keys:
                return Divergence(f"{path}[{key!r}]", _short(lval), "<missing key>")
            rval = right_keys[key_bytes][1]
            found = _diff(lval, rval, f"{path}[{key!r}]")
            if found is not None:
                return found
        for key_bytes, (key, rval) in right_keys.items():
            if key_bytes not in left_keys:
                return Divergence(f"{path}[{key!r}]", "<missing key>", _short(rval))
        return Divergence(path, _short(left), _short(right))
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        if type(left) is not type(right):
            return Divergence(path, _short(left), _short(right))
        for index in range(min(len(left), len(right))):
            found = _diff(left[index], right[index], f"{path}[{index}]")
            if found is not None:
                return found
        if len(left) != len(right):
            return Divergence(
                f"{path}[{min(len(left), len(right))}]",
                f"<{len(left)} items>",
                f"<{len(right)} items>",
            )
    if isinstance(left, (set, frozenset)) and isinstance(right, (set, frozenset)):
        if type(left) is not type(right):
            return Divergence(path, _short(left), _short(right))
        left_only = {encode(x): x for x in left}
        right_only = {encode(x): x for x in right}
        for key_bytes, item in left_only.items():
            if key_bytes not in right_only:
                return Divergence(path, _short(item), "<missing element>")
        for key_bytes, item in right_only.items():
            if key_bytes not in left_only:
                return Divergence(path, "<missing element>", _short(item))
    return Divergence(path, _short(left), _short(right))


def explain(left: object, right: object) -> Divergence | None:
    """Return the first structural divergence, or ``None`` if equivalent.

    The path uses ``$.key`` / ``$[index]`` notation and points at the first
    place where the canonical encodings differ.
    """
    return _diff(left, right, "$")