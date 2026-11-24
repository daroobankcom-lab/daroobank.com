"""Decode selected bounded database JSON as text without trusting its shape."""
import json

# All current supported candidate/review snapshot integers are IDs, counts or
# rial values; their valid range is far smaller than this defensive ceiling.
MAX_INTEGER_DIGITS = 128


def _bounded_int(value):
    if len(value.lstrip('-')) > MAX_INTEGER_DIGITS:
        raise ValueError('JSON integer exceeds the supported inspection range')
    return int(value)


def decode_bounded_json(value):
    """Return a decoded value, or None if it cannot be safely decoded.

    Call only on a value already limited in SQL. Invalid input and JSON null
    both become None; current consumers reject non-dictionary payloads.
    This does not validate a schema, authenticate data or bound database work.
    """
    if value is None:
        return None
    try:
        return json.loads(value, parse_int=_bounded_int)
    except (TypeError, ValueError, RecursionError):
        return None
