"""Shared helpers for mcq-report: strict UTC timestamps, JSON files, tool errors.

Nothing here reads the clock. Times only come from arguments.
"""

import datetime
import json
import re

UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


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


def render_json(obj) -> str:
    """Deterministic JSON: sorted keys, 2 spaces indent, ASCII, trailing newline."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def read_json_bytes(data: bytes, label: str):
    """Decode and parse JSON bytes; any failure is a bad_json tool error."""
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ToolError("bad_json", f"{label} is not valid JSON") from None


def read_json_file(path: str, label: str):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise ToolError("unreadable", f"{label}: {e.strerror}") from None
    return read_json_bytes(data, label)
