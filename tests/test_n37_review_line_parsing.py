"""Tests for N37 review line parsing changes (Decisions 1, 2, 3, 4).

All data is synthetic (acme/widgets, vendor/model-x).
"""

import copy
import json
import re

from taskquality.conventions import DEFAULT_CONFIG, extract_verdicts_detailed
from taskquality.score import score_ticket

TICKET = "acme/widgets#11"


def comment(i, created_at, first_line):
    return {"id": i, "created_at": created_at, "first_line": first_line}


def make_pr(
    n,
    *,
    state="closed",
    merged_at="2030-01-02T05:00:00Z",
    comments=(),
    reviews=(),
    ci_runs=(),
    title="Closes #11",
):
    return {
        "id": f"acme/widgets#{n}",
        "title": title,
        "body": "",
        "state": state,
        "created_at": "2030-01-02T03:00:00Z",
        "merged_at": merged_at,
        "head_sha": "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "comments": list(comments),
        "reviews": list(reviews),
        "ci_runs": list(ci_runs),
    }


def snapshot(*prs):
    return {
        "kind": "taskquality-snapshot",
        "schema_version": 1,
        "ticket": TICKET,
        "prs": list(prs),
    }


def test_decision3_verdicts_before_at_and_after_merged_at():
    """Decision 3: merged PR only keeps verdicts with at <= merged_at (same second included).

    Later verdicts are counted in post_merge_verdicts and do not affect review metrics.
    """
    merged_at = "2030-01-02T05:00:00Z"
    pr = make_pr(
        21,
        merged_at=merged_at,
        comments=[
            comment(1, "2030-01-02T04:00:00Z", "審查：vendor/model-x 結論：要修（head 0000000）"),
            comment(2, "2030-01-02T05:00:00Z", "審查：vendor/model-x 結論：可以 merge（head 1111111）"),
            comment(3, "2030-01-02T05:00:01Z", "審查：vendor/model-x 結論：要修（head 1111111）"),
        ],
    )
    snap = snapshot(pr)
    rep = score_ticket(snap, None, DEFAULT_CONFIG)

    pr_res = rep["prs"][0]
    assert pr_res["verdicts"] == 2
    assert pr_res["post_merge_verdicts"] == 1
    # Comment 2 (at == merged_at) counts as the final verdict: pass on head 1111111.
    # Comment 3 (after merged_at) is separate, so fix_rounds is 1 (not 2).
    assert pr_res["fix_rounds"] == 1
    assert pr_res["re_reviews"] == 1
    assert pr_res["approved_head_stale"] is False

    assert rep["metrics"]["post_merge_verdicts"] == 1

    # Open PRs and closed_unmerged PRs are not filtered by merged_at
    pr_open = make_pr(
        22,
        state="open",
        merged_at=None,
        comments=[
            comment(4, "2030-01-02T06:00:00Z", "審查：vendor/model-x 結論：可以 merge（head 1111111）"),
        ],
    )
    rep_open = score_ticket(snapshot(pr_open), None, DEFAULT_CONFIG)
    assert rep_open["prs"][0]["post_merge_verdicts"] == 0
    assert rep_open["prs"][0]["verdicts"] == 1

    # Input override verdicts also apply decision 3
    input_data = {
        "kind": "taskquality-input",
        "schema_version": 1,
        "ticket": TICKET,
        "prs": {
            "acme/widgets#21": {
                "verdicts": [
                    {
                        "at": "2030-01-02T04:59:59Z",
                        "role": "審查",
                        "model": "vendor/model-x",
                        "verdict": "pass",
                        "head": "1111111",
                    },
                    {
                        "at": "2030-01-02T05:00:01Z",
                        "role": "審查",
                        "model": "vendor/model-x",
                        "verdict": "pass",
                        "head": "1111111",
                    },
                ]
            }
        },
    }
    rep_in = score_ticket(snapshot(pr), input_data, DEFAULT_CONFIG)
    assert rep_in["prs"][0]["verdicts"] == 1
    assert rep_in["prs"][0]["post_merge_verdicts"] == 1


def test_decision3_post_merge_verdict_only_keeps_unreviewed_merged():
    """Decision 3: review lines added after merge keep the PR as unreviewed_merged_prs."""
    pr = make_pr(
        21,
        merged_at="2030-01-02T05:00:00Z",
        comments=[
            comment(1, "2030-01-02T05:00:01Z", "審查：vendor/model-x 結論：可以 merge（head 1111111）"),
        ],
    )
    snap = snapshot(pr)
    rep = score_ticket(snap, None, DEFAULT_CONFIG)

    pr_res = rep["prs"][0]
    assert pr_res["verdicts"] == 0
    assert pr_res["post_merge_verdicts"] == 1
    assert pr_res["first_review_pass"] is None
    assert pr_res["fix_rounds"] is None

    assert rep["metrics"]["unreviewed_merged_prs"] == 1
    assert rep["metrics"]["post_merge_verdicts"] == 1
    assert rep["clean"] is False


def test_decision1_acceptance_pm_cases():
    """PM acceptance criteria for Decision 1 with built-in DEFAULT_CONFIG:

    1. '審查：vendor/model-x（管道，high） 結論：可以 merge（head 1234567）' recognized:
       model='vendor/model-x', note='管道，high'
    2. '審查：vendor/model-x（架構師結構審） 結論：通過（head 1234567）' does not enter review metrics,
       counted in structure_note_verdicts
    3. '審查：vendor/model-x（x） 結論：可以 merge（head 1234567）' recognized:
       model='vendor/model-x', note='x'
    """
    pat = re.compile(DEFAULT_CONFIG["verdict_pattern"])

    # 1. Note with comma and space
    line1 = "審查：vendor/model-x（管道，high） 結論：可以 merge（head 1234567）"
    m1 = pat.match(line1)
    assert m1 is not None, line1
    assert m1.group("role") == "審查"
    assert m1.group("model") == "vendor/model-x"
    assert m1.group("note") == "管道，high"
    assert m1.group("verdict") == "可以 merge"
    assert m1.group("head") == "1234567"

    # 2. Architecture note
    line2 = "審查：vendor/model-x（架構師結構審） 結論：通過（head 1234567）"
    m2 = pat.match(line2)
    assert m2 is not None, line2
    assert m2.group("role") == "審查"
    assert m2.group("model") == "vendor/model-x"
    assert m2.group("note") == "架構師結構審"
    assert m2.group("verdict") == "通過"
    assert m2.group("head") == "1234567"

    # 3. Old syntax with full-width brackets but no space
    line3 = "審查：vendor/model-x（x） 結論：可以 merge（head 1234567）"
    m3 = pat.match(line3)
    assert m3 is not None, line3
    assert m3.group("role") == "審查"
    assert m3.group("model") == "vendor/model-x"
    assert m3.group("note") == "x"
    assert m3.group("verdict") == "可以 merge"
    assert m3.group("head") == "1234567"

    # Verify score behavior with built-in config
    pr = make_pr(
        21,
        comments=[
            comment(1, "2030-01-02T04:00:00Z", line1),
            comment(2, "2030-01-02T04:10:00Z", line2),
            comment(3, "2030-01-02T04:20:00Z", line3),
        ],
    )
    rep = score_ticket(snapshot(pr), None, DEFAULT_CONFIG)
    pr_res = rep["prs"][0]
    # line1 and line3 enter V -> 2 verdicts
    # line2 has architecture note -> structure_note_verdicts
    assert pr_res["verdicts"] == 2
    assert pr_res["structure_note_verdicts"] == 1
    assert rep["metrics"]["structure_note_verdicts"] == 1


def test_decision2_structure_note_excluded_with_pattern():
    """Decision 2: if pattern has a 'note' group, role in review_roles, and note contains

    '架構' or '結構' -> excluded from V, counted in structure_note_verdicts.
    If pattern does not have 'note' group, rule is a no-op.
    """
    pr = make_pr(
        21,
        comments=[
            comment(1, "2030-01-02T04:00:00Z", "審查：vendor/model-x（架構審查） 結論：通過（head 1111111）"),
            comment(2, "2030-01-02T04:05:00Z", "審查：vendor/model-x（結構檢驗） 結論：通過（head 1111111）"),
            comment(3, "2030-01-02T04:10:00Z", "審查：vendor/model-x（一般註記） 結論：可以 merge（head 1111111）"),
            comment(4, "2030-01-02T04:15:00Z", "結構審查：vendor/model-x 結論：通過（head 1111111）"),
        ],
    )
    snap = snapshot(pr)

    # Built-in config has 'note' group: Decision 2 activates
    rep_default = score_ticket(snap, None, DEFAULT_CONFIG)
    pr_res = rep_default["prs"][0]
    assert pr_res["structure_note_verdicts"] == 2
    assert pr_res["verdicts"] == 1
    assert rep_default["metrics"]["structure_note_verdicts"] == 2

    # Custom config WITHOUT note group: Decision 2 does not activate
    cfg_no_note = copy.deepcopy(DEFAULT_CONFIG)
    cfg_no_note["verdict_pattern"] = (
        r"^(?P<role>\S*審查)：(?P<model>\S+) 結論：(?P<verdict>[^（]+)（head (?P<head>[0-9a-f]{7,40})）"
    )
    rep_no_note = score_ticket(snap, None, cfg_no_note)
    assert rep_no_note["prs"][0]["structure_note_verdicts"] == 0


def test_decision4_unparsed_verdict_lines_and_warning():
    """Decision 4: comment first lines matching ^\\S*審查： but not verdict_pattern

    are counted in unparsed_verdict_lines and emit a warning when N > 0.
    The warning never contains the comment text.
    """
    pr = make_pr(
        21,
        comments=[
            # Half-width parenthesis with spaces fails pattern
            comment(1, "2030-01-02T04:00:00Z", "審查：vendor/model-x (custom note) 結論：可以 merge（head 1111111）"),
            # Regular comment does not match ^\S*審查：
            comment(2, "2030-01-02T04:05:00Z", "一般留言：這是一則普通討論"),
            # Valid verdict line
            comment(3, "2030-01-02T04:10:00Z", "審查：vendor/model-x 結論：可以 merge（head 1111111）"),
        ],
    )
    snap = snapshot(pr)
    rep = score_ticket(snap, None, DEFAULT_CONFIG)

    pr_res = rep["prs"][0]
    assert pr_res["unparsed_verdict_lines"] == 1
    assert pr_res["verdicts"] == 1
    assert rep["metrics"]["unparsed_verdict_lines"] == 1

    expected_warning = "unparsed_verdict_lines: 1 verdict-like line(s) did not match verdict_pattern"
    assert rep["warnings"] == [expected_warning]
    assert "custom note" not in rep["warnings"][0]

    # Under legacy pattern without note group, note containing spaces is unparsed
    cfg_legacy = copy.deepcopy(DEFAULT_CONFIG)
    cfg_legacy["verdict_pattern"] = (
        r"^(?P<role>\S*審查)：(?P<model>\S+) 結論：(?P<verdict>[^（]+)（head (?P<head>[0-9a-f]{7,40})）"
    )
    pr_legacy = make_pr(
        21,
        comments=[
            comment(1, "2030-01-02T04:00:00Z", "審查：vendor/model-x（某管道 high） 結論：可以 merge（head 1111111）"),
            comment(2, "2030-01-02T04:10:00Z", "審查：vendor/model-x 結論：可以 merge（head 1111111）"),
        ],
    )
    rep_legacy = score_ticket(snapshot(pr_legacy), None, cfg_legacy)
    assert rep_legacy["prs"][0]["unparsed_verdict_lines"] == 1
    assert rep_legacy["warnings"] == [expected_warning]


def test_no_special_cases_zero_new_fields():
    """When none of the special cases occur, new fields are 0 and other fields match."""
    pr = make_pr(
        21,
        comments=[
            comment(1, "2030-01-02T04:00:00Z", "審查：vendor/model-x 結論：要修（head 0000000）"),
            comment(2, "2030-01-02T04:50:00Z", "審查：vendor/model-x 結論：可以 merge（head 1111111）"),
        ],
    )
    snap = snapshot(pr)
    rep = score_ticket(snap, None, DEFAULT_CONFIG)

    pr_res = rep["prs"][0]
    assert pr_res["nonstandard_verdict_lines"] == 0
    assert pr_res["post_merge_verdicts"] == 0
    assert pr_res["structure_note_verdicts"] == 0
    assert pr_res["unparsed_verdict_lines"] == 0

    m = rep["metrics"]
    assert m["nonstandard_verdict_lines"] == 0
    assert m["post_merge_verdicts"] == 0
    assert m["structure_note_verdicts"] == 0
    assert m["unparsed_verdict_lines"] == 0

    assert rep["warnings"] == []


def test_decision_addition2_head_note_tolerance():
    """PM 追加 2 acceptance tests:

    - Positive cases: full-width semicolon (；) and half-width semicolon (;) inside head parens.
      Both are parsed, enter V, and increment nonstandard_verdict_lines.
    - Negative case: directly appending text to head SHA without semicolon is not parsed.
      It increments unparsed_verdict_lines and does not increment nonstandard_verdict_lines.
    """
    # 1. Full-width semicolon in head section
    line_full = "審查：vendor/model-x（註記） 結論：可以 merge（head 1234567；低 2 皆措辭）"
    # 2. Half-width semicolon in head section
    line_half = "審查：vendor/model-x 結論：可以 merge（head 2345678;說明）"
    # 3. Negative case: text directly without semicolon
    line_neg = "審查：vendor/model-x 結論：可以 merge（head 3456789說明）"

    pr = make_pr(
        21,
        comments=[
            comment(1, "2030-01-02T04:00:00Z", line_full),
            comment(2, "2030-01-02T04:10:00Z", line_half),
            comment(3, "2030-01-02T04:20:00Z", line_neg),
        ],
    )
    rep = score_ticket(snapshot(pr), None, DEFAULT_CONFIG)
    pr_res = rep["prs"][0]

    # line_full and line_half enter V (head captured as 1234567 and 2345678)
    assert pr_res["verdicts"] == 2
    assert pr_res["nonstandard_verdict_lines"] == 2
    assert pr_res["unparsed_verdict_lines"] == 1
    assert rep["metrics"]["nonstandard_verdict_lines"] == 2
    assert rep["metrics"]["unparsed_verdict_lines"] == 1


def test_m1_builtin_config_note_with_half_width_space():
    """M-1: note containing half-width space is parsed under built-in config.

    Mutating note group to [^）\\s]* must fail this test.
    """
    line = "審查：vendor/model-x（pipe a, high） 結論：可以 merge（head 1234567）"
    pat = re.compile(DEFAULT_CONFIG["verdict_pattern"])
    m = pat.match(line)
    assert m is not None, line
    assert m.group("role") == "審查"
    assert m.group("model") == "vendor/model-x"
    assert m.group("note") == "pipe a, high"
    assert m.group("verdict") == "可以 merge"
    assert m.group("head") == "1234567"

    pr = make_pr(
        21,
        comments=[comment(1, "2030-01-02T04:00:00Z", line)],
    )
    rep = score_ticket(snapshot(pr), None, DEFAULT_CONFIG)
    pr_res = rep["prs"][0]
    assert pr_res["verdicts"] == 1
    assert pr_res["unparsed_verdict_lines"] == 0
    assert rep["metrics"]["unparsed_verdict_lines"] == 0
    assert rep["warnings"] == []


def test_m6_metrics_unparsed_verdict_lines_only_counts_merged_prs():
    """M-6 (L-1): metrics and warning for unparsed_verdict_lines only count merged PRs.

    Open and closed-unmerged PRs do not contribute to metrics or warning unparsed counts.
    """
    # Merged PR: 1 valid verdict line, 0 unparsed
    pr_merged = make_pr(
        21,
        comments=[
            comment(1, "2030-01-02T04:00:00Z", "審查：vendor/model-x 結論：可以 merge（head 1111111）"),
        ],
    )
    # Open PR: 1 unparsed line
    pr_open = make_pr(
        22,
        state="open",
        merged_at=None,
        comments=[
            comment(2, "2030-01-02T04:00:00Z", "審查：vendor/model-x (custom note) 結論：可以 merge（head 1111111）"),
        ],
    )
    # Closed unmerged PR: 1 unparsed line
    pr_closed = make_pr(
        23,
        state="closed",
        merged_at=None,
        comments=[
            comment(3, "2030-01-02T04:00:00Z", "審查：vendor/model-x (custom note 2) 結論：可以 merge（head 1111111）"),
        ],
    )
    snap = snapshot(pr_merged, pr_open, pr_closed)
    rep = score_ticket(snap, None, DEFAULT_CONFIG)

    assert rep["prs"][0]["unparsed_verdict_lines"] == 0
    assert rep["prs"][1]["unparsed_verdict_lines"] == 1
    assert rep["prs"][2]["unparsed_verdict_lines"] == 1

    # metrics and warning only count merged PRs
    assert rep["metrics"]["unparsed_verdict_lines"] == 0
    assert rep["warnings"] == []


def test_m7_structure_review_prefix_unparsed_verdict_line():
    """M-7: comment first line starting with 結構審查： but not matching verdict_pattern

    is counted in unparsed_verdict_lines (VERDICT_LINE_PREFIX_RE is ^\\S*審查：).
    """
    pr = make_pr(
        21,
        comments=[
            comment(1, "2030-01-02T04:00:00Z", "結構審查：vendor/model-x (broken format) 結論：通過（head 1111111）"),
        ],
    )
    snap = snapshot(pr)
    rep = score_ticket(snap, None, DEFAULT_CONFIG)

    pr_res = rep["prs"][0]
    assert pr_res["unparsed_verdict_lines"] == 1
    assert rep["metrics"]["unparsed_verdict_lines"] == 1
    assert rep["warnings"] == [
        "unparsed_verdict_lines: 1 verdict-like line(s) did not match verdict_pattern"
    ]


def test_m15_empty_note_not_counted_as_structure_note():
    """M-15: empty note （） matches pattern and is not treated as a structure note."""
    line = "審查：vendor/model-x（） 結論：可以 merge（head 1234567）"
    pat = re.compile(DEFAULT_CONFIG["verdict_pattern"])
    m = pat.match(line)
    assert m is not None, line
    assert m.group("note") == ""

    pr = make_pr(
        21,
        comments=[comment(1, "2030-01-02T04:00:00Z", line)],
    )
    rep = score_ticket(snapshot(pr), None, DEFAULT_CONFIG)
    pr_res = rep["prs"][0]
    assert pr_res["structure_note_verdicts"] == 0
    assert pr_res["verdicts"] == 1
    assert rep["metrics"]["structure_note_verdicts"] == 0


def test_l2_nonstandard_head_checks_only_after_head_and_in_v():
    """L-2: nonstandard_verdict_lines checks semicolon immediately after head group,

    and only counts on verdicts that actually enter V.
    """
    # 1. Fake head paren inside note group, but standard head
    line1 = "審查：vendor/model-x（（head 1234567；x） 結論：通過（head 1234567）"
    # 2. 結構審查 has head with semicolon, but role is not in review_roles -> not in V
    line2 = "結構審查：vendor/model-z 結論：通過（head 1234567；說明）"
    # 3. Structure note excluded from V -> nonstandard not counted
    line3 = "審查：vendor/model-x（架構師結構審） 結論：通過（head 1234567；說明）"
    # 4. Standard review with head semicolon enters V -> nonstandard counted
    line4 = "審查：vendor/model-x 結論：通過（head 1234567；說明）"

    pr = make_pr(
        21,
        comments=[
            comment(1, "2030-01-02T04:00:00Z", line1),
            comment(2, "2030-01-02T04:05:00Z", line2),
            comment(3, "2030-01-02T04:10:00Z", line3),
            comment(4, "2030-01-02T04:15:00Z", line4),
        ],
    )
    rep = score_ticket(snapshot(pr), None, DEFAULT_CONFIG)
    pr_res = rep["prs"][0]
    # line1 enters V (standard head -> nonstd=0)
    # line2 does not enter V (role not in review_roles)
    # line3 does not enter V (structure note)
    # line4 enters V (nonstd=1)
    assert pr_res["verdicts"] == 2
    assert pr_res["structure_note_verdicts"] == 1
    assert pr_res["nonstandard_verdict_lines"] == 1
    assert rep["metrics"]["nonstandard_verdict_lines"] == 1


def test_l4_decision3_reviews_source_and_merged_open_scope():
    """L-4: decision 3 with reviews source, and merged + open PRs existing simultaneously."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["verdict_sources"] = ["comments", "reviews"]

    pr_merged = make_pr(
        21,
        merged_at="2030-01-02T05:00:00Z",
        reviews=[
            {"id": 1, "submitted_at": "2030-01-02T04:00:00Z", "state": "CHANGES_REQUESTED", "commit_id": "0000000"},
            {"id": 2, "submitted_at": "2030-01-02T05:00:00Z", "state": "APPROVED", "commit_id": "1111111"},
            {"id": 3, "submitted_at": "2030-01-02T05:00:02Z", "state": "APPROVED", "commit_id": "1111111"},
        ],
        comments=[
            # 1 unparsed line in merged PR
            comment(10, "2030-01-02T04:30:00Z", "審查：vendor/model-x (broken) 結論：通過（head 1111111）"),
        ],
    )
    pr_open = make_pr(
        22,
        state="open",
        merged_at=None,
        reviews=[
            {"id": 4, "submitted_at": "2030-01-02T06:00:00Z", "state": "APPROVED", "commit_id": "1111111"},
        ],
        comments=[
            # 1 unparsed line in open PR
            comment(11, "2030-01-02T06:30:00Z", "審查：vendor/model-x (broken open) 結論：通過（head 1111111）"),
        ],
    )

    snap = snapshot(pr_merged, pr_open)
    rep = score_ticket(snap, None, cfg)

    # Merged PR: review 1 & 2 <= merged_at count; review 3 is post_merge
    res_m = rep["prs"][0]
    assert res_m["verdicts"] == 2
    assert res_m["post_merge_verdicts"] == 1
    assert res_m["fix_rounds"] == 1
    assert res_m["unparsed_verdict_lines"] == 1

    # Open PR: review 4 counts, post_merge is 0
    res_o = rep["prs"][1]
    assert res_o["verdicts"] == 1
    assert res_o["post_merge_verdicts"] == 0
    assert res_o["unparsed_verdict_lines"] == 1

    # Metrics and warnings only count merged PR
    assert rep["metrics"]["post_merge_verdicts"] == 1
    assert rep["metrics"]["unparsed_verdict_lines"] == 1
    assert rep["warnings"] == [
        "unparsed_verdict_lines: 1 verdict-like line(s) did not match verdict_pattern"
    ]


