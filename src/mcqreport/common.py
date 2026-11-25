"""Shared helpers for mcq-report: strict UTC timestamps, JSON files, tool errors.

Nothing here reads the clock. Times only come from arguments.
"""

import datetime
import json
import re

UTC_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
MAX_DAYS = 36500  # keeps timedelta and datetime arithmetic inside the representable range


class ToolError(Exception):
    """Exit code 2 tool error with a code and a message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def parse_utc(value, field: str) -> datetime.datetime:
    """Parse YYYY-MM-DDTHH:MM:SSZ strictly and return an aware UTC datetime."""
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        raise ToolError("bad_time", f"{field} must match YYYY-MM-DDTHH:MM:SSZ: {value!r}")
    try:
        parsed = datetime.datetime.strptime(value, UTC_FORMAT)
    except ValueError:
        raise ToolError("bad_time", f"{field} is not a valid time: {value!r}") from None
    return parsed.replace(tzinfo=datetime.timezone.utc)


def check_days(value, field: str, minimum: int) -> int:
    """Whole days from minimum to MAX_DAYS. Anything else is a bad_arguments tool error."""
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= MAX_DAYS:
        raise ToolError("bad_arguments", f"{field} must be an integer from {minimum} to {MAX_DAYS}: {value!r}")
    return value


def render_json(obj) -> str:
    """Deterministic JSON: sorted keys, 2 spaces indent, ASCII, no NaN or Infinity, trailing newline."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"


def read_json_bytes(data: bytes, label: str):
    """Decode and parse JSON bytes; any failure is a bad_json tool error.

    ValueError covers bad UTF-8, bad JSON, and integers over the digit limit; the other two cover huge nesting.
    """
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, OverflowError, RecursionError):
        raise ToolError("bad_json", f"{label} is not valid JSON") from None


def read_json_file(path: str, label: str):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise ToolError("unreadable", f"{label}: {e.strerror}") from None
    return read_json_bytes(data, label)
