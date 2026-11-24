"""Formats, serialization, and schema validation for taskquality files."""

import datetime
import hashlib
import json
import re
from pathlib import Path

RECOGNIZED_CONFIG_KEYS = frozenset([
    "ci_green_conclusions",
    "ci_workflows",
    "fail_verdicts",
    "github_review_role",
    "kind",
    "pass_verdicts",
    "review_roles",
    "rework_keywords",
    "schema_version",
    "ticket_ref_keywords",
    "verdict_pattern",
    "verdict_sources",
])

ISO_UTC_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$")
PR_ID_RE = re.compile(r"^([^#]+)#(\d+)$")
HEX_HEAD_RE = re.compile(r"^[0-9a-f]{7,40}$")
VALID_USAGE_ROLES = frozenset(["impl", "review", "arch", "pm", "other"])
USAGE_INT_KEYS = frozenset([
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost_micro_usd",
])


class ToolError(Exception):
    """Exit code 2 tool error with code and message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def parse_iso_utc(ts: str) -> datetime.datetime:
    """Validate YYYY-MM-DDTHH:MM:SSZ and return datetime without calling clock."""
    if not isinstance(ts, str):
        raise ToolError("bad_time", f"timestamp must be a string: {ts!r}")
    m = ISO_UTC_RE.match(ts)
    if not m:
        raise ToolError("bad_time", f"timestamp must be YYYY-MM-DDTHH:MM:SSZ: {ts!r}")
    year, month, day, hour, minute, second = (int(g) for g in m.groups())
    try:
        return datetime.datetime(
            year, month, day, hour, minute, second, tzinfo=datetime.timezone.utc
        )
    except ValueError as e:
        raise ToolError("bad_time", f"invalid calendar time: {ts!r}: {e}") from e


def parse_pr_id(pr_id: str, err_code: str = "snapshot_bad_shape") -> tuple[str, int]:
    """Parse owner/repo#number into (owner/repo, number)."""
    if not isinstance(pr_id, str):
        raise ToolError(err_code, f"PR id must be string: {pr_id!r}")
    m = PR_ID_RE.match(pr_id)
    if not m or "/" not in m.group(1):
        raise ToolError(err_code, f"PR id must match owner/repo#number: {pr_id!r}")
    return m.group(1), int(m.group(2))


def read_json_file(path: str | Path, kind_name: str) -> dict:
    """Read a JSON file, returning dict or raising ToolError."""
    p = Path(path)
    try:
        content = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ToolError("file_unreadable", f"cannot read {path}: {e}") from e

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ToolError("file_not_json", f"file is not valid JSON ({path}): {e}") from e

    if not isinstance(data, dict):
        raise ToolError(f"{kind_name}_bad_shape", f"{kind_name} must be a JSON object ({path})")
    return data


def validate_snapshot(snap: dict) -> None:
    """Validate snapshot structure."""
    if snap.get("kind") != "taskquality-snapshot" or snap.get("schema_version") != 1:
        raise ToolError("snapshot_bad_shape", "snapshot must have kind='taskquality-snapshot' and schema_version=1")
    ticket = snap.get("ticket")
    if not isinstance(ticket, str) or not PR_ID_RE.match(ticket):
        raise ToolError("snapshot_bad_shape", f"snapshot has invalid ticket: {ticket!r}")
    prs = snap.get("prs")
    if not isinstance(prs, list):
        raise ToolError("snapshot_bad_shape", "snapshot prs must be a list")

    for pr in prs:
        if not isinstance(pr, dict):
            raise ToolError("snapshot_bad_shape", "PR item must be an object")
        parse_pr_id(pr.get("id"))
        created_at = pr.get("created_at")
        parse_iso_utc(created_at)
        merged_at = pr.get("merged_at")
        if merged_at is not None:
            parse_iso_utc(merged_at)
        closed_at = pr.get("closed_at")
        if closed_at is not None:
            parse_iso_utc(closed_at)

        for c in pr.get("comments", []):
            if not isinstance(c, dict) or "id" not in c or "first_line" not in c:
                raise ToolError("snapshot_bad_shape", "invalid comment structure")
            parse_iso_utc(c.get("created_at"))

        for r in pr.get("reviews", []):
            if not isinstance(r, dict) or "id" not in r or "state" not in r or "commit_id" not in r:
                raise ToolError("snapshot_bad_shape", "invalid review structure")
            commit_id = r["commit_id"]
            if not isinstance(commit_id, str) or not commit_id:
                raise ToolError("snapshot_bad_shape", f"review commit_id must be a non-empty string: {commit_id!r}")
            parse_iso_utc(r.get("submitted_at"))

        for run in pr.get("ci_runs", []):
            if not isinstance(run, dict) or "run_id" not in run or "workflow" not in run:
                raise ToolError("snapshot_bad_shape", "invalid ci_run structure")
            run_attempt = run.get("run_attempt")
            if run_attempt is None or isinstance(run_attempt, bool) or not isinstance(run_attempt, int):
                raise ToolError("snapshot_bad_shape", f"ci_run run_attempt must be an integer: {run_attempt!r}")
            parse_iso_utc(run.get("created_at"))


def validate_input(input_data: dict, snapshot_ticket: str) -> None:
    """Validate input structure and ticket match."""
    if input_data.get("kind") != "taskquality-input" or input_data.get("schema_version") != 1:
        raise ToolError("input_bad_shape", "input must have kind='taskquality-input' and schema_version=1")
    in_ticket = input_data.get("ticket")
    if in_ticket != snapshot_ticket:
        raise ToolError("ticket_mismatch", f"snapshot ticket ({snapshot_ticket}) does not match input ticket ({in_ticket})")

    started_at = input_data.get("started_at")
    if started_at is not None:
        parse_iso_utc(started_at)

    if "prs" in input_data and input_data["prs"] is not None:
        if not isinstance(input_data["prs"], dict):
            raise ToolError("input_bad_shape", "input.prs must be an object")
        for prid, pr_override in input_data["prs"].items():
            parse_pr_id(prid, "input_bad_shape")
            if not isinstance(pr_override, dict):
                raise ToolError("input_bad_shape", f"input.prs.{prid} must be an object")
            if "verdicts" in pr_override and pr_override["verdicts"] is not None:
                if not isinstance(pr_override["verdicts"], list):
                    raise ToolError("input_bad_shape", f"input.prs.{prid}.verdicts must be a list or null")
                for v in pr_override["verdicts"]:
                    if not isinstance(v, dict):
                        raise ToolError("input_bad_shape", "verdict item must be an object")
                    parse_iso_utc(v.get("at"))
                    if v.get("verdict") not in ("pass", "fail", "other"):
                        raise ToolError("input_bad_shape", f"invalid verdict value: {v.get('verdict')!r}")
                    head = v.get("head")
                    if not isinstance(head, str) or not HEX_HEAD_RE.match(head):
                        raise ToolError("input_bad_shape", f"verdict head must be 7-40 lowercase hex digits: {head!r}")
            if "rework" in pr_override and pr_override["rework"] is not None:
                if not isinstance(pr_override["rework"], bool):
                    raise ToolError("input_bad_shape", f"input.prs.{prid}.rework must be a boolean or null")

    if "usage" in input_data and input_data["usage"] is not None:
        if not isinstance(input_data["usage"], list):
            raise ToolError("input_bad_shape", "input.usage must be a list or null")
        for item in input_data["usage"]:
            if not isinstance(item, dict):
                raise ToolError("input_bad_shape", "usage item must be an object")
            provider = item.get("provider")
            if not isinstance(provider, str) or not provider:
                raise ToolError("input_bad_shape", f"usage item provider must be a non-empty string: {provider!r}")
            model = item.get("model")
            if not isinstance(model, str) or not model:
                raise ToolError("input_bad_shape", f"usage item model must be a non-empty string: {model!r}")
            role = item.get("role")
            if role not in VALID_USAGE_ROLES:
                raise ToolError("input_bad_shape", f"invalid usage role: {role!r}")
            if "pr" in item and item["pr"] is not None:
                parse_pr_id(item["pr"], "input_bad_shape")
            for key in USAGE_INT_KEYS:
                if key in item and item[key] is not None:
                    val = item[key]
                    if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                        raise ToolError("input_bad_shape", f"usage item {key} must be a non-negative integer or null: {val!r}")

    if "counters" in input_data and input_data["counters"] is not None:
        if not isinstance(input_data["counters"], dict):
            raise ToolError("input_bad_shape", "input.counters must be an object or null")
        for k, v in input_data["counters"].items():
            if not isinstance(k, str):
                raise ToolError("input_bad_shape", f"counter key must be a string: {k!r}")
            if v is not None:
                if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                    raise ToolError("input_bad_shape", f"counter {k} value must be a non-negative integer or null: {v!r}")


def validate_config(cfg: dict) -> None:
    """Validate config structure and compile regex."""
    if cfg.get("kind") != "taskquality-config" or cfg.get("schema_version") != 1:
        raise ToolError("config_bad_shape", "config must have kind='taskquality-config' and schema_version=1")

    required_keys = [
        "ticket_ref_keywords",
        "verdict_sources",
        "github_review_role",
        "verdict_pattern",
        "review_roles",
        "pass_verdicts",
        "fail_verdicts",
        "rework_keywords",
        "ci_workflows",
        "ci_green_conclusions",
    ]
    for k in required_keys:
        if k not in cfg:
            raise ToolError("config_bad_shape", f"config missing required key: {k}")

    sources = cfg.get("verdict_sources")
    if not isinstance(sources, list) or len(sources) == 0:
        raise ToolError("config_bad_shape", "verdict_sources must be a non-empty list")
    if len(sources) != len(set(sources)):
        raise ToolError("config_bad_shape", "verdict_sources cannot contain duplicates")
    for s in sources:
        if s not in ("comments", "reviews"):
            raise ToolError("config_bad_shape", f"invalid verdict_sources element: {s!r}")

    pat_str = cfg.get("verdict_pattern")
    if not isinstance(pat_str, str):
        raise ToolError("config_bad_shape", "verdict_pattern must be a string")
    try:
        compiled = re.compile(pat_str)
    except re.error as e:
        raise ToolError("bad_pattern", f"cannot compile verdict_pattern: {e}") from e

    required_groups = {"role", "model", "verdict", "head"}
    if not required_groups.issubset(compiled.groupindex.keys()):
        raise ToolError("config_bad_shape", f"verdict_pattern missing required named groups: {required_groups}")


def calculate_config_digest(cfg: dict) -> str:
    """Calculate sha256 config digest on recognized keys only."""
    filtered = {k: cfg[k] for k in RECOGNIZED_CONFIG_KEYS if k in cfg}
    canonical = json.dumps(filtered, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    h = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{h}"


def render_json(obj: dict) -> str:
    """Deterministic JSON output with sorted keys, 2 spaces indent, and trailing newline."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
