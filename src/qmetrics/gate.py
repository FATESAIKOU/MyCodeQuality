"""Q1 gate: decide pass/fail from a `qmetrics diff --json` report. Pure, no network, no git."""

import json

from qmetrics import gitio

GATED_COUNTS = ("crossing_1000", "ast_dup")
ALLOW_LABEL = "quality:arch-ok"


def load_counts(path):
    try:
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
    except OSError as e:
        raise gitio.ToolError("report_unreadable", f"cannot read {path}: {e.strerror}")
    except ValueError:
        raise gitio.ToolError("report_not_json", f"{path} is not valid JSON")
    counts = report.get("counts") if isinstance(report, dict) else None
    if not isinstance(counts, dict):
        raise gitio.ToolError("report_bad_shape", f"{path}: missing or non-object 'counts'")
    for k in GATED_COUNTS:
        v = counts.get(k, "missing")
        if v == "missing":
            raise gitio.ToolError("report_bad_shape", f"{path}: counts.{k} is missing")
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
            raise gitio.ToolError("report_bad_shape", f"{path}: counts.{k} must be a non-negative integer or null")
    return {k: counts[k] for k in GATED_COUNTS}


def parse_labels(text):
    try:
        labels = json.loads(text)
    except ValueError:
        raise gitio.ToolError("labels_not_json", "--labels-json is not valid JSON")
    if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
        raise gitio.ToolError("labels_bad_shape", "--labels-json must be a JSON array of strings")
    return labels


def decide(file, event, labels_json):
    """Return (exit_code, lines). Only pull_request is judged; label match is exact."""
    if event != "pull_request":
        return 0, [f"gate: event {event} is report-only, not judged"]
    counts = load_counts(file)
    labels = parse_labels(labels_json)
    over = [f"{k}={v}" for k, v in counts.items() if v is not None and v > 0]
    unknown = [k for k, v in counts.items() if v is None]
    if not over and not unknown:
        return 0, ["gate: pass (crossing_1000 and ast_dup are 0)"]
    parts = []
    if over:
        parts.append("count above 0: " + ", ".join(over))
    if unknown:
        parts.append("unknown (null: a parse failure under src made it undetermined; fail-closed): "
                     + ", ".join(unknown))
    detail = "; ".join(parts)
    if ALLOW_LABEL in labels:
        return 0, [f"notice: {detail}; allowed by label {ALLOW_LABEL}"]
    return 1, [f"gate: FAIL {detail}; an architect may allow it with label {ALLOW_LABEL}"]
