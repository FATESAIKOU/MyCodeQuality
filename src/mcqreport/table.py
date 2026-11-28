"""Weekly table (`mcq-weekly-table`, N10b): one row per ticket from taskquality reports, a summary, and flags.

Pure functions: no I/O and no clock. `mcq-report table` reads and validates the files; this module only computes.
Public API:
- build_table(reports, window, closed_at=None) -> dict: the table as a plain dict (render_json-ready).
- render_md(table) -> str: the human-readable Markdown table.
"""

from mcqreport import __version__ as TOOL_VERSION
from mcqreport.common import ToolError, parse_utc

KIND = "mcq-weekly-table"
SCHEMA_VERSION = 1
SAMPLE_MIN = 20
WEEK_SECONDS = 7 * 86400
DASH = "—"

TOKEN_KEYS = [
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost_micro_usd",
]

# count columns: summary = sum of non-null rows, plus <name>_null_rows
COUNT_FIELDS = [
    "prs_merged",
    "review_rounds",
    "fix_rounds",
    "unreviewed_merged_prs",
    "prs_without_ci",
    "unparsed_verdict_lines",
    "post_merge_verdicts",
    "first_review_head_stale_prs",
    "fix_prs_within_7d",
]
# ratio columns: summary = {num, den, null_rows, sample_sufficient}
RATIO_FIELDS = ["review_first_pass", "ci_first_green"]
# distribution columns: summary = {n, median, p90, sample_sufficient}
DIST_FIELDS = ["review_rounds", "cycle_seconds"]

# report metrics copied one-to-one into the row (a missing key stays null, never 0)
METRIC_FIELDS = [
    "prs_merged",
    "fix_rounds",
    "review_first_pass",
    "ci_first_green",
    "unreviewed_merged_prs",
    "prs_without_ci",
    "unparsed_verdict_lines",
    "post_merge_verdicts",
    "first_review_head_stale_prs",
    "cycle_seconds",
]


def _number_or_none(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _ratio_or_none(value):
    if not isinstance(value, dict):
        return None
    num, den = _number_or_none(value.get("num")), _number_or_none(value.get("den"))
    return None if num is None or den is None else {"num": num, "den": den}


def _fix_prs_within_7d(prs):
    """Merged PRs whose merged_at is after the earliest merged_at and at most 7 days after it (inclusive).

    No merged PR -> None.
    """
    merged_at = []
    for p in prs:
        if p.get("state") == "merged":
            merged_at.append(parse_utc(p.get("merged_at"), f"prs[{p.get('pr')}].merged_at"))
    if not merged_at:
        return None
    earliest = min(merged_at)
    return sum(1 for t in merged_at if 0 < (t - earliest).total_seconds() <= WEEK_SECONDS)


def _review_rounds(prs):
    """Sum of verdicts over merged PRs. Any null verdicts -> None; no merged PR -> None."""
    merged = [p for p in prs if p.get("state") == "merged"]
    if not merged:
        return None
    counts = [_number_or_none(p.get("verdicts")) for p in merged]
    return None if any(c is None for c in counts) else sum(counts)


def _row(report, closed_at):
    metrics = report.get("metrics") or {}
    prs = report.get("prs")
    usage = report.get("usage")
    row = {
        "ticket": report["ticket"],
        "status": report.get("status"),
        "tool_version": report.get("tool_version"),
        "config_digest": report.get("config_digest"),
        "closed_at": closed_at,
    }
    for key in METRIC_FIELDS:
        row[key] = metrics.get(key)
    if isinstance(prs, list):
        row["review_rounds"] = _review_rounds(prs)
        row["fix_prs_within_7d"] = _fix_prs_within_7d(prs)
    else:
        row["review_rounds"] = None
        row["fix_prs_within_7d"] = None
    row["fix_rounds"] = _number_or_none(metrics.get("fix_rounds"))
    row["review_first_pass"] = _ratio_or_none(metrics.get("review_first_pass"))
    row["ci_first_green"] = _ratio_or_none(metrics.get("ci_first_green"))
    row["usage"] = usage.get("by_role_model") if isinstance(usage, dict) else None
    return row


def _sum_or_none(values):
    """Sum of non-null values. None when all rows are null (or there are no rows)."""
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _summarize_counts(rows):
    out = {}
    for key in COUNT_FIELDS:
        vals = [r[key] for r in rows]
        out[key] = sum(v for v in vals if v is not None)
        out[key + "_null_rows"] = sum(1 for v in vals if v is None)
    return out


def _summarize_ratio(rows, key):
    vals = [r[key] for r in rows]
    num = sum(v["num"] for v in vals if v is not None)
    den = sum(v["den"] for v in vals if v is not None)
    return {
        "num": num,
        "den": den,
        "null_rows": sum(1 for v in vals if v is None),
        "sample_sufficient": den >= SAMPLE_MIN,
    }


def _nearest_rank(sorted_vals, p_num, p_den):
    """Nearest-rank percentile with integer arithmetic: the ceil(p*n)-th smallest value (1-based)."""
    n = len(sorted_vals)
    idx = -((-p_num * n) // p_den)  # ceil(p_num * n / p_den)
    return sorted_vals[idx - 1]


def _summarize_dist(rows, key):
    vals = sorted(r[key] for r in rows if r[key] is not None)
    n = len(vals)
    sufficient = n >= SAMPLE_MIN
    return {
        "n": n,
        "median": _nearest_rank(vals, 1, 2) if sufficient else None,
        "p90": _nearest_rank(vals, 9, 10) if sufficient else None,
        "sample_sufficient": sufficient,
    }


def _summarize_usage(rows):
    """Add by_role_model entries of all rows per (role, provider, model). None if no row has usage."""
    groups = {}
    any_usage = False
    for r in rows:
        if r["usage"] is None:
            continue
        any_usage = True
        for e in r["usage"]:
            groups.setdefault((e["role"], e["provider"], e["model"]), []).append(e)
    if not any_usage:
        return None
    out = []
    for role, provider, model in sorted(groups):
        items = groups[(role, provider, model)]
        entry = {"model": model, "provider": provider, "role": role}
        for t_k in TOKEN_KEYS:
            vals = [it.get(t_k) for it in items]
            entry[t_k] = None if any(v is None for v in vals) else sum(vals)
        # same rule as #61: weighted keys appear when any participating entry carries them
        if any("weighted_micro_units" in it for it in items):
            entry["weighted_micro_units"] = _sum_or_none(
                [it["weighted_micro_units"] for it in items if "weighted_micro_units" in it]
            )
            # an entry without the weighted key counts as one null row (no item count is kept in the report)
            entry["weighted_null_rows"] = sum(
                it["weighted_null_rows"] if "weighted_micro_units" in it else 1 for it in items
            )
        out.append(entry)
    return out


def _flags(reports):
    """Per-PR lists, sorted by (ticket, pr). flags_null_prs counts PRs whose flag could not be decided."""
    without_review, without_ci, mismatch = [], [], []
    null_prs = 0
    for report in sorted(reports, key=lambda r: r["ticket"]):
        ticket = report["ticket"]
        prs = report.get("prs")
        if not isinstance(prs, list):
            continue
        for pr in sorted(prs, key=lambda p: p.get("pr", "")):
            pr_id = pr.get("pr")
            state = pr.get("state")
            unknown = False
            if state == "merged":
                verdicts = _number_or_none(pr.get("verdicts"))
                ci_runs = _number_or_none(pr.get("ci_runs"))
                if verdicts is None:
                    unknown = True
                elif verdicts == 0:
                    without_review.append({"ticket": ticket, "pr": pr_id})
                if ci_runs is None:
                    unknown = True
                elif ci_runs == 0:
                    without_ci.append({"ticket": ticket, "pr": pr_id})
            unparsed = _number_or_none(pr.get("unparsed_verdict_lines"))
            if unparsed is None:
                unknown = True
            elif unparsed > 0:
                mismatch.append({"ticket": ticket, "pr": pr_id, "state": state, "lines": unparsed})
            if unknown:
                null_prs += 1
    return {
        "flags_null_prs": null_prs,
        "merged_without_ci": without_ci,
        "merged_without_review": without_review,
        "verdict_format_mismatch": mismatch,
    }


def _reason_key(item):
    return (str(item.get("repo", item.get("ticket", ""))), str(item.get("reason", "")))


def build_table(reports, window, closed_at=None, incomplete_reasons=None):
    """Build the weekly table dict.

    reports: taskquality-report dicts (already read and kind-checked; one per ticket).
    window: {"from": UTC, "to": UTC}; written to the output only, rows are not filtered by it.
    closed_at: optional {ticket: UTC string or None}; a missing ticket gives null.
    incomplete_reasons: optional [{"repo" or "ticket": ..., "reason": ...}] from the driver (#63).
        Any reason makes the table incomplete. None (standalone mcq-report table) gives [] and false.
    """
    tickets = [r["ticket"] for r in reports]
    if len(set(tickets)) != len(tickets):
        raise ToolError("duplicate_ticket", "more than one report for the same ticket")
    rows = [_row(r, (closed_at or {}).get(r["ticket"])) for r in sorted(reports, key=lambda r: r["ticket"])]

    summary = _summarize_counts(rows)
    for key in RATIO_FIELDS:
        summary[key] = _summarize_ratio(rows, key)
    for key in DIST_FIELDS:
        summary[key + "_dist"] = _summarize_dist(rows, key)
    summary["tickets"] = len(rows)
    summary["usage_null_rows"] = sum(1 for r in rows if r["usage"] is None)
    summary["usage_by_role_model"] = _summarize_usage(rows)

    reasons = sorted((dict(item) for item in (incomplete_reasons or [])), key=_reason_key)
    return {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "window": {"from": window["from"], "to": window["to"]},
        "incomplete": bool(reasons),
        "incomplete_reasons": reasons,
        "rows": rows,
        "summary": summary,
        "flags": _flags(reports),
    }


# --- Markdown ----------------------------------------------------------------

def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def _join(values):
    return "、".join(_cell(v) for v in values) if values else DASH


def _ratio_text(ratio):
    return DASH if ratio is None or ratio["den"] == 0 else f"{ratio['num']}/{ratio['den']}"


def _count_text(value):
    return DASH if value is None else str(value)


def _row_cost(usage):
    if not usage:
        return DASH
    total = _sum_or_none([e.get("weighted_micro_units") for e in usage])
    return DASH if total is None else str(total)


def _md_row(cells):
    return "| " + " | ".join(cells) + " |"


def render_md(table):
    """Markdown table: one line per ticket, then a 合計 line from the summary. Null values show as —."""
    s = table["summary"]
    usage_total = s["usage_by_role_model"]
    lines = [
        "# 每週表（mcq-weekly-table）",
        "",
        f"窗：{table['window']['from']} ～ {table['window']['to']}；單數：{s['tickets']}",
        "",
        _md_row(["單", "模型", "角色", "成本", "審查輪數", "一次過", "CI 首綠", "未審先合", "無 CI 合併", "首審過期（Q-8）", "7 天內修正（Q-9）"]),
        _md_row(["---"] * 11),
    ]
    for r in table["rows"]:
        usage = r["usage"] or []
        models = [f"{e['provider']}/{e['model']}" for e in usage]
        roles = [e["role"] for e in usage]
        lines.append(_md_row([
            _cell(r["ticket"]),
            _join(models) if r["usage"] is not None else DASH,
            _join(roles) if r["usage"] is not None else DASH,
            _row_cost(usage),
            _count_text(r["review_rounds"]),
            _ratio_text(r["review_first_pass"]),
            _ratio_text(r["ci_first_green"]),
            _count_text(r["unreviewed_merged_prs"]),
            _count_text(r["prs_without_ci"]),
            _count_text(r["first_review_head_stale_prs"]),
            _count_text(r["fix_prs_within_7d"]),
        ]))

    rr = s["review_rounds_dist"]
    rr_text = f"中位 {_count_text(rr['median'])}、P90 {_count_text(rr['p90'])}"
    if not rr["sample_sufficient"]:
        rr_text += "（樣本不足）"
    rf, cf = s["review_first_pass"], s["ci_first_green"]
    rf_text = _ratio_text(rf) + ("" if rf["sample_sufficient"] or rf["den"] == 0 else "（樣本不足）")
    cf_text = _ratio_text(cf) + ("" if cf["sample_sufficient"] or cf["den"] == 0 else "（樣本不足）")
    total_models = [f"{e['provider']}/{e['model']}" for e in usage_total] if usage_total is not None else []
    total_roles = [e["role"] for e in usage_total] if usage_total is not None else []
    lines.append(_md_row([
        "合計",
        _join(total_models) if usage_total is not None else DASH,
        _join(total_roles) if usage_total is not None else DASH,
        _row_cost(usage_total or []),
        rr_text,
        rf_text,
        cf_text,
        str(s["unreviewed_merged_prs"]),
        str(s["prs_without_ci"]),
        str(s["first_review_head_stale_prs"]),
        str(s["fix_prs_within_7d"]),
    ]))
    return "\n".join(lines) + "\n"
