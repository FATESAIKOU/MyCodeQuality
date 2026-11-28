"""mcq-report compare (#64): before/after comparison of two mcq-weekly-table files.

Stdlib only. Never reads the clock. Rules and the reading guide are in docs/weekly-compare.md.

- Counts: the delta is after - before; a null on either side gives a null delta.
- Ratios ({num, den}): the delta is given only when both dens reach MIN_SAMPLE. It is a string rounded
  half-up to DECIMALS places, so the bytes do not depend on float formatting.
- Distributions (median, p90 of n values): the delta is given only when both n reach MIN_SAMPLE.
"""

from fractions import Fraction

from mcqreport import __version__
from mcqreport.common import ToolError, render_json

TABLE_KIND = "mcq-weekly-table"
COMPARE_KIND = "mcq-weekly-compare"
SCHEMA_VERSION = 1
MIN_SAMPLE = 20
DECIMALS = 4
SAMPLE_NOTE = "樣本不足，不下結論"

# Same order as the summary of mcq-weekly-table; the compare lists metrics in this order.
COUNT_KEYS = (
    "tickets",
    "prs_merged",
    "review_rounds",
    "fix_rounds",
    "unreviewed_merged_prs",
    "prs_without_ci",
    "unparsed_verdict_lines",
    "post_merge_verdicts",
    "first_review_head_stale_prs",
    "fix_prs_within_7d",
)
RATIO_KEYS = ("review_first_pass", "ci_first_green")
DIST_KEYS = ("review_rounds_dist", "cycle_seconds_dist")
# Top-level `flags` in the table: per-PR lists. Compared by their lengths only (count rule).
FLAG_KEYS = ("merged_without_review", "merged_without_ci", "verdict_format_mismatch")
# Count of PRs whose verdicts are null (inside `flags`). Missing key → null, not zero.
FLAG_NULL_KEY = "flags_null_prs"
INCOMPLETE_WARNINGS = ("before_incomplete", "after_incomplete")


def _nonneg_int(value) -> bool:
    return type(value) is int and value >= 0


def _check_table(obj, label: str) -> None:
    """Refuse anything that is not a version-1 weekly table, and any summary missing a column."""
    if not isinstance(obj, dict) or obj.get("kind") != TABLE_KIND:
        raise ToolError("bad_kind", f"{label} must be a {TABLE_KIND} file")
    if type(obj.get("schema_version")) is not int or obj["schema_version"] != SCHEMA_VERSION:
        raise ToolError("bad_schema_version", f"{label} schema_version must be {SCHEMA_VERSION}")
    rows, summary, window = obj.get("rows"), obj.get("summary"), obj.get("window")
    if not isinstance(rows, list) or not isinstance(summary, dict) or not isinstance(window, dict):
        raise ToolError("bad_table", f"{label} needs rows (list), window and summary (objects)")
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ToolError("bad_table", f"{label}.rows[{i}] must be an object")
    for key in COUNT_KEYS:
        value = summary.get(key, "missing")
        if value is not None and not _nonneg_int(value):
            raise ToolError("bad_table", f"{label}.summary.{key} must be null or a count")
    for key in RATIO_KEYS:
        value = summary.get(key)
        if not isinstance(value, dict) or not _nonneg_int(value.get("num")) or not _nonneg_int(value.get("den")):
            raise ToolError("bad_table", f"{label}.summary.{key} needs num and den counts")
    for key in DIST_KEYS:
        value = summary.get(key)
        if not isinstance(value, dict) or not _nonneg_int(value.get("n")):
            raise ToolError("bad_table", f"{label}.summary.{key} needs an n count")
        for stat in ("median", "p90"):
            if value.get(stat) is not None and not _nonneg_int(value.get(stat)):
                raise ToolError("bad_table", f"{label}.summary.{key}.{stat} must be null or an integer")
    # Old tables have no flags at all: that is null, not zero. A flags object may still lack a list.
    flags = obj.get("flags")
    if flags is not None:
        if not isinstance(flags, dict):
            raise ToolError("bad_table", f"{label}.flags must be an object or null")
        for key in FLAG_KEYS:
            if flags.get(key) is not None and not isinstance(flags[key], list):
                raise ToolError("bad_table", f"{label}.flags.{key} must be a list or null")
        if flags.get(FLAG_NULL_KEY) is not None and not _nonneg_int(flags[FLAG_NULL_KEY]):
            raise ToolError("bad_table", f"{label}.flags.{FLAG_NULL_KEY} must be a count or null")


def _fixed(value: Fraction) -> str:
    """Round half up to DECIMALS places and print as a string. Exact arithmetic, no floats."""
    scaled = abs(value) * 10**DECIMALS
    units = (2 * scaled.numerator + scaled.denominator) // (2 * scaled.denominator)
    whole, frac = divmod(units, 10**DECIMALS)
    sign = "-" if value < 0 and units else ""
    return f"{sign}{whole}.{frac:0{DECIMALS}d}"


def _diff(after, before):
    return None if after is None or before is None else after - before


def _count_metric(name, before, after) -> dict:
    return {"name": name, "before": before, "after": after, "delta": _diff(after, before)}


def _ratio_metric(name, before, after) -> dict:
    metric = {
        "name": name,
        "before": {"num": before["num"], "den": before["den"]},
        "after": {"num": after["num"], "den": after["den"]},
    }
    if before["den"] >= MIN_SAMPLE and after["den"] >= MIN_SAMPLE:
        delta = Fraction(after["num"], after["den"]) - Fraction(before["num"], before["den"])
        metric["delta_ratio"] = _fixed(delta)
    else:
        metric["delta_ratio"] = None
        metric["conclusion"] = "sample_insufficient"
    return metric


def _dist_view(value) -> dict:
    return {"n": value["n"], "median": value["median"], "p90": value["p90"]}


def _dist_metric(name, before, after) -> dict:
    metric = {"name": name, "before": _dist_view(before), "after": _dist_view(after)}
    if before["n"] >= MIN_SAMPLE and after["n"] >= MIN_SAMPLE:
        metric["delta_median"] = _diff(after["median"], before["median"])
        metric["delta_p90"] = _diff(after["p90"], before["p90"])
    else:
        metric["delta_median"] = None
        metric["delta_p90"] = None
        metric["conclusion"] = "sample_insufficient"
    return metric


def _flag_count(flags, key):
    if flags is None or flags.get(key) is None:
        return None
    return len(flags[key])


def _flags_null_prs(flags):
    return None if flags is None else flags.get(FLAG_NULL_KEY)


def _warnings(before, after) -> list[str]:
    """Differing config or tool versions, or an incomplete side, mean the numbers need a second look."""
    out = []
    before_rows, after_rows = before["rows"], after["rows"]
    if {r.get("config_digest") for r in before_rows} != {r.get("config_digest") for r in after_rows}:
        out.append("config_digest_differs")
    if {r.get("tool_version") for r in before_rows} != {r.get("tool_version") for r in after_rows}:
        out.append("tool_version_differs")
    # Old tables have no `incomplete` key: that is false, not an error.
    if before.get("incomplete") is True:
        out.append("before_incomplete")
    if after.get("incomplete") is True:
        out.append("after_incomplete")
    return sorted(out)


def compare_tables(before, after) -> dict:
    """Pure function of two parsed weekly tables. Returns the mcq-weekly-compare object."""
    _check_table(before, "before")
    _check_table(after, "after")
    bs, a_s = before["summary"], after["summary"]
    metrics = [_count_metric(k, bs.get(k), a_s.get(k)) for k in COUNT_KEYS]
    metrics += [_ratio_metric(k, bs[k], a_s[k]) for k in RATIO_KEYS]
    metrics += [_dist_metric(k, bs[k], a_s[k]) for k in DIST_KEYS]
    bf, af = before.get("flags"), after.get("flags")
    metrics += [
        _count_metric(f"flags.{k}", _flag_count(bf, k), _flag_count(af, k)) for k in FLAG_KEYS
    ]
    metrics.append(_count_metric(FLAG_NULL_KEY, _flags_null_prs(bf), _flags_null_prs(af)))
    return {
        "kind": COMPARE_KIND,
        "schema_version": SCHEMA_VERSION,
        "tool_version": __version__,
        "before": {"window": before["window"], "tickets": bs.get("tickets")},
        "after": {"window": after["window"], "tickets": a_s.get("tickets")},
        "metrics": metrics,
        "warnings": _warnings(before, after),
    }


def _cell(value) -> str:
    return "—" if value is None else str(value)


def _signed(value) -> str:
    return "—" if value is None else f"{value:+d}"


def _ratio_cell(value) -> str:
    return f"{value['num']}/{value['den']}"


def _dist_cell(value) -> str:
    if value["median"] is None:
        return f"—（n={value['n']}）"
    return f"中位 {value['median']}、p90 {value['p90']}（n={value['n']}）"


def _md_row(metric) -> list[str]:
    if "delta" in metric:
        return [metric["name"], _cell(metric["before"]), _cell(metric["after"]), _signed(metric["delta"]), ""]
    note = SAMPLE_NOTE if metric.get("conclusion") else ""
    if "delta_ratio" in metric:
        return [metric["name"], _ratio_cell(metric["before"]), _ratio_cell(metric["after"]), _cell(metric["delta_ratio"]), note]
    if metric["delta_median"] is None:
        delta = "—"
    else:
        delta = f"中位 {_signed(metric['delta_median'])}、p90 {_signed(metric['delta_p90'])}"
    return [metric["name"], _dist_cell(metric["before"]), _dist_cell(metric["after"]), delta, note]


def render_md(out: dict) -> str:
    """Human-readable table: one metric per row. Deterministic for the same compare object."""
    before, after = out["before"], out["after"]
    lines = [
        "# 每週表前後對照",
        "",
        f"- 前：{_cell(before['window'].get('from'))} 至 {_cell(before['window'].get('to'))}（{_cell(before['tickets'])} 張單）",
        f"- 後：{_cell(after['window'].get('from'))} 至 {_cell(after['window'].get('to'))}（{_cell(after['tickets'])} 張單）",
    ]
    digest_warnings = [w for w in out["warnings"] if w not in INCOMPLETE_WARNINGS]
    incomplete = [w for w in out["warnings"] if w in INCOMPLETE_WARNINGS]
    if digest_warnings:
        lines += ["", f"> 注意：新舊不可直接比（{'、'.join(digest_warnings)}）"]
    if incomplete:
        lines += ["", f"> 注意：週表不完整（{'、'.join(incomplete)}）"]
    lines += ["", "| 指標 | 前 | 後 | 變化 | 說明 |", "|---|---|---|---|---|"]
    lines += ["| " + " | ".join(_md_row(m)) + " |" for m in out["metrics"]]
    return "\n".join(lines) + "\n"
